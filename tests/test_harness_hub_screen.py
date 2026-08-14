"""Focused Harness Hub and structured outcome contracts."""

from __future__ import annotations

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from superqode.app.harness_picker import HarnessPickerItem
from superqode.app.outcomes import Outcome, OutcomeAction, OutcomeSeverity, OutcomeStore
from superqode.harness.hub import hub_ecosystem_picker_items
from superqode.widgets.harness_hub import HarnessHubResult, HarnessHubScreen
from superqode.widgets.outcome_screen import ActivityScreen, OutcomeScreen, OutcomeSelection


def _item(
    item_id: str,
    name: str,
    *,
    ready: bool = True,
    group: str = "SuperQode harnesses",
) -> HarnessPickerItem:
    return HarnessPickerItem(
        id=item_id,
        display_name=name,
        description=f"{name} description",
        runtime="builtin",
        source="file" if group == "Project harnesses" else "built-in",
        group=group,
        available=ready,
        issue="install it" if not ready else "",
        continuity="same-session",
    )


class _HubApp(App):
    def __init__(self) -> None:
        super().__init__()
        self.selection: HarnessHubResult | None = None

    def compose(self) -> ComposeResult:
        return []

    def on_mount(self) -> None:
        self.push_screen(
            HarnessHubScreen(
                [
                    _item("core", "Core"),
                    _item("tau", "Tau", ready=False),
                    _item("project", "Project Harness", group="Project harnesses"),
                ],
                current_id="core",
            ),
            callback=self._selected,
        )

    def _selected(self, result: HarnessHubResult | None) -> None:
        self.selection = result


def test_outcome_store_caps_history_and_tracks_unread() -> None:
    store = OutcomeStore(limit=2)
    first = store.add(Outcome("One", "First", severity=OutcomeSeverity.SUCCESS))
    second = store.add(Outcome("Two", "Second"))
    store.mark_read(first.id)
    third = store.add(Outcome("Three", "Third"))

    assert [item.id for item in store.list()] == [third.id, second.id]
    assert store.unread_count == 2
    assert third.receipt == "Three: Third"


@pytest.mark.asyncio
async def test_hub_search_filter_and_keyboard_selection() -> None:
    app = _HubApp()
    async with app.run_test(size=(100, 34)) as pilot:
        screen = app.screen
        assert isinstance(screen, HarnessHubScreen)
        assert len(screen.filtered_items) == 3

        await pilot.pause()
        assert await pilot.click("#hub-filter-setup")
        await pilot.pause()
        assert [item.id for item in screen.filtered_items] == ["tau"]

        assert await pilot.click("#hub-filter-all")
        await pilot.pause()
        await pilot.press("/")
        await pilot.press("p", "r", "o", "j", "e", "c", "t")
        await pilot.pause()
        assert [item.id for item in screen.filtered_items] == ["project"]

        await pilot.press("enter")
        await pilot.press("enter")
        await pilot.pause()
        assert app.selection == HarnessHubResult("use", "project")


@pytest.mark.asyncio
async def test_mouse_selection_previews_until_use_is_clicked() -> None:
    app = _HubApp()
    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        screen = app.screen
        assert isinstance(screen, HarnessHubScreen)

        # Clicking a row selects it for inspection without switching harness.
        assert await pilot.click("#hub-list", offset=(4, 3))
        await pilot.pause()
        assert app.selection is None

        selected_id = screen._selected_id()
        assert selected_id == "tau"

        assert await pilot.click("#hub-use")
        await pilot.pause()
        assert app.selection == HarnessHubResult("use", selected_id)


@pytest.mark.asyncio
async def test_enter_activates_the_focused_hub_button() -> None:
    app = _HubApp()
    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        app.screen.query_one("#hub-close", Button).focus()

        await pilot.press("enter")
        await pilot.pause()

        assert not isinstance(app.screen, HarnessHubScreen)
        assert app.selection is None


@pytest.mark.asyncio
async def test_zcode_is_browsable_but_enter_opens_inspection() -> None:
    zcode = next(item for item in hub_ecosystem_picker_items() if item.id == "ecosystem:zcode")
    app = App()
    selected: list[HarnessHubResult | None] = []

    async with app.run_test(size=(100, 34)) as pilot:
        app.push_screen(
            HarnessHubScreen([zcode], initial_filter="coming"),
            callback=selected.append,
        )
        await pilot.pause()

        screen = app.screen
        assert isinstance(screen, HarnessHubScreen)
        assert [item.id for item in screen.filtered_items] == ["ecosystem:zcode"]
        assert str(screen.query_one("#hub-use", Button).label) == "Learn more"

        await pilot.press("enter")
        await pilot.pause()

        assert selected == [HarnessHubResult("inspect", "ecosystem:zcode")]


@pytest.mark.asyncio
async def test_hub_catalog_keeps_the_main_content_visible() -> None:
    """Guard against flexible header children swallowing the catalog viewport."""
    app = _HubApp()
    async with app.run_test(size=(100, 34)) as pilot:
        await pilot.pause()
        screen = app.screen
        header = screen.query_one("#hub-header")
        body = screen.query_one("#hub-body")
        harness_list = screen.query_one("#hub-list")

        assert header.outer_size.height == 5
        assert body.size.height >= 16
        assert harness_list.outer_size.height == body.outer_size.height


@pytest.mark.asyncio
async def test_outcome_and_activity_screens_return_clicked_actions() -> None:
    outcome = Outcome(
        "Harness ready",
        "Codex can be used now",
        actions=(OutcomeAction("use", "Use Codex", ":harness switch codex", primary=True),),
    )
    app = App()

    async with app.run_test() as pilot:
        selected = []
        app.push_screen(OutcomeScreen(outcome), callback=selected.append)
        await pilot.pause()
        await pilot.click("#outcome-action-use")
        await pilot.pause()
        assert selected == [OutcomeSelection("use", ":harness switch codex")]

        activity_selected = []
        app.push_screen(ActivityScreen([outcome]), callback=activity_selected.append)
        await pilot.pause()
        assert app.screen.query_one("#activity-open", Button).label == "Use Codex"
        await pilot.click("#activity-open")
        await pilot.pause()
        assert activity_selected == [OutcomeSelection("use", ":harness switch codex")]
