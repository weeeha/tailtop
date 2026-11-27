"""Detail pane for the board under the Fleet table cursor."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from rich.text import Text
from textual.widgets import Static

from tailtop.data.fleet import Board, Verdict, since, verdict, warnings
from tailtop.data.fleet_poller import USER_HINT, FleetHistory
from tailtop.state import sparkline
from tailtop.widgets.fleet_table import STATE_STYLE, fmt_since


def _uptime(seconds: float | None) -> str:
    if seconds is None:
        return "–"
    d, rem = divmod(int(seconds), 86400)
    h = rem // 3600
    return f"{d}d {h}h" if d else f"{h}h {rem % 3600 // 60}m"


class FleetDetail(Static):
    def show(
        self, board: Board | None, history: FleetHistory, now: datetime, config_path: Path
    ) -> None:
        if board is None:
            self.update(Text("no boards on the tailnet", style="dim"))
            return
        v = verdict(board, now=now)
        t = Text()
        t.append(board.name, style="bold")
        if board.config.label:
            t.append(f" · {board.config.label}", style="dim")
        t.append("\n")
        t.append(v.value, style=STATE_STYLE[v])
        t.append(f" {fmt_since(since(board, now=now))}\n\n", style="dim")

        if v is Verdict.DOWN:
            t.append("offline in Tailscale\n", style="dim")
            if board.peer.last_seen:
                t.append(f"last seen {board.peer.last_seen:%Y-%m-%d %H:%M} UTC\n", style="dim")
            return self._finish(t, board)

        h = board.health
        if h is None:
            t.append("probing…\n", style="dim")
            return self._finish(t, board)
        if h.error:
            t.append(f"{h.error}\n", style="#f0c674")
            if h.error == USER_HINT:
                t.append(f"config: {config_path}\n", style="dim")
            return self._finish(t, board)

        if h.model:
            t.append(f"{h.model}\n", style="dim")
        t.append(f"up {_uptime(h.uptime_s)}\n")
        if board.config.service:
            on = h.service_state == "active"
            t.append("● " if on else "○ ", style="#7be39b" if on else "#ff7e88")
            t.append(f"{board.config.service} {h.service_state or 'unknown'}\n")
        else:
            t.append("service not set\n", style="dim")
        t.append("\n")
        temps, loads = history.temps(board.name), history.loads(board.name)
        t.append(f"temp {sparkline(temps, 16)} ")
        t.append(f"{h.temp_c:.0f}°C\n" if h.temp_c is not None else "–\n")
        t.append(f"load {sparkline(loads, 16)} ")
        t.append(f"{h.load1:.2f}\n" if h.load1 is not None else "–\n")
        if h.mem_pct is not None:
            t.append(f"mem  {h.mem_pct:.0f}%   ")
        if h.disk_pct is not None:
            t.append(f"disk {h.disk_pct:.0f}%")
        t.append("\n")
        if h.throttle is None:
            t.append("throttle: n/a\n", style="dim")
        else:
            th = h.throttle

            def names(uv: bool, thr: bool) -> str:
                return "+".join(n for n, on in (("volt", uv), ("throttle", thr)) if on)

            now_s = names(th.undervolt_now, th.throttled_now)
            ever_s = names(th.undervolt_ever, th.throttled_ever)
            if now_s:
                t.append(f"power: {now_s} now\n", style="#f0c674")
            elif ever_s:
                t.append(f"power: {ever_s} since boot\n", style="dim")
            else:
                t.append("power: ok\n", style="dim")
        warn = warnings(board)
        if warn:
            t.append(f"\n⚠ {' · '.join(warn)}\n", style="#f0c674")
        age = int((now - h.probed_at).total_seconds())
        t.append(f"\nlast probe {max(age, 0)}s ago\n", style="dim")
        return self._finish(t, board)

    def _finish(self, t: Text, board: Board) -> None:
        self.update(t)

