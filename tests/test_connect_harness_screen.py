"""The harness route: pick a harness, confirm it, then pick its model.

Choosing a harness and choosing a model are two decisions, so they are two
screens with a confirmation between them, not one combined list.
"""

from __future__ import annotations

from superqode.providers.connection_profiles import (
    CONNECT_MENU_BUILD,
    CONNECT_MENU_HARNESS,
    CONNECT_MENU_MODELS,
    CONNECT_MENU_PLAN,
    CONNECT_MENU_ROOT,
    CONNECT_MENU_TITLES,
    CONNECT_MENUS,
    connection_profile_ids,
    get_connection_profile,
    list_connection_profiles,
)


class FakeLog:
    def __init__(self):
        self.items = []

    def write(self, value):
        self.items.append(value.plain if hasattr(value, "plain") else str(value))

    def clear(self):
        pass

    def add_info(self, message):
        self.items.append(f"INFO {message}")

    def add_error(self, message):
        self.items.append(f"ERROR {message}")


class DispatchStub:
    """Records what a profile selection actually did."""

    def __init__(self):
        self.harness_commands = []
        self.menus = []

    def _reset_connect_selection_states(self):
        pass

    def _harness_cmd(self, args, log):
        self.harness_commands.append(args)

    def _show_connect_type_picker(self, log, menu=None, **kwargs):
        self.menus.append(menu)


def _card_renderer():
    """A real instance, so the card's helper methods bind to it."""
    from superqode.app.mixins.connect import ConnectMixin

    class Card(ConnectMixin):
        pass

    return Card()


def dispatch(profile_id):
    from superqode.app_main import SuperQodeApp

    stub = DispatchStub()
    SuperQodeApp._dispatch_connection_profile(stub, get_connection_profile(profile_id), FakeLog())
    return stub


# --- the three root choices ---------------------------------------------------


def test_root_offers_the_three_ways_to_get_a_harness():
    assert [(p.id, p.label) for p in list_connection_profiles(CONNECT_MENU_ROOT)] == [
        ("agents", "Connect an existing harness"),
        ("models", "Connect a harness with your model"),
        ("build", "Build your own harness"),
    ]


def test_root_copy_never_names_the_product_at_the_user():
    """Whose harness it is cannot matter before the user has picked one."""
    profiles = list_connection_profiles(CONNECT_MENU_ROOT)
    copy = " ".join(f"{p.label} {p.description}" for p in profiles).lower()

    assert "superqode" not in copy


# --- step one: the harness ----------------------------------------------------


def test_harness_step_lists_the_built_in_harnesses_with_core_first():
    profiles = list_connection_profiles(CONNECT_MENU_HARNESS)

    assert [p.id for p in profiles] == [
        "harness-core",
        "harness-workbench",
        "harness-presets",
        "harness-repo",
    ]
    assert profiles[0].label == "Core"


def test_the_second_root_choice_opens_the_harness_step():
    assert dispatch("models").menus == [CONNECT_MENU_HARNESS]


def test_choosing_a_harness_activates_it():
    """Selecting Core must switch to Core, which is what confirms it and then
    asks for the model."""
    assert dispatch("harness-core").harness_commands == ["switch core"]
    assert dispatch("harness-workbench").harness_commands == ["switch workbench"]


def test_the_harness_catalog_never_offers_vendor_or_acp_agents(tmp_path, monkeypatch):
    """This branch is "a harness with your model", so the other branch's
    products would ask the user to re-answer a question they just answered."""
    monkeypatch.chdir(tmp_path)

    from superqode.app.mixins.connect import ConnectMixin

    class CatalogStub(ConnectMixin):
        def __init__(self):
            self.kwargs = None

        def _reset_connect_selection_states(self):
            pass

        def _show_harness_picker(self, log, **kwargs):
            self.kwargs = kwargs

    for profile_id in ("harness-presets", "harness-repo"):
        stub = CatalogStub()
        stub._dispatch_connection_profile(get_connection_profile(profile_id), FakeLog())
        entries = stub.kwargs["catalog_entries"]
        assert entries, profile_id
        # Everything offered is a HarnessSpec we ship or the repo defines.
        for entry in entries:
            assert entry.source in {
                "built-in",
                "built-in-template",
                "optional:tau",
                "file",
                "registry",
            }


