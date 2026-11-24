"""The Fleet board table: one row per board, worst first."""

from __future__ import annotations

from datetime import datetime, timedelta

from rich.text import Text
from textual.widgets import DataTable

from tailtop.data.fleet import Board, Verdict, since, verdict
from tailtop.data.fleet_poller import USER_HINT

DASH = "–"

STATE_STYLE = {
    Verdict.DOWN: "bold #ff7e88",
    Verdict.USELESS: "bold #ff7e88",
    Verdict.UNREACHABLE: "#f0c674",
    Verdict.REBOOTING: "#f0c674",
    Verdict.WARN: "#f0c674",
    Verdict.OK: "#7be39b",
    Verdict.PENDING: "dim",
}


def fmt_since(td: timedelta | None) -> str:
    if td is None:
        return DASH
    s = td.total_seconds()
    if s >= 86400:
        return f"{int(s // 86400)}d"
    if s >= 3600:
        return f"{int(s // 3600)}h"
    if s >= 60:
        return f"{int(s // 60)}m"
    return "<1m"


def row_cells(board: Board, now: datetime) -> list[str]:
    v = verdict(board, now=now)
    h = board.health if board.health and not board.health.error else None

    def num(value, fmt: str) -> str:
        return DASH if value is None else fmt.format(value)

    state = v.value
    if v is Verdict.UNREACHABLE and board.health and board.health.error == USER_HINT:
        state = "unreachable · set user"
    return [
        board.name,
        state,
        fmt_since(since(board, now=now)),
        num(h.temp_c if h else None, "{:.0f}°"),
        num(h.load1 if h else None, "{:.2f}"),
        num(h.mem_pct if h else None, "{:.0f}%"),
        num(h.disk_pct if h else None, "{:.0f}%"),
    ]


class FleetTable(DataTable):
    COLUMNS = ("board", "state", "since", "temp", "load", "mem", "disk")

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.add_columns(*self.COLUMNS)
        self._names: list[str] = []

    def set_boards(self, boards: list[Board], now: datetime) -> None:
        keep = self.selected_name()
        self.clear()
        self._names = []
        for b in boards:
            cells = row_cells(b, now)
            style = STATE_STYLE[verdict(b, now=now)]
            self.add_row(
                Text(cells[0], style="bold" if style != "dim" else "dim"),
                Text(cells[1], style=style),
                *(Text(c, style="dim" if c == DASH else "") for c in cells[2:]),
                key=b.name,
            )
            self._names.append(b.name)
        if keep in self._names:
            self.select_board(keep)

    def board_names(self) -> list[str]:
        return list(getattr(self, "_names", []))

    def row_text(self, name: str) -> list[str]:
        return [str(c) for c in self.get_row(name)]

    def select_board(self, name: str) -> None:
        if name in self._names:
            self.move_cursor(row=self._names.index(name))

    def selected_name(self) -> str | None:
        names = getattr(self, "_names", [])
        if not names or self.cursor_row is None or not 0 <= self.cursor_row < len(names):
            return None
        return names[self.cursor_row]
