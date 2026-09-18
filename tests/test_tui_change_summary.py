"""File-change summary is hidden by default and never fabricated.

Regression tests for the rule that a turn only reports files it actually
changed, shown as a single collapsed line unless the user opts into verbose.
"""

from __future__ import annotations

from rich.text import Text

from superqode.app_main import SuperQodeApp


class _StubLog:
    def __init__(self, mode="normal"):
        self.buf: list[str] = []
        self.tool_output_mode = mode
        self.auto_scroll = True
        self._last_response = ""

    def write(self, x):
        self.buf.append(x.plain if isinstance(x, Text) else str(x))

    def write_final_response(self, *a, **k):
        self.buf.append("[response]")

    def clear(self):
        pass

    def scroll_end(self, *a, **k):
        pass

    def scroll_home(self, *a, **k):
        pass

    @property
    def text(self) -> str:
        return "\n".join(self.buf)


def _app():
    app = SuperQodeApp.__new__(SuperQodeApp)
    app.set_timer = lambda *a, **k: None
    app._navigate_to_sidebar_changes = lambda files: None
    app._last_response = ""
    return app


def _summary(**over):
    base = {
        "duration": 0.3,
        "tool_count": 0,
        "files_modified": [],
        "files_read": [],
        "file_diffs": {},
    }
    base.update(over)
    return base


def test_simple_question_shows_no_change_block():
    log = _StubLog()
    SuperQodeApp._show_final_outcome(_app(), "The answer is 42.", "qwen", _summary(), log)
    assert "changed" not in log.text
    assert "▸" not in log.text
    assert "File Changes" not in log.text


def test_edits_show_single_collapsed_line_in_normal_mode():
    log = _StubLog(mode="normal")
    summary = _summary(
        tool_count=2,
        files_modified=["a.py", "b.py"],
        file_diffs={
            "a.py": {"additions": 5, "deletions": 1},
            "b.py": {"additions": 3, "deletions": 0},
        },
    )
    SuperQodeApp._show_final_outcome(_app(), "Done.", "qwen", summary, log)
    collapsed = [line for line in log.buf if "▸" in line]
    assert len(collapsed) == 1
    assert "2 files changed (+8/-1)" in collapsed[0]
    assert ":diff" in collapsed[0]
    # Full panel must not appear in normal mode.
    assert "File Changes" not in log.text


def test_verbose_mode_expands_full_panel():
    log = _StubLog(mode="verbose")
    summary = _summary(
        tool_count=1,
        files_modified=["a.py"],
        file_diffs={"a.py": {"additions": 5, "deletions": 1, "diff_text": "@@ -1 +1 @@\n-x\n+y"}},
    )
    SuperQodeApp._show_final_outcome(_app(), "Done.", "qwen", summary, log)
    assert "File Changes" in log.text


def test_no_git_fallback_for_ambient_working_tree(monkeypatch):
    # Even if the repo has unrelated uncommitted changes, a no-edit turn must
    # not surface them. We assert the code path never calls git for a fallback.
    import superqode.app_main as m

    def _boom(*a, **k):  # pragma: no cover - should never be called
        raise AssertionError("git fallback should not run")

    monkeypatch.setattr(m, "get_git_changes", _boom, raising=False)
    log = _StubLog()
    SuperQodeApp._show_final_outcome(_app(), "Just answering.", "qwen", _summary(), log)
    assert "changed" not in log.text


def test_jev_card_stays_at_top_after_final_outcome_and_delayed_scroll():
    import asyncio
    import json
    from textual.app import App, ComposeResult
    from superqode.app.widgets import ConversationLog

    class Preview(App):
        def compose(self) -> ComposeResult:
            yield ConversationLog(id="log")

        def _record_milestone(self, *args):
            pass

        def _run_used_shell(self, summary):
            return False

        def _run_hit_an_error(self, summary):
            return False

        def _maybe_reveal_next_capability(self, log):
            pass

    async def check():
        async with Preview().run_test(size=(80, 20)) as pilot:
            log = pilot.app.query_one("#log", ConversationLog)
            log.start_agent_session("Jev", "jev-1.13.0")
            response = json.dumps(
                {
                    "status": "decided",
                    "outputs": {"route": "review"},
                    "answers": {f"check_{i}": {"noul": 0.9} for i in range(25)},
                    "abstained": [],
                    "metadata": {"pack": "test@1.0.0"},
                }
            )
            log.end_agent_session(response_text=response)
            SuperQodeApp._show_final_outcome(pilot.app, response, "Jev", _summary(), log)
            await pilot.pause(0.2)
            visible = "\n".join(
                line.text for line in log.lines[int(log.scroll_y) : int(log.scroll_y) + 20]
            )
            assert "Jev · System One decision" in visible
            assert log.scroll_y < log.max_scroll_y
            assert not log.auto_scroll
            log.add_user("Next task")
            assert log.auto_scroll

    asyncio.run(check())
