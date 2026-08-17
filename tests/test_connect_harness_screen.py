"""The harness route: pick a harness, confirm it, then pick its model."""

from __future__ import annotations

import pytest

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

    def _open_connect_screen(self, log):
        pass

    def _harness_cmd(self, args, log):
        self.harness_commands.append(args)

    def _show_connect_type_picker(self, log, menu=None, **kwargs):
        self.menus.append(menu)

    def _begin_key_harness(self, profile, log):
        from superqode.app.mixins.connect import ConnectMixin

        ConnectMixin._begin_key_harness(self, profile, log)


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
    """Root copy does not name the product."""
    profiles = list_connection_profiles(CONNECT_MENU_ROOT)
    copy = " ".join(f"{p.label} {p.description}" for p in profiles).lower()

    assert "superqode" not in copy


# --- step one: the harness ----------------------------------------------------


def test_harness_step_lists_the_built_in_harnesses_with_core_first():
    profiles = list_connection_profiles(CONNECT_MENU_HARNESS)

    assert [p.id for p in profiles] == [
        "harness-core",
        "harness-rlm",
        "harness-pipy",
        "harness-workbench",
        "harness-presets",
        "harness-repo",
    ]
    # Core is the right default, and the row says so rather than leaving the
    # user to infer it from position alone.
    assert profiles[0].label == "Core (recommended)"


def test_the_second_root_choice_opens_the_harness_step():
    assert dispatch("models").menus == [CONNECT_MENU_HARNESS]


def test_choosing_a_harness_activates_it():
    """Selecting a harness switches to it."""
    assert dispatch("harness-core").harness_commands == ["switch core"]
    assert dispatch("harness-rlm").harness_commands == ["switch rlm"]
    assert dispatch("harness-workbench").harness_commands == ["switch workbench"]
    assert dispatch("harness-pipy").harness_commands == ["switch pipy"]


def test_the_harness_catalog_never_offers_vendor_or_acp_agents(tmp_path, monkeypatch):
    """The harness catalogue excludes vendor and ACP agents."""
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
                "optional:deepseek-harness",
                "optional:deepagents",
                "file",
                "registry",
            }


def test_switching_a_harness_says_what_it_can_do(tmp_path, monkeypatch):
    """The switch card states what the harness can do."""
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


def test_a_host_executing_harness_states_its_permissions_on_every_route(tmp_path, monkeypatch):
    """`:connect harness-rlm` and `:harness switch` skip the picker warning."""
    monkeypatch.chdir(tmp_path)

    from pathlib import Path

    from superqode.app_main import SuperQodeApp
    from superqode.harness import list_harnesses

    entry = next(e for e in list_harnesses(Path.cwd()) if e.id == "rlm")
    assert entry.spec.metadata["selection_warning"]

    log = FakeLog()
    SuperQodeApp._write_harness_detail_card(SuperQodeApp(), entry, log)

    rendered = log.items[-1]
    assert "Warning" in rendered
    assert "permissions of" in rendered
    assert "no approval prompts or sandbox" in rendered


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
    """Each subscription row states the transport used to reach it."""
    from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

    badges = {p.id: p.badges for p in list_connection_profiles(CONNECT_MENU_VENDORS)}

    assert badges["codex"][-1] == "via SDK"
    assert badges["cursor"][-1] == "via ACP"
    assert badges["antigravity"][-1] == "via CLI"
    # Copilot really does take either route, and the dispatcher prefers the SDK.
    assert badges["copilot"][-1] == "via SDK or CLI"


# --- existing harnesses: subscriptions and ACP are different kinds ------------


@pytest.mark.parametrize(
    "menu_version,expected",
    [
        (
            "v1",
            [
                ("agent-subscriptions", "Subscriptions"),
                ("agent-acp", "ACP agents"),
                ("other-harnesses", "Other harnesses"),
            ],
        ),
        (
            "v2",
            [
                ("agent-subscriptions", "Subscriptions"),
                ("agent-acp", "ACP agents"),
                ("agent-open-harnesses", "Open harnesses"),
            ],
        ),
    ],
)
def test_existing_harnesses_is_three_categories_you_step_into(menu_version, expected, monkeypatch):
    """Existing harnesses split by connection kind; v2 replaces Other with Open."""
    monkeypatch.setenv("SUPERQODE_CONNECT_MENU", menu_version)
    from superqode.providers.connection_profiles import CONNECT_MENU_AGENTS

    assert [(p.id, p.label) for p in list_connection_profiles(CONNECT_MENU_AGENTS)] == expected
    assert "Closed harnesses" not in {
        p.label for p in list_connection_profiles(CONNECT_MENU_AGENTS)
    }


