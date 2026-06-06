"""Observatory mode — live topology. Intent: observe."""

from __future__ import annotations

from collections import deque

from rich.console import Group
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Static

from tailtop.data.models import Status
from tailtop.modes.base import ModeView
from tailtop.state import RateHistory, human_rate, sparkline
from tailtop.widgets.topology import build_topology


class ObservatoryMode(ModeView):
    cadence = 0.5

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._total_rx: deque[float] = deque(maxlen=40)
        self._total_tx: deque[float] = deque(maxlen=40)

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Static(id="obs-header")
            yield Static(id="obs-core")
            with Horizontal(id="obs-cols"):
                yield Static(id="obs-direct")
                yield Static(id="obs-relayed")
            yield Static(id="obs-traffic")

    def update_data(self, status: Status, rates: RateHistory) -> None:
        topo = build_topology(status)

        # header
        self.query_one("#obs-header", Static).update(
            Text.assemble(
                ("TAILNET ▸ LIVE TOPOLOGY", "bold #c792ea"),
                ("    ", ""),
                (f"{status.online_count}/{status.total_count} online", "#7be39b"),
            )
        )

        # core "you" node
        me = status.self_peer
        core = Text()
        core.append("◉ YOU  ", style="bold #8bb6ff")
        core.append(me.name, style="bold white")
        core.append(f"   {me.ipv4}", style="dim")
        self.query_one("#obs-core", Static).update(core)

        # direct column
        direct = [Text("◢ DIRECT", style="bold #7be39b"), Text("")]
        if topo.direct:
            for p in topo.direct:
                row = Text()
                row.append("● ", style="#7be39b")
                row.append(f"{p.name:<16.16} ", style="white")
                row.append(p.cur_addr or "—", style="dim")
                direct.append(row)
        else:
            direct.append(Text("  (none)", style="dim"))
        self.query_one("#obs-direct", Static).update(Group(*direct))

        # relayed column (grouped by DERP region)
        relayed = [Text("◢ RELAYED · via DERP", style="bold #f0c674"), Text("")]
        if topo.relayed:
            for region in sorted(topo.relayed):
                relayed.append(Text(f"  {region}", style="bold #f0c674"))
                for p in topo.relayed[region]:
                    row = Text()
                    row.append("  ● ", style="#f0c674")
                    row.append(f"{p.name:<16.16} ", style="white")
                    row.append(p.os, style="dim")
                    relayed.append(row)
        else:
            relayed.append(Text("  (none)", style="dim"))
        self.query_one("#obs-relayed", Static).update(Group(*relayed))

        # aggregate traffic strip
        tot_rx = sum(rates.current_rx(p.id) for p in status.peers)
        tot_tx = sum(rates.current_tx(p.id) for p in status.peers)
        self._total_rx.append(tot_rx)
        self._total_tx.append(tot_tx)
        traffic = Text()
        traffic.append("rx ", style="dim")
        traffic.append(sparkline(list(self._total_rx), width=30), style="#f0c674")
        traffic.append(f"  {human_rate(tot_rx)}\n", style="white")
        traffic.append("tx ", style="dim")
        traffic.append(sparkline(list(self._total_tx), width=30), style="#7be39b")
        traffic.append(f"  {human_rate(tot_tx)}", style="white")
        self.query_one("#obs-traffic", Static).update(traffic)
