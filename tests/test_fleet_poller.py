"""FleetPoller with a fake probe runner, and the real ssh runner against a fake binary."""

from __future__ import annotations

import asyncio
import stat
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from tailtop.data.fleet import Board, Verdict, verdict
from tailtop.data.fleet_config import FleetConfig
from tailtop.data.fleet_poller import FleetHistory, FleetPoller, ProbeError, ssh_probe_runner
from tailtop.data.models import Peer, Status

FIXTURES = Path(__file__).parent / "fixtures"
PROBE = (FIXTURES / "probe_pi4.txt").read_text()
NOW = datetime(2026, 11, 23, 21, 0, tzinfo=UTC)


def peer(name: str, online: bool = True, days_ago: float | None = None) -> Peer:
    d = {"ID": name, "HostName": name, "OS": "linux", "Online": online}
    if days_ago is not None:
        d["LastSeen"] = (NOW - timedelta(days=days_ago)).isoformat().replace("+00:00", "Z")
    return Peer.from_json(d)


def status(*peers: Peer) -> Status:
    me = Peer.from_json({"ID": "me", "HostName": "mac", "OS": "macOS"}, is_self=True)
    return Status("1", "Running", [], "", "", me, list(peers))


class Recorder:
    def __init__(self, text: str = PROBE, fail: dict[str, str] | None = None) -> None:
        self.text = text
        self.fail = fail or {}
        self.calls: list[tuple[str, str | None, str | None]] = []
        self.in_flight = 0
        self.max_in_flight = 0

    async def __call__(self, host: str, user: str | None, service: str | None) -> str:
        self.calls.append((host, user, service))
        self.in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self.in_flight)
        try:
            await asyncio.sleep(0.01)
            if host in self.fail:
                raise ProbeError(self.fail[host])
            return self.text
        finally:
            self.in_flight -= 1


def make_poller(runner, st, config: FleetConfig | None = None):
    updates: list[list[Board]] = []
    box = {"status": st}
    poller = FleetPoller(
        runner, lambda: box["status"], config or FleetConfig(), updates.append, clock=lambda: NOW
    )
    return poller, updates, box


async def test_offline_boards_not_probed() -> None:
    r = Recorder()
    poller, _, _ = make_poller(r, status(peer("plant"), peer("slow", online=False, days_ago=168)))
    await poller.cycle()
    assert [c[0] for c in r.calls] == ["plant"]


async def test_concurrency_capped_at_4() -> None:
    r = Recorder()
    poller, _, _ = make_poller(r, status(*(peer(f"b{i}") for i in range(8))))
    await poller.cycle()
    assert len(r.calls) == 8
    assert r.max_in_flight == 4


async def test_probe_error_becomes_unreachable() -> None:
    r = Recorder(fail={"plant": "unreachable · set user in fleet.toml"})
    poller, _, _ = make_poller(r, status(peer("plant")))
    await poller.cycle()
    b = poller.boards["plant"]
    assert b.health.error == "unreachable · set user in fleet.toml"
    assert b.health.temp_c is None
    assert verdict(b, now=NOW) is Verdict.UNREACHABLE


async def test_board_going_offline_drops_numbers() -> None:
    poller, _, box = make_poller(Recorder(), status(peer("plant")))
    await poller.cycle()
    assert poller.boards["plant"].health.temp_c == 52.0
    box["status"] = status(peer("plant", online=False, days_ago=0.01))
    await poller.cycle()
    assert poller.boards["plant"].health is None
    assert verdict(poller.boards["plant"], now=NOW) is Verdict.DOWN


async def test_on_update_gets_ranked_list() -> None:
    poller, updates, _ = make_poller(Recorder(), status(peer("plant"), peer("slow", False, 168)))
    await poller.cycle()
    assert [b.name for b in updates[-1]] == ["slow", "plant"]


