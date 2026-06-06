"""The only CLI-aware code in tailtop.

``TailscaleClient`` shells out to the ``tailscale`` binary, applies timeouts,
normalizes failures into typed exceptions, and returns parsed models. Every
read and every action funnels through here.
"""

from __future__ import annotations

import asyncio
import json
import shutil

from tailtop.data.models import Status


class TailscaleError(Exception):
    """A tailscale command failed (non-zero exit)."""

    def __init__(self, args: list[str], returncode: int, stderr: str) -> None:
        self.args = args
        self.returncode = returncode
        self.stderr = stderr.strip()
        super().__init__(f"`tailscale {' '.join(args)}` failed: {self.stderr}")


class TailscaleNotFound(Exception):
    """The tailscale binary is not on PATH."""


class TailscaleTimeout(Exception):
    """A tailscale command exceeded its timeout."""


class TailscaleClient:
    """Async wrapper around the tailscale CLI."""

    def __init__(self, binary: str | None = None, default_timeout: float = 10.0) -> None:
        self._binary = binary or shutil.which("tailscale") or "tailscale"
        self.default_timeout = default_timeout

    @property
    def available(self) -> bool:
        return shutil.which(self._binary) is not None or self._binary == "tailscale"

    # ---- low-level runner --------------------------------------------------

    async def run(
        self, *args: str, timeout: float | None = None, check: bool = True
    ) -> str:
        """Run ``tailscale <args>`` and return stdout.

        Raises TailscaleNotFound / TailscaleTimeout / TailscaleError.
        """
        try:
            proc = await asyncio.create_subprocess_exec(
                self._binary,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except FileNotFoundError as exc:
            raise TailscaleNotFound(self._binary) from exc

        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=timeout or self.default_timeout
            )
        except asyncio.TimeoutError as exc:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
            raise TailscaleTimeout(" ".join(args)) from exc

        stdout = out.decode("utf-8", "replace")
        if check and proc.returncode != 0:
            raise TailscaleError(list(args), proc.returncode or -1, err.decode("utf-8", "replace"))
        return stdout

    # ---- reads -------------------------------------------------------------

    async def status(self) -> Status:
        raw = await self.run("status", "--json", timeout=8.0)
        return Status.from_json(json.loads(raw))

    async def netcheck(self) -> dict:
        raw = await self.run("netcheck", "--format=json", timeout=20.0)
        return json.loads(raw)

    async def whois(self, ip: str) -> str:
        return await self.run("whois", ip, timeout=8.0)

    async def ping_once(self, host: str) -> str:
        """One ping; stdout carries 'via DERP(region)' or 'direct ... in Nms'."""
        return await self.run("ping", "--c", "1", "--timeout", "3s", host, timeout=6.0, check=False)
