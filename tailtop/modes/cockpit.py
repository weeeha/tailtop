"""Cockpit mode — live cards. Intent: operate. (Built out in a later pass.)"""

from __future__ import annotations

from textual.app import ComposeResult
from textual.widgets import Static

from tailtop.data.models import Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory


class CockpitMode(ModeView):
    cadence = 1.0

    def compose(self) -> ComposeResult:
        yield Static("Cockpit — coming up next", id="cockpit-placeholder")

    def update_data(self, status: Status, rates: RateHistory) -> None:
        self.query_one("#cockpit-placeholder", Static).update(
            f"Cockpit\n\n{status.online_count}/{status.total_count} peers online\n"
            "live cards + sparklines land here"
        )
