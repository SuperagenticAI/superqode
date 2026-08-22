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

    def add_warning(self, message):
        self.items.append(f"WARN {message}")

    def add_system(self, message):
        self.items.append(f"SYSTEM {message}")


class DispatchStub:
    """Records what a profile selection actually did."""

    def __init__(self):
        self.harness_commands = []
        self.menus = []

    def _reset_connect_selection_states(self):
        pass

    def _clear_key_harness_session(self):
        # The app always has this; a stub that dispatches has to model it.
        self._key_harness_session = None
        self._pending_key_harness_route = None

    def _open_connect_screen(self, log):
        pass

    def _harness_cmd(self, args, log):
        self.harness_commands.append(args)

    def _show_connect_type_picker(self, log, menu=None, **kwargs):
        self.menus.append(menu)

    def _begin_key_harness(self, profile, log):
        from superqode.app.mixins.connect import ConnectMixin

        ConnectMixin._begin_key_harness(self, profile, log)

    def _begin_vendor_key(self, profile, log):
        self.vendor_keys = getattr(self, "vendor_keys", [])
        self.vendor_keys.append(profile.id)


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


# --- the root choices ---------------------------------------------------------


def test_root_offers_the_ways_to_get_a_harness():
    """Three owners you name, plus the loop that lives behind a protocol."""
    assert [(p.id, p.label) for p in list_connection_profiles(CONNECT_MENU_ROOT)] == [
        ("agents", "Connect an existing harness"),
        ("models", "Connect a harness with your model"),
        ("build", "Build your own harness"),
        ("protocols", "Connect to existing agent protocols"),
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
                "optional:uhp",
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
                ("agent-acp", "ACP"),
                ("agent-open-harnesses", "Open harnesses"),
                ("agent-closed-harnesses", "Closed harnesses"),
            ],
        ),
    ],
)
def test_existing_harnesses_is_three_categories_you_step_into(menu_version, expected, monkeypatch):
    """Existing harnesses split by connection kind; v2 replaces Other with Open/Closed."""
    monkeypatch.setenv("SUPERQODE_CONNECT_MENU", menu_version)
    from superqode.providers.connection_profiles import CONNECT_MENU_AGENTS

    assert [(p.id, p.label) for p in list_connection_profiles(CONNECT_MENU_AGENTS)] == expected
    if menu_version == "v1":
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


def test_closed_category_opens_the_closed_list():
    from superqode.providers.connection_profiles import CONNECT_MENU_CLOSED

    assert dispatch("agent-closed-harnesses").menus == [CONNECT_MENU_CLOSED]
    assert dispatch("closed-harnesses").menus == [CONNECT_MENU_CLOSED]


def test_selecting_droid_key_uses_vendor_key_not_harness_switch():
    stub = dispatch("droid-key")
    assert stub.harness_commands == []
    assert getattr(stub, "vendor_keys", []) == ["droid-key"]


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


def test_the_muse_key_row_gates_on_the_key_instead_of_erroring(monkeypatch):
    """`muse-key` shares Muse's external-cli connector but is not the plan row.

    The branch matched `muse` and `antigravity` by id, so the Closed key row
    fell through to "Unsupported external CLI profile" and META_API_KEY was
    never read.
    """
    from superqode.app_main import SuperQodeApp

    monkeypatch.delenv("META_API_KEY", raising=False)

    from superqode.app.mixins.connect import ConnectMixin

    class KeyStub(DispatchStub, ConnectMixin):
        """DispatchStub's recorders win; ConnectMixin supplies the real key path."""

        def __init__(self):
            super().__init__()
            self.cards = []

        def _write_api_key_required_panel(self, log, **kwargs):
            self.cards.append(("panel", kwargs))

        def _write_harness_setup_card(self, log, entry, spec):
            self.cards.append(("setup", entry.id))

    stub = KeyStub()
    log = FakeLog()
    SuperQodeApp._dispatch_connection_profile(stub, get_connection_profile("muse-key"), log)

    assert not [item for item in log.items if str(item).startswith("ERROR")]
    assert [kind for kind, _ in stub.cards] == ["panel"]
    _kind, kwargs = stub.cards[0]
    assert kwargs["env_vars"] == ("META_API_KEY",)
    assert kwargs["retry"] == ":connect muse-key"
    # No `meta` login: META_API_KEY is Muse's own key, not the BYOK slot.
    assert kwargs["login_id"] == ""

    monkeypatch.setenv("META_API_KEY", "sk-muse-test")
    stub = KeyStub()
    SuperQodeApp._dispatch_connection_profile(stub, get_connection_profile("muse-key"), FakeLog())

    assert stub.cards == [("setup", "muse-key")]


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
        "junie",
        "fx",
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
    from superqode.providers.connection_profiles import CONNECT_MENU_KEY_MODELS

    assert parent_menu(CONNECT_MENU_KEY_MODELS) == CONNECT_MENU_OPEN
    assert (
        parent_menu(CONNECT_MENU_KEY_MODELS, return_menu=CONNECT_MENU_CLOSED) == CONNECT_MENU_CLOSED
    )


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


