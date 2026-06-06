"""Modal screens: confirm a mutation, show command output, prompt for input."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Button, Input, Label, Static


class ConfirmScreen(ModalScreen[bool]):
    """Yes/No gate before a mutating action."""

    DEFAULT_CSS = """
    ConfirmScreen { align: center middle; }
    ConfirmScreen > #dialog {
        width: 60; height: auto; padding: 1 2;
        background: #15151c; border: round #f0c674;
    }
    ConfirmScreen #question { width: 100%; padding: 1 0 2 0; }
    ConfirmScreen #buttons { height: auto; align-horizontal: right; }
    ConfirmScreen Button { margin-left: 2; }
    """

    BINDINGS = [
        Binding("y", "yes", "Yes"),
        Binding("n", "no", "No"),
        Binding("escape", "no", "Cancel"),
    ]

    def __init__(self, question: str, confirm_label: str = "Confirm") -> None:
        super().__init__()
        self._question = question
        self._confirm_label = confirm_label

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._question, id="question")
            with Horizontal(id="buttons"):
                yield Button(self._confirm_label, variant="warning", id="yes")
                yield Button("Cancel", id="no")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "yes")

    def action_yes(self) -> None:
        self.dismiss(True)

    def action_no(self) -> None:
        self.dismiss(False)


class ResultScreen(ModalScreen[None]):
    """Scrollable read-only output from a command (ping, netcheck, whois …)."""

    DEFAULT_CSS = """
    ResultScreen { align: center middle; }
    ResultScreen > #dialog {
        width: 84; height: 80%; padding: 1 2;
        background: #15151c; border: round #8bb6ff;
    }
    ResultScreen #title { text-style: bold; color: #8bb6ff; padding-bottom: 1; }
    ResultScreen #body { height: 1fr; }
    ResultScreen #hint { color: #6b6f78; padding-top: 1; }
    """

    BINDINGS = [
        Binding("escape", "close", "Close"),
        Binding("enter", "close", "Close"),
        Binding("q", "close", "Close"),
    ]

    def __init__(self, title: str, body: str) -> None:
        super().__init__()
        self._title = title
        self._body = body

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Label(self._title, id="title")
            with VerticalScroll(id="body"):
                yield Static(self._body or "(no output)")
            yield Label("esc / enter to close", id="hint")

    def action_close(self) -> None:
        self.dismiss(None)


class InputScreen(ModalScreen[str | None]):
    """Prompt for a single line of text (e.g. a file path or port)."""

    DEFAULT_CSS = """
    InputScreen { align: center middle; }
    InputScreen > #dialog {
        width: 70; height: auto; padding: 1 2;
        background: #15151c; border: round #7be39b;
    }
    InputScreen #prompt { padding-bottom: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, prompt: str, placeholder: str = "") -> None:
        super().__init__()
        self._prompt = prompt
        self._placeholder = placeholder

    def compose(self) -> ComposeResult:
        with Vertical(id="dialog"):
            yield Static(self._prompt, id="prompt")
            yield Input(placeholder=self._placeholder, id="value")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value or None)

    def action_cancel(self) -> None:
        self.dismiss(None)
