"""A live device card for Cockpit mode — status, path, and RX/TX sparklines."""

from __future__ import annotations

from rich.console import Group
from rich.text import Text
from textual.widgets import Static

from tailtop.data.models import ConnType, Peer
from tailtop.state import RateHistory, human_rate, sparkline

_CONN_COLOR = {
    ConnType.DIRECT: "#7be39b",
    ConnType.DERP: "#f0c674",
    ConnType.SELF: "#8bb6ff",
    ConnType.IDLE: "#f0c674",
    ConnType.OFFLINE: "#6b6f78",
}


class DeviceCard(Static):
    """One peer, rendered as a bordered tile. Updated in place each poll."""

    def __init__(self, peer_id: str) -> None:
        super().__init__("", classes="devcard")
        self._peer_id = peer_id

    def update_card(self, peer: Peer, rates: RateHistory) -> None:
        color = _CONN_COLOR.get(peer.conn_type, "white")
        self.border_title = peer.name
        self.set_class(not peer.online, "offline")

        status_line = Text()
        status_line.append("◉ " if peer.online else "○ ", style=color)
        status_line.append("ONLINE" if peer.online else "OFFLINE", style=color)
        status_line.append(f"  {peer.os}", style="dim")

        path_line = Text(peer.relay_label, style=color)

        rx = Text()
        rx.append(sparkline(rates.rx_series(peer.id), width=8), style="#f0c674")
        rx.append(f"  {human_rate(rates.current_rx(peer.id))}", style="dim")

        tx = Text()
        tx.append(sparkline(rates.tx_series(peer.id), width=8), style="#7be39b")
        tx.append(f"  {human_rate(rates.current_tx(peer.id))}", style="dim")

        self.update(Group(status_line, path_line, Text(""), rx, tx))
