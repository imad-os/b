"""Pulsebox Motion Studio: calibrate controllers and build reviewable move templates."""
import re
import time
import sys
from collections import deque
import pygame

from game.data import load_moves, save_moves
from game.models import Move
from game.diagnostics import app_logger, report
from motion.calibration import build_calibration
from motion.controller import JoyConProvider
from motion.storage import add_template, delete_templates, load_calibration, load_templates, save_calibration
from motion.types import SensorFrame

pygame.init()
LOGICAL_SIZE = (1180, 720)
DISPLAY = pygame.display.set_mode(LOGICAL_SIZE, pygame.RESIZABLE)
SCREEN = pygame.Surface(LOGICAL_SIZE)
pygame.display.set_caption("Pulsebox Motion Studio")
CLOCK = pygame.time.Clock()
LOGGER = app_logger("motion_studio")
INK = PAPER = CARD = MUTED = CORAL = TEAL = LINE = PANEL = SELECT = GLOW = None


def windows_uses_dark_mode():
    """Follow Windows' AppsUseLightTheme preference, with a light fallback."""
    try:
        import winreg
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        return winreg.QueryValueEx(key, "AppsUseLightTheme")[0] == 0
    except (ImportError, OSError, FileNotFoundError):
        return False


def apply_system_theme():
    global INK, PAPER, CARD, MUTED, CORAL, TEAL, LINE, PANEL, SELECT, GLOW
    if windows_uses_dark_mode():
        INK, PAPER, CARD, MUTED = (237, 242, 248), (14, 19, 27), (25, 33, 44), (157, 171, 187)
        CORAL, TEAL, LINE, PANEL, SELECT, GLOW = (255, 117, 107), (54, 212, 194), (59, 72, 88), (17, 24, 33), (57, 42, 49), (20, 53, 51)
    else:
        INK, PAPER, CARD, MUTED = (18, 24, 32), (245, 247, 250), (255, 255, 255), (113, 126, 142)
        CORAL, TEAL, LINE, PANEL, SELECT, GLOW = (255, 91, 83), (28, 191, 177), (223, 229, 235), (18, 24, 32), (255, 239, 237), (231, 246, 244)


apply_system_theme()


def text(value, x, y, size=18, color=None, bold=False, anchor="topleft"):
    image = pygame.font.SysFont("segoeui", size, bold=bold).render(str(value), True, INK if color is None else color)
    SCREEN.blit(image, image.get_rect(**{anchor: (x, y)}))


def box(rect, color, radius=14):
    pygame.draw.rect(SCREEN, color, pygame.Rect(rect), border_radius=radius)


def logical_position(position):
    display_w, display_h = DISPLAY.get_size()
    scale = min(display_w / LOGICAL_SIZE[0], display_h / LOGICAL_SIZE[1])
    return ((position[0] - (display_w - LOGICAL_SIZE[0] * scale) / 2) / scale,
            (position[1] - (display_h - LOGICAL_SIZE[1] * scale) / 2) / scale)


