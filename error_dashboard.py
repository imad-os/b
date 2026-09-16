"""Standalone dark-mode dashboard for Pulsebox log errors.

Run with: python error_dashboard.py
"""
import re
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

import pygame


ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "logs"
HEADER = re.compile(r"^(?P<stamp>\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2},\d{3}) \| (?P<level>[A-Z]+) \| (?P<message>.*)$")

BG, SURFACE, PANEL = (12, 16, 23), (22, 29, 40), (30, 39, 53)
TEXT, MUTED, LINE = (238, 242, 248), (151, 163, 181), (57, 70, 89)
BLUE, RED, GOLD, GREEN = (83, 150, 255), (244, 97, 104), (251, 190, 71), (76, 205, 165)


def parse_logs():
    """Read Python logging records and keep traceback lines with their ERROR."""
    records = []
    for path in sorted(LOG_DIR.glob("*.log")):
        current = None
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        for line in lines:
            match = HEADER.match(line)
            if match:
                if current and current["level"] in ("ERROR", "CRITICAL"):
                    records.append(current)
                current = {**match.groupdict(), "source": path.name, "detail_lines": []}
            elif current:
                current["detail_lines"].append(line)
        if current and current["level"] in ("ERROR", "CRITICAL"):
            records.append(current)

    for record in records:
        record["date"] = record["stamp"][:10]
        record["category"] = category_for(record)
        detail = "\n".join(record["detail_lines"])
        record["full"] = f"{record['stamp']} | {record['level']} | {record['message']}\n{detail}".rstrip()
    return sorted(records, key=lambda item: item["stamp"], reverse=True)


def category_for(record):
    """Prefer application context over the final Python exception name."""
    message = record["message"]
    if message.endswith(" failed"):
        return message[:-7]
    for line in reversed(record["detail_lines"]):
        if ":" in line and not line.lstrip().startswith("File "):
            return line.strip().split(":", 1)[0]
    return record["source"].removesuffix(".log")


def font(size, bold=False, mono=False):
    return pygame.font.SysFont("consolas" if mono else "segoeui", size, bold=bold)


def draw_text(surface, value, pos, size=16, color=TEXT, bold=False, anchor="topleft", mono=False):
    image = font(size, bold, mono).render(str(value), True, color)
    surface.blit(image, image.get_rect(**{anchor: pos}))


def rounded(surface, rect, color, radius=12, width=0):
    pygame.draw.rect(surface, color, pygame.Rect(rect), width, radius)


def wrapped_lines(value, max_width, size=14, mono=False):
    words, lines, line = str(value).replace("\t", "    ").split(), [], ""
    active_font = font(size, mono=mono)
    for word in words:
        candidate = f"{line} {word}".strip()
        if line and active_font.size(candidate)[0] > max_width:
            lines.append(line); line = word
        else:
            line = candidate
    if line:
        lines.append(line)
    return lines or [""]


