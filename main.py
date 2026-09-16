import random
import time
import math
from datetime import datetime
from pathlib import Path
import numpy as np
import pygame

from game.data import load_moves, save_moves, load_challenges, save_challenges, load_profile, save_profile, load_session_history, save_session_result, save_heart_rate_session
from game.models import Challenge
from game.input import KeyboardInput
from game.diagnostics import app_logger, report, system_uses_dark_mode
from game.watch import WatchReceiver
from motion.controller import JoyConProvider
from motion.engine import MotionRecognizer
from motion.storage import load_calibration

pygame.init()
pygame.display.set_caption("Pulsebox — fitness boxing")
LOGICAL_SIZE = (1280, 760)
DISPLAY = pygame.display.set_mode(LOGICAL_SIZE, pygame.RESIZABLE)
SCREEN = pygame.Surface(LOGICAL_SIZE)
CLOCK = pygame.time.Clock()
LOGGER = app_logger("pulsebox_game")
ACTIONS_DIR = Path(__file__).resolve().parent / "assets" / "actions"
CHALLENGE_TYPES = ("All", "Box", "HIIT", "Dance", "Other")

# Colors are reloaded from the Windows app-theme setting at launch and during play.
INK = PAPER = MUTED = LINE = CARD = PANEL = WASH_CORAL = WASH_TEAL = CORAL = TEAL = BLUE = GOLD = RED = None


def apply_system_theme():
    global INK, PAPER, MUTED, LINE, CARD, PANEL, WASH_CORAL, WASH_TEAL, CORAL, TEAL, BLUE, GOLD, RED
    CORAL, TEAL, BLUE, GOLD, RED = (255, 105, 98), (41, 203, 186), (105, 145, 255), (255, 190, 83), (235, 91, 91)
    if system_uses_dark_mode():
        INK, PAPER, MUTED, LINE, CARD, PANEL = (239, 244, 250), (13, 18, 26), (158, 173, 190), (58, 70, 87), (25, 33, 44), (17, 24, 33)
        WASH_CORAL, WASH_TEAL = (57, 42, 49), (20, 53, 51)
    else:
        INK, PAPER, MUTED, LINE, CARD, PANEL = (18, 24, 32), (245, 247, 250), (113, 126, 142), (223, 229, 235), (255, 255, 255), (18, 24, 32)
        WASH_CORAL, WASH_TEAL = (255, 239, 237), (232, 246, 244)


apply_system_theme()

def font(size, bold=False):
    return pygame.font.SysFont("segoeui", size, bold=bold)


def txt(surface, value, x, y, size=20, color=None, bold=False, anchor="topleft"):
    image = font(size, bold).render(str(value), True, INK if color is None else color)
    surface.blit(image, image.get_rect(**{anchor: (x, y)}))


def rounded(surface, rect, color, radius=18, border=0):
    pygame.draw.rect(surface, color, pygame.Rect(rect), border, radius)


def initials(name):
    return "".join(p[0] for p in name.split()[:2]).upper() or "?"


def logical_position(position):
    """Convert a physical-window click to the fixed responsive UI canvas."""
    display_w, display_h = DISPLAY.get_size()
    scale = min(display_w / LOGICAL_SIZE[0], display_h / LOGICAL_SIZE[1])
    offset_x = (display_w - LOGICAL_SIZE[0] * scale) / 2
    offset_y = (display_h - LOGICAL_SIZE[1] * scale) / 2
    return ((position[0] - offset_x) / scale, (position[1] - offset_y) / scale)


