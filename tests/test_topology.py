"""Topology grouping tests."""

from __future__ import annotations

import json
from pathlib import Path

from tailtop.data.models import Status
from tailtop.widgets.topology import build_topology

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


def test_groups_sum_to_peer_count() -> None:
    status = Status.from_json(json.loads(FIXTURE.read_text()))
    topo = build_topology(status)
    total = topo.direct_count + topo.relayed_count + len(topo.offline)
    assert total == status.total_count


def test_relayed_keyed_by_region() -> None:
    status = Status.from_json(json.loads(FIXTURE.read_text()))
    topo = build_topology(status)
    # every relayed peer sits under its DERP region code
    for region, peers in topo.relayed.items():
        assert region  # non-empty region label
        for p in peers:
            assert p.online
