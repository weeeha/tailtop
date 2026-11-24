"""Fleet probing loop.

``FleetPoller`` reads the app's latest ``Status`` to learn which boards are
online, probes those over an injected runner (real: ``tailscale ssh``; demo and
tests: canned text), ranks the result and hands it to a callback. It runs only
while Fleet mode is on screen.
"""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from tailtop.data.fleet import (
    PROBE_SCRIPT,
    Board,
    BoardHealth,
    parse_probe,
    rank_boards,
    select_boards,
    verdict,
)
from tailtop.data.fleet_config import FleetConfig
from tailtop.data.models import Status

HISTORY_LEN = 60
REBOOT_PROBE_INTERVAL = 15.0
USER_HINT = "unreachable · set user in fleet.toml"


class ProbeError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


ProbeRunner = Callable[[str, str | None, str | None], Awaitable[str]]


def ssh_probe_runner(binary: str = "tailscale", timeout: float = 10.0) -> ProbeRunner:
    """A runner that pipes ``PROBE_SCRIPT`` to ``sh`` on the board over Tailscale SSH."""

    async def run(host: str, user: str | None, service: str | None) -> str:
        target = f"{user}@{host}" if user else host
        try:
            proc = await asyncio.create_subprocess_exec(
                binary, "ssh", target, "sh", "-s", "--", service or "",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise ProbeError("tailscale CLI not found") from exc
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(PROBE_SCRIPT.encode()), timeout=timeout
            )
        except (TimeoutError, asyncio.CancelledError) as exc:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            await proc.wait()
            if isinstance(exc, asyncio.CancelledError):
                raise
            raise ProbeError(f"timeout after {timeout:g}s") from exc

        stdout = out.decode("utf-8", "replace")
        if proc.returncode == 0 or "hostname=" in stdout:
            return stdout
        stderr = err.decode("utf-8", "replace").strip()
        if "failed to look up local user" in stderr or "does not permit" in stderr:
            raise ProbeError(USER_HINT)
        lines = [ln for ln in stderr.splitlines() if ln.strip()]
        raise ProbeError(lines[-1] if lines else f"ssh exited {proc.returncode}")

    return run


class FleetHistory:
    """Per-board temperature and load ring buffers for sparklines."""

    def __init__(self) -> None:
        self._temps: dict[str, deque[float]] = {}
        self._loads: dict[str, deque[float]] = {}

    def record(self, name: str, temp_c: float | None, load1: float | None) -> None:
        if temp_c is not None:
            self._temps.setdefault(name, deque(maxlen=HISTORY_LEN)).append(temp_c)
        if load1 is not None:
            self._loads.setdefault(name, deque(maxlen=HISTORY_LEN)).append(load1)

    def temps(self, name: str) -> list[float]:
        return list(self._temps.get(name, ()))

    def loads(self, name: str) -> list[float]:
        return list(self._loads.get(name, ()))


def _failed(message: str, now: datetime) -> BoardHealth:
    return BoardHealth(
        None, None, None, None, None, None, None, None, None, None, None, message, now
    )


class FleetPoller:
    def __init__(
        self,
        runner: ProbeRunner,
        get_status: Callable[[], Status | None],
        config: FleetConfig,
        on_update: Callable[[list[Board]], None],
        *,
        interval: float | None = None,
        concurrency: int = 4,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self.runner = runner
        self.get_status = get_status
        self.config = config
        self.on_update = on_update
        self.interval = interval if interval is not None else config.interval
        self.concurrency = concurrency
        self.clock = clock
        self.boards: dict[str, Board] = {}
        self.history = FleetHistory()
        self._verdicts: dict[str, object] = {}
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    # ---- control -----------------------------------------------------------

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def probe_now(self, name: str | None = None) -> None:
        """Run a cycle now. A cycle probes every online board, ``name`` included."""
        self._wake.set()

    def mark_rebooting(self, name: str) -> None:
        board = self.boards.get(name)
        if board is not None:
            board.rebooting_since = self.clock()
        self._wake.set()

    # ---- one pass ----------------------------------------------------------

    async def cycle(self) -> None:
        status = self.get_status()
        if status is None:
            return
        now = self.clock()
        boards: dict[str, Board] = {}
        for peer, cfg in select_boards(status, self.config):
            b = self.boards.get(peer.host_name) or Board(peer.host_name, peer, cfg)
            b.peer, b.config = peer, cfg
            if not peer.online:
                b.health = None
            boards[b.name] = b
        self.boards = boards

        sem = asyncio.Semaphore(self.concurrency)

        async def probe(b: Board) -> None:
            async with sem:
                try:
                    text = await self.runner(b.name, self.config.user_for(b.name), b.config.service)
                    b.health = parse_probe(text, now=now)
                except ProbeError as exc:
                    b.health = _failed(exc.message, now)
                except Exception as exc:  # noqa: BLE001 — one board must not stop the fleet
                    b.health = _failed(str(exc) or type(exc).__name__, now)
            if b.health.error is None:
                b.rebooting_since = None
                self.history.record(b.name, b.health.temp_c, b.health.load1)

        await asyncio.gather(*(probe(b) for b in boards.values() if b.peer.online))

        for b in boards.values():
            v = verdict(b, now=now)
            if self._verdicts.get(b.name) != v:
                self._verdicts[b.name] = v
                b.state_since = now
        self.on_update(rank_boards(list(boards.values()), now=now))

    async def _loop(self) -> None:
        while True:
            await self.cycle()
            rebooting = any(b.rebooting_since for b in self.boards.values())
            wait = min(self.interval, REBOOT_PROBE_INTERVAL) if rebooting else self.interval
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=wait)
            except TimeoutError:
                pass