class Dashboard:
    def __init__(self):
        pygame.init()
        pygame.display.set_caption("Pulsebox Error Dashboard")
        self.screen = pygame.display.set_mode((1280, 760), pygame.RESIZABLE)
        self.clock = pygame.time.Clock()
        self.records = []
        self.dates = []
        self.date_index = 0
        self.category = "All errors"
        self.selected = 0
        self.modal = False
        self.running = True
        self.reload()

    @property
    def rect(self):
        return self.screen.get_rect()

    def reload(self):
        previous_date = self.current_date
        self.records = parse_logs()
        self.dates = sorted({item["date"] for item in self.records}, reverse=True)
        self.date_index = self.dates.index(previous_date) if previous_date in self.dates else 0
        self.category = "All errors"
        self.selected = 0

    @property
    def current_date(self):
        return self.dates[self.date_index] if self.dates else None

    @property
    def date_records(self):
        return [item for item in self.records if item["date"] == self.current_date]

    @property
    def categories(self):
        counts = Counter(item["category"] for item in self.date_records)
        return [("All errors", len(self.date_records)), *sorted(counts.items(), key=lambda item: (-item[1], item[0]))]

    @property
    def filtered(self):
        """Collapse repeated identical failures, retaining newest record and count."""
        items = self.date_records
        if self.category != "All errors":
            items = [item for item in items if item["category"] == self.category]
        unique = {}
        for item in items:  # Input is newest first, so first item is retained.
            signature = (item["source"], item["category"], item["message"], tuple(item["detail_lines"]))
            if signature not in unique:
                grouped = dict(item)
                grouped["occurrences"] = 0
                unique[signature] = grouped
            unique[signature]["occurrences"] += 1
        return list(unique.values())

    @property
    def selected_record(self):
        items = self.filtered
        if not items:
            return None
        self.selected = max(0, min(self.selected, len(items) - 1))
        return items[self.selected]

    def change_date(self, direction):
        if self.dates:
            self.date_index = max(0, min(len(self.dates) - 1, self.date_index + direction))
            self.category, self.selected = "All errors", 0

    def event(self, event):
        if event.type == pygame.QUIT:
            self.running = False
        elif event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode(event.size, pygame.RESIZABLE)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE and self.modal:
                self.modal = False
            elif event.key == pygame.K_ESCAPE:
                self.running = False
            elif event.key == pygame.K_LEFT:
                self.change_date(1)
            elif event.key == pygame.K_RIGHT:
                self.change_date(-1)
            elif event.key == pygame.K_DOWN:
                self.selected = min(len(self.filtered) - 1, self.selected + 1)
            elif event.key == pygame.K_UP:
                self.selected = max(0, self.selected - 1)
            elif event.key in (pygame.K_RETURN, pygame.K_SPACE) and self.selected_record:
                self.modal = True
            elif event.key == pygame.K_r:
                self.reload()
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            self.click(event.pos)

    def click(self, position):
        if self.modal:
            self.modal = False
            return
        w = self.rect.width
        if pygame.Rect(44, 100, 44, 38).collidepoint(position):
            self.change_date(1); return
        if pygame.Rect(310, 100, 44, 38).collidepoint(position):
            self.change_date(-1); return
        if pygame.Rect(w - 154, 100, 110, 38).collidepoint(position):
            self.reload(); return
        for index, (category, _count) in enumerate(self.categories):
            if pygame.Rect(44, 192 + index * 42, 260, 34).collidepoint(position):
                self.category, self.selected = category, 0
                return
        for index, _record in enumerate(self.filtered[:10]):
            if pygame.Rect(328, 192 + index * 51, w - 372, 44).collidepoint(position):
                self.selected = index
                return
        if pygame.Rect(w - 260, self.rect.height - 73, 216, 38).collidepoint(position) and self.selected_record:
            self.modal = True

    def draw(self):
        self.screen.fill(BG); w, h = self.rect.size
        draw_text(self.screen, "PULSEBOX", (44, 35), 14, BLUE, True)
        draw_text(self.screen, "Error dashboard", (44, 60), 30, TEXT, True)
        draw_text(self.screen, "Local logs only - R reload - arrows navigate - Enter opens details", (44, 141), 13, MUTED)
        rounded(self.screen, (44, 100, 44, 38), PANEL); draw_text(self.screen, "<", (66, 119), 20, TEXT, True, "center")
        date_label = self.current_date or "No logged errors"
        rounded(self.screen, (98, 100, 202, 38), SURFACE); draw_text(self.screen, date_label, (199, 119), 15, TEXT, True, "center")
        rounded(self.screen, (310, 100, 44, 38), PANEL); draw_text(self.screen, ">", (332, 119), 20, TEXT, True, "center")
        rounded(self.screen, (w - 154, 100, 110, 38), PANEL); draw_text(self.screen, "RELOAD", (w - 99, 119), 12, BLUE, True, "center")

        rounded(self.screen, (44, 174, 260, h - 218), SURFACE, 16)
        draw_text(self.screen, "CATEGORIES", (62, 193), 11, MUTED, True)
        for index, (category, count) in enumerate(self.categories):
            row = pygame.Rect(52, 216 + index * 42, 244, 34)
            active = category == self.category
            if active: rounded(self.screen, row, (37, 61, 91), 9)
            draw_text(self.screen, category[:24], (row.x + 10, row.centery), 13, TEXT if active else MUTED, active, "midleft")
            draw_text(self.screen, count, (row.right - 12, row.centery), 13, BLUE if active else MUTED, True, "midright")

        rounded(self.screen, (328, 174, w - 372, h - 218), SURFACE, 16)
        draw_text(self.screen, f"UNIQUE ERRORS  /  {self.category.upper()}", (348, 193), 11, MUTED, True)
        items = self.filtered
        if not items:
            draw_text(self.screen, "No errors for this date.", (w // 2 + 20, 320), 18, MUTED, True, "center")
        for index, record in enumerate(items[:10]):
            row = pygame.Rect(340, 216 + index * 51, w - 396, 44)
            if index == self.selected: rounded(self.screen, row, PANEL, 10)
            dot = RED if record["level"] == "ERROR" else GOLD
            pygame.draw.circle(self.screen, dot, (row.x + 13, row.centery), 5)
            draw_text(self.screen, record["stamp"][11:23], (row.x + 27, row.y + 7), 12, MUTED, True)
            draw_text(self.screen, record["category"], (row.x + 115, row.y + 7), 13, TEXT, True)
            draw_text(self.screen, f"x{record['occurrences']}", (row.right - 12, row.y + 7), 14, RED, True, "topright")
            summary = wrapped_lines(record["message"], row.width - 56, 12)[0]
            draw_text(self.screen, summary, (row.x + 27, row.y + 26), 12, MUTED)

        record = self.selected_record
        if record:
            draw_text(self.screen, f"Selected: {record['source']} - {record['category']} - {record['occurrences']} occurrence(s)", (348, h - 73), 13, MUTED)
            rounded(self.screen, (w - 260, h - 73, 216, 38), BLUE, 10)
            draw_text(self.screen, "VIEW FULL ERROR", (w - 152, h - 54), 12, BG, True, "center")
        if self.modal and record:
            self.draw_modal(record)
        pygame.display.flip()

    def draw_modal(self, record):
        overlay = pygame.Surface(self.rect.size, pygame.SRCALPHA); overlay.fill((0, 0, 0, 185)); self.screen.blit(overlay, (0, 0))
        panel = pygame.Rect(85, 65, self.rect.width - 170, self.rect.height - 130)
        rounded(self.screen, panel, (17, 23, 32), 18); pygame.draw.rect(self.screen, BLUE, panel, 1, 18)
        draw_text(self.screen, "FULL ERROR MESSAGE", (panel.x + 26, panel.y + 25), 13, BLUE, True)
        draw_text(self.screen, f"{record['source']}  |  latest: {record['stamp']}  |  {record['category']}  |  {record['occurrences']} occurrence(s)", (panel.x + 26, panel.y + 52), 13, MUTED)
        y = panel.y + 88
        for raw_line in record["full"].splitlines():
            for line in wrapped_lines(raw_line or " ", panel.width - 52, 13, mono=True):
                if y > panel.bottom - 45:
                    draw_text(self.screen, "Message truncated in viewer.", (panel.x + 26, y), 12, GOLD); break
                draw_text(self.screen, line, (panel.x + 26, y), 13, TEXT, mono=True); y += 19
        draw_text(self.screen, "CLICK ANYWHERE OR PRESS ESC TO CLOSE", (panel.centerx, panel.bottom - 22), 12, MUTED, True, "center")

    def run(self):
        while self.running:
            for event in pygame.event.get():
                self.event(event)
            self.draw(); self.clock.tick(60)
        pygame.quit()


if __name__ == "__main__":
    Dashboard().run()
