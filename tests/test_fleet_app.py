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


# ---- fixes (Task 7) --------------------------------------------------------

from tailtop.data.fleet import Verdict, fix_command, verdict  # noqa: E402
from tailtop.data.fleet_poller import ProbeError  # noqa: E402
from tailtop.screens import ConfirmScreen  # noqa: E402


async def fleet_app_with_handover(pilot_app: TailtopApp, pilot, board: str) -> list[list[str]]:
    calls: list[list[str]] = []
    pilot_app._handover = lambda argv: calls.append(list(argv))
    await load(pilot_app, pilot)
    await pilot.press("4")
    await pilot.pause()
    pilot_app.query_one(FleetTable).select_board(board)
    await pilot.pause()
    return calls


async def test_restart_without_service_warns_no_confirm() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        calls = await fleet_app_with_handover(app, pilot, "clock-hall")
        await pilot.press("R")
        await pilot.pause()
        assert calls == []
        assert not isinstance(app.screen, ConfirmScreen)


async def test_reboot_offline_warns() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        calls = await fleet_app_with_handover(app, pilot, "eink-bed")
        await pilot.press("B")
        await pilot.pause()
        assert calls == []
        assert not isinstance(app.screen, ConfirmScreen)


async def test_restart_confirm_shows_board_and_command() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await fleet_app_with_handover(app, pilot, "plant-monitor")
        await pilot.press("R")
        await pilot.pause()
        assert isinstance(app.screen, ConfirmScreen)
        q = app.screen._question
        assert "plant-monitor" in q and "sudo systemctl restart plantd" in q


async def test_restart_yes_hands_over_exact_argv() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        calls = await fleet_app_with_handover(app, pilot, "plant-monitor")
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert calls == [
            ["tailscale", "ssh", "-t", "demo@plant-monitor", "sudo", "systemctl", "restart", "plantd"]
        ]


async def test_restart_no_runs_nothing() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        calls = await fleet_app_with_handover(app, pilot, "plant-monitor")
        await pilot.press("R")
        await pilot.pause()
        await pilot.press("n")
        await pilot.pause()
        assert calls == []


async def test_reboot_yes_marks_rebooting() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        calls = await fleet_app_with_handover(app, pilot, "clock-desk")
        await pilot.press("B")
        await pilot.pause()
        await pilot.press("y")
        await pilot.pause()
        assert calls == [["tailscale", "ssh", "-t", "demo@clock-desk", "sudo", "systemctl", "reboot"]]
        real = app.fleet.runner

        async def down_for_desk(host, user, service):
            if host == "clock-desk":
                raise ProbeError("timeout after 10s")
            return await real(host, user, service)

        app.fleet.runner = down_for_desk
        await app.fleet.cycle()
        from datetime import UTC, datetime

        assert verdict(app.fleet.boards["clock-desk"], now=datetime.now(UTC)) is Verdict.REBOOTING


async def test_ssh_in_fleet_uses_board_user() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        calls = await fleet_app_with_handover(app, pilot, "plant-monitor")
        await pilot.press("s")
        await pilot.pause()
        assert calls[-1] == ["tailscale", "ssh", "demo@plant-monitor"]


def test_fix_command_exact() -> None:
    from tailtop.data.fleet import Board
    from tailtop.data.fleet_config import BoardConfig
    from tailtop.data.models import Peer

    b = Board("fastclock", Peer.from_json({"ID": "1", "HostName": "fastclock"}),
              BoardConfig("fastclock", service="kiosk"))
    assert fix_command("tailscale", b, "boarduser", "reboot") == [
        "tailscale", "ssh", "-t", "boarduser@fastclock", "sudo", "systemctl", "reboot"
    ]
    assert fix_command("tailscale", b, None, "restart") == [
        "tailscale", "ssh", "-t", "fastclock", "sudo", "systemctl", "restart", "kiosk"
    ]


async def test_status_flip_reaches_table_without_probe() -> None:
    app = make_app()
    async with app.run_test() as pilot:
        await load(app, pilot)
        await pilot.press("4")
        await pilot.pause()
        st = await app.client.status()
        for p in st.peers:
            if p.host_name == "plant-monitor":
                p.online = False
        app._on_status(st)
        await pilot.pause()
        assert app.query_one(FleetTable).row_text("plant-monitor")[1] == "down"
