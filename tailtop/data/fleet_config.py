"""Fleet mode configuration: which boards, which SSH user, which service.

The file is optional. Without it every Linux peer is a board and probes run as
Tailscale's default SSH user. Names that reach a remote shell (``user`` and
``service``) must match ``NAME_RE``; anything else is dropped with an error the
app shows once, so the config can never inject a command on a board.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_PATH = Path.home() / ".config" / "tailtop" / "fleet.toml"
NAME_RE = re.compile(r"^[A-Za-z0-9@._:-]+$")
MIN_INTERVAL = 5.0


@dataclass(frozen=True)
class BoardConfig:
    name: str
    user: str | None = None
    service: str | None = None
    label: str | None = None
    ignore: bool = False


@dataclass(frozen=True)
class FleetConfig:
    user: str | None = None
    interval: float = 30.0
    only_listed: bool = False
    boards: dict[str, BoardConfig] = field(default_factory=dict)

    def board(self, name: str) -> BoardConfig:
        return self.boards.get(name) or BoardConfig(name)

    def user_for(self, name: str) -> str | None:
        return self.board(name).user or self.user


def _safe_name(value: object, where: str, errors: list[str]) -> str | None:
    if value is None:
        return None
    if isinstance(value, str) and NAME_RE.match(value):
        return value
    errors.append(f"fleet.toml: {where} {value!r} is not a valid name, ignored")
    return None


def load_fleet_config(path: Path = DEFAULT_PATH) -> tuple[FleetConfig, list[str]]:
    """Read ``path``; return the config and human-readable errors."""
    if not path.exists():
        return FleetConfig(), []
    try:
        raw = tomllib.loads(path.read_text())
    except (tomllib.TOMLDecodeError, OSError, UnicodeDecodeError) as exc:
        return FleetConfig(), [f"fleet.toml: {exc}"]

    errors: list[str] = []
    defaults = raw.get("defaults") or {}
    if not isinstance(defaults, dict):
        defaults = {}

    try:
        interval = max(MIN_INTERVAL, float(defaults.get("interval", 30.0)))
    except (TypeError, ValueError):
        errors.append("fleet.toml: defaults.interval must be a number, using 30")
        interval = 30.0

    boards: dict[str, BoardConfig] = {}
    for name, b in (raw.get("boards") or {}).items():
        if not isinstance(b, dict):
            continue
        label = b.get("label")
        boards[name] = BoardConfig(
            name=name,
            user=_safe_name(b.get("user"), f"boards.{name}.user", errors),
            service=_safe_name(b.get("service"), f"boards.{name}.service", errors),
            label=label if isinstance(label, str) else None,
            ignore=bool(b.get("ignore", False)),
        )

    return (
        FleetConfig(
            user=_safe_name(defaults.get("user"), "defaults.user", errors),
            interval=interval,
            only_listed=bool(defaults.get("only_listed", False)),
            boards=boards,
        ),
        errors,
    )
