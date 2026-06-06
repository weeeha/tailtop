"""Rate-history and sparkline tests."""

from __future__ import annotations

from tailtop.state import RateHistory, human_rate, sparkline


def test_rate_is_bytes_per_second() -> None:
    h = RateHistory()
    h.update("p1", rx_bytes=0, tx_bytes=0, now=0.0)
    h.update("p1", rx_bytes=1000, tx_bytes=500, now=1.0)  # +1000B / +500B over 1s
    assert h.current_rx("p1") == 1000.0
    assert h.current_tx("p1") == 500.0


def test_counter_reset_clamps_to_zero() -> None:
    h = RateHistory()
    h.update("p1", rx_bytes=5000, tx_bytes=0, now=0.0)
    h.update("p1", rx_bytes=10, tx_bytes=0, now=1.0)  # peer reconnected, counter reset
    assert h.current_rx("p1") == 0.0


def test_first_sample_has_no_rate() -> None:
    h = RateHistory()
    h.update("p1", rx_bytes=1234, tx_bytes=0, now=0.0)
    assert h.rx_series("p1") == []  # need two samples to make a rate


def test_sparkline_width_and_empty() -> None:
    assert sparkline([], width=8) == "·" * 8
    out = sparkline([1, 2, 3, 4, 5, 6, 7, 8], width=8)
    assert len(out) == 8
    assert out[-1] == "█"  # the max scales to a full block


def test_human_rate() -> None:
    assert human_rate(512) == "512 B/s"
    assert human_rate(1536) == "1.5 KB/s"
    assert human_rate(5 * 1024 * 1024) == "5.0 MB/s"
