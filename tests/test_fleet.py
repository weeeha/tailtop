"""Fleet probe parsing, throttle decoding, verdicts and ranking."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tailtop.data.fleet import (
    Board,
    Throttle,
    Verdict,
    decode_throttled,
    parse_probe,
    rank_boards,
    select_boards,
    since,
    verdict,
    warnings,
)
from tailtop.data.fleet_config import BoardConfig, FleetConfig
from tailtop.data.models import Peer, Status

FIXTURES = Path(__file__).parent / "fixtures"
NOW = datetime(2026, 11, 23, 21, 0, tzinfo=UTC)


def fixture(name: str) -> str:
    return (FIXTURES / name).read_text()


def make_peer(name: str, *, online: bool = True, os: str = "linux", last_seen=None) -> Peer:
    d = {"ID": name, "HostName": name, "OS": os, "Online": online}
    if last_seen is not None:
        d["LastSeen"] = last_seen.isoformat().replace("+00:00", "Z")
    return Peer.from_json(d)


def make_board(
    name: str = "b",
    *,
    online: bool = True,
    last_seen=None,
    fixture_name: str = "probe_pi4.txt",
    error: str | None = None,
    service: str | None = None,
    temp_milli: int | None = None,
    throttled: str | None = None,
    rebooting_since=None,
    probed: bool = True,
    state_since=None,
) -> Board:
    peer = make_peer(name, online=online, last_seen=last_seen)
    health = None
    if online and probed:
        text = fixture(fixture_name)
        if temp_milli is not None:
            text = text.replace("temp_milli=52000", f"temp_milli={temp_milli}")
        if throttled is not None:
            text = text.replace("throttled=0x0", f"throttled={throttled}")
        health = parse_probe(text, now=NOW)
        if error is not None:
            health = parse_probe("", now=NOW)
            health.error = error
    return Board(
        name=name,
        peer=peer,
        config=BoardConfig(name, service=service),
        health=health,
        rebooting_since=rebooting_since,
        state_since=state_since,
    )


# ---- parsing -----------------------------------------------------------------


def test_parse_zero2w() -> None:
    h = parse_probe(fixture("probe_zero2w.txt"), now=NOW)
    assert h.temp_c == pytest.approx(47.2, abs=0.05)
    assert (h.load1, h.cores, h.disk_pct) == (0.02, 4, 46)
    assert h.mem_pct == pytest.approx(50.7, abs=0.1)
    assert h.throttle == Throttle(False, False, False, False)
    assert h.model == "Raspberry Pi Zero 2 W Rev 1.0"
    assert h.service_state is None
    assert h.error is None
    assert h.probed_at == NOW


def test_parse_missing_keys_are_none() -> None:
    h = parse_probe(fixture("probe_no_vcgencmd.txt"), now=NOW)
    assert h.throttle is None
    assert h.model is None
    assert h.temp_c == 52.0


def test_parse_garbage_and_empty() -> None:
    h = parse_probe("temp_milli=hot\nloadavg=x y z\nnot a line", now=NOW)
    assert h.temp_c is None and h.load1 is None and h.error is None
    assert parse_probe("", now=NOW).error == "empty probe output"


def test_decode_throttled() -> None:
    assert decode_throttled("0x50005") == Throttle(True, True, True, True)
    assert decode_throttled("0x50000") == Throttle(False, False, True, True)
    assert decode_throttled("nope") == Throttle(False, False, False, False)


# ---- verdicts ----------------------------------------------------------------


def test_verdicts() -> None:
    assert verdict(make_board(online=False), now=NOW) is Verdict.DOWN
    assert verdict(make_board(error="refused"), now=NOW) is Verdict.UNREACHABLE
    assert (
        verdict(make_board(error="timeout", rebooting_since=NOW - timedelta(seconds=60)), now=NOW)
        is Verdict.REBOOTING
    )
    assert (
        verdict(make_board(error="timeout", rebooting_since=NOW - timedelta(seconds=200)), now=NOW)
        is Verdict.UNREACHABLE
    )
    inactive = "probe_service_inactive.txt"
    assert verdict(make_board(fixture_name=inactive, service="kiosk"), now=NOW) is Verdict.USELESS
    assert verdict(make_board(fixture_name=inactive, service=None), now=NOW) is Verdict.OK
    assert verdict(make_board(temp_milli=72000), now=NOW) is Verdict.WARN
    assert verdict(make_board(throttled="0x4"), now=NOW) is Verdict.WARN
    assert verdict(make_board(throttled="0x40000"), now=NOW) is Verdict.OK  # only "ever"
    assert verdict(make_board(probed=False), now=NOW) is Verdict.PENDING


def test_warnings_text() -> None:
    assert warnings(make_board(temp_milli=72000)) == ["72°C"]
    assert warnings(make_board(throttled="0x5")) == ["under-voltage", "throttled"]
    assert warnings(make_board()) == []


def test_since_down_uses_last_seen() -> None:
    b = make_board(online=False, last_seen=NOW - timedelta(days=168))
    assert since(b, now=NOW) == timedelta(days=168)
    assert since(make_board(online=False), now=NOW) is None


def test_rank_worst_first_and_longest_down_first() -> None:
    a = make_board("a", online=False, last_seen=NOW - timedelta(days=4))
    b = make_board("b", online=False, last_seen=NOW - timedelta(days=168))
    c = make_board("c")
    d = make_board("d", temp_milli=75000)
    p = make_board("p", probed=False)
    assert [x.name for x in rank_boards([c, p, a, d, b], now=NOW)] == ["b", "a", "d", "c", "p"]


# ---- selection ---------------------------------------------------------------


def _status(*peers: Peer) -> Status:
    me = Peer.from_json({"ID": "me", "HostName": "mac", "OS": "macOS"}, is_self=True)
    return Status("1", "Running", [], "", "", me, list(peers))


def test_select_boards() -> None:
    st = _status(
        make_peer("plant"), make_peer("pc", os="windows"), make_peer("mac2", os="macOS"),
        make_peer("srv"), make_peer("clock", os="Linux"),
    )
    names = lambda cfg: sorted(p.host_name for p, _ in select_boards(st, cfg))  # noqa: E731
    assert names(FleetConfig()) == ["clock", "plant", "srv"]
    ignore = FleetConfig(boards={"srv": BoardConfig("srv", ignore=True)})
    assert names(ignore) == ["clock", "plant"]
    only = FleetConfig(only_listed=True, boards={"plant": BoardConfig("plant", service="x")})
    assert names(only) == ["plant"]
    assert select_boards(st, only)[0][1].service == "x"


# ---- final review fixes ------------------------------------------------------


def test_offline_inside_reboot_window_is_rebooting() -> None:
    b = make_board(online=False, rebooting_since=NOW - timedelta(seconds=30))
    assert verdict(b, now=NOW) is Verdict.REBOOTING
    old = make_board(online=False, rebooting_since=NOW - timedelta(seconds=400))
    assert verdict(old, now=NOW) is Verdict.DOWN


def test_board_name_is_magicdns_label() -> None:
    from tailtop.data.fleet import board_name

    p = Peer.from_json({"ID": "1", "HostName": "raspberrypi", "DNSName": "raspberrypi-1.tail.ts.net."})
    assert board_name(p) == "raspberrypi-1"
    assert board_name(Peer.from_json({"ID": "2", "HostName": "plain"})) == "plain"


def test_duplicate_hostnames_stay_separate() -> None:
    a = Peer.from_json({"ID": "1", "HostName": "raspberrypi", "OS": "linux",
                        "DNSName": "raspberrypi.tail.ts.net."})
    b = Peer.from_json({"ID": "2", "HostName": "raspberrypi", "OS": "linux",
                        "DNSName": "raspberrypi-1.tail.ts.net."})
    cfg = FleetConfig(boards={"raspberrypi-1": BoardConfig("raspberrypi-1", service="kiosk")})
    picked = select_boards(_status(a, b), cfg)
    assert [c.name for _, c in picked] == ["raspberrypi", "raspberrypi-1"]
    assert picked[1][1].service == "kiosk"


def test_row_shows_user_hint() -> None:
    from tailtop.data.fleet_poller import USER_HINT
    from tailtop.widgets.fleet_table import row_cells

    b = make_board(error=USER_HINT)
    assert row_cells(b, NOW)[1] == "unreachable · set user"
