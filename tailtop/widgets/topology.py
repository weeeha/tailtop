"""Topology helpers — group peers by how we reach them.

Pure functions so the grouping is testable without a running app.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from tailtop.data.models import ConnType, Peer, Status


@dataclass
class Topology:
    direct: list[Peer] = field(default_factory=list)
    relayed: dict[str, list[Peer]] = field(default_factory=dict)  # region → peers
    offline: list[Peer] = field(default_factory=list)

    @property
    def direct_count(self) -> int:
        return len(self.direct)

    @property
    def relayed_count(self) -> int:
        return sum(len(v) for v in self.relayed.values())


def build_topology(status: Status) -> Topology:
    topo = Topology()
    for peer in sorted(status.peers, key=lambda p: p.name.lower()):
        match peer.conn_type:
            case ConnType.DIRECT:
                topo.direct.append(peer)
            case ConnType.DERP:
                topo.relayed.setdefault(peer.relay, []).append(peer)
            case ConnType.OFFLINE:
                topo.offline.append(peer)
            case _:
                # IDLE: online but no path yet — treat as relayed-unknown
                topo.relayed.setdefault(peer.relay or "?", []).append(peer)
    return topo