def test_key_models_menu_is_local_and_byok_without_plan():
    from superqode.providers.connection_profiles import CONNECT_MENU_KEY_MODELS

    assert [(p.id, p.label) for p in list_connection_profiles(CONNECT_MENU_KEY_MODELS)] == [
        ("local", "Local"),
        ("byok", "BYOK (use your own API key)"),
    ]
    # Native model list is untouched: Plan stays on SuperQode's own harness path.
    assert [p.id for p in list_connection_profiles(CONNECT_MENU_MODELS)] == [
        "local",
        "byok",
        "plan",
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


def test_selecting_an_available_open_row_starts_a_key_harness_session(monkeypatch):
    from types import SimpleNamespace

    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.providers.connection_profiles import CONNECT_MENU_OPEN

    monkeypatch.setattr(
        "superqode.harness.resolve_harness",
        lambda *args, **kwargs: SimpleNamespace(available=False),
    )

    class Stub(DispatchStub):
        def __init__(self):
            super().__init__()
            self._key_harness_session = None
            self._pending_key_harness_route = None

        def _prompt_model_for_harness(self, *args, **kwargs):
            raise AssertionError("switch should be the real _harness_cmd in this test")

    stub = Stub()
    ConnectMixin._begin_key_harness(stub, get_connection_profile("tau"), FakeLog())
    assert stub.harness_commands == ["switch tau"]
    session = stub._key_harness_session
    assert isinstance(session, KeyHarnessSession)
    assert session.entry_id == "tau"
    assert session.after_auth == "switch-and-model"
    assert session.return_menu == CONNECT_MENU_OPEN
    assert session.openness == "open"


@pytest.mark.parametrize("profile_id", ("jcode", "letta", "warp", "goose-key"))
def test_setup_card_rows_render_without_unknown_theme_keys(profile_id):
    """Open rows that cannot launch must still paint a card on click/Enter."""
    from superqode.app.mixins.connect import ConnectMixin

    class Stub(ConnectMixin):
        def __init__(self):
            self.harness_commands = []

        def _harness_cmd(self, args, log):
            self.harness_commands.append(args)

        def _begin_vendor_key(self, profile, log):
            raise AssertionError("setup-card rows must not take the vendor-key path")

    stub = Stub()
    log = FakeLog()
    ConnectMixin._begin_key_harness(stub, get_connection_profile(profile_id), log)
    assert stub.harness_commands == []
    body = "\n".join(log.items)
    assert get_connection_profile(profile_id).label in body
    assert "does not start its loop" in body


def test_reset_connect_states_keeps_key_harness_session():
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry("tau")
    spec = next(s for s in entry.auth if s.mode == "byok")
    session = KeyHarnessSession(
        entry_id="tau",
        openness="open",
        auth_spec=spec,
        return_menu="open-harnesses",
        after_auth="switch-and-model",
    )

    class Stub(ConnectMixin):
        def __init__(self):
            self._key_harness_session = session
            self._awaiting_byok_provider = True

    stub = Stub()
    stub._reset_connect_selection_states()
    assert stub._key_harness_session is session
    assert stub._awaiting_byok_provider is False


def test_esc_from_key_models_keeps_session_esc_to_agents_clears_it():
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_AGENTS,
        CONNECT_MENU_KEY_MODELS,
        CONNECT_MENU_OPEN,
    )
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry("tau")
    spec = next(s for s in entry.auth if s.mode == "byok")
    session = KeyHarnessSession(
        entry_id="tau",
        openness="open",
        auth_spec=spec,
        return_menu=CONNECT_MENU_OPEN,
        after_auth="switch-and-model",
    )

    class Stub(ConnectMixin):
        def __init__(self):
            self._awaiting_connect_type = True
            self._connect_menu = CONNECT_MENU_KEY_MODELS
            self._key_harness_session = session
            self.menus = []

        def query_one(self, *args, **kwargs):
            return FakeLog()

        def _show_connect_type_picker(self, log, menu=None, **kwargs):
            self.menus.append(menu)
            self._connect_menu = menu

    stub = Stub()
    assert stub.action_connect_menu_back() is True
    assert stub.menus == [CONNECT_MENU_OPEN]
    assert stub._key_harness_session is session

    assert stub.action_connect_menu_back() is True
    assert stub.menus[-1] == CONNECT_MENU_AGENTS
    assert stub._key_harness_session is None


