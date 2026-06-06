"""Verb wiring tests — selection, copy, ping result, exit-node guard, palette."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.app import TailtopApp
from tailtop.data.models import Status
from tailtop.screens import ResultScreen

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


class FakeClient:
    available = True
    _binary = "tailscale"

    def __init__(self, status: Status, output: str = "pong: direct 6ms") -> None:
        self._status = status
        self._output = output
        self.calls: list[tuple[str, ...]] = []

    async def status(self) -> Status:
        return self._status

    async def run(self, *args: str, **kwargs) -> str:
        self.calls.append(args)
        return self._output


@pytest.fixture
def status() -> Status:
    return Status.from_json(json.loads(FIXTURE.read_text()))


async def test_copy_ip_copies_selected(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    captured: list[str] = []
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        peer = status.peers[0]
        app.selected_peer_id = peer.id
        app.copy_to_clipboard = lambda text: captured.append(text)  # type: ignore[method-assign]
        app.action_copy_ip()
        assert captured == [peer.ipv4]


async def test_ping_opens_result_screen(status: Status) -> None:
    client = FakeClient(status, output="pong from 100.x: direct, 6ms")
    app = TailtopApp(client=client, auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        app.selected_peer_id = status.peers[0].id
        app.action_ping()
        for _ in range(8):
            await pilot.pause()
            if isinstance(app.screen, ResultScreen):
                break
        assert isinstance(app.screen, ResultScreen)
        assert client.calls and client.calls[0][0] == "ping"


async def test_exit_node_guard_on_non_exit(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        # pick a peer that is not an exit-node option
        peer = next(p for p in status.peers if not p.exit_node_option)
        app.selected_peer_id = peer.id
        app.action_exit_node()
        for _ in range(4):
            await pilot.pause()
        # no confirm screen should appear for a non-exit-node peer
        assert app.screen is app.screen_stack[0]


async def test_palette_entries_include_peer_verbs(status: Status) -> None:
    app = TailtopApp(client=FakeClient(status), auto_poll=False)
    async with app.run_test() as pilot:
        app._on_status(status)
        await pilot.pause()
        app.selected_peer_id = status.peers[0].id
        labels = [label for label, _cb, _help in app.palette_entries()]
    assert any(label.startswith("ping ") for label in labels)
    assert any("netcheck" in label for label in labels)
    assert any("exit node" in label for label in labels)