def present():
    display_w, display_h = DISPLAY.get_size()
    scale = min(display_w / LOGICAL_SIZE[0], display_h / LOGICAL_SIZE[1])
    size = (round(LOGICAL_SIZE[0] * scale), round(LOGICAL_SIZE[1] * scale))
    frame = pygame.transform.smoothscale(SCREEN, size) if size != LOGICAL_SIZE else SCREEN
    DISPLAY.fill((0, 0, 0))
    DISPLAY.blit(frame, ((display_w - size[0]) // 2, (display_h - size[1]) // 2))
    pygame.display.flip()


class Studio:
    def __init__(self):
        self.moves = load_moves()
        self.provider = JoyConProvider()
        self.index = 0
        self.profile = "developer"
        self.calibration = load_calibration(self.profile)
        self.recording = None
        self.calibrating = None
        self.live = {"LEFT": deque(maxlen=150), "RIGHT": deque(maxlen=150)}
        self.review_index = None
        self.notice = "Connect both Joy-Cons, then calibrate before recording."
        self.form = None
        self.draft = ""
        self.theme_check_at = 0
        self.buttons = {}
        self.confirm_remove = False
        self.error_message = ""
        self.running = True
        self.fullscreen = False

    @property
    def selected(self):
        return self.moves[self.index]

    def start_calibration(self):
        self.calibrating = {"start": time.monotonic(), "frames": {"LEFT": [], "RIGHT": []}}
        self.notice = "Hold a relaxed boxing guard completely still for 3 seconds."

    def start_recording(self):
        if not self.calibration:
            self.notice = "Calibrate this profile first. Recordings require a neutral reference."
            return
        self.recording = {"start": time.monotonic(), "frames": []}
        self.notice = f"Perform one clean {self.selected.label} with your {self.selected.hand.lower()} side."

    def update_motion(self):
        frames = self.provider.poll()
        now = time.monotonic()
        for frame in frames:
            self.live.setdefault(frame.hand, deque(maxlen=150)).append(frame)
        if self.calibrating:
            for frame in frames:
                self.calibrating["frames"].setdefault(frame.hand, []).append(frame)
            if now - self.calibrating["start"] >= 3:
                calibration = build_calibration(self.calibrating["frames"])
                if len(calibration["hands"]) == 2:
                    self.calibration = calibration
                    save_calibration(self.profile, calibration)
                    self.notice = "Calibration saved. You can now record motion templates."
                else:
                    self.notice = "Calibration needs both Joy-Cons. Check Bluetooth pairing and try again."
                self.calibrating = None
        if self.recording:
            for frame in frames:
                if frame.hand == self.selected.hand:
                    self.recording["frames"].append(frame)
            if now - self.recording["start"] >= 1.8:
                captured = self.recording["frames"]
                if len(captured) >= 20:
                    count = add_template(self.selected.id, self.selected.hand, captured,
                        {"profile": self.profile, "captured_at": time.time(), "duration": 1.8})
                    self.review_index = count - 1
                    self.notice = f"Saved template {count}. The lower chart shows exactly what was stored."
                else:
                    self.notice = "Not enough IMU frames. Confirm the selected Joy-Con is connected."
                self.recording = None

    def add_move(self):
        label = self.draft.strip()
        move_id = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
        if not label or not move_id:
            return
        if any(move.id == move_id for move in self.moves):
            self.notice = "That move already exists. Choose a different name."
            return
        key = next((key for key in "abcdefghijklmnopqrstuvwxyz" if key not in {move.key for move in self.moves}), "z")
        self.moves.append(Move(move_id, label, key, 5, 3, "Custom", "LEFT", .82))
        save_moves(self.moves)
        self.index = len(self.moves) - 1
        self.form = None
        self.notice = f"Added {label}. Set its side with H, then record samples."

    def edit_acceptance(self):
        try:
            raw = float(self.draft.replace("%", ""))
            self.selected.acceptance = min(.99, max(.05, raw / 100 if raw > 1 else raw))
            save_moves(self.moves)
            self.notice = "Acceptance threshold saved."
        except ValueError:
            self.notice = "Use a percentage such as 74."
        self.form = None

    def edit_name(self):
        label = self.draft.strip()
        if label:
            self.selected.label = label
            save_moves(self.moves)
            self.notice = "Move name updated. Existing motion recordings remain linked."
        self.form = None

    def remove_selected(self):
        if len(self.moves) <= 1:
            self.notice = "At least one move must remain in the library."
            return
        if not self.confirm_remove:
            self.confirm_remove = True
            self.notice = f"Click DELETE again to remove {self.selected.label} and all of its saved recordings."
            return
        deleted = self.selected
        delete_templates(deleted.id)
        self.moves.pop(self.index)
        self.index = max(0, min(self.index, len(self.moves) - 1))
        save_moves(self.moves)
        self.confirm_remove = False
        self.review_index = None
        self.notice = f"Removed {deleted.label} and its saved recordings."

    def draw_button(self, name, label, rect, color=CORAL):
        rect = pygame.Rect(rect)
        self.buttons[name] = rect
        box(rect, color, 9)
        text(label, rect.centerx, rect.centery, 12, PAPER if color != CARD else INK, True, "center")

    def handle_click(self, position):
        if self.form:
            return
        for i in range(min(13, len(self.moves))):
            if pygame.Rect(62, 179 + i * 31, 272, 28).collidepoint(position):
                self.index, self.review_index, self.confirm_remove = i, None, False
                return
        for name, rect in self.buttons.items():
            if rect.collidepoint(position):
                if name == "add": self.form, self.draft = "new", ""
                elif name == "edit": self.form, self.draft = "edit_name", self.selected.label
                elif name == "delete": self.remove_selected()
                elif name == "calibrate": self.start_calibration()
                elif name == "record": self.start_recording()
                elif name == "review": self.review_template()
                elif name == "threshold": self.form, self.draft = "acceptance", str(round(self.selected.acceptance * 100))
                return

    def review_template(self, direction=1):
        templates = load_templates(self.selected.id)
        if not templates:
            self.notice = "This move has no saved recordings yet."
            return
        self.review_index = 0 if self.review_index is None else (self.review_index + direction) % len(templates)
        self.notice = f"Reviewing saved template {self.review_index + 1} of {len(templates)}."

    def event(self, event):
        global DISPLAY
        if event.type == pygame.QUIT:
            self.running = False
        if event.type == pygame.VIDEORESIZE and not self.fullscreen:
            DISPLAY = pygame.display.set_mode(event.size, pygame.RESIZABLE)
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.handle_click(logical_position(event.pos))
            return
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_F11:
            self.fullscreen = not self.fullscreen
            DISPLAY = pygame.display.set_mode((0, 0), pygame.FULLSCREEN) if self.fullscreen else pygame.display.set_mode(LOGICAL_SIZE, pygame.RESIZABLE)
            return
        if self.form:
            if event.key == pygame.K_ESCAPE:
                self.form = None
            elif event.key == pygame.K_RETURN:
                if self.form == "new": self.add_move()
                elif self.form == "edit_name": self.edit_name()
                else: self.edit_acceptance()
            elif event.key == pygame.K_BACKSPACE:
                self.draft = self.draft[:-1]
            elif event.unicode and event.unicode.isprintable():
                self.draft += event.unicode
            return
        if event.key == pygame.K_ESCAPE:
            self.running = False
        elif event.key == pygame.K_DOWN:
            self.index = min(len(self.moves) - 1, self.index + 1); self.review_index = None
        elif event.key == pygame.K_UP:
            self.index = max(0, self.index - 1); self.review_index = None
        elif event.key == pygame.K_c:
            self.start_calibration()
        elif event.key == pygame.K_r:
            self.start_recording()
        elif event.key == pygame.K_v:
            self.review_template()
        elif event.key == pygame.K_LEFT and self.review_index is not None:
            self.review_template(-1)
        elif event.key == pygame.K_RIGHT and self.review_index is not None:
            self.review_template(1)
        elif event.key == pygame.K_x:
            self.review_index = None; self.notice = "Returned to live-only view."
        elif event.key == pygame.K_p:
            self.profile = "user" if self.profile == "developer" else "developer"
            self.calibration = load_calibration(self.profile)
            self.notice = f"Switched to {self.profile} calibration profile."
        elif event.key == pygame.K_h:
            self.selected.hand = "RIGHT" if self.selected.hand == "LEFT" else "LEFT"
            save_moves(self.moves); self.notice = f"{self.selected.label} is now a {self.selected.hand}-side move."
        elif event.key == pygame.K_a:
            self.form, self.draft = "acceptance", str(round(self.selected.acceptance * 100))
        elif event.key == pygame.K_n:
            self.form, self.draft = "new", ""

    def draw_trace(self, rect, frames, title, review=False):
        rect = pygame.Rect(rect)
        box(rect, PANEL, 12)
        pale = (181, 199, 214)
        text(title, rect.x + 14, rect.y + 12, 12, pale, True)
        if not frames:
            text("No saved frames" if review else "Waiting for live IMU samples", rect.centerx, rect.centery, 14, MUTED, False, "center")
            return
        values = [frame.accel for frame in frames]
        scale = max(1.0, max(abs(value) for row in values for value in row))
        chart = pygame.Rect(rect.x + 14, rect.y + 37, rect.width - 28, rect.height - 56)
        pygame.draw.line(SCREEN, LINE, (chart.left, chart.centery), (chart.right, chart.centery), 1)
        for axis, color in enumerate((CORAL, TEAL, (105, 148, 255))):
            points = [(chart.left + chart.width * i / max(1, len(values) - 1), chart.centery - row[axis] / scale * chart.height * .42)
                      for i, row in enumerate(values)]
            if len(points) > 1:
                pygame.draw.lines(SCREEN, color, False, points, 2)
        text("X", chart.left, rect.bottom - 19, 11, CORAL, True)
        text("Y", chart.left + 25, rect.bottom - 19, 11, TEAL, True)
        text("Z", chart.left + 50, rect.bottom - 19, 11, (105, 148, 255), True)
        last = values[-1]
        text(f"{last[0]:+.2f}  {last[1]:+.2f}  {last[2]:+.2f}", rect.right - 14, rect.bottom - 19, 11, pale, True, "topright")

    def draw(self):
        SCREEN.fill(PAPER)
        self.buttons = {}
        w, _ = SCREEN.get_size()
        pygame.draw.circle(SCREEN, GLOW, (w - 20, 25), 210)
        text("PULSEBOX / MOTION STUDIO", 46, 34, 14, CORAL, True)
        text("Controller calibration and move capture", 46, 61, 30, INK, True)
        text("CONNECTED" if self.provider.connected else "WAITING FOR JOY-CONS", w - 46, 42, 13, TEAL if self.provider.connected else CORAL, True, "topright")
        theme = "DARK" if windows_uses_dark_mode() else "LIGHT"
        text(f"{theme} THEME  |  {self.profile.upper()} PROFILE  |  CALIBRATION: {'READY' if self.calibration else 'REQUIRED'}", w - 46, 66, 12, MUTED, True, "topright")
        library_width = 320
        box((46, 126, library_width, 490), CARD)
        text("MOVE LIBRARY", 72, 151, 12, MUTED, True)
        for i, move in enumerate(self.moves[:13]):
            y = 184 + i * 31
            if i == self.index:
                box((62, y - 5, library_width - 32, 26), SELECT, 7)
            text(move.label, 76, y, 16, INK, i == self.index)
            text(move.hand, 290, y + 2, 11, CORAL if move.hand == "RIGHT" else TEAL, True, "topright")
            text(f"{move.acceptance:.0%}" if move.acceptance else "LEVEL", 340, y + 2, 11, MUTED, True, "topright")
        self.draw_button("add", "ADD", (62, 580, 84, 27), TEAL)
        self.draw_button("edit", "EDIT", (154, 580, 84, 27), CORAL)
        delete_label = "DELETE?" if self.confirm_remove else "DELETE"
        self.draw_button("delete", delete_label, (246, 580, 88, 27), (205, 70, 70))
        px, pw = 392, w - 438
        box((px, 126, pw, 490), CARD)
        move, templates = self.selected, load_templates(self.selected.id)
        text("SELECTED MOVE", px + 28, 151, 12, MUTED, True)
        text(move.label, px + 28, 177, 28, INK, True)
        text(f"{move.hand} SIDE  |  LEVEL {move.min_level}  |  {len(templates)} SAVED", px + 28, 218, 13, MUTED, True)
        text(f"Acceptance: {move.acceptance:.0%}" if move.acceptance else "Acceptance: level default", px + 28, 246, 15, CORAL, True)
        self.draw_button("threshold", "EDIT THRESHOLD", (px + pw - 170, 237, 142, 28), CARD)
        self.draw_trace((px + 22, 281, pw - 44, 130), list(self.live.get(move.hand, [])), f"LIVE {move.hand} ACCELERATION - controller now")
        review_frames, review_title = [], "SAVED RECORDING - press V to review"
        if self.review_index is not None and templates:
            self.review_index %= len(templates)
            review_frames = [SensorFrame.from_dict(frame) for frame in templates[self.review_index].get("frames", [])]
            review_title = f"SAVED TEMPLATE {self.review_index + 1}/{len(templates)} - LEFT/RIGHT switch, X live only"
        self.draw_trace((px + 22, 426, pw - 44, 130), review_frames, review_title, review=True)
        if self.calibrating:
            left, right = len(self.calibrating["frames"]["LEFT"]), len(self.calibrating["frames"]["RIGHT"])
            text(f"CALIBRATING {max(0, 3 - (time.monotonic() - self.calibrating['start'])):.1f}s  L:{left} R:{right}", px + 28, 576, 13, (255, 181, 71), True)
        elif self.recording:
            text(f"RECORDING {max(0, 1.8 - (time.monotonic() - self.recording['start'])):.1f}s", px + 28, 576, 13, CORAL, True)
        self.draw_button("calibrate", "CALIBRATE", (px + 22, 570, 112, 27), TEAL)
        self.draw_button("record", "RECORD", (px + 142, 570, 96, 27), CORAL)
        self.draw_button("review", "REVIEW SAVED", (px + 246, 570, 126, 27), CARD)
        text("Live lines: X red, Y teal, Z blue. The lower chart is exactly the saved data.", px + 28, 607, 12, MUTED)
        box((46, 642, w - 92, 42), PANEL, 10)
        if self.form:
            # A modal makes it obvious that typing is expected after Add/Edit.
            shade = pygame.Surface(SCREEN.get_size(), pygame.SRCALPHA)
            shade.fill((0, 0, 0, 115))
            SCREEN.blit(shade, (0, 0))
            modal = pygame.Rect(w // 2 - 270, 270, 540, 172)
            box(modal, CARD, 18)
            label = "New move name" if self.form == "new" else ("Move name" if self.form == "edit_name" else "Acceptance percentage")
            text(label, modal.x + 30, modal.y + 28, 14, CORAL, True)
            text(self.draft + "_", modal.x + 30, modal.y + 62, 24, INK, True)
            text("ENTER saves   ESC cancels", modal.x + 30, modal.y + 126, 13, MUTED, True)
        else:
            text("UP/DOWN select  C calibrate  R record  V review  LEFT/RIGHT saved samples  X live  P profile  H side  A threshold  N add  F11 fullscreen  ESC exit", 68, 654, 12, PAPER, True)
        text(self.error_message or self.notice, 46, 700, 13, CORAL if self.error_message else MUTED)
        present()

    def run(self):
        while self.running:
            for event in pygame.event.get():
                try:
                    self.event(event)
                except Exception as exc:
                    self.error_message = report(LOGGER, "Input handling", exc)
            try:
                if time.monotonic() >= self.theme_check_at:
                    apply_system_theme()
                    self.theme_check_at = time.monotonic() + 2
                self.update_motion()
            except Exception as exc:
                self.error_message = report(LOGGER, "Controller update", exc)
            try:
                self.draw()
            except Exception as exc:
                self.error_message = report(LOGGER, "Screen render", exc)
                SCREEN.fill((30, 20, 25))
                text(self.error_message, 30, 30, 16, (255, 160, 150))
                present()
            CLOCK.tick(60)
        pygame.quit()


if __name__ == "__main__":
    try:
        Studio().run()
    except Exception as exc:
        LOGGER.exception("Startup failed", exc_info=(type(exc), exc, exc.__traceback__))
        raise
