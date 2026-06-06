"""Demo client — a synthetic tailnet for screenshots and design review.

Drop-in replacement for :class:`TailscaleClient` that returns a believable
tech-company tailnet snapshot and animates rx/tx counters so the sparklines
and Observatory mode feel alive. Activate with ``tailtop --demo`` or
``TAILTOP_DEMO=1``.

No CLI is shelled. Verbs return canned but plausible text so the result modals
still render. Nothing here ever touches the real tailscaled daemon.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from tailtop.data.models import Peer, Status


@dataclass
class _Profile:
    """How much traffic a node typically pushes."""

    rx_mean: float  # bytes/sec
    tx_mean: float
    jitter: float = 0.4  # +/- fraction of mean per tick
    bursty: bool = False


# Believable Anthropic-ish device profiles. Mean rates picked so the
# Observatory aggregate lands in the few-MB/s range the spec illustrates.
_IDLE = _Profile(rx_mean=0, tx_mean=0)
_LIGHT = _Profile(rx_mean=8 * 1024, tx_mean=2 * 1024)
_DESK = _Profile(rx_mean=40 * 1024, tx_mean=12 * 1024)
_API = _Profile(rx_mean=600 * 1024, tx_mean=900 * 1024, jitter=0.3)
_GPU = _Profile(rx_mean=1_400 * 1024, tx_mean=2_200 * 1024, jitter=0.5, bursty=True)
_OBSERV = _Profile(rx_mean=180 * 1024, tx_mean=40 * 1024)
_BURST = _Profile(rx_mean=300 * 1024, tx_mean=300 * 1024, jitter=0.9, bursty=True)


@dataclass
class _PeerSpec:
    id: str
    host_name: str
    os: str
    ipv4: str
    profile: _Profile
    relay: str = ""  # set non-empty for DERP-relayed peers
    direct: bool = True
    online: bool = True
    exit_node: bool = False
    exit_node_option: bool = False
    tags: list[str] = field(default_factory=list)
    last_handshake_ago_s: float | None = 6.0
    key_expiry_days: float = 47.0

    # Mutable counters maintained across status() ticks.
    rx: int = 0
    tx: int = 0


# A small Anthropic-flavored tailnet. The shape matches the design screenshot:
# a clear "you" node, a couple of direct peers, a couple of DERP-relayed
# peers, plus deeper infra you'd expect inside a model lab.
_SELF = _PeerSpec(
    id="self",
    host_name="you",
    os="macOS",
    ipv4="100.64.0.10",
    profile=_DESK,
    direct=True,
    tags=["tag:laptop"],
    last_handshake_ago_s=None,
)

_PEERS: list[_PeerSpec] = [
    # The cast from the screenshot.
    _PeerSpec(
        "p-artstation",
        "artstation",
        "Linux",
        "100.64.0.21",
        _BURST,
        direct=True,
        tags=["tag:workstation"],
        last_handshake_ago_s=4,
    ),
    _PeerSpec(
        "p-fastclock",
        "fastclock",
        "Linux",
        "100.64.0.22",
        _OBSERV,
        relay="nyc",
        direct=False,
        tags=["tag:metrics"],
        last_handshake_ago_s=12,
    ),
    _PeerSpec(
        "p-macstudio",
        "mac-studio",
        "macOS",
        "100.64.0.23",
        _DESK,
        direct=True,
        tags=["tag:render"],
        last_handshake_ago_s=3,
    ),
    _PeerSpec(
        "p-iphone15",
        "iphone-15",
        "iOS",
        "100.64.0.24",
        _LIGHT,
        relay="sfo",
        direct=False,
        tags=["tag:mobile"],
        last_handshake_ago_s=27,
    ),
    # Anthropic-shaped infra that fills out the Comfort + Cockpit views.
    _PeerSpec(
        "p-api-prod-1",
        "api-prod-1",
        "Linux",
        "100.64.10.11",
        _API,
        direct=True,
        tags=["tag:prod", "tag:api"],
        last_handshake_ago_s=2,
    ),
    _PeerSpec(
        "p-api-prod-2",
        "api-prod-2",
        "Linux",
        "100.64.10.12",
        _API,
        direct=True,
        tags=["tag:prod", "tag:api"],
        last_handshake_ago_s=2,
    ),
    _PeerSpec(
        "p-inference-h100",
        "inference-h100-a",
        "Linux",
        "100.64.20.4",
        _GPU,
        direct=True,
        tags=["tag:prod", "tag:gpu"],
        last_handshake_ago_s=1,
    ),
    _PeerSpec(
        "p-inference-a100",
        "inference-a100-b",
        "Linux",
        "100.64.20.5",
        _GPU,
        direct=True,
        tags=["tag:prod", "tag:gpu"],
        last_handshake_ago_s=2,
    ),
    _PeerSpec(
        "p-eval-runner",
        "eval-runner-01",
        "Linux",
        "100.64.30.7",
        _BURST,
        direct=True,
        tags=["tag:ci"],
        last_handshake_ago_s=8,
    ),
    _PeerSpec(
        "p-bastion-sfo",
        "bastion-sfo",
        "Linux",
        "100.64.40.1",
        _LIGHT,
        direct=True,
        exit_node_option=True,
        tags=["tag:exit"],
        last_handshake_ago_s=5,
    ),
    _PeerSpec(
        "p-bastion-nyc",
        "bastion-nyc",
        "Linux",
        "100.64.40.2",
        _LIGHT,
        relay="nyc",
        direct=False,
        exit_node_option=True,
        tags=["tag:exit"],
        last_handshake_ago_s=14,
    ),
    _PeerSpec(
        "p-grafana",
        "metrics-grafana",
        "Linux",
        "100.64.50.3",
        _OBSERV,
        direct=True,
        tags=["tag:observability"],
        last_handshake_ago_s=6,
    ),
    _PeerSpec(
        "p-mbp-priya",
        "claude-mbp-priya",
        "macOS",
        "100.64.60.8",
        _DESK,
        direct=True,
        tags=["tag:laptop"],
        last_handshake_ago_s=11,
    ),
    _PeerSpec(
        "p-mbp-jordan",
        "claude-mbp-jordan",
        "macOS",
        "100.64.60.9",
        _DESK,
        relay="fra",
        direct=False,
        tags=["tag:laptop"],
        last_handshake_ago_s=33,
    ),
    _PeerSpec(
        "p-pi-lab",
        "raspberry-pi-lab",
        "Linux",
        "100.64.70.2",
        _IDLE,
        direct=True,
        tags=["tag:lab"],
        last_handshake_ago_s=180,
    ),
    _PeerSpec(
        "p-old-windows",
        "legacy-windows-box",
        "Windows",
        "100.64.99.99",
        _IDLE,
        online=False,
        direct=False,
        tags=["tag:legacy"],
        last_handshake_ago_s=60 * 60 * 26,  # offline > a day
    ),
]


def _spec_to_peer(spec: _PeerSpec, *, is_self: bool = False) -> Peer:
    now = datetime.now(UTC)
    last = (
        None
        if spec.last_handshake_ago_s is None
        else now - timedelta(seconds=spec.last_handshake_ago_s)
    )
    cur_addr = ""
    if spec.online and spec.direct and not is_self:
        # A plausible direct endpoint. The port is stable per spec so the
        # screenshot doesn't flicker on each tick.
        port = 41000 + (abs(hash(spec.id)) % 9000)
        cur_addr = f"{spec.ipv4.replace('100.64.', '198.51.100.')}:{port}"
    return Peer(
        id=spec.id,
        host_name=spec.host_name,
        dns_name=f"{spec.host_name}.tail-anthropic.ts.net.",
        os=spec.os,
        ips=[spec.ipv4, f"fd7a:115c:a1e0::{abs(hash(spec.id)) % 0xFFFF:x}"],
        online=spec.online,
        active=spec.online and (spec.rx > 0 or spec.tx > 0),
        exit_node=spec.exit_node,
        exit_node_option=spec.exit_node_option,
        relay=spec.relay,
        cur_addr=cur_addr,
        rx_bytes=spec.rx,
        tx_bytes=spec.tx,
        last_handshake=last,
        key_expiry=now + timedelta(days=spec.key_expiry_days),
        tags=list(spec.tags),
        is_self=is_self,
    )


class DemoClient:
    """A fake :class:`TailscaleClient` for screenshots and design review."""

    def __init__(self, seed: int = 7) -> None:
        self._binary = "tailscale"  # for the SSH suspend path
        self.default_timeout = 10.0
        self._rng = random.Random(seed)
        self._self = _SELF
        self._peers = list(_PEERS)
        self._last_tick = time.monotonic()
        # Prime byte counters so the first frame already has a baseline.
        self._tick(dt=1.0)

    # Mirrors TailscaleClient's surface ------------------------------------

    @property
    def available(self) -> bool:
        return True

    async def status(self) -> Status:
        now = time.monotonic()
        dt = max(0.1, now - self._last_tick)
        self._last_tick = now
        self._tick(dt)

        self_peer = _spec_to_peer(self._self, is_self=True)
        peers = [_spec_to_peer(p) for p in self._peers]
        return Status(
            version="1.78.0-demo",
            backend_state="Running",
            tailscale_ips=[self._self.ipv4],
            magic_dns_suffix="tail-anthropic.ts.net",
            user_display="you@anthropic.com",
            self_peer=self_peer,
            peers=peers,
        )

    async def netcheck(self) -> dict:
        return {
            "UDP": True,
            "IPv4": True,
            "IPv6": True,
            "PreferredDERP": 9,
            "DERPLatency": {"sfo": 12.4, "nyc": 28.9, "fra": 96.1, "sea": 22.6},
        }

    async def whois(self, ip: str) -> str:
        return f"{ip}\n  Node: demo\n  User: you@anthropic.com\n  Tags: tag:laptop"

    async def ping_once(self, host: str) -> str:
        ms = round(self._rng.uniform(4, 14), 1)
        return f"pong from {host} via direct in {ms}ms"

    async def run(self, *args: str, timeout: float | None = None, check: bool = True) -> str:
        """Stub the low-level runner so verbs still produce result modals."""
        if args[:1] == ("status",):
            # Used only if anything bypasses status(); shouldn't happen.
            return "{}"
        if args[:1] == ("ping",):
            host = args[-1]
            return await self.ping_once(host)
        if args[:1] == ("whois",):
            return await self.whois(args[-1])
        if args[:1] == ("netcheck",):
            return (
                "* UDP: yes\n* IPv4: yes\n* IPv6: yes\n* DERP latency:\n"
                "  - sfo: 12.4ms\n  - nyc: 28.9ms\n  - fra: 96.1ms\n  - sea: 22.6ms"
            )
        if args[:2] == ("lock", "status"):
            return "Tailnet lock is NOT enabled."
        if args[:2] == ("serve", "status"):
            return "(no serve config; demo mode)"
        if args[:1] == ("file",):
            return "(demo) file send acknowledged"
        if args[:2] == ("funnel",) or args[:1] == ("funnel",):
            return "(demo) funnel toggled"
        if args[:1] == ("set",):
            return "(demo) set applied"
        return "(demo) ok"

    # Animation ------------------------------------------------------------

    def _tick(self, dt: float) -> None:
        """Advance rx/tx byte counters for every node by one tick."""
        for spec in (self._self, *self._peers):
            if not spec.online:
                continue
            prof = spec.profile
            rx = prof.rx_mean
            tx = prof.tx_mean
            if prof.bursty and self._rng.random() < 0.25:
                # Occasional GPU/CI burst — multiply by 3-6x.
                spike = self._rng.uniform(3.0, 6.0)
                rx *= spike
                tx *= spike
            rx *= 1 + self._rng.uniform(-prof.jitter, prof.jitter)
            tx *= 1 + self._rng.uniform(-prof.jitter, prof.jitter)
            spec.rx += int(max(0, rx) * dt)
            spec.tx += int(max(0, tx) * dt)
