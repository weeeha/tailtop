"""Base class for mode views.

A mode is a full-screen view (Comfort / Cockpit / Observatory). The app owns
the data and pushes it down via ``update_data`` whenever a fresh poll lands or
the user switches into the mode.
"""

from __future__ import annotations

from textual.containers import Container

from tailtop.data.models import Status
from tailtop.state import RateHistory


class ModeView(Container):
    """Common interface every mode implements."""

    #: cadence (seconds) the poller should use while this mode is active
    cadence: float = 2.0

    def update_data(self, status: Status, rates: RateHistory) -> None:  # noqa: B027
        """Receive a fresh snapshot. Override in subclasses."""
