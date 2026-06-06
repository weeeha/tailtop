"""Action command-building tests — assert argv without ever running mutations."""

from __future__ import annotations

from tailtop.data import actions


def test_ping_is_read_only() -> None:
    a = actions.ping("100.114.149.53")
    assert a.args == ["ping", "100.114.149.53"]
    assert a.mutating is False


def test_set_exit_node_argv() -> None:
    a = actions.set_exit_node("100.78.29.28")
    assert a.args == ["set", "--exit-node=100.78.29.28"]
    assert a.mutating is True


def test_clear_exit_node_argv() -> None:
    assert actions.clear_exit_node().args == ["set", "--exit-node="]


def test_send_file_targets_peer_with_trailing_colon() -> None:
    a = actions.send_file("/tmp/x.zip", "artstation")
    assert a.args == ["file", "cp", "/tmp/x.zip", "artstation:"]
    assert a.mutating is True


def test_ssh_hands_over_terminal() -> None:
    a = actions.ssh("nick@mac-studio")
    assert a.args == ["ssh", "nick@mac-studio"]
    assert a.hands_over_terminal is True
    assert a.mutating is False


def test_funnel_argv() -> None:
    assert actions.funnel(8080).args == ["funnel", "8080"]
