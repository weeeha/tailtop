"""Observatory mode — topology. Intent: observe. (Built out in a later pass.)"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from tailtop.data.models import Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory


class ObservatoryMode(ModeView):
    cadence = 0.5

    def compose(self) -> ComposeResult:
        yield Static("Observatory — coming up next", id="observatory-placeholder")

    def update_data(self, status: Status, rates: RateHistory) -> None:
        direct = sum(1 for p in status.peers if p.conn_type.value == "direct")
        derp = sum(1 for p in status.peers if p.conn_type.value == "derp")
        self.query_one("#observatory-placeholder", Static).update(
            f"Observatory\n\n{status.online_count}/{status.total_count} online\n"
            f"{direct} direct · {derp} relayed\n"
            "live topology graph lands here"
        )