def test_each_category_opens_its_own_screen():
    from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

    assert dispatch("agent-subscriptions").menus == [CONNECT_MENU_VENDORS]


def test_open_category_opens_the_open_list():
    from superqode.providers.connection_profiles import CONNECT_MENU_OPEN

    assert dispatch("agent-open-harnesses").menus == [CONNECT_MENU_OPEN]
    assert dispatch("open-harnesses").menus == [CONNECT_MENU_OPEN]


def test_other_harnesses_aliases_to_open_under_v2(monkeypatch):
    monkeypatch.setenv("SUPERQODE_CONNECT_MENU", "v2")
    from superqode.providers.connection_profiles import CONNECT_MENU_OPEN

    assert dispatch("other-harnesses").menus == [CONNECT_MENU_OPEN]


def test_selecting_an_open_row_switches_that_optional_harness():
    assert dispatch("tau").harness_commands == ["switch tau"]
    assert dispatch("deepseek-harness").harness_commands == ["switch deepseek-harness"]
    assert dispatch("deepagents").harness_commands == ["switch deepagents"]


def test_the_acp_category_opens_the_original_catalogue_screen():
    """The ACP category hands off to the existing catalogue screen."""
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


def test_selecting_muse_reports_readiness_instead_of_failing():
    """Muse is the first live user of the external-cli connector.

    That branch previously matched only Antigravity and errored on anything
    else, so a Muse row that dispatched nowhere would look broken.
    """
    from superqode.app_main import SuperQodeApp

    class MuseStub(DispatchStub):
        def __init__(self):
            super().__init__()
            self.shown = 0

        def _show_muse_connect(self, log):
            self.shown += 1

    stub = MuseStub()
    log = FakeLog()
    SuperQodeApp._dispatch_connection_profile(stub, get_connection_profile("muse"), log)

    assert stub.shown == 1
    assert not [item for item in log.items if str(item).startswith("ERROR")]


def test_the_subscriptions_category_holds_every_plan_codex_first():
    """Plan order is fixed, so a product sits in the same place everywhere."""
    from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

    assert [p.id for p in list_connection_profiles(CONNECT_MENU_VENDORS)] == [
        "codex",
        "cursor",
        "amp",
        "antigravity",
        "muse",
        "prime-agent",
        "grok",
        "copilot",
        "devin",
        "droid",
        "kiro",
        "glm-cli",
        "qwen-code",
        "kimi-code",
        "deepagents-code",
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
    """A plan needing setup states how to enable it."""
    from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS

    for profile in list_connection_profiles(CONNECT_MENU_VENDORS):
        if not profile.available:
            assert profile.unavailable_hint, profile.id


def test_connecting_a_vendor_names_its_own_commands():
    """The connection card names the vendor's own controls."""
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
    """A plain model connection gets no vendor command section."""
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
        CONNECT_MENU_CLOSED,
        CONNECT_MENU_OPEN,
        CONNECT_MENU_VENDORS,
        parent_menu,
    )

    assert parent_menu(CONNECT_MENU_VENDORS) == CONNECT_MENU_AGENTS
    assert parent_menu(CONNECT_MENU_ACP) == CONNECT_MENU_AGENTS
    assert parent_menu(CONNECT_MENU_OPEN) == CONNECT_MENU_AGENTS
    assert parent_menu(CONNECT_MENU_CLOSED) == CONNECT_MENU_AGENTS
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


