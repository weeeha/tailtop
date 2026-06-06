"""Prove the poller → watch_status → render path end-to-end with a fake client.

This decouples the data-flow from the real subprocess: if this passes, a live
terminal will populate (the real client's status() is covered separately).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.app import TailtopApp
from tailtop.data.models import Status
from tailtop.widgets.device_list import DeviceList

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


class FakeClient:
    available = True

    def __init__(self, status: Status) -> None:
        self._status = status

    async def status(self) -> Status:
        return self._status


async def test_poller_populates_app() -> None:
    status = Status.from_json(json.loads(FIXTURE.read_text()))
    app = TailtopApp(client=FakeClient(status), auto_poll=True)
    async with app.run_test() as pilot:
        # give the poller a couple of ticks to deliver the first status
        for _ in range(5):
            await pilot.pause()
            if app.status is not None:
                break
        assert app.status is not None
        assert app.query_one(DeviceList).__len__() == status.total_count
