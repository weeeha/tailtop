"""Fleet mode data: the board probe, its parser, and the health verdict.

Pure code with no Textual imports, so a future collector can reuse it. A probe
is one read-only ``sh`` script run over ``tailscale ssh``; it prints
``key=value`` lines and anything it cannot read is simply missing.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import Enum
from typing import Literal

from tailtop.data.fleet_config import BoardConfig, FleetConfig
from tailtop.data.models import Peer, Status

# Read on stdin by ``sh -s -- <service>``. POSIX sh only; never needs sudo.
PROBE_SCRIPT = r"""
echo "hostname=$(hostname)"
read up _ < /proc/uptime && echo "uptime=$up"
read l1 l5 l15 _ < /proc/loadavg && echo "loadavg=$l1 $l5 $l15"
command -v nproc >/dev/null 2>&1 && echo "cores=$(nproc)"
[ -r /sys/class/thermal/thermal_zone0/temp ] && echo "temp_milli=$(cat /sys/class/thermal/thermal_zone0/temp)"
awk '/^MemTotal:/{print "mem_total_kb="$2} /^MemAvailable:/{print "mem_avail_kb="$2}' /proc/meminfo
df -P / | awk 'NR==2{gsub("%","",$5); print "disk_pct="$5}'
command -v vcgencmd >/dev/null 2>&1 && vcgencmd get_throttled 2>/dev/null | grep '^throttled='
[ -r /proc/device-tree/model ] && printf 'model=%s\n' "$(tr -d '\0' < /proc/device-tree/model)"
[ -n "$1" ] && echo "service=$(systemctl is-active "$1" 2>/dev/null)"
exit 0
"""

# Warn thresholds (spec 5.4).
WARN_TEMP_C = 70.0
WARN_DISK_PCT = 85.0
WARN_MEM_PCT = 90.0
WARN_LOAD_PER_CORE = 2.0
REBOOT_WINDOW = timedelta(seconds=180)


@dataclass(frozen=True)
class Throttle:
    undervolt_now: bool
    throttled_now: bool
    undervolt_ever: bool
    throttled_ever: bool


def decode_throttled(hex_value: str) -> Throttle:
    """Decode ``vcgencmd get_throttled`` bits 0, 2, 16 and 18."""
    try:
        v = int(hex_value, 16)
    except (TypeError, ValueError):
        return Throttle(False, False, False, False)
    return Throttle(bool(v & 1 << 0), bool(v & 1 << 2), bool(v & 1 << 16), bool(v & 1 << 18))


@dataclass
class BoardHealth:
    temp_c: float | None
    load1: float | None
    load5: float | None
    load15: float | None
    cores: int | None
    mem_pct: float | None
    disk_pct: float | None
    uptime_s: float | None
    throttle: Throttle | None
    model: str | None
    service_state: str | None
    error: str | None
    probed_at: datetime


def _num(value: str | None, cast=float):
    if value is None:
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        return None


def parse_probe(text: str, *, now: datetime) -> BoardHealth:
    """Turn probe output into ``BoardHealth``; missing or bad values become None."""
    kv: dict[str, str] = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            kv[key.strip()] = value.strip()

    load = (kv.get("loadavg") or "").split()
    loads = [_num(x) for x in load[:3]] + [None] * (3 - len(load[:3]))

    temp_milli = _num(kv.get("temp_milli"))
    total = _num(kv.get("mem_total_kb"))
    avail = _num(kv.get("mem_avail_kb"))
    mem_pct = 100.0 * (total - avail) / total if total and avail is not None else None

    return BoardHealth(
        temp_c=temp_milli / 1000.0 if temp_milli is not None else None,
        load1=loads[0],
        load5=loads[1],
        load15=loads[2],
        cores=_num(kv.get("cores"), int),
        mem_pct=mem_pct,
        disk_pct=_num(kv.get("disk_pct")),
        uptime_s=_num(kv.get("uptime")),
        throttle=decode_throttled(kv["throttled"]) if "throttled" in kv else None,
        model=kv.get("model") or None,
        service_state=kv.get("service") or None,
        error=None if kv else "empty probe output",
        probed_at=now,
    )


class Verdict(Enum):
    DOWN = "down"
    UNREACHABLE = "unreachable"
    REBOOTING = "rebooting"
    USELESS = "useless"
    WARN = "warn"
    OK = "ok"
    PENDING = "probing"

    @property
    def rank(self) -> int:
        return _RANK[self]


_RANK = {
    Verdict.DOWN: 0,
    Verdict.UNREACHABLE: 1,
    Verdict.REBOOTING: 1,
    Verdict.USELESS: 2,
    Verdict.WARN: 3,
    Verdict.OK: 4,
    Verdict.PENDING: 5,
}


@dataclass
class Board:
    name: str
    peer: Peer
    config: BoardConfig
    health: BoardHealth | None = None
    rebooting_since: datetime | None = None
    state_since: datetime | None = None


def warnings(board: Board) -> list[str]:
    """Human reasons a probed board is in WARN; empty when there are none."""
    h = board.health
    if h is None or h.error:
        return []
    out: list[str] = []
    if h.temp_c is not None and h.temp_c >= WARN_TEMP_C:
        out.append(f"{h.temp_c:.0f}°C")
    if h.disk_pct is not None and h.disk_pct >= WARN_DISK_PCT:
        out.append(f"disk {h.disk_pct:.0f}%")
    if h.mem_pct is not None and h.mem_pct >= WARN_MEM_PCT:
        out.append(f"mem {h.mem_pct:.0f}%")
    if h.load1 is not None and h.cores and h.load1 >= WARN_LOAD_PER_CORE * h.cores:
        out.append(f"load {h.load1:.1f}")
    if h.throttle is not None:
        if h.throttle.undervolt_now:
            out.append("under-voltage")
        if h.throttle.throttled_now:
            out.append("throttled")
    return out


def verdict(board: Board, *, now: datetime) -> Verdict:
    h = board.health
    rebooting = board.rebooting_since is not None and now - board.rebooting_since < REBOOT_WINDOW
    # Checked before DOWN: Tailscale marks a rebooting board offline within seconds.
    if rebooting and (not board.peer.online or h is None or h.error):
        return Verdict.REBOOTING
    if not board.peer.online:
        return Verdict.DOWN
    if h is None:
        return Verdict.PENDING
    if h.error:
        return Verdict.UNREACHABLE
    if board.config.service and h.service_state != "active":
        return Verdict.USELESS
    if warnings(board):
        return Verdict.WARN
    return Verdict.OK


def since(board: Board, *, now: datetime) -> timedelta | None:
    """How long the board has been in its current state, when known."""
    if not board.peer.online:
        return now - board.peer.last_seen if board.peer.last_seen else None
    return now - board.state_since if board.state_since else None


def rank_boards(boards: list[Board], *, now: datetime) -> list[Board]:
    """Worst first; within a state, the longest in it first; then by name."""

    def key(b: Board):
        s = since(b, now=now)
        return (verdict(b, now=now).rank, -(s.total_seconds() if s else 0.0), b.name)

    return sorted(boards, key=key)


def board_name(peer: Peer) -> str:
    """The MagicDNS label: unique per tailnet and what `tailscale ssh` resolves."""
    return peer.dns_name.split(".", 1)[0] or peer.host_name


def select_boards(status: Status, config: FleetConfig) -> list[tuple[Peer, BoardConfig]]:
    """Linux peers (not self) that the config does not ignore or exclude.

    The returned ``BoardConfig.name`` is the board's MagicDNS label; a config
    table keyed by the device's HostName still matches as a fallback.
    """
    out: list[tuple[Peer, BoardConfig]] = []
    for peer in status.peers:
        if peer.is_self or peer.os.lower() != "linux":
            continue
        name = board_name(peer)
        cfg = config.boards.get(name) or config.boards.get(peer.host_name)
        if config.only_listed and cfg is None:
            continue
        cfg = replace(cfg, name=name) if cfg else BoardConfig(name)
        if cfg.ignore:
            continue
        out.append((peer, cfg))
    return out


def fix_command(
    binary: str, board: Board, user: str | None, kind: Literal["restart", "reboot"]
) -> list[str]:
    """The exact argv handed to the terminal for a fix (spec 5.6)."""
    target = f"{user}@{board.name}" if user else board.name
    base = [binary, "ssh", "-t", target, "sudo", "systemctl"]
    if kind == "restart":
        return [*base, "restart", board.config.service or ""]
    return [*base, "reboot"]
