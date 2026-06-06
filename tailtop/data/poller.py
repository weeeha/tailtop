"""Async refresh loop.

Polls ``status`` on an interval and hands each fresh ``Status`` to a callback.
The cadence is adjustable at runtime so the active mode can speed it up
(Cockpit) or slow it down (Comfort). Errors are delivered to an optional error
callback rather than killing the loop.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable

from tailtop.data.client import TailscaleClient
from tailtop.data.models import Status

StatusCallback = Callable[[Status], Awaitable[None] | None]
ErrorCallback = Callable[[Exception], Awaitable[None] | None]


class Poller:
    def __init__(
        self,
        client: TailscaleClient,
        on_status: StatusCallback,
        on_error: ErrorCallback | None = None,
        interval: float = 2.0,
    ) -> None:
        self._client = client
        self._on_status = on_status
        self._on_error = on_error
        self._interval = interval
        self._task: asyncio.Task | None = None
        self._wake = asyncio.Event()

    @property
    def interval(self) -> float:
        return self._interval

    def set_interval(self, seconds: float) -> None:
        """Change cadence; takes effect on the next cycle immediately."""
        self._interval = max(0.1, seconds)
        self._wake.set()

    def refresh_now(self) -> None:
        self._wake.set()

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

    async def _loop(self) -> None:
        while True:
            try:
                status = await self._client.status()
                result = self._on_status(status)
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 — surfaced, not swallowed
                if self._on_error:
                    result = self._on_error(exc)
                    if asyncio.iscoroutine(result):
                        await result
            # Sleep until interval elapses or someone pokes _wake.
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self._interval)
            except asyncio.TimeoutError:
                pass
