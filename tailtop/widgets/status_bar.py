"""Bottom status bar — connection state, identity, counts, active mode."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from tailtop.data.models import Status

_MODE_LABEL = {
    "comfort": ("COMFORT", "#8bb6ff"),
    "cockpit": ("COCKPIT", "#f0c674"),
    "observatory": ("OBSERVATORY", "#c792ea"),
}


class StatusBar(Static):
    def set_state(self, status: Status | None, mode: str, error: str = "") -> None:
        line = Text()

        if error:
            line.append(" ✦ ", style="#ff7e88")
            line.append(error, style="#ff7e88")
        elif status is None:
            line.append(" ◌ ", style="dim")
            line.append("connecting…", style="dim")
        else:
            dot = "●" if status.connected else "○"
            color = "#7be39b" if status.connected else "#6b6f78"
            line.append(f" {dot} ", style=color)
            line.append("Connected" if status.connected else status.backend_state, style=color)
            line.append("   ")
            line.append(status.user_display or "—", style="white")
            line.append("   ")
            line.append(f"{status.online_count}/{status.total_count} online", style="dim")

        label, color = _MODE_LABEL.get(mode, (mode.upper(), "white"))
        tail = Text()
        tail.append("Tab ", style="dim")
        tail.append("mode  ", style="dim")
        tail.append(f"{label} ", style=f"bold {color}")
        tail.append("  ? help  q quit ", style="dim")

        # pad the head and right-align the tail
        line.append("  ")
        self.update(Text.assemble(line, Text(" " * 2), tail))
