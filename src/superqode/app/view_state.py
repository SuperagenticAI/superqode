"""Ownership of inline picker input and delayed renders."""

from __future__ import annotations


PICKER_FLAGS = (
    "_awaiting_connect_type",
    "_awaiting_acp_agent_selection",
    "_awaiting_byok_provider",
    "_awaiting_byok_model",
    "_awaiting_local_provider",
    "_awaiting_local_model",
    "_awaiting_codex_model",
    "_awaiting_codex_effort",
    "_awaiting_session_resume",
    "_awaiting_mode_selection",
    "_awaiting_harness_selection",
    "_awaiting_runtime_selection",
    "_awaiting_recommendation_selection",
    "_awaiting_free_selection",
    "_awaiting_harness_wizard",
    "_awaiting_model_selection",
)

INLINE_SELECTION_FLAGS = PICKER_FLAGS + (
    "_awaiting_harness_confirmation",
    "_awaiting_harness_preset",
    "_awaiting_harness_import",
    "_awaiting_explore",
)


def clear_picker_input(app) -> None:
    """Discard an old number without removing an unrelated prompt draft."""
    buffer = getattr(app, "_selection_digit_buffer", "")
    timer = getattr(app, "_selection_digit_timer", None)
    if timer is not None:
        timer.stop()
    app._selection_digit_buffer = ""
    app._selection_digit_timer = None
    if buffer:
        try:
            prompt = app.query_one("#prompt-input")
            if prompt.value == buffer:
                prompt.value = ""
        except Exception:
            pass


def begin_inline_view(app, *, selection_flags=(), clear_input: bool = True) -> int:
    """Replace the current view; only its declared picker may consume input.

    Connection identities, harness configuration and approval decisions are
    retained. Generations distinguish an old load from a later visit to the
    same page, including navigation Back to that page.
    """
    show_chat = getattr(app, "_show_workspace_chat", None)
    if callable(show_chat):
        show_chat()
    generation = getattr(app, "_inline_view_generation", 0) + 1
    app._inline_view_generation = generation
    if clear_input:
        clear_picker_input(app)
    for flag in INLINE_SELECTION_FLAGS:
        if flag not in selection_flags:
            setattr(app, flag, False)
    picker = getattr(app, "_model_picker_widget", None)
    if picker is not None and "_awaiting_byok_model" not in selection_flags:
        app._model_picker_widget = None
        app._picker_provider_id = None
        app._picker_log = None
        picker.remove()
    prompts = getattr(app, "_prompts", None)
    if not selection_flags and prompts is not None:
        prompts.clear()
    return generation


def inline_view_current(app, generation: int) -> bool:
    return getattr(app, "_inline_view_generation", 0) == generation
