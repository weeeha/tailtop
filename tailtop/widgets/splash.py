"""Boot splash: chunky pixel TAILTOP with a rainbow gradient and drop-shadow.

Shown while the first ``status`` call to ``tailscaled`` is in flight. Auto-
dismisses on the first status (success or empty), on any keystroke, or after
a short timeout — whichever comes first.
"""

from __future__ import annotations

import colorsys

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Static

# 5×7 pixel font. ``#`` = lit, ``.`` = empty.
_FONT: dict[str, list[str]] = {
    "T": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "..#.."],
    "A": [".###.", "#...#", "#...#", "#####", "#...#", "#...#", "#...#"],
    "I": ["#####", "..#..", "..#..", "..#..", "..#..", "..#..", "#####"],
    "L": ["#....", "#....", "#....", "#....", "#....", "#....", "#####"],
    "O": [".###.", "#...#", "#...#", "#...#", "#...#", "#...#", ".###."],
    "P": ["####.", "#...#", "#...#", "####.", "#....", "#....", "#...."],
}
_GLYPH_W = 5
_GLYPH_H = 7
_GAP = 1
_BLOCK = "██"  # 2 chars per logical pixel ≈ square cell
_EMPTY = "  "


def _hex(h: float, s: float, lightness: float) -> str:
    h = h % 360.0
    s = max(0.0, min(1.0, s))
    lightness = max(0.0, min(1.0, lightness))
    r, g, b = colorsys.hls_to_rgb(h / 360.0, lightness, s)
    return f"#{int(r * 255):02x}{int(g * 255):02x}{int(b * 255):02x}"


def render_banner(word: str, phase: float = 0.0) -> Text:
    """Render ``word`` as a chunky rainbow pixel banner with a drop shadow."""
    chars = [c for c in word.upper() if c in _FONT]
    if not chars:
        return Text("")
    total_px = len(chars) * _GLYPH_W + max(0, len(chars) - 1) * _GAP
    span = max(1, total_px - 1)

    # On-cells from the font.
    on: dict[tuple[int, int], float] = {}
    x = 0
    for ch in chars:
        for r, row in enumerate(_FONT[ch]):
            for c, p in enumerate(row):
                if p == "#":
                    on[(r, x + c)] = (x + c) / span
        x += _GLYPH_W + _GAP

    # Shadow = darker rainbow offset one cell down-right.
    shadow: dict[tuple[int, int], float] = {}
    for (r, c), t in on.items():
        for dr, dc in ((1, 0), (0, 1), (1, 1)):
            pos = (r + dr, c + dc)
            if pos not in on and pos not in shadow:
                shadow[pos] = t

    max_r = max(r for r, _ in on) + 1
    max_c = max(c for _, c in on) + 1
    out = Text()
    for r in range(max_r + 1):
        for c in range(max_c + 1):
            if (r, c) in on:
                hue = on[(r, c)] * 240.0 + phase  # red → blue arc
                out.append(_BLOCK, style=_hex(hue, 0.95, 0.58))
            elif (r, c) in shadow:
                hue = shadow[(r, c)] * 240.0 + phase
                out.append(_BLOCK, style=_hex(hue, 0.75, 0.22))
            else:
                out.append(_EMPTY)
        if r < max_r:
            out.append("\n")
    return out


class SplashScreen(ModalScreen[None]):
    """Boot splash. Dismisses on first status, on key press, or on timeout."""

    DEFAULT_CSS = """
    SplashScreen { align: center middle; background: #0d0d12; }
    SplashScreen #wrap { width: auto; height: auto; align: center middle; }
    SplashScreen #banner { width: auto; height: auto; }
    SplashScreen #caption {
        color: #7e8590; padding-top: 2; text-align: center; width: 100%;
    }
    SplashScreen #hint {
        color: #45484f; padding-top: 1; text-align: center; width: 100%;
    }
    """

    def __init__(self, word: str = "TAILTOP") -> None:
        super().__init__()
        self._word = word
        self._phase = 0.0
        self._tick = 0
        self._message = "warming up tailnet"
        self._dismissed = False

    def compose(self) -> ComposeResult:
        with Vertical(id="wrap"):
            yield Static("", id="banner")
            yield Static("", id="caption")
            yield Static("press any key to skip", id="hint")

    def on_mount(self) -> None:
        self._paint()
        self.set_interval(1 / 18, self._animate)

    def _animate(self) -> None:
        if self._dismissed:
            return
        self._phase = (self._phase + 5.0) % 360.0
        self._tick = (self._tick + 1) % 64
        self._paint()

    def _paint(self) -> None:
        if self._dismissed:
            return
        try:
            banner = self.query_one("#banner", Static)
            caption = self.query_one("#caption", Static)
        except Exception:
            return
        banner.update(render_banner(self._word, self._phase))
        dots = "." * ((self._tick // 4) % 4)
        caption.update(f"{self._message}{dots}")

    def set_message(self, msg: str) -> None:
        self._message = msg
        self._paint()

    def safe_dismiss(self) -> None:
        if self._dismissed:
            return
        self._dismissed = True
        self.dismiss(None)

    def on_key(self, event: events.Key) -> None:
        event.stop()
        self.safe_dismiss()
