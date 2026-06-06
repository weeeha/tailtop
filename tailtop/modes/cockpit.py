"""Cockpit mode — live cards + sparklines. Intent: operate."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container, Vertical
from textual.widgets import Static

from tailtop.data.models import Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory
from tailtop.widgets.device_card import DeviceCard


class CockpitMode(ModeView):
    cadence = 1.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._cards: dict[str, DeviceCard] = {}

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("▌ TAILNET · COCKPIT", id="cockpit-topbar")
            yield Container(id="cockpit-grid")
            yield Static(id="cockpit-footer")

    def on_mount(self) -> None:
        self.query_one("#cockpit-footer", Static).update(
            "⌘P palette   s ssh   f send   e exit-node   p ping   F funnel"
        )

    def update_data(self, status: Status, rates: RateHistory) -> None:
        grid = self.query_one("#cockpit-grid", Container)
        seen: set[str] = set()
        for peer in status.sorted_peers():
            seen.add(peer.id)
            card = self._cards.get(peer.id)
            if card is None:
                card = DeviceCard(peer.id)
                self._cards[peer.id] = card
                grid.mount(card)
            card.update_card(peer, rates)
        for pid in list(self._cards):
            if pid not in seen:
                self._cards.pop(pid).remove()

        self.query_one("#cockpit-topbar", Static).update(
            f"▌ TAILNET · COCKPIT          {status.online_count}/{status.total_count} online"
        )