async def test_user_and_service_passed_to_runner() -> None:
    from tailtop.data.fleet_config import BoardConfig

    r = Recorder()
    cfg = FleetConfig(user="u1", boards={"plant": BoardConfig("plant", service="tailprobe")})
    poller, _, _ = make_poller(r, status(peer("plant")), cfg)
    await poller.cycle()
    assert r.calls == [("plant", "u1", "tailprobe")]


async def test_state_since_set_on_change() -> None:
    poller, _, _ = make_poller(Recorder(), status(peer("plant")))
    await poller.cycle()
    assert poller.boards["plant"].state_since == NOW


async def test_history_bounded_at_60() -> None:
    poller, _, _ = make_poller(Recorder(), status(peer("plant")))
    for _ in range(65):
        await poller.cycle()
    assert len(poller.history.temps("plant")) == 60
    assert poller.history.loads("plant")[-1] == 0.40


def test_history_skips_none() -> None:
    h = FleetHistory()
    h.record("x", None, 0.5)
    assert h.temps("x") == [] and h.loads("x") == [0.5]


async def test_mark_rebooting_shows_rebooting() -> None:
    r = Recorder()
    poller, _, _ = make_poller(r, status(peer("plant")))
    await poller.cycle()
    poller.mark_rebooting("plant")
    r.fail["plant"] = "timeout after 10s"
    await poller.cycle()
    assert verdict(poller.boards["plant"], now=NOW) is Verdict.REBOOTING


async def test_stop_cancels_inflight() -> None:
    cancelled = asyncio.Event()

    async def hang(host, user, service):
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    poller, _, _ = make_poller(hang, status(peer("plant")))
    poller.start()
    await asyncio.sleep(0.05)
    await poller.stop()
    assert cancelled.is_set()
    assert poller._task is None


async def test_no_status_is_a_noop() -> None:
    r = Recorder()
    poller, updates, _ = make_poller(r, None)
    await poller.cycle()
    assert r.calls == [] and updates == []


# ---- the real ssh runner against a fake ``tailscale`` binary ----------------


def fake_binary(tmp_path: Path, body: str) -> str:
    p = tmp_path / "tailscale"
    p.write_text("#!/bin/sh\n" + body)
    p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return str(p)


async def test_ssh_runner_maps_refused_user(tmp_path) -> None:
    b = fake_binary(tmp_path, 'echo "tailscale: failed to look up local user \\"nickv\\"" >&2\nexit 255\n')
    with pytest.raises(ProbeError, match="set user in fleet.toml"):
        await ssh_probe_runner(b)("plant", None, None)


async def test_ssh_runner_maps_policy_denied(tmp_path) -> None:
    b = fake_binary(tmp_path, 'echo "tailnet policy does not permit you to SSH as user" >&2\nexit 255\n')
    with pytest.raises(ProbeError, match="set user in fleet.toml"):
        await ssh_probe_runner(b)("plant", "pi", None)


async def test_ssh_runner_timeout(tmp_path) -> None:
    b = fake_binary(tmp_path, "sleep 5\n")
    with pytest.raises(ProbeError, match="timeout"):
        await ssh_probe_runner(b, timeout=0.2)("plant", None, None)


async def test_ssh_runner_argv_and_partial_success(tmp_path) -> None:
    log = tmp_path / "argv"
    b = fake_binary(tmp_path, f'echo "$@" > {log}\ncat >/dev/null\necho hostname=plant\nexit 1\n')
    out = await ssh_probe_runner(b)("plant", "nickv2026", "tailprobe")
    assert out.strip() == "hostname=plant"
    assert log.read_text().strip() == "ssh nickv2026@plant sh -s -- tailprobe"


async def test_ssh_runner_other_error_uses_last_stderr_line(tmp_path) -> None:
    b = fake_binary(tmp_path, 'echo "first" >&2\necho "connection refused" >&2\nexit 255\n')
    with pytest.raises(ProbeError, match="^connection refused$"):
        await ssh_probe_runner(b)("plant", None, None)


