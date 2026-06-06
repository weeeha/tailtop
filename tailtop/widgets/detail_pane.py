"""Detail pane — the selected peer's addresses and metadata."""

from __future__ import annotations

from datetime import datetime, timezone

from rich.console import Group
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from tailtop.data.models import ConnType, Peer


def _ago(when: datetime | None) -> str:
    if when is None:
        return "—"
    now = datetime.now(timezone.utc)
    delta = now - when.astimezone(timezone.utc)
    secs = int(delta.total_seconds())
    if secs < 0:
        return "—"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def _expiry(when: datetime | None) -> str:
    if when is None:
        return "never"
    now = datetime.now(timezone.utc)
    days = int((when.astimezone(timezone.utc) - now).total_seconds() // 86400)
    if days < 0:
        return "expired"
    if days < 60:
        return f"in {days} days"
    return f"in {days // 30} months"


class DetailPane(Static):
    """Renders one peer's detail, GUI-style."""

    def show_empty(self, message: str = "No device selected") -> None:
        self.update(Text(message, style="dim"))

    def update_peer(self, peer: Peer) -> None:
        conn_style = {
            ConnType.DIRECT: "#7be39b",
            ConnType.DERP: "#f0c674",
            ConnType.SELF: "#8bb6ff",
            ConnType.IDLE: "#f0c674",
            ConnType.OFFLINE: "#6b6f78",
        }.get(peer.conn_type, "white")

        title = Text()
        title.append(peer.name, style="bold")
        title.append("\n")
        dot = "●" if peer.online else "○"
        state = "Connected" if peer.online else "Offline"
        title.append(f"{dot} {state}", style=conn_style)

        addrs = Table.grid(padding=(0, 2))
        addrs.add_column(style="dim", justify="left")
        addrs.add_column()
        addrs.add_row("MagicDNS", peer.magic_dns or "—")
        addrs.add_row("IPv4", peer.ipv4 or "—")
        if peer.ipv6:
            addrs.add_row("IPv6", peer.ipv6)
        addrs.add_row("Path", Text(peer.relay_label, style=conn_style))
        addrs.add_row("OS", peer.os or "—")
        addrs.add_row("Last seen", _ago(peer.last_handshake))
        addrs.add_row("Key expiry", _expiry(peer.key_expiry))
        if peer.exit_node_option:
            addrs.add_row("Exit node", "available" + (" · in use" if peer.exit_node else ""))

        self.update(Group(title, Text(""), addrs))
