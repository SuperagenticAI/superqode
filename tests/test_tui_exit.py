"""Exit/command routing must win over picker selection on Enter.

Regression: from inside a local-provider picker (LM Studio / MLX / Ollama),
typing ``:exit`` and pressing Enter was swallowed by the picker (it confirmed
the highlighted item) so the user could never leave the TUI.
"""

from superqode.app_main import SelectionAwareInput

# Call the method unbound with lightweight stand-ins; it only reads
# ``self.value`` and attributes off ``app``.
_handle = SelectionAwareInput._handle_selection_enter


class _Stub:
    """Stands in for the input widget; ``value`` is the typed text."""

    def __init__(self, value):
        self.value = value


class _App:
    """Stands in for the app; selection flags + the highlighted-select action."""

    def __init__(self, **flags):
        self.selected = False
        for k, v in flags.items():
            setattr(self, k, v)

    def action_select_highlighted_local_model(self):
        self.selected = True


def test_command_prefixes_bypass_picker_selection():
    # In a local-model picker, a typed command/shell line must NOT select the
    # highlighted item — it must fall through to be submitted as a command.
    app = _App(_awaiting_local_model=True)
    for typed in (":exit", ":quit", ":q", ":home", "/help", "!ls", "  :exit  "):
        assert _handle(_Stub(typed), app) is False, typed
    assert app.selected is False


def test_empty_enter_still_selects_highlighted():
    # Empty Enter inside a picker confirms the highlighted item (unchanged).
    app = _App(_awaiting_local_model=True)
    assert _handle(_Stub(""), app) is True
    assert app.selected is True


def test_plain_text_still_selects_highlighted():
    # A non-command line (e.g. a typed model name) keeps the old behaviour.
    app = _App(_awaiting_local_model=True)
    assert _handle(_Stub("qwen3"), app) is True
    assert app.selected is True


def test_command_bypasses_even_with_no_active_picker():
    # No picker active: a command line is not consumed as a selection.
    assert _handle(_Stub(":exit"), _App()) is False
