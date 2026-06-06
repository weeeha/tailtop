"""Tests for the boot splash screen."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tailtop.app import TailtopApp
from tailtop.data.models import Status
from tailtop.widgets.splash import SplashScreen, render_banner

FIXTURE = Path(__file__).parent / "fixtures" / "status.json"


@pytest.fixture
def status() -> Status:
    return Status.from_json(json.loads(FIXTURE.read_text()))


def test_render_banner_is_non_empty_and_colored() -> None:
    text = render_banner("TAILTOP")
    plain = text.plain
    assert "█" in plain, "banner should render block pixels"
    # Each on-pixel and shadow-pixel gets its own colored span.
    assert len(text.spans) > 20, "expected many colored spans for a rainbow"


def test_render_banner_animates_with_phase() -> None:
    a = render_banner("TAILTOP", phase=0.0)
    b = render_banner("TAILTOP", phase=90.0)
    # Same shape, different colors → identical plain text, different spans.
    assert a.plain == b.plain
    a_styles = [str(s.style) for s in a.spans]
    b_styles = [str(s.style) for s in b.spans]
    assert a_styles != b_styles


def test_render_banner_handles_unknown_chars() -> None:
    # Unknown chars are skipped; empty string returns empty Text.
    assert render_banner("").plain == ""
    assert render_banner("?!").plain == ""
    # Known + unknown → renders only the known glyphs.
    only_known = render_banner("T?T")
    just_tt = render_banner("TT")
    assert only_known.plain == just_tt.plain


async def test_splash_dismisses_on_first_status(status: Status) -> None:
    app = TailtopApp(auto_poll=False, splash=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SplashScreen)
        app._on_status(status)
        await pilot.pause()
        assert not isinstance(app.screen, SplashScreen)


async def test_splash_dismisses_on_keypress() -> None:
    app = TailtopApp(auto_poll=False, splash=True)
    async with app.run_test() as pilot:
        await pilot.pause()
        assert isinstance(app.screen, SplashScreen)
        await pilot.press("space")
        await pilot.pause()
        assert not isinstance(app.screen, SplashScreen)


async def test_no_splash_when_disabled() -> None:
    app = TailtopApp(auto_poll=False)  # default: splash off when not polling
    async with app.run_test() as pilot:
        await pilot.pause()
        assert not isinstance(app.screen, SplashScreen)
