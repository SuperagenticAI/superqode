"""Searchable, paginated session browser for resume and rename.

A dedicated Textual screen (same pattern as Harness Hub / FileEditor) replaces
the capped transcript resume picker. Listing stays read-only via
``ensure_sessions_listed``; resume still registers only the chosen session.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from rich.text import Text
from textual import on
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen
from textual.widgets import Button, Footer, Input, OptionList, Static
from textual.widgets.option_list import Option

from superqode.agent.session_manager import SessionMetadata
from superqode.session.harness_bridge import (
    SessionResumeDescriptor,
    describe_session_resume,
    filter_sessions,
    harness_display_name,
    model_short_name,
    paginate_sessions,
    relative_age,
    rename_session_title,
    session_last_user_preview,
    session_list_preview,
)


PAGE_SIZE = 40


@dataclass(frozen=True)
class SessionBrowserResult:
    """An action chosen from the session browser."""

    action: str  # resume | continue_last | cancel
    session_id: str = ""


@dataclass(frozen=True)
class SessionBrowserLoadResult:
    """Sessions and durable ids discovered away from the Textual event loop."""

    sessions: list[SessionMetadata]
    registered_ids: set[str]


class SessionBrowserScreen(ModalScreen[SessionBrowserResult | None]):
    """Searchable session history with pagination and availability detail."""

    BINDINGS = [
        Binding("escape", "close", "Close", priority=True),
        Binding("q", "close", "Close", show=False),
        Binding("/", "search", "Search"),
        Binding("enter", "resume", "Resume", priority=True),
        Binding("c", "continue_last", "Continue last", show=False),
        Binding("r", "rename", "Rename"),
        Binding("n", "next_page", "Next page", show=False),
        Binding("p", "prev_page", "Prev page", show=False),
        Binding("left", "prev_page", "Prev page", show=False),
        Binding("right", "next_page", "Next page", show=False),
    ]

    CSS = """
    SessionBrowserScreen {
        align: center middle;
        background: #000000 70%;
    }
    SessionBrowserScreen > Vertical {
        width: 96%;
        height: 94%;
        border: round #a855f7;
        background: #000000;
    }
    SessionBrowserScreen Footer {
        background: #000000;
        dock: bottom;
        height: 1;
    }
    SessionBrowserScreen #sb-header {
        height: 5;
        min-height: 5;
        max-height: 5;
        padding: 1 2 0 2;
        background: #000000;
    }
    SessionBrowserScreen #sb-heading {
        width: 1fr;
        height: 3;
    }
    SessionBrowserScreen #sb-title {
        width: 1fr;
        height: 1;
        color: #c4b5fd;
        text-style: bold;
    }
    SessionBrowserScreen #sb-subtitle {
        width: 1fr;
        height: 1;
        color: #d4d4d4;
    }
    SessionBrowserScreen #sb-search {
        width: 1fr;
        max-width: 42;
        height: 3;
        background: #000000;
        color: #f0f0f0;
        border: tall #2a2a2a;
    }
    SessionBrowserScreen #sb-search:focus {
        border: tall #7c3aed;
    }
    SessionBrowserScreen #sb-toolbar {
        height: auto;
        padding: 0 1;
        background: #000000;
    }
    SessionBrowserScreen #sb-toolbar Button {
        min-width: 12;
        height: 3;
        margin-right: 1;
        background: #1a1a1a;
        color: #d8d8d8;
        border: tall #3a3a3a;
    }
    SessionBrowserScreen #sb-toolbar Button.-primary {
        background: #3b1d7a;
        color: #f3e8ff;
        border: tall #c4b5fd;
    }
    SessionBrowserScreen #sb-page-label {
        width: 1fr;
        color: #a1a1aa;
        padding: 1 1 0 1;
    }
    SessionBrowserScreen #sb-body {
        height: 1fr;
        min-height: 8;
        padding: 1 1 1 1;
    }
    SessionBrowserScreen #sb-list {
        width: 58%;
        height: 100%;
        background: #000000;
        border: round #27272a;
        scrollbar-background: #000000;
        scrollbar-color: #2a2a2a;
        overflow-x: hidden;
        margin-right: 1;
    }
    SessionBrowserScreen #sb-list > .option-list--option {
        padding: 0 1;
    }
    SessionBrowserScreen #sb-list > .option-list--option-highlighted {
        background: #1a1030;
    }
    SessionBrowserScreen #sb-list:focus > .option-list--option-highlighted {
        background: #241542;
    }
    SessionBrowserScreen #sb-detail {
        width: 1fr;
        height: 100%;
        padding: 1 2;
        background: #000000;
        overflow-y: auto;
        overflow-x: hidden;
        border: round #27272a;
    }
    SessionBrowserScreen #sb-actions {
        height: auto;
        padding: 0 1 1 1;
        background: #000000;
        align: right middle;
    }
    SessionBrowserScreen #sb-actions Button {
        min-width: 14;
        height: 3;
        margin-left: 1;
        background: #000000;
        color: #e6e6e6;
        border: tall #2a2a2a;
    }
    SessionBrowserScreen #sb-actions Button.-primary {
        background: #3b1d7a;
        color: #f3e8ff;
        border: tall #c4b5fd;
    }
    SessionBrowserScreen #sb-rename {
        display: none;
        height: 3;
        margin: 0 1;
        background: #000000;
        border: tall #7c3aed;
    }
    SessionBrowserScreen.renaming #sb-rename {
        display: block;
    }
    SessionBrowserScreen.narrow #sb-body {
        layout: vertical;
    }
    SessionBrowserScreen.narrow #sb-list {
        width: 100%;
        height: 1fr;
    }
    SessionBrowserScreen.narrow #sb-detail {
        width: 100%;
        height: 10;
    }
    """

    def __init__(
        self,
        sessions: Iterable[SessionMetadata] | None = None,
        *,
        cwd: str | Path | None = None,
        current_id: str = "",
        last_session_id: str = "",
        query: str = "",
        page_size: int = PAGE_SIZE,
        registered_ids: set[str] | None = None,
        storage_dir: str | Path = ".superqode/sessions",
        loader: Callable[[], SessionBrowserLoadResult] | None = None,
    ) -> None:
        super().__init__()
        self.cwd = Path(cwd or Path.cwd()).expanduser().resolve()
        self.storage_dir = storage_dir
        self.all_sessions = list(sessions or [])
        self.current_id = (current_id or "").strip()
        self.last_session_id = (last_session_id or "").strip()
        self.search_query = (query or "").strip()
        self.page_size = max(1, int(page_size))
        self.page = 0
        self.registered_ids = registered_ids
        self.loader = loader
        self._loading = loader is not None
        self.filtered: list[SessionMetadata] = list(self.all_sessions)
        self.page_rows: list[SessionMetadata] = []
        self.total_pages = 1
        self._renaming = False
        self._descriptor_cache: dict[str, SessionResumeDescriptor] = {}
        self._probe_generation = 0

    def compose(self) -> ComposeResult:
        with Vertical():
            with Horizontal(id="sb-header"):
                with Vertical(id="sb-heading"):
                    yield Static(
                        Text.assemble(
                            ("Session", "bold #e9d5ff"),
                            (" Browser", "bold #a78bfa"),
                        ),
                        id="sb-title",
                    )
                    yield Static(
                        "Search, page, and resume without dumping history into the transcript.",
                        id="sb-subtitle",
                    )
                yield Input(
                    value=self.search_query,
                    placeholder="Search title, harness, model, id...",
                    id="sb-search",
                )
            with Horizontal(id="sb-toolbar"):
                yield Button("Continue last", id="sb-continue", variant="primary")
                yield Button("Prev", id="sb-prev")
                yield Button("Next", id="sb-next")
                yield Static("", id="sb-page-label")
            yield Input(placeholder="New title for selected session", id="sb-rename")
            with Horizontal(id="sb-body"):
                yield OptionList(id="sb-list")
                yield Static("Select a session.", id="sb-detail")
            with Horizontal(id="sb-actions"):
                yield Button("Resume · Enter", id="sb-resume", variant="primary")
                yield Button("Rename · R", id="sb-rename-btn")
                yield Button("Close · Esc", id="sb-close")
            yield Footer()

    def on_mount(self) -> None:
        if self.size.width < 90:
            self.add_class("narrow")
        if self._loading:
            self._show_loading()
            self.run_worker(self._load_sessions(), exclusive=False)
        else:
            self._normalise_last_session()
            self._apply_filter(keep_position=False)
        try:
            self.query_one("#sb-list", OptionList).focus()
        except Exception:
            pass

    def on_resize(self, _event) -> None:
        if self.size.width < 90:
            self.add_class("narrow")
        else:
            self.remove_class("narrow")

    def _show_loading(self) -> None:
        option_list = self.query_one("#sb-list", OptionList)
        option_list.clear_options()
        option_list.add_option(Option("Discovering sessions…", id="sb-loading", disabled=True))
        self.query_one("#sb-detail", Static).update(
            Text("Reading project sessions without blocking the TUI…", style="#a78bfa")
        )
        self.query_one("#sb-page-label", Static).update("Loading…")
        for selector in ("#sb-resume", "#sb-continue", "#sb-prev", "#sb-next"):
            self.query_one(selector, Button).disabled = True

    async def _load_sessions(self) -> None:
        try:
            result = await asyncio.to_thread(self.loader) if self.loader is not None else None
        except Exception as exc:
            self._loading = False
            self.query_one("#sb-page-label", Static).update("Could not load sessions")
            self.query_one("#sb-detail", Static).update(
                Text(f"Session discovery failed: {exc}", style="#f97316")
            )
            return
        if result is None:
            return
        self.all_sessions = list(result.sessions)
        self.registered_ids = set(result.registered_ids)
        self._loading = False
        self._normalise_last_session()
        self._apply_filter(keep_position=False)

    def _normalise_last_session(self) -> None:
        ids = {item.session_id for item in self.all_sessions}
        if self.last_session_id not in ids:
            self.last_session_id = self.all_sessions[0].session_id if self.all_sessions else ""

    def _descriptor(self, metadata: SessionMetadata) -> SessionResumeDescriptor | None:
        return self._descriptor_cache.get(metadata.session_id)

    def _schedule_page_descriptors(self) -> None:
        candidates = list(self.page_rows)
        last = next(
            (row for row in self.all_sessions if row.session_id == self.last_session_id),
            None,
        )
        if last is not None and all(row.session_id != last.session_id for row in candidates):
            candidates.append(last)
        missing = [row for row in candidates if row.session_id not in self._descriptor_cache]
        if not missing:
            return
        self._probe_generation += 1
        generation = self._probe_generation
        self.run_worker(self._load_page_descriptors(missing, generation), exclusive=False)

    async def _load_page_descriptors(
        self,
        rows: list[SessionMetadata],
        generation: int,
    ) -> None:
        def probe_rows() -> list[SessionResumeDescriptor]:
            return [
                describe_session_resume(
                    row,
                    cwd=self.cwd,
                    storage_dir=self.storage_dir,
                    registered_ids=self.registered_ids,
                )
                for row in rows
            ]

        descriptors = await asyncio.to_thread(probe_rows)
        if generation != self._probe_generation:
            return
        self._descriptor_cache.update(
            {descriptor.metadata.session_id: descriptor for descriptor in descriptors}
        )
        selected = self._selected_id()
        self._rebuild_list(prefer_id=selected)
        self._update_continue_button()

    def _update_continue_button(self) -> None:
        descriptor = self._descriptor_cache.get(self.last_session_id)
        self.query_one("#sb-continue", Button).disabled = (
            not self.last_session_id or descriptor is None or not descriptor.resumable
        )

    def _apply_filter(self, *, keep_position: bool = True) -> None:
        if self._loading:
            return
        previous_id = self._selected_id() if keep_position else ""
        self.filtered = filter_sessions(self.all_sessions, self.search_query)
        self.page_rows, self.page, self.total_pages = paginate_sessions(
            self.filtered,
            page=self.page,
            page_size=self.page_size,
        )
        self._rebuild_list(prefer_id=previous_id or self.current_id or self.last_session_id)
        self._update_page_label()
        self._update_continue_button()

    def _update_page_label(self) -> None:
        total = len(self.filtered)
        if total == 0:
            label = "No sessions match"
        else:
            start = self.page * self.page_size + 1
            end = min(total, start + len(self.page_rows) - 1)
            label = f"{start}-{end} of {total}  ·  page {self.page + 1}/{self.total_pages}"
        self.query_one("#sb-page-label", Static).update(label)
        self.query_one("#sb-prev", Button).disabled = self.page <= 0
        self.query_one("#sb-next", Button).disabled = self.page >= self.total_pages - 1

    def _option_label(self, metadata: SessionMetadata) -> Text:
        descriptor = self._descriptor(metadata)
        status = descriptor.availability.status if descriptor is not None else "checking"
        mark_color = {
            "ok": "#22c55e",
            "missing_harness": "#f59e0b",
            "bad_credentials": "#f97316",
            "external_only": "#a78bfa",
            "missing_transcript": "#f97316",
            "checking": "#71717a",
        }.get(status, "#a1a1aa")
        title = session_list_preview(metadata, max_len=42)
        harness = harness_display_name(
            metadata.harness_id,
            explicit=metadata.harness_display_name,
        )
        model = model_short_name(metadata.model) if metadata.model else (metadata.provider or "?")
        age = relative_age(metadata.updated_at)
        text = Text()
        text.append("● ", style=mark_color)
        text.append(title, style="bold #f4f4f5")
        if metadata.session_id == self.current_id:
            text.append("  ACTIVE", style="bold #c4b5fd")
        elif metadata.session_id == self.last_session_id:
            text.append("  LAST", style="bold #a78bfa")
        text.append("\n    ", style="")
        text.append(f"{harness}", style="#c4b5fd")
        text.append(f" · {model} · {age} · ", style="#71717a")
        state_label = descriptor.continuity_label if descriptor is not None else "checking…"
        text.append(state_label, style=mark_color)
        text.append(f" · {metadata.session_id[:8]}", style="#52525b")
        return text

    def _rebuild_list(self, *, prefer_id: str = "") -> None:
        option_list = self.query_one("#sb-list", OptionList)
        option_list.clear_options()
        if not self.page_rows:
            option_list.add_option(
                Option("No sessions match this search", id="sb-empty", disabled=True)
            )
            self.query_one("#sb-detail", Static).update(
                Text(
                    "Try another search, clear the filter, or start a new conversation.",
                    style="#a1a1aa",
                )
            )
            self.query_one("#sb-resume", Button).disabled = True
            return

        for item in self.page_rows:
            option_list.add_option(Option(self._option_label(item), id=item.session_id))

        index = 0
        if prefer_id:
            index = next(
                (i for i, item in enumerate(self.page_rows) if item.session_id == prefer_id),
                0,
            )
        option_list.highlighted = index
        if index == 0:
            option_list.scroll_to(y=0, animate=False)
        self._update_detail(self.page_rows[index])
        selected_descriptor = self._descriptor(self.page_rows[index])
        self.query_one("#sb-resume", Button).disabled = (
            selected_descriptor is None or not selected_descriptor.resumable
        )
        self._schedule_page_descriptors()

    def _selected_id(self) -> str:
        try:
            option_list = self.query_one("#sb-list", OptionList)
            if option_list.highlighted is None:
                return ""
            option = option_list.get_option_at_index(option_list.highlighted)
            return str(option.id or "")
        except Exception:
            return ""

    def _selected_session(self) -> SessionMetadata | None:
        selected_id = self._selected_id()
        return next((item for item in self.page_rows if item.session_id == selected_id), None)

    def _update_detail(self, metadata: SessionMetadata) -> None:
        descriptor = self._descriptor(metadata)
        availability = descriptor.availability if descriptor is not None else None
        harness = harness_display_name(
            metadata.harness_id,
            explicit=metadata.harness_display_name,
        )
        model = metadata.model or metadata.provider or "model?"
        text = Text()
        title = (metadata.title or "").strip() or "untitled"
        text.append(f"{title}\n", style="bold #f4f4f5")
        text.append(f"{metadata.session_id}\n", style="#71717a")
        text.append("\n")
        rows = (
            ("Harness", harness),
            ("Model", model),
            ("Age", relative_age(metadata.updated_at)),
            ("Availability", availability.label if availability is not None else "checking…"),
            (
                "Continuity",
                descriptor.continuity_label if descriptor is not None else "checking…",
            ),
            ("Messages", str(metadata.message_count)),
            ("Project", metadata.working_directory or str(self.cwd)),
        )
        for label, value in rows:
            text.append(f"{label:<14}", style="#71717a")
            text.append(f"{value}\n", style="#e4e4e7")
        if availability is not None and availability.detail:
            text.append("\nStatus\n", style="bold #a78bfa")
            text.append(f"{availability.detail}\n", style="#e9d5ff")
        if availability is not None and availability.recovery and availability.status != "ok":
            text.append("\nRecovery\n", style="bold #f59e0b")
            text.append(f"{availability.recovery}\n", style="#fbbf24")
        preview = session_list_preview(metadata, max_len=120)
        # Prefer a real last-user preview only for the highlighted row.
        try:
            live = session_last_user_preview(metadata, storage_dir=self.storage_dir, max_len=120)
            if live:
                preview = live
        except Exception:
            pass
        text.append("\nPreview\n", style="bold #c4b5fd")
        text.append(f"{preview or 'No preview available'}\n", style="#d4d4d8")
        if descriptor is not None and descriptor.resumable:
            text.append(
                "\nEnter or Resume restores this session without sending a prompt.\n",
                style="#86efac",
            )
        self.query_one("#sb-detail", Static).update(text)

    def action_search(self) -> None:
        self.query_one("#sb-search", Input).focus()

    def action_close(self) -> None:
        if self._renaming:
            self._exit_rename()
            return
        self.dismiss(SessionBrowserResult(action="cancel"))

    def action_resume(self) -> None:
        if self._renaming:
            self._commit_rename()
            return
        session = self._selected_session()
        if session is None:
            return
        descriptor = self._descriptor(session)
        if descriptor is None or not descriptor.resumable:
            return
        self.dismiss(SessionBrowserResult(action="resume", session_id=session.session_id))

    def action_continue_last(self) -> None:
        target = self.last_session_id
        if not target and self.all_sessions:
            target = self.all_sessions[0].session_id
        if not target:
            return
        descriptor = self._descriptor_cache.get(target)
        if descriptor is None or not descriptor.resumable:
            return
        self.dismiss(SessionBrowserResult(action="continue_last", session_id=target))

    def action_next_page(self) -> None:
        if self.page < self.total_pages - 1:
            self.page += 1
            self._apply_filter(keep_position=False)

    def action_prev_page(self) -> None:
        if self.page > 0:
            self.page -= 1
            self._apply_filter(keep_position=False)

    def action_rename(self) -> None:
        session = self._selected_session()
        if session is None:
            return
        self._renaming = True
        self.add_class("renaming")
        field = self.query_one("#sb-rename", Input)
        field.value = (session.title or "").strip()
        field.focus()

    def _exit_rename(self) -> None:
        self._renaming = False
        self.remove_class("renaming")
        try:
            self.query_one("#sb-list", OptionList).focus()
        except Exception:
            pass

    def _commit_rename(self) -> None:
        session = self._selected_session()
        if session is None:
            self._exit_rename()
            return
        title = self.query_one("#sb-rename", Input).value.strip()
        if not title:
            self._exit_rename()
            return
        try:
            updated = rename_session_title(session.session_id, title, storage_dir=self.storage_dir)
        except Exception as exc:
            self.query_one("#sb-detail", Static).update(
                Text(f"Could not rename: {exc}", style="#f97316")
            )
            return
        for index, item in enumerate(self.all_sessions):
            if item.session_id == updated.session_id:
                self.all_sessions[index] = updated
                break
        self._descriptor_cache.pop(updated.session_id, None)
        self._exit_rename()
        self._apply_filter(keep_position=True)

    @on(Input.Changed, "#sb-search")
    def _on_search_changed(self, event: Input.Changed) -> None:
        self.search_query = event.value
        self.page = 0
        self._apply_filter(keep_position=False)

    @on(Input.Submitted, "#sb-search")
    def _on_search_submitted(self, _event: Input.Submitted) -> None:
        try:
            self.query_one("#sb-list", OptionList).focus()
        except Exception:
            pass

    @on(Input.Submitted, "#sb-rename")
    def _on_rename_submitted(self, _event: Input.Submitted) -> None:
        self._commit_rename()

    @on(OptionList.OptionHighlighted, "#sb-list")
    def _on_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        session_id = str(getattr(event.option, "id", "") or "")
        session = next((item for item in self.page_rows if item.session_id == session_id), None)
        if session is not None:
            self._update_detail(session)
            descriptor = self._descriptor(session)
            self.query_one("#sb-resume", Button).disabled = (
                descriptor is None or not descriptor.resumable
            )

    @on(OptionList.OptionSelected, "#sb-list")
    def _on_selected(self, _event: OptionList.OptionSelected) -> None:
        # Mouse activation mirrors Enter: resume the highlighted row.
        self.action_resume()

    @on(Button.Pressed)
    def _on_button(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id or ""
        if button_id == "sb-close":
            self.action_close()
        elif button_id == "sb-resume":
            self.action_resume()
        elif button_id == "sb-continue":
            self.action_continue_last()
        elif button_id == "sb-prev":
            self.action_prev_page()
        elif button_id == "sb-next":
            self.action_next_page()
        elif button_id == "sb-rename-btn":
            self.action_rename()


__all__ = [
    "PAGE_SIZE",
    "SessionBrowserLoadResult",
    "SessionBrowserResult",
    "SessionBrowserScreen",
]
