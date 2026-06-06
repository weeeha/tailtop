"""Disk usage table — `df -h` rendered as grouped, color-thresholded panels.

Each ``MountGroup`` becomes one rounded panel ("4 local devices"), and inside
it the rows show MOUNTED ON / SIZE / USED / AVAIL / USE% / TYPE / FILESYSTEM.
USE% is a 20-char text bar plus the percentage; AVAIL turns warm when free
space gets tight; the bar/percent tint by used-percentage threshold.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rich import box
from rich.console import Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text
from textual.widgets import Static

_GIB = 1024**3


@dataclass
class MountEntry:
    mounted_on: str
    size: int  # bytes
    used: int  # bytes
    avail: int  # bytes
    fs_type: str
    filesystem: str

    @property
    def use_pct(self) -> float:
        if self.size <= 0:
            return 0.0
        return max(0.0, min(100.0, (self.used / self.size) * 100.0))


@dataclass
class MountGroup:
    label: str  # "local devices", "network devices", "special devices"
    entries: list[MountEntry] = field(default_factory=list)


# Palette — aligned with tailtop's existing themes (see widgets/device_card.py).
_C_TEXT = "#cfd3da"
_C_DIM = "#6b6f78"
_C_PATH = "#8bb6ff"
_C_OK = "#7be39b"
_C_WARN = "#f0c674"
_C_HOT = "#e09060"
_C_CRIT = "#ff7878"
_C_BAR_EMPTY = "#3a3a45"
_C_BORDER = "#3a3a45"


def human_bytes(n: int) -> str:
    """Render bytes in binary units the way `df -h` does: 80.0G, 1.4T, 436.4M."""
    if n < 1024:
        return f"{n}B"
    f = float(n) / 1024.0
    for unit in ("K", "M", "G", "T", "P"):
        if f < 1024:
            return f"{f:.1f}{unit}"
        f /= 1024.0
    return f"{f:.1f}E"


def avail_color(avail: int, use_pct: float) -> str:
    # Absolute scarcity wins over percentage — sub-gig free is always alarming.
    if avail < _GIB:
        return _C_CRIT
    if use_pct >= 80.0:
        return _C_WARN
    return _C_OK


def pct_color(pct: float) -> str:
    if pct >= 95.0:
        return _C_CRIT
    if pct >= 80.0:
        return _C_HOT
    if pct >= 50.0:
        return _C_WARN
    return _C_OK


def use_bar(pct: float, width: int = 20) -> Text:
    filled = max(0, min(width, round((pct / 100.0) * width)))
    color = pct_color(pct)
    bar = Text()
    bar.append("[", style=_C_DIM)
    bar.append("#" * filled, style=color)
    bar.append("." * (width - filled), style=_C_BAR_EMPTY)
    bar.append("] ", style=_C_DIM)
    bar.append(f"{pct:>5.1f}%", style=color)
    return bar


class DiskTable(Static):
    """A grouped df-style disk usage table.

    Pass a list of ``MountGroup``s; each renders as a rounded Rich Panel
    titled "<count> <label>" with df columns inside. Call ``set_groups`` to
    swap the data after construction.
    """

    DEFAULT_CSS = """
    DiskTable {
        height: auto;
        padding: 0 1;
    }
    """

    def __init__(self, groups: list[MountGroup] | None = None) -> None:
        self._groups: list[MountGroup] = list(groups or [])
        super().__init__(self._renderable())

    def set_groups(self, groups: list[MountGroup]) -> None:
        self._groups = list(groups)
        self.update(self._renderable())

    def _renderable(self):
        if not self._groups:
            return Text("no disks", style=_C_DIM)
        parts: list = []
        for i, group in enumerate(self._groups):
            if i > 0:
                parts.append(Text(""))  # one blank row between sections
            parts.append(_build_panel(group))
        return Group(*parts)


def _build_panel(group: MountGroup) -> Panel:
    table = Table(
        show_header=True,
        header_style=f"bold {_C_TEXT}",
        show_edge=False,
        box=box.SIMPLE_HEAD,
        pad_edge=False,
        expand=True,
    )
    table.add_column("MOUNTED ON", style=_C_PATH, no_wrap=True)
    table.add_column("SIZE", style=_C_TEXT, justify="right", no_wrap=True)
    table.add_column("USED", style=_C_TEXT, justify="right", no_wrap=True)
    table.add_column("AVAIL", justify="right", no_wrap=True)
    table.add_column("USE%", no_wrap=True)
    table.add_column("TYPE", style=_C_TEXT, no_wrap=True)
    table.add_column("FILESYSTEM", style=_C_PATH, no_wrap=True)

    for e in group.entries:
        size = human_bytes(e.size) if e.size > 0 else "0B"
        used = human_bytes(e.used) if e.used > 0 else "0B"
        avail = Text(human_bytes(e.avail), style=avail_color(e.avail, e.use_pct))
        bar: Text | str = use_bar(e.use_pct) if e.used > 0 else ""
        table.add_row(e.mounted_on, size, used, avail, bar, e.fs_type, e.filesystem)

    return Panel(
        table,
        title=f" {len(group.entries)} {group.label} ",
        title_align="left",
        border_style=_C_BORDER,
        box=box.ROUNDED,
        padding=(0, 1),
    )


# --- demo -------------------------------------------------------------------
#
# Run `python -m tailtop.widgets.disk_table` to render the sample from the
# design reference image directly to your terminal — no Textual app required.

if __name__ == "__main__":
    from rich.console import Console

    def _g(x: float) -> int:
        return int(x * _GIB)

    def _t(x: float) -> int:
        return int(x * 1024 * _GIB)

    def _m(x: float) -> int:
        return int(x * 1024 * 1024)

    def _k(x: float) -> int:
        return int(x * 1024)

    local = MountGroup(
        label="local devices",
        entries=[
            MountEntry("/", _g(80.0), _g(70.3), _g(8.3), "btrfs", "/dev/bender/root"),
            MountEntry("/boot", _m(511), _m(74.5), _m(436.4), "vfat", "/dev/sda1"),
            MountEntry("/home", _g(128.0), _g(118.7), _g(8.1), "btrfs", "/dev/bender/home"),
            MountEntry("/media/hole", _t(7.2), _t(5.5), _t(1.4), "ext4", "/dev/mapper/hole"),
        ],
    )

    nibbler_mounts = [
        "books", "development", "documents", "downloads", "music",
        "photo", "recording", "transfer", "video",
    ]
    network = MountGroup(
        label="network devices",
        entries=[
            MountEntry(
                f"/media/nibbler/{m}", _t(21.8), _t(14.2), _t(7.6), "cifs",
                f"//nibbler/{m}",
            )
            for m in nibbler_mounts
        ],
    )

    special = MountGroup(
        label="special devices",
        entries=[
            MountEntry("/dev", _g(15.6), 0, _g(15.6), "devtmpfs", "devtmpfs"),
            MountEntry("/dev/shm", _g(15.6), _g(1.2), _g(14.4), "tmpfs", "tmpfs"),
            MountEntry("/run", _g(6.2), _m(10.0), _g(6.2), "tmpfs", "tmpfs"),
            MountEntry("/run/user/1000", _g(3.1), _k(148.0), _g(3.1), "tmpfs", "tmpfs"),
            MountEntry("/sys/fs/cgroup", _m(4.0), 0, _m(4.0), "tmpfs", "tmpfs"),
            MountEntry("/tmp", _g(15.6), _m(2.2), _g(15.6), "tmpfs", "tmpfs"),
        ],
    )

    console = Console(width=140)
    widget = DiskTable([local, network, special])
    console.print(widget._renderable())
