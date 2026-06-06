"""Comfort mode — List view, GUI parity. Intent: manage."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from tailtop.data.models import Peer, Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory
from tailtop.widgets.detail_pane import DetailPane
from tailtop.widgets.device_list import DeviceList


class ComfortMode(ModeView):
    cadence = 2.0

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._selected_id: str | None = None

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static("Devices", id="comfort-header")
            with Horizontal(id="comfort-body"):
                yield DeviceList(id="device-list")
                yield DetailPane(id="detail-pane")

    def on_mount(self) -> None:
        self.query_one(DetailPane).show_empty("Loading devices…")

    def update_data(self, status: Status, rates: RateHistory) -> None:
        peers = status.sorted_peers()
        header = self.query_one("#comfort-header", Static)
        header.update(f"Devices · {status.online_count}/{status.total_count} online")
        self.query_one(DeviceList).populate(peers, keep_id=self._selected_id)
        if peers and self._selected_id is None:
            self._select(peers[0])

    def on_device_list_peer_highlighted(self, event: DeviceList.PeerHighlighted) -> None:
        if event.peer:
            self._select(event.peer)

    def _select(self, peer: Peer) -> None:
        self._selected_id = peer.id
        self.query_one(DetailPane).update_peer(peer)