def test_return_to_model_step_reopens_key_models_when_session_is_set():
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.providers.connection_profiles import CONNECT_MENU_KEY_MODELS
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry("deepseek-harness")
    spec = next(s for s in entry.auth if s.mode == "byok")

    class Stub(ConnectMixin):
        def __init__(self):
            self._key_harness_session = KeyHarnessSession(
                entry_id="deepseek-harness",
                openness="open",
                auth_spec=spec,
                return_menu="open-harnesses",
                after_auth="switch-and-model",
            )
            self.menus = []

        def query_one(self, *args, **kwargs):
            return FakeLog()

        def _show_connect_type_picker(self, log, menu=None, **kwargs):
            self.menus.append(menu)

    stub = Stub()
    stub._return_to_model_step()
    assert stub.menus == [CONNECT_MENU_KEY_MODELS]


def test_prompt_model_for_harness_uses_key_models_when_session_is_set():
    from superqode.app.mixins.commands_impl import CommandImplMixin
    from superqode.app.mixins.connect import KeyHarnessSession
    from superqode.providers.connection_profiles import CONNECT_MENU_KEY_MODELS
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry("deepagents")
    spec = next(s for s in entry.auth if s.mode == "byok")

    class Stub(CommandImplMixin):
        def __init__(self):
            self._key_harness_session = KeyHarnessSession(
                entry_id="deepagents",
                openness="open",
                auth_spec=spec,
                return_menu="open-harnesses",
                after_auth="switch-and-model",
            )
            self.menus = []
            self._connect_context_note = ""

        def _show_connect_type_picker(self, log, menu=None, **kwargs):
            self.menus.append(menu)

    stub = Stub()
    stub._prompt_model_for_harness("DeepAgents (SDK)", FakeLog())
    assert stub.menus == [CONNECT_MENU_KEY_MODELS]
    assert "deepagents-code" not in (stub._connect_context_note or "").lower()


