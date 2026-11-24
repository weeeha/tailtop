"""Fleet mode in the app: mode switching, ranked table, poller lifecycle."""

from __future__ import annotations

from tailtop.app import TailtopApp
from tailtop.data.demo import DemoClient, demo_fleet_config, demo_probe_runner
from tailtop.modes.fleet import FleetMode
from tailtop.widgets.fleet_table import FleetTable


def make_app() -> TailtopApp:
    return TailtopApp(
        client=DemoClient(),
        auto_poll=False,
        splash=False,
        fleet_runner=demo_probe_runner(),
        fleet_config=demo_fleet_config(),
    )


async def load(app: TailtopApp, pilot) -> None:
    app._on_status(await app.client.status())
    await app.fleet.cycle()
    await pilot.pause()


async def test_number_keys_switch_modes() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await load(app, pilot)
        await pilot.press("4")
        assert app.active_mode == "fleet"
        await pilot.press("2")
        assert app.active_mode == "cockpit"
        await pilot.press("1")
        assert app.active_mode == "comfort"


async def test_tab_cycles_through_fleet() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await load(app, pilot)
        seen = []
        for _ in range(4):
            await pilot.press("tab")
            seen.append(app.active_mode)
        assert seen == ["cockpit", "observatory", "fleet", "comfort"]


async def test_fleet_table_worst_first() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await load(app, pilot)
        table = app.query_one(FleetTable)
        names = table.board_names()
        assert names[0] == "eink-bed"  # down 117 d
        assert names[1] == "clock-round"  # down 41 d
        assert set(names[-3:]) == {"clock-hall", "clock-desk", "plant-monitor"}  # ok


async def test_missing_numbers_render_dash() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await load(app, pilot)
        row = app.query_one(FleetTable).row_text("clock-round")
        assert row[1] == "down"
        assert row[2] == "41d"
        assert row[3:] == ["–", "–", "–", "–"]


async def test_summary_counts() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await load(app, pilot)
        mode = app.query_one(FleetMode)
        assert "8" in mode.summary_text("fleet-boards")
        assert "2" in mode.summary_text("fleet-down")
        assert "1" in mode.summary_text("fleet-useless")


async def test_leaving_fleet_stops_poller() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await load(app, pilot)
        await pilot.press("4")
        await pilot.pause()
        assert app.fleet._task is not None
        await pilot.press("1")
        await pilot.pause()
        await pilot.pause()
        assert app.fleet._task is None or app.fleet._task.done()


async def test_cursor_kept_across_updates() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await load(app, pilot)
        table = app.query_one(FleetTable)
        table.select_board("plant-monitor")
        await app.fleet.cycle()
        await pilot.pause()
        assert app.query_one(FleetMode).selected_board().name == "plant-monitor"
