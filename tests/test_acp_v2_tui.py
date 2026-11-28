"""Authoritative ACP message replacements preserve unrelated rendered activity."""

from textual.app import App, ComposeResult

from superqode.app.widgets import ConversationLog


class LogApp(App):
    def compose(self) -> ComposeResult:
        yield ConversationLog(id="log")


async def test_stream_replacement_and_clear_preserve_tool_rows():
    app = LogApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        await pilot.pause()
        log.reset_response_stream("Fixture")
        log.set_response_snapshot("obsolete answer\n\n")
        log.add_meta("Keep this tool result", "↳")
        log.set_response_snapshot("corrected answer\n\n")
        await pilot.pause()
        text = "\n".join(strip.text for strip in log.lines)
        assert "obsolete answer" not in text
        assert "corrected answer" in text
        assert "Keep this tool result" in text
        log.set_response_snapshot("")
        await pilot.pause()
        text = "\n".join(strip.text for strip in log.lines)
        assert "corrected answer" not in text
        assert "Keep this tool result" in text


async def test_child_message_and_terminal_replacements_are_independent():
    app = LogApp()
    async with app.run_test() as pilot:
        log = app.query_one("#log", ConversationLog)
        await pilot.pause()
        log.set_acp_entity_snapshot(("child", "message", "m"), "old child answer")
        log.set_acp_entity_snapshot(("root", "terminal", "t"), "terminal output")
        log.set_acp_entity_snapshot(("child", "message", "m"), "new child answer")
        text = "\n".join(strip.text for strip in log.lines)
        assert "old child answer" not in text
        assert "new child answer" in text and "terminal output" in text
        log.set_acp_entity_snapshot(("child", "message", "m"), "")
        text = "\n".join(strip.text for strip in log.lines)
        assert "child answer" not in text and "terminal output" in text
