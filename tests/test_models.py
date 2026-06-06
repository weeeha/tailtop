"""Parsing tests — pin the shape of ``tailscale status --json`` to our models.

The fixture is a sanitized capture of a real tailnet (public keys and emails
redacted; CGNAT IPs and hostnames kept so the data is realistic).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.data.models import ConnType, Peer, Status

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


@pytest.fixture
def raw() -> dict:
    return json.loads(FIXTURE.read_text())


@pytest.fixture
def status(raw: dict) -> Status:
    return Status.from_json(raw)


def test_parses_top_level(status: Status) -> None:
    assert status.backend_state == "Running"
    assert status.connected is True
    assert status.version  # non-empty
    assert status.magic_dns_suffix  # e.g. tailXXXX.ts.net


def test_self_peer(status: Status) -> None:
    assert status.self_peer.is_self is True
    assert status.self_peer.conn_type is ConnType.SELF
    assert status.self_peer.ipv4.startswith("100.")


def test_peer_count_matches_fixture(status: Status, raw: dict) -> None:
    assert status.total_count == len(raw["Peer"])
    assert status.total_count == 10


def test_online_count(status: Status) -> None:
    # The captured tailnet had at least one peer online.
    assert 0 < status.online_count <= status.total_count


def test_connection_type_logic() -> None:
    """CurAddr ⇒ direct; else Relay ⇒ DERP; offline ⇒ offline."""
    direct = Peer.from_json(
        {"Online": True, "CurAddr": "192.168.4.43:41641", "Relay": "tor"}
    )
    assert direct.conn_type is ConnType.DIRECT
    assert direct.relay_label == "direct"

    derp = Peer.from_json({"Online": True, "CurAddr": "", "Relay": "nyc"})
    assert derp.conn_type is ConnType.DERP
    assert derp.relay_label == "DERP·nyc"

    offline = Peer.from_json({"Online": False, "Relay": "nyc"})
    assert offline.conn_type is ConnType.OFFLINE

    idle = Peer.from_json({"Online": True, "CurAddr": "", "Relay": ""})
    assert idle.conn_type is ConnType.IDLE


def test_ipv4_and_ipv6_split() -> None:
    p = Peer.from_json({"TailscaleIPs": ["100.114.149.53", "fd7a:115c::1"]})
    assert p.ipv4 == "100.114.149.53"
    assert p.ipv6 == "fd7a:115c::1"


def test_magic_dns_strips_trailing_dot() -> None:
    p = Peer.from_json({"DNSName": "artstation.tail01c8fc.ts.net."})
    assert p.magic_dns == "artstation.tail01c8fc.ts.net"


def test_zero_handshake_is_none() -> None:
    p = Peer.from_json({"LastHandshake": "0001-01-01T00:00:00Z"})
    assert p.last_handshake is None


def test_sorted_peers_online_first(status: Status) -> None:
    types = [p.online for p in status.sorted_peers()]
    # once we hit the first offline peer, none after it may be online
    if False in types:
        first_offline = types.index(False)
        assert all(t is False for t in types[first_offline:])
