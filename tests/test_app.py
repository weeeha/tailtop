"""App-level render tests using Textual's headless harness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.app import TailtopApp
from tailtop.data.models import Status
from tailtop.widgets.device_list import DeviceList

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


@pytest.fixture
def status() -> Status:
    return Status.from_json(json.loads(FIXTURE.read_text()))


async def test_app_mounts_and_populates(status: Status) -> None:
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        device_list = app.query_one(DeviceList)
        assert len(device_list) == status.total_count == 10
        assert app.error == ""


async def test_tab_cycles_modes(status: Status) -> None:
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        assert app.active_mode == "comfort"
        await pilot.press("tab")
        assert app.active_mode == "cockpit"
        await pilot.press("tab")
        assert app.active_mode == "observatory"
        await pilot.press("tab")
        assert app.active_mode == "comfort"


async def test_navigation_updates_selection(status: Status) -> None:
    app = TailtopApp(auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        comfort = app.query_one("#comfort")
        first = comfort._selected_id
        await pilot.press("j")
        await pilot.pause()
        assert comfort._selected_id != first  # moved to next peer
