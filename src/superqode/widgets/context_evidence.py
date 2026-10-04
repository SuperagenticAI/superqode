"""Inspect host context decisions and explicitly retrieve bounded originals."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, OptionList, Static, TextArea
from textual.widgets.option_list import Option

from superqode.governance import governance_scope, load_governance
from superqode.harness.context_artifacts import ContextArtifactStore
from .panel_shortcuts import PanelShortcutMixin, PanelShortcuts


class ContextEvidenceScreen(PanelShortcutMixin, ModalScreen):
    BINDINGS = [Binding("escape", "close", "Back", priority=True)]
    CSS = """
    ContextEvidenceScreen { align: center middle; }
    #context-evidence { width: 94%; height: 90%; background: #0a0a0a; border: round #7c3aed; padding: 0 1; }
    #context-evidence-title { height: 3; color: #a855f7; }
    #context-evidence-list { height: 6; max-height: 30%; }
    #context-evidence-detail { height: 1fr; }
    #context-evidence-actions { height: 3; }
    #context-evidence-actions Button { width: 1fr; min-width: 10; }
    """

    def __init__(self, trace, root: Path, *, permission_manager=None):
        super().__init__()
        self.trace, self.root, self.permission_manager = trace, root, permission_manager
        self.decisions = list(trace.get("decisions") or ())
        self.page = None
        self._reading = False
        self._generation = 0

    def compose(self) -> ComposeResult:
        t = self.trace
        heading = f"Context · {t.get('mode')} · {t.get('selector')} · cache {'reused' if t.get('cache_hit') else 'miss'}\n"
        heading += f"Actual characters {t.get('chars_before')} → {t.get('chars_after')} · proposed {t.get('proposed_chars_after')} · selector calls {t.get('scorer_calls', 0)}"
        with Vertical(id="context-evidence"):
            yield Static(Text(heading), id="context-evidence-title")
            yield OptionList(
                *(
                    Option(Text(f"{d['action']} · {d['reason']} · {d['reference']}"))
                    for d in self.decisions
                ),
                id="context-evidence-list",
            )
            yield TextArea(
                "No eligible evidence. Original session history is retained.",
                read_only=True,
                id="context-evidence-detail",
            )
            with Horizontal(id="context-evidence-actions"):
                yield Button("Excerpt", id="context-evidence-excerpt")
                yield Button(
                    "Open original", id="context-evidence-open", disabled=not bool(self.decisions)
                )
                yield Button("Next page", id="context-evidence-next", disabled=True)
                yield Button("Back", id="context-evidence-back")
            yield PanelShortcuts(
                {
                    "context-evidence-list": "↑↓ Select · Enter Inspect · Tab Actions · Esc Back",
                    "context-evidence-detail": "↑↓ Scroll · Tab Actions · Esc Back",
                },
                "Tab Next control · Esc Back",
            )

    def on_mount(self):
        self.query_one("#context-evidence-list", OptionList).highlighted = (
            0 if self.decisions else None
        )
        self.show_excerpt()
        self.query_one("#context-evidence-list", OptionList).focus()

    def selected(self):
        index = self.query_one("#context-evidence-list", OptionList).highlighted
        return self.decisions[index] if index is not None else None

    def show_excerpt(self):
        self._generation += 1
        self.page = None
        d = self.selected()
        if d:
            text = d.get("excerpt") or "Full evidence retained; no excerpt substitution proposed."
            text += "\n\n" + json.dumps({k: v for k, v in d.items() if k != "excerpt"}, indent=2)
            self.query_one("#context-evidence-detail", TextArea).load_text(text)
        self.query_one("#context-evidence-next", Button).disabled = True

    def _read(self, decision, offset):
        # Host-owned scope grants no authority. Recheck current project policy
        # and the originating permission manager on every page.
        with governance_scope(load_governance(self.root)):
            store = ContextArtifactStore(self.trace["artifact_store_path"])
            scope = self.trace["artifact_scope"]
            if self.permission_manager:
                from superqode.harness.context_artifacts import originating_tool
                from superqode.tools.permissions import Permission

                record = store.describe(scope, decision["reference"])
                if (
                    self.permission_manager.check_permission(
                        originating_tool(record.metadata), record.metadata.get("arguments") or {}
                    )
                    != Permission.ALLOW
                ):
                    raise PermissionError("Evidence denied")
            return store.read_page(scope, decision["reference"], offset=offset, limit=4000)

    async def open_original(self, *, next_page=False):
        d = self.selected()
        if not d or self._reading:
            return
        generation = self._generation
        self._reading = True
        try:
            offset = self.page.next_offset if next_page and self.page else 0
            page = await asyncio.to_thread(self._read, d, offset)
            if generation != self._generation or not self.is_mounted:
                return
            self.page = page
            self.query_one("#context-evidence-detail", TextArea).load_text(
                f"Characters {page.offset}–{page.next_offset} of {page.total_chars}\n\n{page.text}"
            )
            self.query_one("#context-evidence-next", Button).disabled = page.eof
        except Exception:
            self.page = None
            self.query_one("#context-evidence-detail", TextArea).load_text(
                "Evidence unavailable or denied under current policy."
            )
            self.query_one("#context-evidence-next", Button).disabled = True
        finally:
            self._reading = False

    @on(OptionList.OptionHighlighted)
    def highlighted(self):
        self.show_excerpt()

    @on(OptionList.OptionSelected)
    def inspect_selected(self):
        self.query_one("#context-evidence-detail", TextArea).focus()

    @on(Button.Pressed)
    async def pressed(self, event):
        event.stop()
        action = event.button.id.removeprefix("context-evidence-")
        if action == "back":
            self.dismiss(None)
        elif action == "excerpt":
            self.show_excerpt()
        else:
            await self.open_original(next_page=action == "next")

    def action_close(self):
        self.dismiss(None)