def test_v2_normalizes_other_harnesses_to_the_open_menu(monkeypatch):
    monkeypatch.setenv("SUPERQODE_CONNECT_MENU", "v2")
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_OPEN,
        CONNECT_MENU_ROOT,
        normalize_menu,
    )

    assert normalize_menu("other-harnesses") == CONNECT_MENU_OPEN
    assert normalize_menu("open-harnesses") == CONNECT_MENU_OPEN
    monkeypatch.setenv("SUPERQODE_CONNECT_MENU", "v1")
    assert normalize_menu("other-harnesses") == CONNECT_MENU_ROOT


def test_model_step_offers_local_key_and_subscription():
    # BYOK is the term people search for; the parenthetical is what it means.
    assert [(p.id, p.label) for p in list_connection_profiles(CONNECT_MENU_MODELS)] == [
        ("local", "Local"),
        ("byok", "BYOK (use your own API key)"),
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


def test_back_from_open_returns_to_existing_harnesses():
    from superqode.app_main import SuperQodeApp
    from superqode.providers.connection_profiles import CONNECT_MENU_AGENTS, CONNECT_MENU_OPEN

    class BackStub(DispatchStub):
        _awaiting_connect_type = True
        _connect_menu = CONNECT_MENU_OPEN

        def query_one(self, *args, **kwargs):
            return FakeLog()

    stub = BackStub()
    assert SuperQodeApp.action_connect_menu_back(stub) is True
    assert stub.menus == [CONNECT_MENU_AGENTS]


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
    for profile_id in (
        "harness-core",
        "harness-rlm",
        "harness-workbench",
        "harness-pipy",
        "harness-presets",
        "harness-repo",
    ):
        assert profile_id in ids


# --- the subscription list ----------------------------------------------------


def test_subscription_is_a_real_menu_not_a_printed_list():
    """Subscriptions is a menu, so it inherits the shared picker machinery."""
    profiles = list_connection_profiles(CONNECT_MENU_PLAN)

    assert len(profiles) > 3
    assert CONNECT_MENU_PLAN in CONNECT_MENUS
    for profile in profiles:
        assert profile.menu == CONNECT_MENU_PLAN
        # Every row has to lead somewhere the dispatcher understands.
        assert profile.connector in {"byok", "grok-api", "copilot"}
        if profile.connector == "byok":
            assert profile.byok_provider
        if profile.connector == "copilot":
            # The vendor route asks the account what it may use. BYOK would
            # list the whole catalogue, which is not plan specific.
            assert profile.runtime
            assert not profile.byok_provider


def test_choosing_a_plan_connects_that_provider():
    from superqode.app_main import SuperQodeApp

    class PlanStub(DispatchStub):
        def __init__(self):
            super().__init__()
            self.byok = []
            self.grok = []
            self.copilot = []

        def _connect_byok_cmd(self, provider, log):
            self.byok.append(provider)

        def _grok_api_cmd(self, rest, log):
            self.grok.append(rest)

        def _connect_copilot_subscription(self, profile, log):
            self.copilot.append(profile.id)

    stub = PlanStub()
    SuperQodeApp._dispatch_connection_profile(
        stub, get_connection_profile("plan-copilot"), FakeLog()
    )
    # The vendor route, not BYOK: BYOK lists the whole Copilot catalogue
    # rather than what this plan may actually use.
    assert stub.copilot == ["plan-copilot"]
    assert stub.byok == []

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


def test_no_menu_row_leads_to_the_legacy_copilot_byok_route():
    """The BYOK route lists the catalogue, not what a plan may use.

    ``connect.py`` prints a warning to anyone who reaches that route by typing,
    so no row in any menu may lead there silently.
    """
    from superqode.providers.connection_profiles import list_connection_profiles

    offenders = [
        profile.id
        for profile in list_connection_profiles()
        if profile.connector == "byok" and profile.byok_provider == "github-copilot"
    ]

    assert offenders == [], f"these rows still use the legacy Copilot BYOK route: {offenders}"


def test_both_copilot_entries_ask_the_account():
    from superqode.providers.connection_profiles import get_connection_profile

    for profile_id in ("copilot", "plan-copilot"):
        profile = get_connection_profile(profile_id)
        assert profile.connector == "copilot", profile_id
        assert profile.runtime == "copilot-sdk", profile_id