async def test_unexpected_runner_error_becomes_unreachable() -> None:
    async def boom(host, user, service):
        raise OSError("pipe broke")

    poller, updates, _ = make_poller(boom, status(peer("plant")))
    await poller.cycle()
    assert poller.boards["plant"].health.error == "pipe broke"
    assert len(updates) == 1


async def test_demo_fleet_covers_every_state() -> None:
    from tailtop.data.demo import DemoClient, demo_fleet_config, demo_probe_runner

    st = await DemoClient().status()
    updates: list[list[Board]] = []
    poller = FleetPoller(demo_probe_runner(), lambda: st, demo_fleet_config(), updates.append)
    await poller.cycle()
    now = datetime.now(UTC)
    names = {b.name for b in updates[-1]}
    assert names == {
        "clock-hall", "clock-desk", "clock-round", "clock-square",
        "eink-bed", "eink-kitchen", "plant-monitor", "tv-board",
    }
    verdicts = {verdict(b, now=now) for b in updates[-1]}
    assert {Verdict.DOWN, Verdict.UNREACHABLE, Verdict.USELESS, Verdict.WARN, Verdict.OK} <= verdicts
    assert updates[-1][0].name == "eink-bed"


async def test_good_probe_right_after_reboot_keeps_rebooting_mark() -> None:
    r = Recorder()
    poller, _, _ = make_poller(r, status(peer("plant")))
    await poller.cycle()
    poller.mark_rebooting("plant")
    await poller.cycle()  # board still answers for a moment before it goes down
    r.fail["plant"] = "timeout after 10s"
    await poller.cycle()
    assert verdict(poller.boards["plant"], now=NOW) is Verdict.REBOOTING


def test_fast_cadence_only_inside_reboot_window() -> None:
    poller, _, _ = make_poller(Recorder(), status(peer("plant")))
    poller.boards["plant"] = Board("plant", peer("plant"), FleetConfig().board("plant"))
    assert poller.next_wait() == 30.0
    poller.boards["plant"].rebooting_since = NOW - timedelta(seconds=10)
    assert poller.next_wait() == 15.0
    poller.boards["plant"].rebooting_since = NOW - timedelta(seconds=400)
    assert poller.next_wait() == 30.0


# ---- final review fixes ------------------------------------------------------


async def test_apply_status_marks_offline_without_probing() -> None:
    r = Recorder()
    poller, updates, box = make_poller(r, status(peer("plant")))
    await poller.cycle()
    calls = len(r.calls)
    box["status"] = status(peer("plant", online=False, days_ago=0.01))
    poller.apply_status()
    assert len(r.calls) == calls
    assert poller.boards["plant"].health is None
    assert verdict(updates[-1][0], now=NOW) is Verdict.DOWN


async def test_apply_status_wakes_when_board_returns() -> None:
    poller, _, box = make_poller(Recorder(), status(peer("plant", online=False, days_ago=1)))
    await poller.cycle()
    box["status"] = status(peer("plant"))
    poller._wake.clear()
    poller.apply_status()
    assert poller._wake.is_set()
    assert verdict(poller.boards["plant"], now=NOW) is Verdict.PENDING


async def test_restart_while_stopping_leaves_a_running_task() -> None:
    async def hang(host, user, service):
        await asyncio.Event().wait()

    poller, _, _ = make_poller(hang, status(peer("plant")))
    poller.start()
    await asyncio.sleep(0.02)
    stopping = asyncio.create_task(poller.stop())
    await asyncio.sleep(0)
    poller.start()
    await stopping
    assert poller._task is not None and not poller._task.done()
    await poller.stop()


async def test_runner_gets_magicdns_name() -> None:
    r = Recorder()
    p = Peer.from_json({"ID": "1", "HostName": "raspberrypi", "OS": "linux", "Online": True,
                        "DNSName": "raspberrypi-1.tail.ts.net."})
    poller, _, _ = make_poller(r, status(p))
    await poller.cycle()
    assert r.calls[0][0] == "raspberrypi-1"
    assert "raspberrypi-1" in poller.boards
