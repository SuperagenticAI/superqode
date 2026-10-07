"""Compact composer payloads; full text is expanded only on explicit send."""

from __future__ import annotations

import re
import uuid

from superqode.app.inputs import SelectionAwareInput
from superqode.app.widgets import ConversationLog

BLOCK_TOKEN = re.compile(r"\[Block ([0-9a-f]{12})\]")
MAX_BLOCK_CHARS = 2 * 1024 * 1024
MAX_TOTAL_CHARS = 4 * 1024 * 1024
PREVIEW_CHARS = 32 * 1024


class ComposerBlocksMixin:
    def _stage_composer_block(self, text, label="Paste"):
        prompt = self.query_one("#prompt-input", SelectionAwareInput)
        if prompt.value.lstrip()[:1] in {":", "/", ">", "!"}:
            self.query_one("#log", ConversationLog).add_error(
                "Stage text in a message draft, not a command line."
            )
            return False
        blocks = getattr(self, "_composer_blocks", {})
        # Retain payloads referenced by the current draft. Deleted markers can
        # still be undone until another block is staged.
        blocks = {key: block for key, block in blocks.items() if f"[Block {key}]" in prompt.value}
        if (
            len(blocks) >= 100
            or len(text) > MAX_BLOCK_CHARS
            or sum(len(b["text"]) for b in blocks.values()) + len(text) > MAX_TOTAL_CHARS
        ):
            self.query_one("#log", ConversationLog).add_error(
                "Block limit reached (100 blocks, 2,097,152 characters per block, 4,194,304 total). Nothing staged."
            )
            return False
        key = uuid.uuid4().hex[:12]
        blocks[key] = {"text": text, "label": label, "lines": text.count("\n") + 1}
        self._composer_blocks = blocks
        edit = prompt.replace(f"[Block {key}]", *prompt.selection)
        prompt.move_cursor(edit.end_location)
        self._refresh_attachment_bar()
        return True

    def _fold_composer_paste(self, text):
        prompt = self.query_one("#prompt-input", SelectionAwareInput)
        if len(text) < 2000 and text.count("\n") < 19:
            return False
        if (prompt.value.lstrip() or text.lstrip())[:1] in {":", "/", ">", "!"}:
            return False
        if getattr(self, "_permission_pending", False) or getattr(
            self, "_awaiting_agent_question", False
        ):
            return False
        if not self._stage_composer_block(text):
            # Do not turn an over-limit paste into an enormous visible document.
            return True
        return True

    def _expand_composer_blocks(self, text):
        blocks = getattr(self, "_composer_blocks", {})

        def expand(match):
            key = match.group(1)
            if key not in blocks:
                raise ValueError(
                    "A pasted block is unavailable. Remove its marker or paste it again."
                )
            return blocks[key]["text"]

        matches = list(BLOCK_TOKEN.finditer(text))
        expanded_size = len(text) + sum(
            len(expand(match)) - len(match.group()) for match in matches
        )
        if matches and expanded_size > MAX_TOTAL_CHARS:
            raise ValueError(
                "Expanded message exceeds 4,194,304 characters. Remove a block or repeated marker."
            )
        return BLOCK_TOKEN.sub(expand, text)

    def _composer_block_chips(self, line):
        from rich.style import Style
        from superqode.app.constants import THEME

        prompt = self.query_one("#prompt-input", SelectionAwareInput)
        count = 0
        for key, block in getattr(self, "_composer_blocks", {}).items():
            if f"[Block {key}]" not in prompt.value:
                continue
            label = f"◇ {block['label']} · {block['lines']} lines · {len(block['text']):,} chars"
            start = len(line)
            line.append(label, style=THEME["purple"])
            line.stylize(Style(meta={"@click": f"app.preview_composer_block('{key}')"}), start)
            start = len(line)
            line.append(" ×", style=THEME["muted"])
            line.stylize(Style(meta={"@click": f"app.remove_composer_block('{key}')"}), start)
            line.append("  ")
            count += 1
        return count

    def action_remove_composer_block(self, key):
        prompt = self.query_one("#prompt-input", SelectionAwareInput)
        token = f"[Block {key}]"
        cursor = prompt.cursor_position
        before = sum(
            min(cursor - match.start(), len(token))
            for match in re.finditer(re.escape(token), prompt.value)
            if match.start() < cursor
        )
        prompt.value = prompt.value.replace(token, "")
        prompt.cursor_position = max(0, cursor - before)
        getattr(self, "_composer_blocks", {}).pop(key, None)
        self._refresh_attachment_bar()

    def action_preview_composer_block(self, key=""):
        from superqode.widgets.composer_block_preview import ComposerBlockPreview

        blocks = getattr(self, "_composer_blocks", {})
        if not key:
            prompt = self.query_one("#prompt-input", SelectionAwareInput)
            key = next((k for k in blocks if f"[Block {k}]" in prompt.value), "")
        block = blocks.get(key)
        if block is None:
            self.query_one("#log", ConversationLog).add_info(
                "No folded block. Paste 20 lines or 2,000 characters to fold it."
            )
            return
        self.push_screen(
            ComposerBlockPreview(
                block["text"], block["label"], remove=lambda: self.action_remove_composer_block(key)
            ),
            lambda _: self._ensure_input_focus(),
        )

    def _remember_shell_output(self, command, output, returncode):
        # One bounded handle; never copy the full terminal history on each tick.
        self._shell_output = {
            "command": command,
            "text": output[:MAX_BLOCK_CHARS],
            "total": len(output),
            "returncode": returncode,
        }
        from rich.text import Text
        from rich.style import Style
        from superqode.app.constants import THEME

        link = Text(
            "◇ Shell output · Preview and stage for next message (:output)", style=THEME["purple"]
        )
        link.stylize(Style(meta={"@click": "app.preview_shell_output()"}))
        self.query_one("#log", ConversationLog).write(link)

    def action_preview_shell_output(self):
        from superqode.widgets.composer_block_preview import ComposerBlockPreview

        output = getattr(self, "_shell_output", None)
        if output is None:
            self.query_one("#log", ConversationLog).add_info(
                "No local shell output yet. Run a command with > or !."
            )
            return

        def stage(text):
            return self._stage_composer_block(
                f"Local shell output\nCommand: {output['command']}\nExit code: {output['returncode']}\n\n{text}",
                "Shell output",
            )

        self.push_screen(
            ComposerBlockPreview(
                output["text"],
                f"Shell · exit {output['returncode']} · {output['command']}",
                stage=stage,
                total=output["total"],
            ),
            lambda _: self._ensure_input_focus(),
        )
