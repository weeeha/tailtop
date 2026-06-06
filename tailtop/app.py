"""tailtop — the Textual application.

Owns the data (client, poller, rate history) and distributes each fresh
snapshot to the active mode. Modes never touch the CLI; they only render the
``Status`` + ``RateHistory`` they're handed. Verbs run through the data layer
and report back via modal screens or notifications.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from collections.abc import Callable
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.reactive import reactive
from textual.widgets import ContentSwitcher

from tailtop.commands import TailtopCommands
from tailtop.data import actions
from tailtop.data.actions import Action
from tailtop.data.client import (
    TailscaleClient,
    TailscaleError,
    TailscaleNotFound,
    TailscaleTimeout,
)
from tailtop.data.models import Peer, Status
from tailtop.data.poller import Poller
from tailtop.modes.cockpit import CockpitMode
from tailtop.modes.comfort import ComfortMode
from tailtop.modes.observatory import ObservatoryMode
from tailtop.screens import ConfirmScreen, InputScreen, ResultScreen
from tailtop.state import RateHistory
from tailtop.widgets.splash import SplashScreen
from tailtop.widgets.status_bar import StatusBar

_THEMES = Path(__file__).parent / "themes"


class TailtopApp(App):
    CSS_PATH = [
        _THEMES / "base.tcss",
        _THEMES / "studio.tcss",
        _THEMES / "mission_control.tcss",
        _THEMES / "brutalist.tcss",
    ]

    COMMANDS = App.COMMANDS | {TailtopCommands}

    BINDINGS = [
        Binding("tab", "cycle_mode", "Mode", priority=True),
        Binding("p", "ping", "Ping"),
        Binding("c", "copy_ip", "Copy IP"),
        Binding("w", "whois", "Whois"),
        Binding("n", "netcheck", "Netcheck"),
        Binding("e", "exit_node", "Exit node"),
        Binding("f", "send_file", "Send"),
        Binding("s", "ssh", "SSH"),
        Binding("r", "refresh", "Refresh"),
        Binding("question_mark", "help", "Help"),
        Binding("q", "quit", "Quit"),
    ]

    MODE_ORDER = ["comfort", "cockpit", "observatory"]

    status: reactive[Status | None] = reactive(None)
    active_mode: reactive[str] = reactive("comfort")
    error: reactive[str] = reactive("")
    selected_peer_id: reactive[str] = reactive("")

    def __init__(
        self,
        client: TailscaleClient | None = None,
        auto_poll: bool = True,
        splash: bool | None = None,
    ) -> None:
        super().__init__()
        self.client = client or TailscaleClient()
        self.rates = RateHistory()
        self.auto_poll = auto_poll
        self.poller = Poller(self.client, self._on_status, self._on_error, interval=2.0)
        self._splash_enabled = auto_poll if splash is None else splash
        self._splash: SplashScreen | None = None

    def compose(self) -> ComposeResult:
        with ContentSwitcher(initial="comfort", id="modes"):
            yield ComfortMode(id="comfort")
            yield CockpitMode(id="cockpit")
            yield ObservatoryMode(id="observatory")
        yield StatusBar(id="statusbar")

    def on_mount(self) -> None:
        self._refresh_status_bar()
        if self._splash_enabled:
            self._splash = SplashScreen()
            self.push_screen(self._splash)
            self.set_timer(3.5, self._dismiss_splash)
        if not self.client.available:
            if self._splash is not None:
                self._splash.set_message("tailscale CLI not found")
            self.notify(
                "tailscale CLI not found on PATH — install it or start tailscaled.",
                title="tailtop",
                severity="error",
                timeout=10,
            )
        if self.auto_poll:
            self.poller.start()

    # ---- data plumbing -----------------------------------------------------

    def _on_status(self, status: Status) -> None:
        now = time.monotonic()
        for p in (status.self_peer, *status.peers):
            self.rates.update(p.id, p.rx_bytes, p.tx_bytes, now)
        self.error = ""
        # Dismiss before triggering watch_status so the mode widgets on the
        # base screen are queryable (the splash hides them otherwise).
        self._dismiss_splash()
        self.status = status  # triggers watch_status

    def _dismiss_splash(self) -> None:
        splash = self._splash
        if splash is None:
            return
        self._splash = None
        splash.safe_dismiss()

    def _on_error(self, exc: Exception) -> None:
        self.error = self._friendly_error(exc)
        self._refresh_status_bar()

    @staticmethod
    def _friendly_error(exc: Exception) -> str:
        if isinstance(exc, TailscaleNotFound):
            return "tailscale CLI not found on PATH"
        if isinstance(exc, TailscaleTimeout):
            return "tailscaled not responding (timeout)"
        if isinstance(exc, TailscaleError):
            return exc.stderr or "tailscale command failed"
        return str(exc)

    def watch_status(self, status: Status | None) -> None:
        if status is not None:
            self._mode_widget().update_data(status, self.rates)
        self._refresh_status_bar()

    def _mode_widget(self):
        return self.query_one(f"#{self.active_mode}")

    def _refresh_status_bar(self) -> None:
        try:
            bar = self.query_one(StatusBar)
        except Exception:
            return
        bar.set_state(self.status, self.active_mode, self.error)

    # ---- selection ---------------------------------------------------------

    def selected_peer(self) -> Peer | None:
        if self.status is None:
            return None
        for p in self.status.peers:
            if p.id == self.selected_peer_id:
                return p
        return self.status.peers[0] if self.status.peers else None

    # ---- mode actions ------------------------------------------------------

    def action_cycle_mode(self) -> None:
        idx = self.MODE_ORDER.index(self.active_mode)
        self.active_mode = self.MODE_ORDER[(idx + 1) % len(self.MODE_ORDER)]
        self.query_one(ContentSwitcher).current = self.active_mode
        mode = self._mode_widget()
        self.poller.set_interval(getattr(mode, "cadence", 2.0))
        if self.status is not None:
            mode.update_data(self.status, self.rates)
        self._refresh_status_bar()

    def action_refresh(self) -> None:
        self.poller.refresh_now()

    def action_help(self) -> None:
        self.notify(
            "Tab modes · j/k navigate · p ping · c copy · w whois · n netcheck · "
            "e exit-node · f send · s ssh · ⌘P palette · q quit",
            title="tailtop",
            timeout=8,
        )

    # ---- verbs -------------------------------------------------------------

    def action_copy_ip(self) -> None:
        peer = self.selected_peer()
        if peer is None:
            self.notify("No device selected", severity="warning")
            return
        self.copy_to_clipboard(peer.ipv4)
        self.notify(f"Copied {peer.ipv4}", title=peer.name)

    @work
    async def action_ping(self) -> None:
        peer = self.selected_peer()
        if peer is None:
            self.notify("No device selected", severity="warning")
            return
        await self._run_read(actions.ping(peer.ipv4), title=f"ping {peer.name}")

    @work
    async def action_whois(self) -> None:
        peer = self.selected_peer()
        if peer is None:
            self.notify("No device selected", severity="warning")
            return
        await self._run_read(actions.whois(peer.ipv4), title=f"whois {peer.name}")

    @work
    async def action_netcheck(self) -> None:
        await self._run_read(actions.netcheck(), title="netcheck")

    @work
    async def action_lock(self) -> None:
        await self._run_read(actions.lock_status(), title="tailnet lock")

    @work
    async def action_serve(self) -> None:
        await self._run_read(actions.serve_status(), title="serve status")

    @work
    async def action_funnel(self) -> None:
        port = await self.push_screen_wait(InputScreen("Funnel which local port?", "8080"))
        if not port:
            return
        try:
            int(port)
        except ValueError:
            self.notify("Port must be a number", severity="warning")
            return
        await self._run_mutation(actions.funnel(int(port)), f"Expose port {port} on the public internet?")

    @work
    async def action_exit_node(self) -> None:
        peer = self.selected_peer()
        if peer is None:
            self.notify("No device selected", severity="warning")
            return
        if peer.exit_node:
            await self._run_mutation(actions.clear_exit_node(), f"Stop using {peer.name} as exit node?")
        elif peer.exit_node_option:
            await self._run_mutation(actions.set_exit_node(peer.ipv4), f"Route all traffic through {peer.name}?")
        else:
            self.notify(f"{peer.name} is not an exit node", severity="warning")

    @work
    async def action_send_file(self) -> None:
        peer = self.selected_peer()
        if peer is None:
            self.notify("No device selected", severity="warning")
            return
        path = await self.push_screen_wait(InputScreen(f"File to send to {peer.name}:", "/path/to/file"))
        if not path:
            return
        await self._run_mutation(
            actions.send_file(path, peer.name), f"Send {path} to {peer.name}?", refresh=False
        )

    @work
    async def action_ssh(self) -> None:
        peer = self.selected_peer()
        if peer is None:
            self.notify("No device selected", severity="warning")
            return
        target = peer.magic_dns or peer.ipv4
        with self.suspend():
            try:
                subprocess.run([self.client._binary, "ssh", target], check=False)  # noqa: S603
            except FileNotFoundError:
                pass
        self.refresh()

    # ---- verb runners ------------------------------------------------------

    async def _run_read(self, action: Action, title: str) -> None:
        try:
            out = await self.client.run(*action.args, timeout=20.0, check=False)
        except Exception as exc:  # noqa: BLE001
            out = self._friendly_error(exc)
        await self.push_screen_wait(ResultScreen(title, out.strip()))

    async def _run_mutation(self, action: Action, question: str, refresh: bool = True) -> None:
        ok = await self.push_screen_wait(ConfirmScreen(question, confirm_label=action.label))
        if not ok:
            return
        try:
            await self.client.run(*action.args, timeout=20.0)
            self.notify(action.label, title="done")
            if refresh:
                self.poller.refresh_now()
        except Exception as exc:  # noqa: BLE001
            self.notify(self._friendly_error(exc), severity="error", title="failed")

    # ---- command palette feed ---------------------------------------------

    def palette_entries(self) -> list[tuple[str, Callable[[], None], str]]:
        entries: list[tuple[str, Callable[[], None], str]] = [
            ("netcheck", self.action_netcheck, "Analyze local network conditions"),
            ("funnel a port", self.action_funnel, "Expose a local port to the internet"),
            ("serve status", self.action_serve, "Show tailnet serve config"),
            ("tailnet lock status", self.action_lock, "Network-lock state"),
            ("refresh", self.action_refresh, "Re-poll tailscaled now"),
        ]
        peer = self.selected_peer()
        if peer is not None:
            n = peer.name
            entries = [
                (f"ping {n}", self.action_ping, "Ping via the tailnet"),
                (f"copy IP · {n}", self.action_copy_ip, peer.ipv4),
                (f"whois {n}", self.action_whois, "Who owns this node"),
                (f"ssh {n}", self.action_ssh, "Open a Tailscale SSH session"),
                (f"send file → {n}", self.action_send_file, "Taildrop a file"),
                (f"exit node · {n}", self.action_exit_node, "Toggle as exit node"),
                *entries,
            ]
        return entries

    async def on_unmount(self) -> None:
        await self.poller.stop()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tailtop", description="htop for your tailnet")
    parser.add_argument(
        "--demo",
        action="store_true",
        default=os.environ.get("TAILTOP_DEMO") in ("1", "true", "yes"),
        help="Run against a synthetic tech-company tailnet (no tailscaled needed).",
    )
    args = parser.parse_args(sys.argv[1:] if argv is None else argv)

    client = None
    if args.demo:
        from tailtop.data.demo import DemoClient

        client = DemoClient()
    TailtopApp(client=client).run()


if __name__ == "__main__":
    main()
