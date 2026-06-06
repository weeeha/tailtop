"""The device list — a keyboard-navigable list of tailnet peers."""

from __future__ import annotations

from rich.text import Text
from textual.message import Message
from textual.widgets import ListItem, ListView, Static

from tailtop.data.models import ConnType, Peer

_DOT = {
    ConnType.SELF: ("●", "dot-self"),
    ConnType.DIRECT: ("●", "dot-online"),
    ConnType.DERP: ("●", "dot-online"),
    ConnType.IDLE: ("●", "dot-idle"),
    ConnType.OFFLINE: ("○", "dot-offline"),
}


class PeerItem(ListItem):
    """A single row carrying its Peer."""

    def __init__(self, peer: Peer) -> None:
        super().__init__()
        self.peer = peer

    def compose(self):
        glyph, css = _DOT.get(peer_conn(self.peer), ("●", "dot-online"))
        line = Text()
        line.append(f"{glyph} ", style=_DOT_STYLE.get(css, "green"))
        line.append(f"{self.peer.name:<18.18} ", style="bold" if self.peer.is_self else "")
        line.append(self.peer.ipv4, style="dim")
        yield Static(line)


# rich styles keyed to the css names above (ListItem styling is also in tcss,
# but the dot color is data-driven so we set it inline)
_DOT_STYLE = {
    "dot-self": "#8bb6ff",
    "dot-online": "#7be39b",
    "dot-idle": "#f0c674",
    "dot-offline": "#6b6f78",
}


def peer_conn(peer: Peer) -> ConnType:
    return peer.conn_type


class DeviceList(ListView):
    """List of peers with vim-style navigation; emits PeerHighlighted."""

    class PeerHighlighted(Message):
        def __init__(self, peer: Peer | None) -> None:
            self.peer = peer
            super().__init__()

    def populate(self, peers: list[Peer], keep_id: str | None = None) -> None:
        """Rebuild rows, preserving the highlighted peer by id when possible."""
        target = keep_id
        if target is None and self.highlighted_child is not None:
            target = getattr(self.highlighted_child, "peer", None) and self.highlighted_child.peer.id

        self.clear()
        new_index = 0
        for i, p in enumerate(peers):
            self.append(PeerItem(p))
            if target and p.id == target:
                new_index = i
        if peers:
            self.index = new_index

    def key_j(self) -> None:
        if self.index is not None and self.index < len(self) - 1:
            self.index += 1

    def key_k(self) -> None:
        if self.index:
            self.index -= 1

    def on_list_view_highlighted(self, event: ListView.Highlighted) -> None:
        peer = getattr(event.item, "peer", None) if event.item else None
        self.post_message(self.PeerHighlighted(peer))
