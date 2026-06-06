"""App-side state: rate history for sparklines.

``status --json`` reports *cumulative* RxBytes/TxBytes. To draw a live rate we
diff successive samples over elapsed wall-time and keep a bounded ring buffer
per peer. This is pure and unit-testable; the Textual app owns one
``RateHistory`` and feeds it each poll.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class _PeerRate:
    last_rx: int | None = None
    last_tx: int | None = None
    last_t: float | None = None
    rx: deque[float] = field(default_factory=lambda: deque(maxlen=_PeerRate.WIDTH))
    tx: deque[float] = field(default_factory=lambda: deque(maxlen=_PeerRate.WIDTH))

    WIDTH = 32  # samples retained for the sparkline

    def update(self, rx_bytes: int, tx_bytes: int, now: float) -> None:
        if self.last_t is not None and now > self.last_t:
            dt = now - self.last_t
            # Guard against counter resets (peer reconnect) → clamp at 0.
            d_rx = max(0, rx_bytes - (self.last_rx or 0)) / dt
            d_tx = max(0, tx_bytes - (self.last_tx or 0)) / dt
            self.rx.append(d_rx)
            self.tx.append(d_tx)
        self.last_rx, self.last_tx, self.last_t = rx_bytes, tx_bytes, now


class RateHistory:
    """Per-peer rolling RX/TX rates, keyed by a stable peer id."""

    def __init__(self) -> None:
        self._peers: dict[str, _PeerRate] = {}

    def update(self, peer_id: str, rx_bytes: int, tx_bytes: int, now: float) -> None:
        self._peers.setdefault(peer_id, _PeerRate()).update(rx_bytes, tx_bytes, now)

    def rx_series(self, peer_id: str) -> list[float]:
        pr = self._peers.get(peer_id)
        return list(pr.rx) if pr else []

    def tx_series(self, peer_id: str) -> list[float]:
        pr = self._peers.get(peer_id)
        return list(pr.tx) if pr else []

    def current_rx(self, peer_id: str) -> float:
        s = self.rx_series(peer_id)
        return s[-1] if s else 0.0

    def current_tx(self, peer_id: str) -> float:
        s = self.tx_series(peer_id)
        return s[-1] if s else 0.0


_SPARK = "▁▂▃▄▅▆▇█"


def sparkline(series: list[float], width: int = 10) -> str:
    """Render a rate series as unicode block sparks, scaled to its own max."""
    if not series:
        return "·" * width
    recent = series[-width:]
    peak = max(recent) or 1.0
    cells = [_SPARK[min(len(_SPARK) - 1, int(v / peak * (len(_SPARK) - 1)))] for v in recent]
    pad = "·" * (width - len(cells))
    return pad + "".join(cells)


def human_rate(bytes_per_sec: float) -> str:
    """e.g. 1536 → '1.5 KB/s'."""
    units = ["B", "KB", "MB", "GB"]
    v = float(bytes_per_sec)
    for u in units:
        if v < 1024 or u == units[-1]:
            return f"{v:.0f} {u}/s" if u == "B" else f"{v:.1f} {u}/s"
        v /= 1024
    return f"{v:.1f} GB/s"