def test_switching_a_harness_says_what_it_can_do(tmp_path, monkeypatch):
    """A name and a tool count do not say whether it can run shell commands."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SUPERQODE_HARNESS", "core")

    from pathlib import Path

    from superqode.app_main import SuperQodeApp
    from superqode.harness import list_harnesses

    entry = next(e for e in list_harnesses(Path.cwd()) if e.id == "workbench")
    log = FakeLog()
    SuperQodeApp._write_harness_detail_card(SuperQodeApp(), entry, log)

    rendered = log.items[-1]
    assert "Runtime" in rendered
    assert "Tools" in rendered
    assert "Sandbox" in rendered
    assert "MCP" in rendered
    assert "shell" in rendered


def test_a_no_tool_harness_says_it_cannot_change_code(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    from pathlib import Path

    from superqode.app_main import SuperQodeApp
    from superqode.harness import list_harnesses

    entry = next(e for e in list_harnesses(Path.cwd()) if e.id == "no-tool")
    log = FakeLog()
    SuperQodeApp._write_harness_detail_card(SuperQodeApp(), entry, log)

    assert "not change it" in log.items[-1]


def test_a_subscription_row_states_the_route_we_take_to_it():
    """ "SDK" alone reads as a property of the product, not as our route."""
    from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

    badges = {p.id: p.badges for p in list_connection_profiles(CONNECT_MENU_VENDORS)}

    assert badges["codex"][-1] == "via SDK"
    assert badges["cursor"][-1] == "via ACP"
    assert badges["antigravity"][-1] == "via CLI"
    # Copilot really does take either route, and the dispatcher prefers the SDK.
    assert badges["copilot"][-1] == "via SDK or CLI"


# --- existing harnesses: subscriptions and ACP are different kinds ------------


def test_existing_harnesses_is_three_categories_you_step_into():
    """Signing in to a plan, launching an ACP process and bolting on a non-ACP
    integration are three different things, so they are three categories."""
    from superqode.providers.connection_profiles import CONNECT_MENU_AGENTS

    assert [(p.id, p.label) for p in list_connection_profiles(CONNECT_MENU_AGENTS)] == [
        ("agent-subscriptions", "Subscriptions"),
        ("agent-acp", "ACP agents"),
        ("other-harnesses", "Other harnesses"),
    ]


def test_each_category_opens_its_own_screen():
    from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

    assert dispatch("agent-subscriptions").menus == [CONNECT_MENU_VENDORS]


def test_the_acp_category_opens_the_original_catalogue_screen():
    """The ACP catalogue has its own screen with install hints and grouping.

    A plain list of profile rows lost all of that, so the category hands off to
    the real screen instead of reimplementing a worse one.
    """
    from superqode.app_main import SuperQodeApp

    class AcpStub(DispatchStub):
        def __init__(self):
            super().__init__()
            self.opened = 0

        def _show_agents(self, log, **kwargs):
            self.opened += 1

    stub = AcpStub()
    SuperQodeApp._dispatch_connection_profile(stub, get_connection_profile("agent-acp"), FakeLog())
    assert stub.opened == 1

    # `:connect acp` keeps working and lands in the same place.
    stub = AcpStub()
    SuperQodeApp._dispatch_connection_profile(stub, get_connection_profile("acp"), FakeLog())
    assert stub.opened == 1


def test_the_subscriptions_category_holds_all_twelve_plans_codex_first():
    """Order is fixed, so a plan is in the same place on every machine.

    Sorting by readiness moved Codex down the screen wherever its optional
    extra was missing, which made the list feel different every time.
    """
    from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

    assert [p.id for p in list_connection_profiles(CONNECT_MENU_VENDORS)] == [
        "codex",
        "cursor",
        "amp",
        "antigravity",
        "grok",
        "copilot",
        "devin",
        "droid",
        "kiro",
        "glm-cli",
        "qwen-code",
        "kimi-code",
    ]


def test_the_subscription_screen_is_one_flat_list():
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_VENDORS,
        display_ordered_profiles,
        grouped_menu_profiles,
    )

    groups = grouped_menu_profiles(CONNECT_MENU_VENDORS)
    assert [name for name, _profiles in groups] == [""]
    # What is drawn stays what selection indexes.
    assert [p.id for p in display_ordered_profiles(CONNECT_MENU_VENDORS)] == [
        p.id for p in list_connection_profiles(CONNECT_MENU_VENDORS)
    ]


def test_a_plan_that_needs_setup_says_so_on_its_own_row():
    """Dropping the readiness sections must not drop the readiness itself."""
    from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

    for profile in list_connection_profiles(CONNECT_MENU_VENDORS):
        if not profile.available:
            assert profile.unavailable_hint, profile.id


def test_connecting_a_vendor_names_its_own_commands():
    """A vendor product keeps its own model and profile controls afterwards.

    Those commands already existed; without naming them on the card there is
    nothing that tells a user Antigravity has ``:agy`` behind it.
    """
    card = _card_renderer()

    log = FakeLog()
    card._write_connection_teaching_card(
        log, label="Antigravity CLI", vendor_owned=True, harness="antigravity-cli"
    )
    rendered = log.items[-1]
    assert ":agy" in rendered
    assert ":antigravity status" in rendered

    log = FakeLog()
    card._write_connection_teaching_card(
        log, label="GitHub Copilot", vendor_owned=True, harness="copilot"
    )
    assert ":copilot" in log.items[-1]

    log = FakeLog()
    card._write_connection_teaching_card(
        log, label="Codex subscription", vendor_owned=True, harness="codex-sdk"
    )
    assert ":codex model" in log.items[-1]


def test_a_plain_model_connection_gets_no_vendor_commands():
    """Ollama has no vendor console, so inventing a section would be noise."""
    log = FakeLog()
    _card_renderer()._write_connection_teaching_card(
        log, label="Ollama · gemma4", vendor_owned=False, harness="core"
    )
    rendered = log.items[-1]
    assert "commands" not in rendered.lower().split("when you're ready")[0]
    assert ":harness" in rendered


def test_back_walks_the_path_the_user_took():
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_ACP,
        CONNECT_MENU_AGENTS,
        CONNECT_MENU_VENDORS,
        parent_menu,
    )

    assert parent_menu(CONNECT_MENU_VENDORS) == CONNECT_MENU_AGENTS
    assert parent_menu(CONNECT_MENU_ACP) == CONNECT_MENU_AGENTS
    assert parent_menu(CONNECT_MENU_AGENTS) == CONNECT_MENU_ROOT
    assert parent_menu(CONNECT_MENU_PLAN) == CONNECT_MENU_MODELS
    assert parent_menu(CONNECT_MENU_MODELS) == CONNECT_MENU_HARNESS


def test_legacy_menu_names_land_on_the_right_category():
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_ACP,
        CONNECT_MENU_MODELS,
        CONNECT_MENU_VENDORS,
        normalize_menu,
    )

    assert normalize_menu("subscriptions") == CONNECT_MENU_VENDORS
    assert normalize_menu("acp") == CONNECT_MENU_ACP
    assert normalize_menu("byok") == CONNECT_MENU_MODELS
    assert normalize_menu("nonsense") == CONNECT_MENU_ROOT


def test_model_step_offers_local_key_and_subscription():
    assert [(p.id, p.label) for p in list_connection_profiles(CONNECT_MENU_MODELS)] == [
        ("local", "Local"),
        ("byok", "Your API key"),
        ("plan", "Subscription"),
    ]


def test_the_two_steps_say_which_step_they_are():
    assert "Step 1 of 2" in CONNECT_MENU_TITLES[CONNECT_MENU_HARNESS][1]
    assert "Step 2 of 2" in CONNECT_MENU_TITLES[CONNECT_MENU_MODELS][1]


def test_back_from_the_model_step_returns_to_the_harness_step():
    from superqode.app_main import SuperQodeApp

    class BackStub(DispatchStub):
        _awaiting_connect_type = True
        _connect_menu = CONNECT_MENU_MODELS

        def query_one(self, *args, **kwargs):
            return FakeLog()

    stub = BackStub()
    assert SuperQodeApp.action_connect_menu_back(stub) is True
    assert stub.menus == [CONNECT_MENU_HARNESS]


def test_back_from_the_harness_step_returns_to_the_root():
    from superqode.app_main import SuperQodeApp

    class BackStub(DispatchStub):
        _awaiting_connect_type = True
        _connect_menu = CONNECT_MENU_HARNESS

        def query_one(self, *args, **kwargs):
            return FakeLog()

    stub = BackStub()
    assert SuperQodeApp.action_connect_menu_back(stub) is True
    assert stub.menus == [CONNECT_MENU_ROOT]


# --- nothing that used to work stopped working --------------------------------


def test_every_pre_existing_connect_id_still_resolves():
    for profile_id in (
        "local",
        "byok",
        "acp",
        "plan",
        "subscriptions",
        "other-harnesses",
        "codex",
        "cursor",
        "amp",
        "antigravity",
        "grok",
        "copilot",
        "devin",
        "droid",
        "kiro",
        "glm-cli",
        "qwen-code",
        "kimi-code",
        "build-import",
        "build-preset",
        "build-wizard",
        "build-blank",
    ):
        assert get_connection_profile(profile_id) is not None, profile_id


def test_build_route_still_has_all_four_ways_in():
    assert [p.id for p in list_connection_profiles(CONNECT_MENU_BUILD)] == [
        "build-import",
        "build-preset",
        "build-wizard",
        "build-blank",
    ]


def test_new_harness_rows_are_addressable_by_name():
    ids = connection_profile_ids()
    for profile_id in ("harness-core", "harness-workbench", "harness-presets", "harness-repo"):
        assert profile_id in ids


# --- the subscription list ----------------------------------------------------


def test_subscription_is_a_real_menu_not_a_printed_list():
    """It used to render text and set no picker state, so nothing responded.

    Being a menu is what gives it arrow keys, Enter, number selection and Esc,
    because every connect screen shares that machinery.
    """
    profiles = list_connection_profiles(CONNECT_MENU_PLAN)

    assert len(profiles) > 3
    assert CONNECT_MENU_PLAN in CONNECT_MENUS
    for profile in profiles:
        assert profile.menu == CONNECT_MENU_PLAN
        # Every row has to lead somewhere the dispatcher understands.
        assert profile.connector in {"byok", "grok-api"}
        if profile.connector == "byok":
            assert profile.byok_provider


def test_choosing_a_plan_connects_that_provider():
    from superqode.app_main import SuperQodeApp

    class PlanStub(DispatchStub):
        def __init__(self):
            super().__init__()
            self.byok = []
            self.grok = []

        def _connect_byok_cmd(self, provider, log):
            self.byok.append(provider)

        def _grok_api_cmd(self, rest, log):
            self.grok.append(rest)

    stub = PlanStub()
    SuperQodeApp._dispatch_connection_profile(
        stub, get_connection_profile("plan-copilot"), FakeLog()
    )
    assert stub.byok == ["github-copilot"]

    stub = PlanStub()
    SuperQodeApp._dispatch_connection_profile(stub, get_connection_profile("plan-grok"), FakeLog())
    assert stub.grok == [""]


def test_the_subscription_row_opens_the_subscription_menu():
    assert dispatch("plan").menus == [CONNECT_MENU_PLAN]


def test_back_from_subscription_returns_to_the_model_step():
    from superqode.app_main import SuperQodeApp

    class BackStub(DispatchStub):
        _awaiting_connect_type = True
        _connect_menu = CONNECT_MENU_PLAN

        def query_one(self, *args, **kwargs):
            return FakeLog()

    stub = BackStub()
    assert SuperQodeApp.action_connect_menu_back(stub) is True
    assert stub.menus == [CONNECT_MENU_MODELS]


def test_every_plan_states_how_to_enable_it():
    for profile in list_connection_profiles(CONNECT_MENU_PLAN):
        if not profile.available:
            assert profile.unavailable_hint, profile.id
