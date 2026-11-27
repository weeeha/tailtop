"""Fleet mode: the Linux boards on the tailnet, worst first. Intent: is anything broken."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.widgets import DataTable, Static

from tailtop.data.fleet import Board, Verdict, since, verdict
from tailtop.data.fleet_config import DEFAULT_PATH
from tailtop.data.fleet_poller import FleetHistory
from tailtop.data.models import Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory
from tailtop.widgets.fleet_detail import FleetDetail
from tailtop.widgets.fleet_table import FleetTable, fmt_since

FOOTER = "R restart service  B reboot  s ssh  r probe now  1-4 mode  ? help  q quit"
SUMMARY = (
    ("fleet-boards", "boards"),
    ("fleet-down", "down"),
    ("fleet-useless", "useless"),
    ("fleet-hottest", "hottest"),
    ("fleet-disk", "fullest disk"),
)


class FleetMode(ModeView):
    cadence = 5.0

    BINDINGS = [
        Binding("R", "app.fleet_restart", "Restart service"),
        Binding("B", "app.fleet_reboot", "Reboot"),
    ]

    def __init__(self, config_path: Path = DEFAULT_PATH, **kwargs) -> None:
        super().__init__(**kwargs)
        self.config_path = config_path
        self._boards: dict[str, Board] = {}
        self._history = FleetHistory()
        self._now: datetime | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("▌ FLEET", id="fleet-topbar")
            with Horizontal(id="fleet-summary"):
                for wid, title in SUMMARY:
                    box = Static("–", id=wid, classes="fleet-box")
                    box.border_title = title
                    yield box
            with Horizontal(id="fleet-body"):
                table = FleetTable(id="fleet-table")
                table.border_title = "fleet · worst first"
                yield table
                detail = FleetDetail(id="fleet-detail")
                detail.border_title = "board"
                yield detail
            yield Static(FOOTER, id="fleet-footer")

    # ---- data in -----------------------------------------------------------

    def update_data(self, status: Status, rates: RateHistory) -> None:
        linux = sum(1 for p in status.peers if p.os.lower() == "linux")
        self.query_one("#fleet-topbar", Static).update(
            f"▌ FLEET          {linux} linux devices on the tailnet"
        )

    def update_fleet(self, boards: list[Board], history: FleetHistory, now: datetime) -> None:
        self._boards = {b.name: b for b in boards}
        self._history = history
        self._now = now
        self.query_one(FleetTable).set_boards(boards, now)
        self._update_summary(boards, now)
        self._show_detail()

    def _update_summary(self, boards: list[Board], now: datetime) -> None:
        verdicts = [verdict(b, now=now) for b in boards]
        down = [b for b, v in zip(boards, verdicts) if v is Verdict.DOWN]
        up = len(boards) - len(down)
        self._set("fleet-boards", f"{len(boards)}\n{up} up", "")
        if down:
            worst = max(down, key=lambda b: (now - b.peer.last_seen).total_seconds()
                        if b.peer.last_seen else 0)
            self._set("fleet-down", f"{len(down)}\nlongest {fmt_since(since(worst, now=now))}",
                      "bold #ff7e88")
        else:
            self._set("fleet-down", "0", "#7be39b")
        useless = sum(1 for v in verdicts if v is Verdict.USELESS)
        self._set("fleet-useless", str(useless), "bold #ff7e88" if useless else "#7be39b")
        probed = [b for b in boards if b.health and not b.health.error]
        hot = [b for b in probed if b.health.temp_c is not None]
        if hot:
            b = max(hot, key=lambda b: b.health.temp_c)
            style = "#f0c674" if b.health.temp_c >= 70 else ""
            self._set("fleet-hottest", f"{b.health.temp_c:.0f}°C\n{b.name}", style)
        else:
            self._set("fleet-hottest", "–", "dim")
        full = [b for b in probed if b.health.disk_pct is not None]
        if full:
            b = max(full, key=lambda b: b.health.disk_pct)
            style = "#f0c674" if b.health.disk_pct >= 85 else ""
            self._set("fleet-disk", f"{b.health.disk_pct:.0f}%\n{b.name}", style)
        else:
            self._set("fleet-disk", "–", "dim")

    def _set(self, wid: str, text: str, style: str) -> None:
        self.query_one(f"#{wid}", Static).update(Text(text, style=style))

    def summary_text(self, wid: str) -> str:
        return str(self.query_one(f"#{wid}", Static).render())

    # ---- selection ---------------------------------------------------------

    def selected_board(self) -> Board | None:
        name = self.query_one(FleetTable).selected_name()
        return self._boards.get(name) if name else None

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        self._show_detail()

    def _show_detail(self) -> None:
        if self._now is None:
            return
        self.query_one(FleetDetail).show(
            self.selected_board(), self._history, self._now, self.config_path
        )
