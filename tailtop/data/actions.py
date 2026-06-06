"""Verb → command construction.

Pure functions that build the ``tailscale`` argument list for each action.
Keeping command-building separate from execution makes mutations trivially
testable (assert the args; never actually run a destructive command in tests)
and gives the UI one obvious place to look up "what does this verb run?".
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Action:
    """A runnable tailscale action with metadata for the UI."""

    key: str  # short id, e.g. "ssh"
    label: str  # palette/menu label
    args: list[str]  # argv passed to `tailscale`
    mutating: bool  # True ⇒ confirm before running
    hands_over_terminal: bool = False  # True ⇒ suspend the TUI (e.g. ssh)


def ping(host: str) -> Action:
    return Action("ping", f"Ping {host}", ["ping", host], mutating=False)


def netcheck() -> Action:
    return Action("netcheck", "Run netcheck", ["netcheck"], mutating=False)


def whois(ip: str) -> Action:
    return Action("whois", f"Whois {ip}", ["whois", ip], mutating=False)


def set_exit_node(ip: str) -> Action:
    return Action(
        "exit-node",
        f"Use {ip} as exit node",
        ["set", f"--exit-node={ip}"],
        mutating=True,
    )


def clear_exit_node() -> Action:
    return Action(
        "exit-node-clear",
        "Stop using exit node",
        ["set", "--exit-node="],
        mutating=True,
    )


def send_file(path: str, peer: str) -> Action:
    # `tailscale file cp <path> <peer>:`  — trailing colon targets the peer.
    return Action(
        "send",
        f"Send {path} → {peer}",
        ["file", "cp", path, f"{peer}:"],
        mutating=True,
    )


def ssh(user_host: str) -> Action:
    return Action(
        "ssh",
        f"SSH to {user_host}",
        ["ssh", user_host],
        mutating=False,
        hands_over_terminal=True,
    )


def funnel(port: int) -> Action:
    return Action("funnel", f"Funnel port {port}", ["funnel", str(port)], mutating=True)


def serve(args: list[str]) -> Action:
    return Action("serve", "Serve", ["serve", *args], mutating=True)


def serve_status() -> Action:
    return Action("serve", "Serve status", ["serve", "status"], mutating=False)


def lock_status() -> Action:
    return Action("lock", "Tailnet lock status", ["lock", "status"], mutating=False)