def test_connect_last_dispatches_acp_agent_not_profile_id(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from superqode.app.mixins.connect import ConnectMixin

    class Stub(ConnectMixin):
        def __init__(self):
            self.acp = []
            self.dispatched = []
            self.byok = []

        def _connect_acp_cmd(self, name, log):
            self.acp.append(name)

        def _dispatch_connection_profile(self, profile, log):
            self.dispatched.append(profile.id)

        def _connect_byok_mode(self, provider, model, log, *args, **kwargs):
            self.byok.append((provider, model))

    stub = Stub()
    stub._save_connection_config(
        category="acp",
        auth_mode="acp",
        harness_id="",
        profile_id="",
        acp_agent="opencode",
        openness="",
        provider="anthropic",
        model="ignored",
        transport="ACP",
        after_auth="",
    )
    stub._connect_last(FakeLog())
    assert stub.acp == ["opencode"]
    assert stub.dispatched == []
    assert stub.byok == []


def test_connect_last_applies_route_only_for_switch_and_model(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from superqode.app.mixins.commands_impl import CommandImplMixin
    from superqode.app.mixins.connect import ConnectMixin

    class Stub(ConnectMixin, CommandImplMixin):
        def __init__(self):
            self.routes = []
            self.harness_commands = []
            self._key_harness_session = None
            self._pending_key_harness_route = None
            self._connect_context_note = ""

        def _harness_cmd(self, args, log):
            self.harness_commands.append(args)
            self._prompt_model_for_harness("Tau", log)

        def _connect_byok_mode(self, provider, model, log, *args, **kwargs):
            self.routes.append(("byok", provider, model))

        def _connect_local_mode(self, provider, model, log, *args, **kwargs):
            self.routes.append(("local", provider, model))

        def _show_connect_type_picker(self, log, menu=None, **kwargs):
            self.routes.append(("menu", menu))

    stub = Stub()
    stub._save_connection_config(
        category="open-harnesses",
        auth_mode="byok",
        harness_id="tau",
        profile_id="tau",
        acp_agent="",
        openness="open",
        provider="anthropic",
        model="claude-sonnet-4-6",
        transport="harness-protocol",
        after_auth="switch-and-model",
    )
    stub._connect_last(FakeLog())
    assert stub.harness_commands == ["switch tau"]
    assert stub.routes == [("byok", "anthropic", "claude-sonnet-4-6")]
    assert stub._pending_key_harness_route is None


def test_connect_last_missing_extra_keeps_route_until_resume(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from superqode.app.mixins.commands_impl import CommandImplMixin
    from superqode.app.mixins.connect import ConnectMixin

    class Stub(ConnectMixin, CommandImplMixin):
        def __init__(self):
            self.routes = []
            self.harness_commands = []
            self._key_harness_session = None
            self._pending_key_harness_route = None
            self._connect_context_note = ""

        def _harness_cmd(self, args, log):
            self.harness_commands.append(args)
            # Extra missing: install prompt, no model step yet.

        def _connect_byok_mode(self, provider, model, log, *args, **kwargs):
            self.routes.append(("byok", provider, model))

        def _show_connect_type_picker(self, log, menu=None, **kwargs):
            self.routes.append(("menu", menu))

    stub = Stub()
    stub._save_connection_config(
        category="open-harnesses",
        auth_mode="byok",
        harness_id="tau",
        profile_id="tau",
        acp_agent="",
        openness="open",
        provider="anthropic",
        model="claude-sonnet-4-6",
        transport="harness-protocol",
        after_auth="switch-and-model",
    )
    stub._connect_last(FakeLog())
    assert stub.harness_commands == ["switch tau"]
    assert stub.routes == []
    assert stub._key_harness_session is not None
    assert stub._key_harness_session.entry_id == "tau"
    assert stub._pending_key_harness_route == ("byok", "anthropic", "claude-sonnet-4-6")

    stub._prompt_model_for_harness("Tau", FakeLog())
    assert stub.routes == [("byok", "anthropic", "claude-sonnet-4-6")]
    assert stub._pending_key_harness_route is None


def test_dispatch_non_key_connectors_clear_the_key_session():
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry("tau")
    spec = next(s for s in entry.auth if s.mode == "byok")

    class Stub(ConnectMixin):
        def __init__(self):
            self._key_harness_session = KeyHarnessSession(
                entry_id="tau",
                openness="open",
                auth_spec=spec,
                return_menu="open-harnesses",
                after_auth="switch-and-model",
            )
            self._pending_key_harness_route = ("byok", "anthropic", "x")
            self.menus = []

        def _open_connect_screen(self, log):
            pass

        def _show_connect_type_picker(self, log, menu=None, **kwargs):
            self.menus.append(menu)

        def _harness_cmd(self, args, log):
            pass

    stub = Stub()
    stub._dispatch_connection_profile(get_connection_profile("models"), FakeLog())
    assert stub._key_harness_session is None
    assert stub._pending_key_harness_route is None


def test_bare_connect_clears_the_key_session():
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.app.mixins.slash_commands import SlashCommandMixin
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry("tau")
    spec = next(s for s in entry.auth if s.mode == "byok")

    class Stub(ConnectMixin, SlashCommandMixin):
        def __init__(self):
            self._key_harness_session = KeyHarnessSession(
                entry_id="tau",
                openness="open",
                auth_spec=spec,
                return_menu="open-harnesses",
                after_auth="switch-and-model",
            )
            self._pending_key_harness_route = ("byok", "anthropic", "x")
            self._awaiting_byok_provider = False
            self._awaiting_byok_model = False
            self._acp_client = None
            self.menus = []

        def _record_ex_command(self, cmd, c):
            pass

        def set_timer(self, *args, **kwargs):
            pass

        def _ensure_input_focus(self):
            pass

        def _show_connect_type_picker(self, log, menu=None, **kwargs):
            self.menus.append(menu or "root")

    stub = Stub()
    stub._handle_command(":connect", FakeLog())
    assert stub._key_harness_session is None
    assert stub._pending_key_harness_route is None


def test_install_cancel_clears_key_session():
    from superqode.app.mixins.commands_impl import CommandImplMixin
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry("tau")
    spec = next(s for s in entry.auth if s.mode == "byok")

    class Stub(ConnectMixin, CommandImplMixin):
        def __init__(self):
            self._key_harness_session = KeyHarnessSession(
                entry_id="tau",
                openness="open",
                auth_spec=spec,
                return_menu="open-harnesses",
                after_auth="switch-and-model",
            )
            self._pending_key_harness_route = ("byok", "anthropic", "x")
            self._awaiting_harness_install = {"id": "tau"}

    stub = Stub()
    assert stub._handle_harness_install_input("n", FakeLog()) is True
    assert stub._key_harness_session is None
    assert stub._pending_key_harness_route is None
    assert stub._awaiting_harness_install is None


def test_acp_subscription_persist_uses_subscriptions_category(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from superqode.app.mixins.connect import ConnectMixin

    class Stub(ConnectMixin):
        def __init__(self):
            self._acp_subscription_vendor = "droid"
            self._connecting_profile_id = "droid"
            self.current_provider = ""
            self.current_model = ""

    stub = Stub()
    stub._persist_acp_connection("droid")
    saved = stub._load_connection_config()
    assert saved["category"] == "subscriptions"
    assert saved["auth_mode"] == "subscription"
    assert saved["profile_id"] == "droid"
    assert saved["acp_agent"] == "droid"

    stub._acp_subscription_vendor = None
    stub._connecting_profile_id = ""
    stub._persist_acp_connection("opencode")
    saved = stub._load_connection_config()
    assert saved["category"] == "acp"
    assert saved["auth_mode"] == "acp"
    assert saved["profile_id"] == ""
    assert saved["acp_agent"] == "opencode"


def test_key_harness_allowlist_filters_dsh_and_deepagents():
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.providers.harness_catalog import get_entry

    class Stub(ConnectMixin):
        def __init__(self, entry_id):
            entry = get_entry(entry_id)
            spec = next(s for s in entry.auth if s.mode == "byok")
            self._key_harness_session = KeyHarnessSession(
                entry_id=entry_id,
                openness="open",
                auth_spec=spec,
                return_menu="open-harnesses",
                after_auth="switch-and-model",
            )

    tau = Stub("tau")
    assert tau._key_harness_allowlist("byok") is None
    assert tau._key_harness_allowlist("local") is None

    dsh = Stub("deepseek-harness")
    assert dsh._key_harness_allowlist("byok") == frozenset({"deepseek"})
    assert "anthropic" not in dsh._key_harness_allowlist("local")

    sdk = Stub("deepagents")
    assert sdk._key_harness_allowlist("byok") == frozenset({"anthropic", "google"})
    assert sdk._key_harness_allowlist("local") == frozenset(
        {"ollama", "lmstudio", "mlx", "llamacpp", "openai-compatible"}
    )


def test_finish_open_connect_records_milestone_and_clears_session(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("SUPERQODE_PROGRESS_DIR", str(tmp_path / "progress"))
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession
    from superqode.app.progress import MILESTONES, clear_progress_cache
    from superqode.providers.harness_catalog import get_entry

    assert "connected_open_harness" in MILESTONES
    clear_progress_cache()
    entry = get_entry("tau")
    spec = next(s for s in entry.auth if s.mode == "byok")
    configured = []

    class Stub(ConnectMixin):
        def __init__(self):
            self._key_harness_session = KeyHarnessSession(
                entry_id="tau",
                openness="open",
                auth_spec=spec,
                return_menu="open-harnesses",
                after_auth="switch-and-model",
            )
            self.milestones = []

        def _record_milestone(self, name):
            self.milestones.append(name)

        def _sync_tau_after_key_connect(self, provider, model, log):
            configured.append((provider, model))

    stub = Stub()
    stub._finish_successful_model_connect("anthropic", "claude-sonnet-4-6", "byok", FakeLog())
    assert configured == [("anthropic", "claude-sonnet-4-6")]
    assert stub.milestones == ["connected_open_harness"]
    assert stub._key_harness_session is None
    saved = stub._load_connection_config()
    assert saved["category"] == "open-harnesses"
    assert saved["harness_id"] == "tau"
    assert saved["provider"] == "anthropic"
    assert saved["after_auth"] == "switch-and-model"
    assert "key" not in saved
    clear_progress_cache()


def test_connection_persist_never_writes_secrets(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    from superqode.app.mixins.connect import ConnectMixin

    class Stub(ConnectMixin):
        pass

    stub = Stub()
    stub._save_byok_config("anthropic", "claude-sonnet-4-6")
    stub._save_connection_config(
        category="open-harnesses",
        auth_mode="byok",
        harness_id="tau",
        profile_id="tau",
        acp_agent="",
        openness="open",
        provider="anthropic",
        model="claude-sonnet-4-6",
        transport="harness-protocol",
        after_auth="switch-and-model",
    )
    saved = stub._read_user_config()
    assert saved["byok"]["last_provider"] == "anthropic"
    assert saved["connection"]["harness_id"] == "tau"
    blob = str(saved)
    assert "sk-" not in blob
    assert "api_key" not in blob
    assert "secret" not in blob.lower()


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
        "droid-key",
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


# --- Open rows that end in an ACP attach ---------------------------------------


class AttachStub:
    """Records the attach without starting an agent or drawing a screen."""

    def __init__(self):
        from superqode.providers.connection_profiles import CONNECT_MENU_OPEN

        self.acp = []
        self.menus = []
        self.saved = {}
        self.milestones = []
        self._acp_extra_env = None
        self._connect_menu = CONNECT_MENU_OPEN

    def _connect_acp_cmd(self, name, log):
        self.acp.append(name)

    def _show_connect_type_picker(self, log, menu=None, **kwargs):
        self.menus.append(menu)
        self._connect_menu = menu

    def _save_connection_config(self, **fields):
        self.saved = fields

    def _record_milestone(self, name):
        self.milestones.append(name)


def _attach_stub():
    from superqode.app.mixins.connect import ConnectMixin

    class Stub(AttachStub, ConnectMixin):
        pass

    return Stub()


def _clear_key_envs(monkeypatch):
    for name in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "GROK_CODE_XAI_API_KEY",
        "XAI_API_KEY",
        "QWEN_API_KEY",
        "DASHSCOPE_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_an_acp_attach_row_asks_for_a_model_instead_of_a_setup_card(monkeypatch):
    """`acp-attach` used to fall through to "SuperQode does not start its loop"."""
    from superqode.providers.connection_profiles import CONNECT_MENU_KEY_MODELS

    _clear_key_envs(monkeypatch)
    stub = _attach_stub()
    stub._begin_key_harness(get_connection_profile("opencode-key"), FakeLog())

    assert stub.menus == [CONNECT_MENU_KEY_MODELS]
    assert stub._key_harness_session.entry_id == "opencode-key"
    assert stub._key_harness_session.after_auth == "acp-attach"


def test_choosing_a_provider_hands_its_key_to_the_agent(monkeypatch, tmp_path):
    """The picker chooses credentials for the agent, not a SuperQode loop."""
    import superqode.auth as auth_module
    from superqode.auth import LocalAuthStorage
    from superqode.providers.dynamic import resolve_provider_def

    _clear_key_envs(monkeypatch)
    monkeypatch.setattr(auth_module, "_storage", LocalAuthStorage(tmp_path / "auth.json"))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")

    stub = _attach_stub()
    stub._begin_key_harness(get_connection_profile("opencode-key"), FakeLog())
    handled = stub._attach_key_harness_over_acp(
        "anthropic", "claude-opus-4-8", resolve_provider_def("anthropic"), FakeLog()
    )

    assert handled is True
    assert stub.acp == ["opencode"]
    assert stub._acp_extra_env == {"ANTHROPIC_API_KEY": "sk-ant-test"}
    assert stub._acp_extra_env_agent == "opencode"
    assert stub.saved["harness_id"] == "opencode-key"
    assert stub.saved["acp_agent"] == "opencode"
    assert stub.saved["transport"] == "ACP"
    assert stub.saved["model"] == "claude-opus-4-8"
    assert "connected_open_harness" in stub.milestones
    # The session ends on success, so a later Core switch cannot inherit it.
    assert stub._key_harness_session is None


def test_a_missing_cloud_key_asks_for_it_rather_than_attaching(monkeypatch, tmp_path):
    """An agent attached without a key fails on its first model call."""
    import superqode.auth as auth_module
    from superqode.auth import LocalAuthStorage
    from superqode.providers.dynamic import resolve_provider_def

    _clear_key_envs(monkeypatch)
    monkeypatch.setattr(auth_module, "_storage", LocalAuthStorage(tmp_path / "auth.json"))

    class Log(FakeLog):
        def write_feedback(self, value):
            self.write(value)

    stub = _attach_stub()
    log = Log()
    stub._begin_key_harness(get_connection_profile("opencode-key"), FakeLog())
    handled = stub._attach_key_harness_over_acp(
        "openai", "gpt-5", resolve_provider_def("openai"), log
    )

    assert handled is True
    assert stub.acp == []
    rendered = " ".join(str(item) for item in log.items)
    assert "API Key Required" in rendered
    assert ":connect opencode-key" in rendered


def test_a_row_that_hides_byok_offers_only_the_local_step(monkeypatch):
    """Grok Build's key is xAI's own, so there is no provider to choose."""
    _clear_key_envs(monkeypatch)
    stub = _attach_stub()
    stub._begin_key_harness(get_connection_profile("grok-key"), FakeLog())

    assert [row.id for row in stub._connect_menu_profiles()] == ["local"]


def test_an_exported_vendor_key_attaches_without_a_model_step(monkeypatch):
    """A step with one right answer is not a question worth asking."""
    _clear_key_envs(monkeypatch)
    monkeypatch.setenv("GROK_CODE_XAI_API_KEY", "xai-test")

    stub = _attach_stub()
    stub._begin_key_harness(get_connection_profile("grok-key"), FakeLog())

    assert stub.menus == []
    assert stub.acp == ["grok"]
    assert stub._acp_extra_env == {"GROK_CODE_XAI_API_KEY": "xai-test"}
    assert stub._key_harness_session is None


def test_a_local_pick_never_invents_a_variable_the_agent_may_not_read(monkeypatch):
    """`OLLAMA_HOST` describes Ollama's client, not what Qwen Code reads.

    Passing an endpoint under a name the agent ignores would look like the
    model choice landed. Only a catalog-declared `base_url_env` is passed, so
    the honest outcome here is an attach plus a line saying what was not set.
    """
    from superqode.providers.dynamic import resolve_provider_def

    _clear_key_envs(monkeypatch)
    stub = _attach_stub()
    log = FakeLog()
    stub._begin_key_harness(get_connection_profile("qwen-code-key"), FakeLog())
    handled = stub._attach_key_harness_over_acp(
        "ollama", "qwen3:8b", resolve_provider_def("ollama"), log
    )

    assert handled is True
    assert stub.acp == ["qwen"]
    assert not stub._acp_extra_env
    notice = " ".join(str(item) for item in log.items)
    assert "keeps its own model configuration" in notice
    assert "qwen3:8b" in notice


def test_a_declared_base_url_env_is_still_passed():
    """DeepSeek Harness names the variable, so the endpoint is safe to set."""
    from superqode.app.mixins.connect import ConnectMixin
    from superqode.providers.dynamic import resolve_provider_def
    from superqode.providers.harness_catalog import get_entry

    entry = get_entry("deepseek-harness")
    spec = next(item for item in entry.auth if item.mode == "local")
    extra = ConnectMixin._key_harness_child_env(
        _attach_stub(), spec, resolve_provider_def("ollama"), "qwen3:8b"
    )

    assert spec.base_url_env == "DEEPSEEK_BASE_URL"
    assert extra["DEEPSEEK_BASE_URL"]


def test_a_session_survives_a_harness_whose_id_differs_from_its_row(monkeypatch):
    """The session matched on the catalog id, which is a different namespace.

    A switch answers with a HarnessDefinition id or a spec path, so a row whose
    `harness_id` differs from its `id` silently lost its session and dropped
    the user into the native Plan step.
    """
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession

    class Stub(ConnectMixin):
        pass

    stub = Stub()
    stub._key_harness_session = KeyHarnessSession(
        entry_id="row-id",
        openness="open",
        auth_spec=None,
        return_menu="open-harnesses",
        after_auth="switch-and-model",
        harness_id="adapter-id",
    )

    assert stub._key_harness_session_matches("adapter-id") is True
    assert stub._key_harness_session_matches("row-id") is True
    assert stub._key_harness_session_matches("/repo/harnesses/adapter-id.yaml") is True
    assert stub._key_harness_session_matches("something-else") is False


def test_a_longer_harness_name_is_not_the_one_the_session_holds():
    """`endswith` made every `*-tau` harness look like `tau`."""
    from superqode.app.mixins.connect import ConnectMixin, KeyHarnessSession

    class Stub(ConnectMixin):
        pass

    stub = Stub()
    stub._key_harness_session = KeyHarnessSession(
        entry_id="tau",
        openness="open",
        auth_spec=None,
        return_menu="open-harnesses",
        after_auth="switch-and-model",
        harness_id="tau",
    )

    assert stub._key_harness_session_matches("tau") is True
    assert stub._key_harness_session_matches("my-tau") is False


def test_the_open_list_states_the_licence_on_the_row():
    """Openness is the point of the list, and AGPL against MIT is the answer."""
    from superqode.providers.connection_profiles import (
        CONNECT_MENU_OPEN,
        list_connection_profiles,
    )

    badges = {p.id: p.badges for p in list_connection_profiles(CONNECT_MENU_OPEN)}

    assert "AGPL-3.0" in badges["warp"]
    assert "MIT" in badges["tau"]
    assert "Apache-2.0" in badges["goose-key"]
    # Openness leads, then the licence that qualifies it.
    assert badges["warp"][:2] == ["open harness", "AGPL-3.0"]


# --- the Open row that ends in Prime's Python RPC ------------------------------


class RpcStub(AttachStub):
    """Records the Prime launch instead of starting the agent."""

    def __init__(self):
        super().__init__()
        self.rpc = []

    def _connect_prime_rpc(self, selector, log, **kwargs):
        self.rpc.append((selector, kwargs.get("extra_env")))
        return True


def _rpc_stub():
    from superqode.app.mixins.connect import ConnectMixin

    class Stub(RpcStub, ConnectMixin):
        pass

    return Stub()


def test_the_prime_key_row_asks_for_a_model_instead_of_a_setup_card(monkeypatch):
    """`vendor-key-rpc` was unimplemented, so its provider lists were unreachable."""
    from superqode.providers.connection_profiles import CONNECT_MENU_KEY_MODELS

    _clear_key_envs(monkeypatch)
    monkeypatch.setattr("superqode.providers.prime_agent.is_installed", lambda: True, raising=False)

    stub = _rpc_stub()
    stub._begin_key_harness(get_connection_profile("prime-agent-key"), FakeLog())

    assert stub.menus == [CONNECT_MENU_KEY_MODELS]
    assert stub._key_harness_session.after_auth == "vendor-key-rpc"
    assert [row.id for row in stub._connect_menu_profiles()] == ["local", "byok"]


def test_a_cloud_provider_reaches_prime_through_the_child_env(monkeypatch, tmp_path):
    """Prime owns the loop; the picker only decides the credentials it gets."""
    import superqode.auth as auth_module
    from superqode.auth import LocalAuthStorage
    from superqode.providers.dynamic import resolve_provider_def

    _clear_key_envs(monkeypatch)
    monkeypatch.setattr(auth_module, "_storage", LocalAuthStorage(tmp_path / "auth.json"))
    monkeypatch.setattr("superqode.providers.prime_agent.is_installed", lambda: True, raising=False)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-prime")

    stub = _rpc_stub()
    stub._begin_key_harness(get_connection_profile("prime-agent-key"), FakeLog())
    handled = stub._attach_key_harness_over_rpc(
        "anthropic", "claude-opus-4-8", resolve_provider_def("anthropic"), FakeLog()
    )

    assert handled is True
    assert stub.rpc == [("anthropic/claude-opus-4-8", {"ANTHROPIC_API_KEY": "sk-ant-prime"})]
    assert stub.saved["transport"] == "Python RPC"
    assert stub.saved["provider"] == "anthropic"
    assert stub._key_harness_session is None


def test_prime_is_never_launched_without_the_key_it_needs(monkeypatch, tmp_path):
    import superqode.auth as auth_module
    from superqode.auth import LocalAuthStorage
    from superqode.providers.dynamic import resolve_provider_def

    _clear_key_envs(monkeypatch)
    monkeypatch.setattr(auth_module, "_storage", LocalAuthStorage(tmp_path / "auth.json"))
    monkeypatch.setattr("superqode.providers.prime_agent.is_installed", lambda: True, raising=False)

    class Log(FakeLog):
        def write_feedback(self, value):
            self.write(value)

    stub = _rpc_stub()
    log = Log()
    stub._begin_key_harness(get_connection_profile("prime-agent-key"), FakeLog())
    handled = stub._attach_key_harness_over_rpc(
        "openai", "gpt-5", resolve_provider_def("openai"), log
    )

    assert handled is True
    assert stub.rpc == []
    assert "API Key Required" in " ".join(str(item) for item in log.items)


def test_a_local_pick_is_registered_in_primes_own_models_file(monkeypatch, tmp_path):
    """Prime is pointed at an endpoint through models.json, not an env variable.

    The home override keeps this out of the developer's real Prime config.
    """
    import json

    from superqode.providers.dynamic import resolve_provider_def

    _clear_key_envs(monkeypatch)
    home = tmp_path / "prime-agent"
    monkeypatch.setenv("PRIME_AGENT_CODING_AGENT_DIR", str(home))
    monkeypatch.setattr("superqode.providers.prime_agent.is_installed", lambda: True, raising=False)

    stub = _rpc_stub()
    stub._begin_key_harness(get_connection_profile("prime-agent-key"), FakeLog())
    handled = stub._attach_key_harness_over_rpc(
        "ollama", "qwen3:8b", resolve_provider_def("ollama"), FakeLog()
    )

    assert handled is True
    assert stub.rpc == [("ollama/qwen3:8b", {})]
    registered = json.loads((home / "models.json").read_text())["providers"]["ollama"]
    assert registered["baseUrl"].endswith("/v1")
    assert registered["api"] == "openai-completions"
    assert registered["models"] == [{"id": "qwen3:8b"}]
    assert stub.saved["auth_mode"] == "local"


def test_prime_is_not_launched_when_it_is_not_installed(monkeypatch):
    from superqode.providers.dynamic import resolve_provider_def

    _clear_key_envs(monkeypatch)
    monkeypatch.setattr(
        "superqode.providers.prime_agent.is_installed", lambda: False, raising=False
    )

    stub = _rpc_stub()
    log = FakeLog()
    stub._begin_key_harness(get_connection_profile("prime-agent-key"), FakeLog())
    handled = stub._attach_key_harness_over_rpc(
        "anthropic", "claude-opus-4-8", resolve_provider_def("anthropic"), log
    )

    assert handled is True
    assert stub.rpc == []
    assert any("not installed" in str(item) for item in log.items)


def test_prime_only_offers_local_engines_it_can_be_pointed_at():
    """Prime needs a resolvable base URL, so the DSH list was too wide."""
    from superqode.providers.dynamic import resolve_base_url, resolve_provider_def
    from superqode.providers.harness_catalog import auth_allowlist, get_entry

    allowed = auth_allowlist(get_entry("prime-agent-key"), "local")

    assert allowed
    assert "openai-compatible" not in allowed
    for provider_id in allowed:
        assert resolve_base_url(resolve_provider_def(provider_id)), provider_id
