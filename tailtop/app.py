"""tailtop — the Textual application.

Owns the data (client, poller, rate history) and distributes each fresh
snapshot to the active mode. Modes never touch the CLI; they only render the
``Status`` + ``RateHistory`` they're handed.
"""

from __future__ import annotations

import time
from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import ContentSwitcher

from tailtop.data.client import TailscaleClient
from tailtop.data.models import Status
from tailtop.data.poller import Poller
from tailtop.modes.cockpit import CockpitMode
from tailtop.modes.comfort import ComfortMode
from tailtop.modes.observatory import ObservatoryMode
from tailtop.state import RateHistory
from tailtop.widgets.status_bar import StatusBar

_THEMES = Path(__file__).parent / "themes"


class TailtopApp(App):
    CSS_PATH = [
        _THEMES / "base.tcss",
        _THEMES / "studio.tcss",
        _THEMES / "mission_control.tcss",
        _THEMES / "brutalist.tcss",
    ]

    BINDINGS = [
        Binding("tab", "cycle_mode", "Mode", priority=True),
        Binding("r", "refresh", "Refresh"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    MODE_ORDER = ["comfort", "cockpit", "observatory"]

    status: reactive[Status | None] = reactive(None)
    active_mode: reactive[str] = reactive("comfort")
    error: reactive[str] = reactive("")

    def __init__(self, client: TailscaleClient | None = None, auto_poll: bool = True) -> None:
        super().__init__()
        self.client = client or TailscaleClient()
        self.rates = RateHistory()
        self.auto_poll = auto_poll
        self.poller = Poller(self.client, self._on_status, self._on_error, interval=2.0)

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="comfort", id="modes"):
            yield ComfortMode(id="comfort")
            yield CockpitMode(id="cockpit")
            yield ObservatoryMode(id="observatory")
        yield StatusBar(id="statusbar")

    def on_mount(self) -> None:
        self._refresh_status_bar()
        if self.auto_poll:
            self.poller.start()

    # ---- data plumbing -----------------------------------------------------

    def _on_status(self, status: Status) -> None:
        now = time.monotonic()
        for p in (status.self_peer, *status.peers):
            self.rates.update(p.id, p.rx_bytes, p.tx_bytes, now)
        self.error = ""
        self.status = status  # triggers watch_status

    def _on_error(self, exc: Exception) -> None:
        self.error = str(exc)
        self._refresh_status_bar()

    def watch_status(self, status: Status | None) -> None:
        if status is not None:
            self._mode_widget().update_data(status, self.rates)
        self._refresh_status_bar()

    def _mode_widget(self):
        return self.query_one(f"#{self.active_mode}")

    def _refresh_status_bar(self) -> None:
        try:
            bar = self.query_one(StatusBar)
        except Exception:
            return
        bar.set_state(self.status, self.active_mode, self.error)

    # ---- actions -----------------------------------------------------------

    def action_cycle_mode(self) -> None:
        idx = self.MODE_ORDER.index(self.active_mode)
        self.active_mode = self.MODE_ORDER[(idx + 1) % len(self.MODE_ORDER)]
        self.query_one(ContentSwitcher).current = self.active_mode
        # adopt the new mode's cadence and push it the latest data
        mode = self._mode_widget()
        self.poller.set_interval(getattr(mode, "cadence", 2.0))
        if self.status is not None:
            mode.update_data(self.status, self.rates)
        self._refresh_status_bar()

    def action_refresh(self) -> None:
        self.poller.refresh_now()

    def action_help(self) -> None:
        self.notify(
            "Tab cycle modes · j/k or ↑/↓ navigate · r refresh · q quit",
            title="tailtop",
            timeout=6,
        )

    async def on_unmount(self) -> None:
        await self.poller.stop()


def main() -> None:
    TailtopApp().run()


if __name__ == "__main__":
    main()