def present():
    """Letterbox the logical layout so it fills any window or fullscreen size."""
    display_w, display_h = DISPLAY.get_size()
    scale = min(display_w / LOGICAL_SIZE[0], display_h / LOGICAL_SIZE[1])
    size = (round(LOGICAL_SIZE[0] * scale), round(LOGICAL_SIZE[1] * scale))
    frame = pygame.transform.smoothscale(SCREEN, size) if size != LOGICAL_SIZE else SCREEN
    DISPLAY.fill((0, 0, 0))
    DISPLAY.blit(frame, ((display_w - size[0]) // 2, (display_h - size[1]) // 2))
    pygame.display.flip()


class App:
    def __init__(self):
        self.moves = load_moves()
        self.challenges = load_challenges()
        self.challenge_scroll = 0
        self.home_type_filter = "All"
        self.dev_type_filter = "All"
        self.profile = load_profile()
        self.session_history = load_session_history()
        self.screen = "profile" if not self.profile else "home"
        self.input = KeyboardInput()
        self.input_mode = "keyboard"
        self.joycons = JoyConProvider()
        self.watch = WatchReceiver()
        self.motion = MotionRecognizer(load_calibration("user"))
        self.last_confidence = None
        self.profile_fields = ["name", "weight", "height", "sex"]
        self.profile_edit = 0
        self.profile_draft = self.profile or {"name": "", "weight": "", "height": "", "sex": "Female"}
        self.workout_index = 0
        self.current = None
        self.deadline = 0
        self.start_time = 0
        self.workout_started_at = None
        self.total = 0
        self.score = 0
        self.streak = 0
        self.best_streak = 0
        self.hits = 0
        self.misses = 0
        self.feedback = ""
        self.feedback_until = 0
        self.dev_index = 0
        self.dev_scroll = 0
        self.dev_field = None
        self.dev_draft = ""
        self.dev_return = "home"
        self.dev_draft = None
        self.dev_name_focus = False
        self.dev_playback = False
        self.live_frames = {"LEFT": [], "RIGHT": []}
        self.action_images = {}
        self.completed_move = None
        self.prompt_transition_started = 0.0
        self.success_sound = self.build_success_sound()
        self.error_message = ""
        self.theme_check_at = 0
        self.running = True
        self.fullscreen = False
        if self.watch.snapshot()["device"]:
            self.watch.start()

    @property
    def rect(self):
        return SCREEN.get_rect()

    def available_moves(self, level):
        return [m for m in self.moves if m.min_level <= level]

    @property
    def active_challenges(self):
        return [challenge for challenge in self.challenges if challenge.is_active]

    def challenges_of_type(self, challenge_type, active_only=False):
        items = self.active_challenges if active_only else self.challenges
        return [challenge for challenge in items if challenge_type == "All" or challenge.sport == challenge_type]

    @property
    def home_challenges(self):
        return self.challenges_of_type(self.home_type_filter, active_only=True)

    @property
    def dev_challenges(self):
        return self.challenges_of_type(self.dev_type_filter)

    def visible_challenge_count(self):
        return max(1, min(8, (self.rect.height - 275) // 45))

    def keep_selected_challenge_visible(self):
        visible = self.visible_challenge_count()
        self.challenge_scroll = max(0, min(self.challenge_scroll, max(0, len(self.home_challenges) - visible)))
        if self.workout_index < self.challenge_scroll:
            self.challenge_scroll = self.workout_index
        elif self.workout_index >= self.challenge_scroll + visible:
            self.challenge_scroll = self.workout_index - visible + 1

    def visible_dev_challenge_count(self):
        return max(1, min(8, (self.rect.height - 416) // 46))

    def keep_dev_challenge_visible(self):
        visible = self.visible_dev_challenge_count()
        self.dev_index = max(0, min(self.dev_index, max(0, len(self.dev_challenges) - 1)))
        self.dev_scroll = max(0, min(self.dev_scroll, max(0, len(self.dev_challenges) - visible)))
        if self.dev_index < self.dev_scroll:
            self.dev_scroll = self.dev_index
        elif self.dev_index >= self.dev_scroll + visible:
            self.dev_scroll = self.dev_index - visible + 1

    def challenge_moves(self, challenge):
        selected = [m for m in self.moves if m.id in challenge.move_ids]
        return selected or self.available_moves(challenge.level)

    def challenge_sequence(self, challenge):
        """Allocate the set length by frequency, keeping lower-level moves first."""
        moves = sorted(self.challenge_moves(challenge), key=lambda move: (move.min_level, move.label))
        if not moves:
            return []
        weights = {move.id: max(1, int((challenge.move_weights or {}).get(move.id, move.frequency))) for move in moves}
        total_weight = sum(weights.values())
        counts = {move.id: int(challenge.rounds * weights[move.id] / total_weight) for move in moves}
        remaining = challenge.rounds - sum(counts.values())
        # Largest remainder makes the total exact while the secondary sort keeps
        # the schedule predictable: level 1, then 2, then 3, and so on.
        ranked = sorted(moves, key=lambda move: (-(challenge.rounds * weights[move.id] / total_weight - counts[move.id]), move.min_level, move.label))
        for move in ranked[:remaining]:
            counts[move.id] += 1
        return [move for move in moves for _ in range(counts[move.id])]

    @staticmethod
    def action_asset_name(move):
        """Return an explicitly supported action illustration, if one exists."""
        names = {
            "left_jab": "left_punch.png", "right_cross": "right_punch.png",
            "left_hook": "hook.png", "right_hook": "hook.png",
            "left_uppercut": "uppercut.png", "right_uppercut": "uppercut.png",
            "slip_left": "dodge.png", "slip_right": "dodge.png",
            "roll_left": "dodge.png", "roll_right": "dodge.png",
            "block": "block.png", "guard": "guard.png", "duck": "duck.png",
        }
        return names.get(move.id)

    def action_image(self, move):
        filename = self.action_asset_name(move)
        if not filename:
            return None
        if filename not in self.action_images:
            path = ACTIONS_DIR / filename
            try:
                self.action_images[filename] = pygame.image.load(str(path)).convert_alpha() if path.is_file() else None
            except pygame.error:
                self.action_images[filename] = None
        return self.action_images[filename]

    @staticmethod
    def build_success_sound():
        """Create a tiny in-memory confirmation chime; audio remains optional."""
        try:
            if not pygame.mixer.get_init():
                pygame.mixer.init()
            sample_rate, _format, channels = pygame.mixer.get_init()
            length = int(sample_rate * .13)
            moment = np.arange(length) / sample_rate
            # A quick rising two-tone chime reads as a positive confirmation.
            tone = (np.sin(2 * np.pi * 660 * moment) + np.sin(2 * np.pi * 880 * moment) * (moment > .045))
            envelope = np.minimum(1, moment * 80) * np.maximum(0, 1 - moment / .13)
            samples = (tone * envelope * 9000).astype(np.int16)
            if channels == 2:
                samples = np.column_stack((samples, samples))
            return pygame.sndarray.make_sound(samples)
        except (pygame.error, ValueError):
            return None

    def play_success_sound(self):
        if self.success_sound:
            try:
                self.success_sound.play()
            except pygame.error:
                pass

    def prompt_next(self):
        self.completed_move = self.current
        self.prompt_transition_started = time.monotonic() if self.current else 0.0
        self.current = self.training_sequence[min(self.total, len(self.training_sequence) - 1)]
        self.deadline = time.monotonic() + 5

    def start_workout(self):
        self.total = self.score = self.streak = self.best_streak = self.hits = self.misses = 0
        self.start_time = time.monotonic()
        self.workout_started_at = datetime.now().astimezone().isoformat(timespec="seconds")
        self.watch.start_recording()
        self.training_sequence = self.challenge_sequence(self.home_challenges[self.workout_index])
        if not self.training_sequence:
            self.feedback = "THIS TRAINING SET HAS NO MOVES"
            self.screen = "workout_details"
            return
        self.feedback = "READY"
        self.last_confidence = None
        self.screen = "play"
        self.prompt_next()

    def complete(self):
        workout = self.home_challenges[self.workout_index]
        heart_rate_samples = self.watch.stop_recording()
        heart_rates = [reading["bpm"] for reading in heart_rate_samples]
        result = {
            "played_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "score": self.score,
            "accuracy": round(100 * self.hits / max(1, self.hits + self.misses)),
            "heart_rate_average": round(sum(heart_rates) / len(heart_rates)) if heart_rates else None,
            "heart_rate_max": max(heart_rates) if heart_rates else None,
        }
        if heart_rate_samples:
            save_heart_rate_session(workout.id, self.workout_started_at, heart_rate_samples)
        save_session_result(workout.id, result)
        self.session_history[workout.id] = result
        self.screen = "summary"

    def handle_profile(self, event):
        if event.key == pygame.K_TAB:
            self.profile_edit = (self.profile_edit + 1) % 4
        elif event.key == pygame.K_UP:
            self.profile_edit = (self.profile_edit - 1) % 4
        elif event.key == pygame.K_DOWN:
            self.profile_edit = (self.profile_edit + 1) % 4
        elif event.key == pygame.K_RETURN:
            if all(str(self.profile_draft.get(x, "")).strip() for x in self.profile_fields[:3]):
                self.profile = self.profile_draft.copy()
                save_profile(self.profile)
                self.screen = "home"
        elif self.profile_fields[self.profile_edit] == "sex" and event.key in (pygame.K_LEFT, pygame.K_RIGHT, pygame.K_SPACE):
            self.profile_draft["sex"] = "Male" if self.profile_draft["sex"] == "Female" else "Female"
        elif self.profile_fields[self.profile_edit] != "sex":
            field = self.profile_fields[self.profile_edit]
            if event.key == pygame.K_BACKSPACE:
                self.profile_draft[field] = self.profile_draft[field][:-1]
            elif event.unicode and event.unicode.isprintable():
                if field == "name" or event.unicode.isdigit() or event.unicode == ".":
                    self.profile_draft[field] += event.unicode

    def handle_home(self, event):
        if not self.home_challenges:
            return
        if event.key in (pygame.K_DOWN, pygame.K_RIGHT):
            self.workout_index = min(len(self.home_challenges) - 1, self.workout_index + 1)
        elif event.key in (pygame.K_UP, pygame.K_LEFT):
            self.workout_index = max(0, self.workout_index - 1)
        elif event.key == pygame.K_RETURN:
            self.screen = "workout_details"
        elif event.key == pygame.K_PAGEUP:
            self.workout_index = max(0, self.workout_index - self.visible_challenge_count())
        elif event.key == pygame.K_PAGEDOWN:
            self.workout_index = min(len(self.home_challenges) - 1, self.workout_index + self.visible_challenge_count())
        self.keep_selected_challenge_visible()

    def handle_workout_details(self, event):
        if event.key == pygame.K_ESCAPE:
            self.screen = "home"
        elif event.key == pygame.K_RETURN:
            self.dev_playback = False
            self.start_workout()

    def handle_play(self, event):
        if event.key == pygame.K_ESCAPE:
            self.screen = "home"
            return
        if self.input_mode != "keyboard":
            return
        resolved = self.input.resolve_move(event, self.challenge_moves(self.home_challenges[self.workout_index]))
        if not resolved:
            return
        if resolved.id == self.current.id:
            self.register_success(1.0, "KEYBOARD")
        else:
            self.misses += 1
            self.streak = 0
            self.feedback = "WRONG SIDE — reset and focus"
            self.feedback_until = time.monotonic() + 1.1

    def register_success(self, confidence, source):
        remaining = max(0, self.deadline - time.monotonic())
        gained = int((80 + remaining * 24 + self.streak * 5) * (.7 + .3 * confidence))
        self.score += gained
        self.hits += 1
        self.total += 1
        self.streak += 1
        self.best_streak = max(self.streak, self.best_streak)
        self.last_confidence = confidence
        self.feedback = f"{source} CLEAN {confidence:.0%}  +{gained}"
        self.feedback_until = time.monotonic() + .8
        self.play_success_sound()
        if self.total >= self.home_challenges[self.workout_index].rounds:
            self.complete()
        else:
            self.prompt_next()

    def update_controller(self):
        frames = self.joycons.poll()
        for frame in frames:
            history = self.live_frames.setdefault(frame.hand, [])
            history.append(frame)
            del history[:-80]
        if self.screen != "play" or self.input_mode != "controller":
            return
        for frame in frames:
            match = self.motion.feed(frame, self.current, self.home_challenges[self.workout_index].level)
            if match:
                self.last_confidence = match.confidence
                if match.accepted:
                    self.register_success(match.confidence, "MOTION")
                else:
                    self.feedback = f"MOTION {match.confidence:.0%} — need {max(getattr(self.current, 'acceptance', 0), {1:.55,2:.62,3:.69,4:.76,5:.82}[self.home_challenges[self.workout_index].level]):.0%}"
                    self.feedback_until = time.monotonic() + 1.2

    def handle_dev(self, event):
        if event.key == pygame.K_ESCAPE:
            self.screen = self.dev_return
        elif event.key in (pygame.K_DOWN, pygame.K_RIGHT):
            self.dev_index = min(len(self.challenges) - 1, self.dev_index + 1)
            self.keep_dev_challenge_visible()
        elif event.key in (pygame.K_UP, pygame.K_LEFT):
            self.dev_index = max(0, self.dev_index - 1)
            self.keep_dev_challenge_visible()
        elif event.key == pygame.K_RETURN and self.challenges:
            self.start_training_editor(self.challenges[self.dev_index])

    def start_training_editor(self, workout=None):
        if workout:
            selected = set(workout.move_ids) or {move.id for move in self.available_moves(workout.level)}
            self.dev_draft = {"id": workout.id, "title": workout.title, "level": workout.level, "rounds": workout.rounds,
                              "accent": workout.accent, "sport": workout.sport, "selected": selected, "weights": dict(workout.move_weights or {}), "is_active": workout.is_active}
        else:
            selected = {move.id for move in self.available_moves(1)}
            number = 1
            used_ids = {challenge.id for challenge in self.challenges}
            while f"challenge_{number}" in used_ids:
                number += 1
            self.dev_draft = {"id": f"challenge_{number}", "title": "New challenge", "level": 1, "rounds": 20,
                              "accent": BLUE, "sport": "Box", "selected": selected, "weights": {}, "is_active": True}
        for move in self.moves:
            self.dev_draft["weights"].setdefault(move.id, move.frequency)
        self.dev_name_focus = False
        self.screen = "dev_edit"

    def save_training_editor(self):
        draft = self.dev_draft
        title = draft["title"].strip() or "Untitled challenge"
        selected = tuple(move.id for move in self.moves if move.id in draft["selected"])
        if not selected:
            self.error_message = "Select at least one move before saving the challenge."
            return
        challenge = Challenge(draft["id"], title, "Custom challenge", draft["level"], draft["rounds"], tuple(draft["accent"]), sport=draft["sport"],
                              move_ids=selected, move_weights={move_id: max(1, int(draft["weights"][move_id])) for move_id in selected}, is_active=draft["is_active"])
        existing = next((index for index, item in enumerate(self.challenges) if item.id == challenge.id), None)
        if existing is None:
            self.challenges.append(challenge)
        else:
            self.challenges[existing] = challenge
        save_challenges(self.challenges)
        self.home_type_filter = challenge.sport
        self.workout_index = next((i for i, item in enumerate(self.home_challenges) if item.id == challenge.id), 0)
        self.keep_selected_challenge_visible()
        self.screen = "dev"

    def training_preview(self):
        draft = self.dev_draft
        temporary = Challenge(draft["id"], draft["title"], "", draft["level"], draft["rounds"], tuple(draft["accent"]),
                            move_ids=tuple(draft["selected"]), move_weights=draft["weights"])
        return self.challenge_sequence(temporary)

    def handle_click(self, position):
        """Mouse navigation for screens; workout moves remain keyboard/controller driven."""
        if self.watch_button_rect().collidepoint(position):
            self.watch_return = self.screen
            self.screen = "watch_details"
            return
        if self.screen == "profile":
            panel = pygame.Rect(self.rect.centerx - 330, 80, 660, 600)
            for i in range(4):
                if pygame.Rect(panel.x + 64, 272 + i * 76, 532, 65).collidepoint(position):
                    self.profile_edit = i
                    if i == 3:
                        self.profile_draft["sex"] = "Male" if self.profile_draft["sex"] == "Female" else "Female"
                    return
            if pygame.Rect(panel.x + 64, 628, 532, 38).collidepoint(position):
                if all(str(self.profile_draft.get(field, "")).strip() for field in self.profile_fields[:3]):
                    self.profile = self.profile_draft.copy()
                    save_profile(self.profile)
                    self.screen = "home"
        elif self.screen == "home":
            for index, challenge_type in enumerate(CHALLENGE_TYPES):
                if pygame.Rect(338 + index * 80, 185, 74, 26).collidepoint(position):
                    self.home_type_filter = challenge_type
                    self.workout_index = self.challenge_scroll = 0
                    return
            if pygame.Rect(56, 570, 255, 38).collidepoint(position):
                self.input_mode = "controller" if self.input_mode == "keyboard" else "keyboard"
                return
            if pygame.Rect(56, 618, 255, 38).collidepoint(position):
                self.watch.start(discover=True)
                return
            if pygame.Rect(56, 666, 255, 38).collidepoint(position):
                connected = self.joycons.refresh()
                self.feedback = "JOY-CON CONNECTED" if connected else "PAIR JOY-CONS IN WINDOWS BLUETOOTH, THEN TRY AGAIN"
                self.feedback_until = time.monotonic() + 3
                return
            start = self.challenge_scroll
            for page_index, _challenge in enumerate(self.home_challenges[start:start + self.visible_challenge_count()]):
                i = start + page_index
                if pygame.Rect(338, 220 + page_index * 45, self.rect.width - 394, 38).collidepoint(position):
                    self.workout_index = i
                    self.screen = "workout_details"
                    return
        elif self.screen == "workout_details":
            w = self.rect.width
            if pygame.Rect(w // 2 - 230, 600, 220, 46).collidepoint(position):
                self.dev_playback = False
                self.start_workout()
            elif pygame.Rect(w // 2 + 10, 600, 220, 46).collidepoint(position):
                self.screen = "home"
        elif self.screen == "play" and pygame.Rect(40, self.rect.height - 72, 340, 48).collidepoint(position):
            self.screen = "home"
        elif self.screen == "summary":
            self.screen = "home"
        elif self.screen == "dev":
            for index, challenge_type in enumerate(CHALLENGE_TYPES):
                if pygame.Rect(315 + index * 80, 200, 74, 26).collidepoint(position):
                    self.dev_type_filter = challenge_type
                    self.dev_index = self.dev_scroll = 0
                    return
            if pygame.Rect(56, 192, 245, 42).collidepoint(position):
                self.start_training_editor()
                return
            for row_index, workout in enumerate(self.dev_challenges[self.dev_scroll:self.dev_scroll + self.visible_dev_challenge_count()]):
                index = self.dev_scroll + row_index
                y = 291 + row_index * 46
                if pygame.Rect(self.rect.width - 250, y, 90, 30).collidepoint(position):
                    self.start_training_editor(workout)
                    return
                if pygame.Rect(self.rect.width - 150, y, 90, 30).collidepoint(position):
                    if len(self.challenges) == 1:
                        self.error_message = "Keep at least one challenge in the library."
                        return
                    self.challenges.pop(index)
                    save_challenges(self.challenges)
                    self.workout_index = min(self.workout_index, max(0, len(self.home_challenges) - 1))
                    self.dev_index = min(self.dev_index, max(0, len(self.dev_challenges) - 1))
                    self.keep_dev_challenge_visible()
                    return
                if pygame.Rect(self.rect.width - 350, y, 90, 30).collidepoint(position):
                    self.home_type_filter = workout.sport
                    active_index = next((i for i, item in enumerate(self.home_challenges) if item.id == workout.id), None)
                    if active_index is None:
                        self.error_message = "Activate this challenge before testing it."
                    else:
                        self.workout_index = active_index
                        self.dev_playback = True
                        self.start_workout()
                    return
            if pygame.Rect(56, self.rect.height - 72, 160, 38).collidepoint(position):
                self.screen = self.dev_return
        elif self.screen == "dev_edit":
            draft = self.dev_draft
            if pygame.Rect(56, 198, 420, 42).collidepoint(position):
                self.dev_name_focus = True
                return
            if pygame.Rect(535, 198, 36, 36).collidepoint(position):
                draft["level"] = max(1, draft["level"] - 1); return
            if pygame.Rect(675, 198, 36, 36).collidepoint(position):
                draft["level"] = min(5, draft["level"] + 1); return
            if pygame.Rect(785, 198, 36, 36).collidepoint(position):
                draft["rounds"] = max(1, draft["rounds"] - 1); return
            if pygame.Rect(965, 198, 36, 36).collidepoint(position):
                draft["rounds"] = min(200, draft["rounds"] + 1); return
            if pygame.Rect(1040, 198, 170, 36).collidepoint(position):
                choices = CHALLENGE_TYPES[1:]
                draft["sport"] = choices[(choices.index(draft["sport"]) + 1) % len(choices)]
                return
            if pygame.Rect(1040, 240, 170, 22).collidepoint(position):
                other_active = any(challenge.id != draft["id"] and challenge.is_active for challenge in self.challenges)
                if draft["is_active"] and not other_active:
                    self.error_message = "Keep at least one active challenge."
                else:
                    draft["is_active"] = not draft["is_active"]
                return
            for index, move in enumerate(self.moves):
                y = 265 + index * 38
                if pygame.Rect(56, y, 350, 32).collidepoint(position):
                    if move.id in draft["selected"]: draft["selected"].remove(move.id)
                    else: draft["selected"].add(move.id)
                    return
                if pygame.Rect(570, y, 28, 28).collidepoint(position):
                    draft["weights"][move.id] = max(1, draft["weights"][move.id] - 1); return
                if pygame.Rect(690, y, 28, 28).collidepoint(position):
                    draft["weights"][move.id] = min(99, draft["weights"][move.id] + 1); return
            if pygame.Rect(self.rect.width - 270, self.rect.height - 72, 105, 38).collidepoint(position):
                self.screen = "dev"; return
            if pygame.Rect(self.rect.width - 150, self.rect.height - 72, 105, 38).collidepoint(position):
                self.save_training_editor()
                return

    def event(self, event):
        global DISPLAY
        if event.type == pygame.QUIT:
            self.running = False
        if event.type == pygame.VIDEORESIZE and not self.fullscreen:
            DISPLAY = pygame.display.set_mode(event.size, pygame.RESIZABLE)
            return
        if event.type == pygame.MOUSEWHEEL and self.screen == "home":
            self.workout_index = max(0, min(len(self.home_challenges) - 1, self.workout_index - event.y))
            self.keep_selected_challenge_visible()
            return
        if event.type == pygame.MOUSEWHEEL and self.screen == "dev":
            self.dev_index = max(0, min(len(self.dev_challenges) - 1, self.dev_index - event.y))
            self.keep_dev_challenge_visible()
            return
        if event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.handle_click(logical_position(event.pos))
            return
        if event.type == pygame.JOYHATMOTION:
            x, y = event.value
            key = pygame.K_UP if y > 0 else pygame.K_DOWN if y < 0 else pygame.K_RIGHT if x > 0 else pygame.K_LEFT if x < 0 else None
            if key is not None:
                event = pygame.event.Event(pygame.KEYDOWN, key=key, unicode="")
        elif event.type == pygame.JOYBUTTONDOWN:
            key = pygame.K_RETURN if event.button in (0, 1, 7) else pygame.K_ESCAPE if event.button in (6, 8, 9) else None
            if key is not None:
                event = pygame.event.Event(pygame.KEYDOWN, key=key, unicode="")
        if event.type != pygame.KEYDOWN:
            return
        if event.key == pygame.K_F11:
            self.fullscreen = not self.fullscreen
            DISPLAY = pygame.display.set_mode((0, 0), pygame.FULLSCREEN) if self.fullscreen else pygame.display.set_mode(LOGICAL_SIZE, pygame.RESIZABLE)
            return
        if event.key == pygame.K_F1 and self.screen != "dev":
            self.dev_return = self.screen
            self.screen = "dev"
            return
        if self.screen == "dev_edit":
            if event.key == pygame.K_ESCAPE:
                self.screen = "dev"
            elif self.dev_name_focus:
                if event.key == pygame.K_BACKSPACE:
                    self.dev_draft["title"] = self.dev_draft["title"][:-1]
                elif event.key == pygame.K_RETURN:
                    self.dev_name_focus = False
                elif event.unicode and event.unicode.isprintable():
                    self.dev_draft["title"] += event.unicode
            return
        if event.key == pygame.K_m and self.screen in ("home", "play"):
            self.input_mode = "controller" if self.input_mode == "keyboard" else "keyboard"
            if self.input_mode == "controller":
                self.motion = MotionRecognizer(load_calibration("user"))
                self.feedback = "CONTROLLER MODE" if self.joycons.connected else "NO JOY-CONS — run Motion Studio to pair/calibrate"
            return
        if self.screen == "profile": self.handle_profile(event)
        elif self.screen == "home": self.handle_home(event)
        elif self.screen == "workout_details": self.handle_workout_details(event)
        elif self.screen == "play": self.handle_play(event)
        elif self.screen == "summary" and event.key in (pygame.K_RETURN, pygame.K_ESCAPE): self.screen = "home"
        elif self.screen == "watch_details" and event.key in (pygame.K_RETURN, pygame.K_ESCAPE): self.screen = getattr(self, "watch_return", "home")
        elif self.screen == "dev": self.handle_dev(event)

    def background(self):
        SCREEN.fill(PAPER)
        w, h = self.rect.size
        pygame.draw.circle(SCREEN, WASH_TEAL, (w - 80, 50), 240)
        pygame.draw.circle(SCREEN, WASH_CORAL, (40, h + 60), 300)

    def topbar(self, title, label="PULSEBOX"):
        txt(SCREEN, label, 56, 34, 15, CORAL, True)
        txt(SCREEN, title, 56, 62, 30, INK, True)
        txt(SCREEN, "F11 FULLSCREEN  ·  F1 DEVELOPER MODE", self.rect.width - 56, 44, 13, MUTED, True, "topright")

    def watch_button_rect(self):
        return pygame.Rect(self.rect.width - 170, 18, 126, 38)

    def draw_watch_indicator(self):
        state = self.watch.snapshot()["state"]
        color = BLUE if state == "connected" else (GOLD if state in ("scanning", "connecting") else RED)
        rect = self.watch_button_rect()
        rounded(SCREEN, rect, CARD, 12)
        pygame.draw.rect(SCREEN, color, rect, 2, 12)
        pygame.draw.rect(SCREEN, color, (rect.x + 12, rect.y + 9, 16, 20), 2, 4)
        pygame.draw.line(SCREEN, color, (rect.x + 17, rect.y + 6), (rect.x + 23, rect.y + 6), 2)
        pygame.draw.line(SCREEN, color, (rect.x + 17, rect.y + 32), (rect.x + 23, rect.y + 32), 2)
        txt(SCREEN, "WATCH", rect.x + 37, rect.centery, 12, color, True, "midleft")

    def draw_profile(self):
        self.background()
        panel = pygame.Rect(self.rect.centerx - 330, 80, 660, 600)
        rounded(SCREEN, panel, CARD, 28)
        txt(SCREEN, "PULSEBOX", panel.centerx, 132, 15, CORAL, True, "midtop")
        txt(SCREEN, "Build your fighter card.", panel.centerx, 164, 32, INK, True, "midtop")
        txt(SCREEN, "Your profile personalizes your training dashboard.", panel.centerx, 210, 16, MUTED, False, "midtop")
        labels = [("name", "Name", "Alex Morgan"), ("weight", "Weight (kg)", "e.g. 72"), ("height", "Height (cm)", "e.g. 174"), ("sex", "Sex", "Female  /  Male")]
        for i, (key, label, hint) in enumerate(labels):
            y = 272 + i * 76
            selected = i == self.profile_edit
            txt(SCREEN, label.upper(), panel.x + 64, y, 12, CORAL if selected else MUTED, True)
            value = self.profile_draft.get(key) or hint
            color = INK if self.profile_draft.get(key) else MUTED
            rounded(SCREEN, (panel.x + 64, y + 21, 532, 42), WASH_CORAL if selected else PAPER, 10)
            if selected: pygame.draw.rect(SCREEN, CORAL, (panel.x + 64, y + 61, 532, 2))
            txt(SCREEN, value, panel.x + 78, y + 32, 17, color, key == "sex")
        rounded(SCREEN, (panel.x + 64, 628, 532, 38), CORAL, 10)
        txt(SCREEN, "START TRAINING", panel.centerx, 647, 13, (255, 255, 255), True, "center")
        txt(SCREEN, "TAB / ↑↓ to navigate • ENTER to start", panel.centerx, 615, 13, MUTED, True, "midtop")

    def draw_home(self):
        self.background(); self.topbar("Training library")
        name = self.profile["name"]
        txt(SCREEN, f"Welcome back, {name.split()[0]}.", 56, 124, 38, INK, True)
        txt(SCREEN, "Choose a session. Your next best move starts here.", 56, 175, 17, MUTED)
        # Player information rail
        rounded(SCREEN, (56, 220, 255, 445), PANEL, 22)
        pygame.draw.circle(SCREEN, CORAL, (104, 273), 26)
        txt(SCREEN, initials(name), 104, 273, 16, (255, 255, 255), True, "center")
        txt(SCREEN, name, 56, 322, 20, (255, 255, 255), True)
        txt(SCREEN, f"{self.profile['weight']} kg  •  {self.profile['height']} cm", 56, 350, 14, (190, 201, 213))
        txt(SCREEN, "TODAY'S FOCUS", 56, 422, 12, (144, 166, 183), True)
        txt(SCREEN, "Precision\nbefore power.", 56, 450, 23, (255, 255, 255), True)
        rounded(SCREEN, (56, 570, 255, 38), (41, 61, 79), 10)
        txt(SCREEN, f"{self.input_mode.title()} INPUT  -  M", 72, 589, 12, (255, 255, 255), True, "midleft")
        rounded(SCREEN, (56, 618, 255, 38), BLUE if self.watch.connected else (67, 42, 47), 10)
        txt(SCREEN, "CONNECT WATCH", 72, 637, 12, (255, 255, 255), True, "midleft")
        rounded(SCREEN, (56, 666, 255, 38), TEAL if self.joycons.connected else (41, 61, 79), 10)
        txt(SCREEN, "CONNECT CONTROLLERS", 72, 685, 12, (255, 255, 255), True, "midleft")
        if time.monotonic() < self.feedback_until:
            txt(SCREEN, self.feedback, 56, 714, 10, TEAL if self.joycons.connected else GOLD, True)
        x = 338
        for index, challenge_type in enumerate(CHALLENGE_TYPES):
            selected_type = challenge_type == self.home_type_filter
            chip = pygame.Rect(x + index * 80, 185, 74, 26)
            rounded(SCREEN, chip, BLUE if selected_type else CARD, 8)
            txt(SCREEN, challenge_type.upper(), chip.centerx, chip.centery, 10, (255, 255, 255) if selected_type else MUTED, True, "center")
        visible = self.visible_challenge_count()
        self.keep_selected_challenge_visible()
        list_rect = pygame.Rect(x, 220, self.rect.width - x - 56, visible * 45 - 7)
        rounded(SCREEN, list_rect.inflate(0, 12), PANEL, 14)
        for page_index, workout in enumerate(self.home_challenges[self.challenge_scroll:self.challenge_scroll + visible]):
            i = self.challenge_scroll + page_index
            row = pygame.Rect(x, 220 + page_index * 45, self.rect.width - x - 68, 38)
            active = i == self.workout_index
            rounded(SCREEN, row, CARD if not active else WASH_CORAL, 10)
            if active: pygame.draw.rect(SCREEN, workout.accent, (row.x, row.y, 5, row.height), border_radius=3)
            txt(SCREEN, f"0{workout.level}", row.x + 20, row.centery, 12, workout.accent, True, "midleft")
            txt(SCREEN, workout.title, row.x + 60, row.centery - 8, 17, INK, True)
            txt(SCREEN, workout.subtitle, row.x + 60, row.centery + 11, 12, MUTED)
            txt(SCREEN, f"LEVEL {workout.level}", row.right - 150, row.centery, 12, MUTED, True, "midleft")
            txt(SCREEN, f"{workout.rounds} MOVES", row.right - 18, row.centery, 12, INK, True, "midright")
        if len(self.home_challenges) > visible:
            track = pygame.Rect(list_rect.right - 8, list_rect.y + 4, 5, list_rect.height - 8)
            pygame.draw.rect(SCREEN, LINE, track, border_radius=3)
            thumb_h = max(24, track.height * visible / len(self.home_challenges))
            thumb_y = track.y + (track.height - thumb_h) * self.challenge_scroll / max(1, len(self.home_challenges) - visible)
            pygame.draw.rect(SCREEN, BLUE, (track.x, thumb_y, track.width, thumb_h), border_radius=3)
        txt(SCREEN, "↑↓ browse    ENTER begin    M switch input    F1 developer mode", x, 690, 13, MUTED, True)

    def draw_workout_details(self):
        self.background()
        workout = self.home_challenges[self.workout_index]
        moves = self.challenge_moves(workout)
        last = self.session_history.get(workout.id)
        panel = pygame.Rect(self.rect.centerx - 430, 92, 860, 580)
        rounded(SCREEN, panel, CARD, 28)
        txt(SCREEN, f"LEVEL {workout.level}", panel.x + 54, panel.y + 50, 13, workout.accent, True)
        txt(SCREEN, workout.title, panel.x + 54, panel.y + 80, 38, INK, True)
        txt(SCREEN, workout.subtitle, panel.x + 54, panel.y + 131, 17, MUTED)
        estimates = max(1, round(workout.rounds * 5 / 60))
        stats = [("LEVEL", workout.level), ("TOTAL MOVES", workout.rounds), ("MOVE TYPES", len(moves)), ("EST. TIME", f"~{estimates} MIN")]
        for i, (label, value) in enumerate(stats):
            x = panel.x + 54 + i * 190
            rounded(SCREEN, (x, panel.y + 188, 166, 76), PAPER, 13)
            txt(SCREEN, value, x + 16, panel.y + 204, 22, INK, True)
            txt(SCREEN, label, x + 16, panel.y + 239, 11, MUTED, True)
        txt(SCREEN, "MOVE TYPES IN THIS SESSION", panel.x + 54, panel.y + 299, 12, MUTED, True)
        for i, move in enumerate(moves):
            x = panel.x + 54 + (i % 3) * 245
            y = panel.y + 328 + (i // 3) * 42
            rounded(SCREEN, (x, y, 228, 31), WASH_CORAL if move.hand == "RIGHT" else WASH_TEAL, 9)
            txt(SCREEN, move.key.upper(), x + 14, y + 8, 13, workout.accent, True)
            txt(SCREEN, f"{move.label} ({move.hand})", x + 40, y + 8, 13, INK, True)
        txt(SCREEN, "LAST PLAYED", panel.x + 54, panel.y + 474, 11, MUTED, True)
        if last:
            played = datetime.fromisoformat(last["played_at"]).strftime("%d %b %Y, %H:%M")
            txt(SCREEN, f"{played}  |  Score {last['score']:,}  |  {last['accuracy']}% accuracy", panel.x + 54, panel.y + 495, 15, INK, True)
        else:
            txt(SCREEN, "Not played yet", panel.x + 54, panel.y + 495, 15, MUTED, True)
        rounded(SCREEN, (self.rect.centerx - 230, 600, 220, 46), workout.accent, 12)
        txt(SCREEN, "START SESSION", self.rect.centerx - 120, 623, 13, (255, 255, 255), True, "center")
        rounded(SCREEN, (self.rect.centerx + 10, 600, 220, 46), PAPER, 12)
        pygame.draw.rect(SCREEN, LINE, (self.rect.centerx + 10, 600, 220, 46), 1, 12)
        txt(SCREEN, "CANCEL", self.rect.centerx + 120, 623, 13, INK, True, "center")
        txt(SCREEN, "ENTER to start  |  ESC to cancel", panel.centerx, panel.bottom - 24, 12, MUTED, True, "midbottom")

    def draw_play(self):
        self.background(); workout = self.home_challenges[self.workout_index]
        elapsed = int(time.monotonic() - self.start_time)
        remaining = max(0, self.deadline - time.monotonic())
        if remaining <= 0:
            self.misses += 1; self.total += 1; self.streak = 0; self.feedback = "TIME OUT"; self.feedback_until = time.monotonic() + .6
            if self.total >= workout.rounds: self.complete()
            else: self.prompt_next()
            remaining = 5
        txt(SCREEN, workout.title.upper(), 56, 36, 13, workout.accent, True)
        txt(SCREEN, f"{elapsed // 60:02}:{elapsed % 60:02}", 56, 62, 31, INK, True)
        txt(SCREEN, f"SCORE  {self.score:,}", self.rect.width - 56, 42, 16, INK, True, "topright")
        txt(SCREEN, f"STREAK  ×{self.streak}", self.rect.width - 56, 69, 13, MUTED, True, "topright")
        rounded(SCREEN, (56, 122, self.rect.width - 112, 8), LINE, 4)
        pygame.draw.rect(SCREEN, workout.accent, (56, 122, (self.rect.width - 112) * self.total / workout.rounds, 8), border_radius=4)
        txt(SCREEN, f"MOVE {min(self.total + 1, workout.rounds)} / {workout.rounds}", 56, 145, 13, MUTED, True)
        self.draw_heart_rate_panel()
        center = (self.rect.centerx, 385)
        pygame.draw.circle(SCREEN, WASH_CORAL, center, 195)
        pygame.draw.circle(SCREEN, CARD, center, 158)
        transition = min(1.0, (time.monotonic() - self.prompt_transition_started) / .34) if self.prompt_transition_started else 1.0
        transitioning = transition < 1.0
        if transitioning and self.completed_move:
            old_action = self.action_image(self.completed_move)
            if old_action:
                old_art = pygame.transform.smoothscale(old_action, (128, 205))
                old_art.set_alpha(int((1.0 - transition) * 190))
                old_x = center[0] - 150 * transition
                SCREEN.blit(old_art, old_art.get_rect(midtop=(old_x, 273)))
            # A fast accent streak makes the accepted move feel like it swipes away.
            streak = pygame.Surface((245, 8), pygame.SRCALPHA)
            pygame.draw.rect(streak, (*TEAL, int((1.0 - transition) * 170)), streak.get_rect(), border_radius=4)
            SCREEN.blit(streak, (center[0] - 20 + transition * 180, 382))
        action = self.action_image(self.current)
        if action:
            # Keep the source art intact and only show it for moves with an
            # explicitly mapped illustration. Unknown/custom moves stay text-only.
            txt(SCREEN, self.current.category.upper(), center[0], 230, 13, workout.accent, True, "midtop")
            txt(SCREEN, self.current.label, center[0], 251, 25, INK, True, "midtop")
            illustration = pygame.transform.smoothscale(action, (128, 205))
            if transitioning:
                illustration.set_alpha(int(transition * 255))
            # The new action settles into place with a small bounce.
            image_y = 273 - (1.0 - transition) * 22 - math.sin(transition * math.pi) * 7
            SCREEN.blit(illustration, illustration.get_rect(midtop=(center[0], image_y)))
            key_y, key_label_y, instruction_y, meter_y, time_y, feedback_y = 486, 563, 579, 608, 632, 678
        else:
            txt(SCREEN, self.current.category.upper(), center[0], 253, 13, workout.accent, True, "midtop")
            txt(SCREEN, self.current.label, center[0], 300, 48, INK, True, "midtop")
            txt(SCREEN, f"{self.current.hand} SIDE", center[0], 365, 15, MUTED, True, "midtop")
            key_y, key_label_y, instruction_y, meter_y, time_y, feedback_y = 404, 481, 497, 536, 560, 610
        # The keycap intentionally stays bright in both system themes.
        key_bounce = int(math.sin(transition * math.pi) * 5) if transitioning else 0
        rounded(SCREEN, (center[0] - 70, key_y - key_bounce, 140, 68), CORAL, 16)
        txt(SCREEN, self.current.key.upper(), center[0], key_y + 34 - key_bounce, 36, (255, 255, 255), True, "center")
        txt(SCREEN, "PRESS THIS KEY", center[0], key_label_y, 12, CORAL, True, "midtop")
        instruction = "PRESS THE MATCHING KEY" if self.input_mode == "keyboard" else "PERFORM THE RECORDED MOTION"
        txt(SCREEN, instruction, center[0], instruction_y, 13, MUTED, True, "midtop")
        # Five-second response meter
        rounded(SCREEN, (center[0] - 160, meter_y, 320, 10), LINE, 5)
        pygame.draw.rect(SCREEN, TEAL if remaining > 1 else CORAL, (center[0] - 160, meter_y, 320 * remaining / 5, 10), border_radius=5)
        txt(SCREEN, f"{remaining:0.1f}s", center[0], time_y, 17, INK, True, "midtop")
        if time.monotonic() < self.feedback_until:
            txt(SCREEN, self.feedback, center[0], feedback_y, 16, CORAL if "WRONG" in self.feedback or "OUT" in self.feedback else TEAL, True, "midtop")
        if self.dev_playback:
            self.draw_motion_debug_panel()
        mode_label = "KEYBOARD" if self.input_mode == "keyboard" else ("JOY-CON MOTION" if self.joycons.connected else "JOY-CON NOT CONNECTED")
        txt(SCREEN, f"{mode_label}  •  M switch input  •  ESC end session", 56, self.rect.height - 44, 12, MUTED, True)

    def draw_motion_debug_panel(self):
        """Development-only raw Joy-Con telemetry; not shown in normal sessions."""
        panel = pygame.Rect(56, 175, 280, 210)
        rounded(SCREEN, panel, PANEL, 14)
        txt(SCREEN, "DEV / LIVE CONTROLLER MOTION", panel.x + 14, panel.y + 14, 11, GOLD, True)
        for index, hand in enumerate(("LEFT", "RIGHT")):
            frames = self.live_frames.get(hand, [])
            y = panel.y + 43 + index * 78
            color = TEAL if hand == "LEFT" else CORAL
            txt(SCREEN, hand, panel.x + 14, y, 12, color, True)
            if not frames:
                txt(SCREEN, "Waiting for IMU data", panel.x + 14, y + 18, 11, MUTED)
                continue
            last = frames[-1]
            txt(SCREEN, "A %+.1f  %+.1f  %+.1f" % last.accel, panel.x + 14, y + 18, 10, (255, 255, 255), True)
            txt(SCREEN, "G %+.1f  %+.1f  %+.1f" % last.gyro, panel.x + 14, y + 33, 10, (255, 255, 255), True)
            values = [frame.accel[0] for frame in frames]
            if len(values) > 1:
                scale = max(1, max(abs(value) for value in values))
                points = [(panel.x + 14 + 245 * i / (len(values) - 1), y + 69 - value / scale * 13) for i, value in enumerate(values)]
                pygame.draw.lines(SCREEN, color, False, points, 2)
        txt(SCREEN, "Raw accelerometer / gyroscope feed", panel.x + 14, panel.bottom - 13, 10, MUTED)

    def draw_summary(self):
        self.background(); rate = round(100 * self.hits / max(1, self.hits + self.misses))
        panel = pygame.Rect(self.rect.centerx - 330, 105, 660, 520); rounded(SCREEN, panel, CARD, 28)
        txt(SCREEN, "SESSION COMPLETE", panel.centerx, 152, 13, TEAL, True, "midtop")
        txt(SCREEN, "That round is in the books.", panel.centerx, 184, 33, INK, True, "midtop")
        txt(SCREEN, f"{self.score:,}", panel.centerx, 267, 58, CORAL, True, "midtop")
        txt(SCREEN, "TOTAL SCORE", panel.centerx, 337, 12, MUTED, True, "midtop")
        last = self.session_history.get(self.home_challenges[self.workout_index].id, {})
        heart_rate = "--" if last.get("heart_rate_average") is None else f"{last['heart_rate_average']} / {last['heart_rate_max']}"
        stats = [("CLEAN MOVES", self.hits), ("ACCURACY", f"{rate}%"), ("AVG / MAX HR", heart_rate)]
        for i, (label, value) in enumerate(stats):
            x = panel.x + 120 + i * 210
            txt(SCREEN, value, x, 415, 28, INK, True, "midtop")
            txt(SCREEN, label, x, 455, 11, MUTED, True, "midtop")
        txt(SCREEN, "ENTER  BACK TO LIBRARY", panel.centerx, 555, 13, MUTED, True, "midtop")

    def draw_dev(self):
        self.background(); self.topbar("Developer mode", "PULSEBOX / TOOLING")
        txt(SCREEN, "Challenges", 56, 128, 34, INK, True)
        txt(SCREEN, "Create, edit, activate, or remove challenges shown in the library.", 56, 170, 16, MUTED)
        rounded(SCREEN, (56, 192, 245, 42), BLUE, 11)
        txt(SCREEN, "+  CREATE NEW CHALLENGE", 178, 213, 12, (255, 255, 255), True, "center")
        for index, challenge_type in enumerate(CHALLENGE_TYPES):
            selected_type = challenge_type == self.dev_type_filter
            chip = pygame.Rect(315 + index * 80, 200, 74, 26)
            rounded(SCREEN, chip, BLUE if selected_type else CARD, 8)
            txt(SCREEN, challenge_type.upper(), chip.centerx, chip.centery, 10, (255, 255, 255) if selected_type else MUTED, True, "center")
        table = pygame.Rect(56, 250, self.rect.width - 112, self.rect.height - 340)
        rounded(SCREEN, table, CARD, 18)
        headers = [(78, "CHALLENGE"), (430, "TYPE"), (510, "LEVEL"), (630, "TOTAL MOVES"), (760, "SELECTED MOVES"), (900, "STATUS")]
        for x, label in headers: txt(SCREEN, label, x, 270, 11, MUTED, True)
        self.keep_dev_challenge_visible()
        visible = self.visible_dev_challenge_count()
        for row_index, workout in enumerate(self.dev_challenges[self.dev_scroll:self.dev_scroll + visible]):
            index = self.dev_scroll + row_index
            y = 291 + row_index * 46
            selected = index == self.dev_index
            rounded(SCREEN, (68, y, self.rect.width - 148, 38), WASH_TEAL if selected else PAPER, 10)
            if selected:
                pygame.draw.rect(SCREEN, TEAL, (68, y, 5, 38), border_radius=3)
            txt(SCREEN, workout.title, 82, y + 10, 15, INK, True)
            txt(SCREEN, workout.sport.upper(), 430, y + 12, 11, BLUE, True)
            txt(SCREEN, f"LEVEL {workout.level}", 510, y + 12, 12, workout.accent, True)
            txt(SCREEN, workout.rounds, 650, y + 12, 13, INK, True)
            txt(SCREEN, len(self.challenge_moves(workout)), 790, y + 12, 13, INK, True)
            txt(SCREEN, "ACTIVE" if workout.is_active else "INACTIVE", 900, y + 12, 11, TEAL if workout.is_active else MUTED, True)
            rounded(SCREEN, (self.rect.width - 350, y + 4, 90, 30), TEAL, 8)
            txt(SCREEN, "TEST", self.rect.width - 305, y + 19, 11, (255, 255, 255), True, "center")
            rounded(SCREEN, (self.rect.width - 250, y + 4, 90, 30), BLUE, 8)
            txt(SCREEN, "EDIT", self.rect.width - 205, y + 19, 11, (255, 255, 255), True, "center")
            rounded(SCREEN, (self.rect.width - 150, y + 4, 90, 30), WASH_CORAL, 8)
            txt(SCREEN, "DELETE", self.rect.width - 105, y + 19, 11, RED, True, "center")
        if len(self.dev_challenges) > visible:
            track = pygame.Rect(table.right - 14, 287, 5, visible * 46 - 8)
            pygame.draw.rect(SCREEN, LINE, track, border_radius=3)
            thumb_h = max(24, track.height * visible / len(self.dev_challenges))
            thumb_y = track.y + (track.height - thumb_h) * self.dev_scroll / max(1, len(self.dev_challenges) - visible)
            pygame.draw.rect(SCREEN, BLUE, (track.x, thumb_y, track.width, thumb_h), border_radius=3)
        rounded(SCREEN, (56, self.rect.height - 72, 160, 38), PANEL, 10)
        txt(SCREEN, "BACK", 136, self.rect.height - 53, 12, (255, 255, 255), True, "center")
        txt(SCREEN, "Mouse wheel / D-pad scroll    Enter edits selected challenge", 236, self.rect.height - 53, 12, MUTED, True, "midleft")

    def draw_dev_edit(self):
        self.background(); self.topbar("Training set editor", "PULSEBOX / TOOLING")
        draft = self.dev_draft
        txt(SCREEN, "Create challenge" if draft["id"].startswith("challenge_") else "Edit challenge", 56, 128, 32, INK, True)
        txt(SCREEN, "Choose moves, set their frequency, then Pulsebox builds a low-level-first sequence.", 56, 166, 15, MUTED)
        txt(SCREEN, "NAME", 56, 180, 11, MUTED, True)
        rounded(SCREEN, (56, 198, 420, 42), CARD, 10)
        txt(SCREEN, draft["title"] + ("|" if self.dev_name_focus else ""), 70, 219, 16, INK, True, "midleft")
        txt(SCREEN, "LEVEL", 535, 180, 11, MUTED, True)
        rounded(SCREEN, (535, 198, 36, 36), PAPER, 8); txt(SCREEN, "-", 553, 216, 18, INK, True, "center")
        rounded(SCREEN, (580, 198, 86, 36), CARD, 8); txt(SCREEN, draft["level"], 623, 216, 16, INK, True, "center")
        rounded(SCREEN, (675, 198, 36, 36), PAPER, 8); txt(SCREEN, "+", 693, 216, 18, INK, True, "center")
        txt(SCREEN, "TOTAL MOVES", 785, 180, 11, MUTED, True)
        rounded(SCREEN, (785, 198, 36, 36), PAPER, 8); txt(SCREEN, "-", 803, 216, 18, INK, True, "center")
        rounded(SCREEN, (830, 198, 126, 36), CARD, 8); txt(SCREEN, draft["rounds"], 893, 216, 16, INK, True, "center")
        rounded(SCREEN, (965, 198, 36, 36), PAPER, 8); txt(SCREEN, "+", 983, 216, 18, INK, True, "center")
        txt(SCREEN, "CHALLENGE TYPE", 1040, 180, 11, MUTED, True)
        rounded(SCREEN, (1040, 198, 170, 36), BLUE, 9)
        txt(SCREEN, draft["sport"].upper() + "  / CLICK", 1125, 216, 12, (255, 255, 255), True, "center")
        rounded(SCREEN, (1040, 240, 170, 22), TEAL if draft["is_active"] else PANEL, 7)
        txt(SCREEN, "ACTIVE" if draft["is_active"] else "INACTIVE", 1125, 251, 10, (255, 255, 255) if draft["is_active"] else MUTED, True, "center")
        txt(SCREEN, "AVAILABLE MOVES — CLICK A ROW TO SELECT", 56, 252, 11, MUTED, True)
        txt(SCREEN, "FREQUENCY", 570, 252, 11, MUTED, True)
        for index, move in enumerate(self.moves):
            y = 265 + index * 38
            selected = move.id in draft["selected"]
            rounded(SCREEN, (56, y, 350, 32), WASH_TEAL if selected else CARD, 8)
            txt(SCREEN, "✓" if selected else "+", 73, y + 16, 15, TEAL if selected else MUTED, True, "center")
            txt(SCREEN, move.label, 94, y + 16, 14, INK, selected, "midleft")
            txt(SCREEN, f"L{move.min_level}", 365, y + 16, 11, move.category == "Punch" and CORAL or TEAL, True, "midright")
            rounded(SCREEN, (570, y + 2, 28, 28), PAPER, 7); txt(SCREEN, "-", 584, y + 16, 15, INK, True, "center")
            rounded(SCREEN, (606, y + 2, 76, 28), CARD, 7); txt(SCREEN, draft["weights"][move.id], 644, y + 16, 13, INK, True, "center")
            rounded(SCREEN, (690, y + 2, 28, 28), PAPER, 7); txt(SCREEN, "+", 704, y + 16, 15, INK, True, "center")
        preview = self.training_preview()
        rounded(SCREEN, (760, 265, self.rect.width - 816, 248), CARD, 16)
        txt(SCREEN, "CALCULATED ORDER", 782, 285, 11, MUTED, True)
        txt(SCREEN, f"{len(preview)} moves", 782, 311, 23, BLUE, True)
        labels = [f"L{move.min_level} {move.label}" for move in preview]
        shown = "  →  ".join(labels[:12]) or "Select one or more moves"
        txt(SCREEN, shown, 782, 355, 12, INK, False)
        if len(labels) > 12: txt(SCREEN, f"… then {len(labels) - 12} more", 782, 382, 12, MUTED)
        txt(SCREEN, "Moves are allocated from frequency and grouped by level: low levels first.", 782, 450, 11, MUTED)
        rounded(SCREEN, (self.rect.width - 270, self.rect.height - 72, 105, 38), PAPER, 10)
        txt(SCREEN, "CANCEL", self.rect.width - 218, self.rect.height - 53, 12, INK, True, "center")
        rounded(SCREEN, (self.rect.width - 150, self.rect.height - 72, 105, 38), BLUE, 10)
        txt(SCREEN, "SAVE", self.rect.width - 98, self.rect.height - 53, 12, (255, 255, 255), True, "center")

    def draw_heart_rate_panel(self):
        """Live HR and a compact history chart while a session is running."""
        panel = pygame.Rect(self.rect.width - 285, 164, 225, 105)
        rounded(SCREEN, panel, CARD, 14)
        snapshot = self.watch.snapshot()
        bpm = snapshot["heart_rate"]
        txt(SCREEN, "LIVE HEART RATE", panel.x + 14, panel.y + 12, 11, MUTED, True)
        txt(SCREEN, f"{bpm if bpm else '--'} BPM", panel.x + 14, panel.y + 34, 26, CORAL if bpm else MUTED, True)
        # Keep the workout screen usable if an older receiver instance is still
        # loaded during development; a restart will then restore the HR graph.
        samples = self.watch.recent_samples() if hasattr(self.watch, "recent_samples") else []
        chart = pygame.Rect(panel.x + 15, panel.y + 72, panel.width - 30, 23)
        pygame.draw.line(SCREEN, LINE, chart.bottomleft, chart.bottomright, 1)
        if len(samples) > 1:
            values = [sample["bpm"] for sample in samples]
            low, high = min(values), max(values)
            spread = max(8, high - low)
            points = [(chart.x + chart.width * i / (len(values) - 1), chart.bottom - (value - low) / spread * chart.height) for i, value in enumerate(values)]
            pygame.draw.lines(SCREEN, BLUE, False, points, 2)
        elif not bpm:
            txt(SCREEN, "Connect a HR broadcast to start", chart.x, chart.y + 4, 10, MUTED)

    def draw_watch_details(self):
        self.background(); self.topbar("Watch connection", "PULSEBOX / BLE")
        panel = pygame.Rect(self.rect.centerx - 330, 110, 660, 480)
        rounded(SCREEN, panel, CARD, 28)
        snapshot = self.watch.snapshot(); device = snapshot["device"]; details = snapshot["details"]
        state = snapshot["state"]
        txt(SCREEN, "CONNECTED" if state == "connected" else state.upper(), panel.centerx, 154, 14, BLUE if state == "connected" else RED, True, "midtop")
        txt(SCREEN, device.get("name", "No watch selected"), panel.centerx, 187, 30, INK, True, "midtop")
        txt(SCREEN, f"LIVE HR  {snapshot['heart_rate'] or '--'} BPM", panel.centerx, 239, 23, CORAL, True, "midtop")
        rows = [
            ("BATTERY", f"{details['battery_percent']}%" if "battery_percent" in details else "Not exposed by broadcast"),
            ("MODEL", details.get("model", "Not exposed by broadcast")),
            ("MANUFACTURER", details.get("manufacturer", "Not exposed by broadcast")),
            ("LOCAL DATE / TIME", datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")),
            ("LAST READING", snapshot["last_seen"] or "No reading yet"),
            ("TODAY'S STEPS", "Not available via BLE HR broadcast"),
        ]
        for index, (label, value) in enumerate(rows):
            y = 290 + index * 38
            txt(SCREEN, label, panel.x + 54, y, 11, MUTED, True)
            txt(SCREEN, value, panel.x + 215, y, 13, INK)
        if snapshot["error"]:
            txt(SCREEN, snapshot["error"], panel.centerx, 505, 12, RED, True, "midtop")
        txt(SCREEN, "CLICK THE WATCH ICON OR PRESS ESC TO GO BACK", panel.centerx, 555, 12, MUTED, True, "midtop")

    def draw(self):
        if self.screen == "profile": self.draw_profile()
        elif self.screen == "home": self.draw_home()
        elif self.screen == "workout_details": self.draw_workout_details()
        elif self.screen == "play": self.draw_play()
        elif self.screen == "summary": self.draw_summary()
        elif self.screen == "dev": self.draw_dev()
        elif self.screen == "dev_edit": self.draw_dev_edit()
        elif self.screen == "watch_details": self.draw_watch_details()
        if self.screen != "watch_details": self.draw_watch_indicator()
        if self.error_message:
            rounded(SCREEN, (34, self.rect.height - 94, self.rect.width - 68, 30), (90, 34, 34), 8)
            txt(SCREEN, self.error_message, 48, self.rect.height - 79, 12, (255, 255, 255), True)
        present()

    def run(self):
        while self.running:
            if time.monotonic() >= self.theme_check_at:
                apply_system_theme()
                self.theme_check_at = time.monotonic() + 2
            for event in pygame.event.get():
                try:
                    self.event(event)
                except Exception as exc:
                    self.error_message = report(LOGGER, "Input handling", exc)
            try:
                self.update_controller()
            except Exception as exc:
                self.error_message = report(LOGGER, "Controller update", exc)
            try:
                self.draw()
            except Exception as exc:
                self.error_message = report(LOGGER, "Screen render", exc)
                SCREEN.fill((35, 20, 24))
                txt(SCREEN, self.error_message, 30, 30, 16, (255, 170, 160))
                present()
            CLOCK.tick(60)
        pygame.quit()


if __name__ == "__main__":
    try:
        App().run()
    except Exception as exc:
        LOGGER.exception("Startup failed", exc_info=(type(exc), exc, exc.__traceback__))
        raise
