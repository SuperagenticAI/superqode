import json
from pathlib import Path

from click.testing import CliRunner

from superqode.app.harness_picker import HarnessPickerItem
from superqode.commands.hub import hub
from superqode.harness.hub import HUB_SCHEMA_VERSION, build_hub_index, filter_hub_records
from superqode.providers.connection_profiles import CONNECT_MENU_VENDORS, connection_profile_ids


def _item(**overrides):
    values = {
        "id": "codex",
        "display_name": "Codex",
        "description": "OpenAI coding agent",
        "runtime": "codex-cli",
        "source": "connection:codex",
        "group": "Coding agents",
        "available": True,
        "issue": "",
        "continuity": "fresh-session",
        "kind": "connection",
    }
    values.update(overrides)
    return HarnessPickerItem(**values)


def test_hub_index_is_versioned_serializable_and_excludes_targets():
    payload = build_hub_index(items=[_item(target=object())])

    assert payload["schema_version"] == HUB_SCHEMA_VERSION
    assert payload["count"] == 1
    assert payload["items"][0]["readiness"] == "ready"
    assert payload["items"][0]["integration_level"] == "managed"
    assert "target" not in payload["items"][0]
    json.dumps(payload)


def test_hub_index_marks_custom_and_setup_required():
    payload = build_hub_index(
        items=[
            _item(
                id="my-harness",
                group="Project harnesses",
                available=False,
                issue="Install the runtime",
                path=None,
                kind="harness",
            )
        ]
    )

    item = payload["items"][0]
    assert item["integration_level"] == "custom"
    assert item["readiness"] == "setup-required"
    assert item["setup"] == "Install the runtime"


def test_public_hub_index_excludes_local_entries_and_paths(tmp_path):
    private = _item(
        id="private",
        group="Project harnesses",
        source="file",
        path=tmp_path / "harness.yaml",
    )
    public = build_hub_index(items=[_item(), private], public=True)
    local = build_hub_index(items=[private])

    assert [item["id"] for item in public["items"]] == ["codex"]
    assert local["items"][0]["project_path"] == ""


def test_public_readiness_ignores_the_exporting_machine():
    """A published snapshot must not report the maintainer's installed CLIs."""
    inventory = [
        _item(id="core", group="SuperQode harnesses", source="built-in", kind="harness"),
        # Same vendor route, opposite local probe results.
        _item(id="codex", available=False, issue="Install the Codex CLI"),
        _item(id="cursor", available=True),
    ]

    public = {item["id"]: item for item in build_hub_index(items=inventory, public=True)["items"]}
    local = {item["id"]: item for item in build_hub_index(items=inventory)["items"]}

    assert public["codex"]["readiness"] == public["cursor"]["readiness"] == "setup-required"
    assert public["core"]["readiness"] == "ready"
    # The terminal still reflects this machine.
    assert local["codex"]["readiness"] == "setup-required"
    assert local["cursor"]["readiness"] == "ready"


def test_public_readiness_keeps_states_that_were_never_probed(monkeypatch):
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )

    by_id = {item["id"]: item for item in build_hub_index(public=True)["items"]}

    assert by_id["ecosystem:zcode"]["readiness"] == "not-supported"


def test_readiness_labels_cover_every_published_state(monkeypatch):
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )
    from superqode.harness.hub import READINESS_LABELS

    published = {item["readiness"] for item in build_hub_index(public=True)["items"]}

    assert published <= set(READINESS_LABELS)


def test_hub_cli_filters_every_published_readiness(monkeypatch):
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )
    runner = CliRunner()

    for state in ("ready", "setup-required", "not-supported"):
        result = runner.invoke(hub, ["list", "--public", "--readiness", state])
        assert result.exit_code == 0, f"{state}: {result.output}"

    ecosystem = runner.invoke(hub, ["list", "--public", "--readiness", "not-supported"])
    assert "Integration pending" in ecosystem.output


def test_every_spec_entry_answers_how_to_measure_and_improve_it():
    """The Hub claims harnesses are evaluated and optimized; entries must show how."""
    by_id = {item["id"]: item for item in build_hub_index(public=True)["items"]}

    assert "superqode harness test --spec harness.yaml" in by_id["workbench"]["eval_commands"]
    assert any("optimize-omni" in c for c in by_id["workbench"]["optimize_commands"])
    # An external agent owns its own loop, so SuperQode must not imply otherwise.
    assert by_id["codex"]["optimize_commands"] == ()
    assert any("not to this agent" in policy for policy in by_id["codex"]["policies"])


def test_published_commands_never_pass_an_identifier_where_a_path_is_required():
    """--spec is a Click PATH; emitting `--spec core` would be a broken command."""
    for item in build_hub_index(public=True)["items"]:
        for command in (*item["eval_commands"], *item["optimize_commands"]):
            if "--spec " in command:
                spec = command.split("--spec ", 1)[1].split()[0]
                assert spec.endswith((".yaml", ".yml")), f"{item['id']}: {command}"


def test_jcode_states_a_buildable_route_unlike_a_desktop_only_harness(monkeypatch):
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )
    by_id = {item["id"]: item for item in build_hub_index(public=True)["items"]}
    jcode = by_id["ecosystem:jcode"]

    assert jcode["readiness"] == "not-supported"
    assert jcode["repository"] == "https://github.com/1jehuang/jcode"
    assert "TypeScript SDK" in jcode["capabilities"]
    # ZCode documents no programmatic surface; jcode does. Say which is which.
    assert "buildable" in jcode["support_note"]
    assert "does not document" in by_id["ecosystem:zcode"]["support_note"]


def test_headlong_has_no_task_contract_unlike_jcode(monkeypatch):
    """jcode publishes a task contract; Headlong publishes an observation."""
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )
    by_id = {item["id"]: item for item in build_hub_index(public=True)["items"]}
    headlong = by_id["ecosystem:headlong"]

    assert headlong["readiness"] == "not-supported"
    assert headlong["kind"] == "ecosystem"
    assert headlong["openness"] == "open"
    assert headlong["license"] == "Apache-2.0"
    assert headlong["interface"] == "Named identity CLI"
    assert "observation" in headlong["support_note"]
    assert "task" in headlong["support_note"]
    # The phrases jcode's entry actually uses for a buildable route. Headlong
    # must not be described the same way a future edit could accidentally
    # restore that analogy.
    assert "route is buildable" not in headlong["support_note"]
    assert "buildable once" not in headlong["support_note"]


def test_letta_and_warp_are_open_ecosystem_clis(monkeypatch):
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )
    by_id = {item["id"]: item for item in build_hub_index(public=True)["items"]}
    letta = by_id["ecosystem:letta"]
    warp = by_id["ecosystem:warp"]

    assert letta["openness"] == "open"
    assert letta["license"] == "Apache-2.0"
    assert letta["repository"] == "https://github.com/letta-ai/letta-code"
    assert "npm install -g @letta-ai/letta-code" in letta["install_command"]
    assert warp["openness"] == "open"
    assert warp["license"] == "AGPL-3.0"
    assert warp["repository"] == "https://github.com/warpdotdev/warp"
    assert "agent-cli" in warp["install_command"]


def test_reference_only_entries_are_never_the_active_harness():
    from superqode.harness.hub import REFERENCE_ONLY_KINDS, hub_ecosystem_picker_items

    items = hub_ecosystem_picker_items()
    kinds = {item.kind for item in items}

    assert kinds == REFERENCE_ONLY_KINDS == {"ecosystem"}
    assert any(item.id == "ecosystem:jcode" for item in items)


def test_hub_lists_harnesses_and_not_general_integrations(monkeypatch):
    """The Hub is a harness catalog.

    Memory providers, sandboxes, protocol surfaces and chat channels are real
    integrations, but someone opening the Hub is choosing a harness. They are
    documented under docs/integrations/ and must not dilute this catalog.
    """
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )
    payload = build_hub_index(public=True)
    categories = set(payload["categories"])
    ids = {item["id"] for item in payload["items"]}

    assert not categories & {
        "Sandboxes",
        "Memory",
        "Protocols and tools",
        "Remote interfaces",
        "Model access plans",
        "Local inference engines",
        "Evaluation and optimization",
    }
    assert not any(
        item_id.startswith(
            (
                "sandbox:",
                "memory:",
                "protocol:",
                "remote:",
                "plan:",
                "inference:",
                "eval:",
                "optimize:",
            )
        )
        for item_id in ids
    )


def test_hub_record_filter_searches_runtime_and_state():
    records = build_hub_index(
        items=[_item(), _item(id="custom", runtime="python", available=False)]
    )["items"]

    assert [item["id"] for item in filter_hub_records(records, query="python")] == ["custom"]
    assert [item["id"] for item in filter_hub_records(records, readiness="setup-required")] == [
        "custom"
    ]


def test_hub_cli_default_and_list_json(monkeypatch):
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )
    runner = CliRunner()

    human = runner.invoke(hub, [])
    machine = runner.invoke(hub, ["list", "--json"])

    assert human.exit_code == 0
    assert "Coding agents" in human.output
    assert "Codex" in human.output
    assert machine.exit_code == 0
    payload = json.loads(machine.output)
    assert payload["schema_version"] == HUB_SCHEMA_VERSION
    assert payload["items"][0]["id"] == "codex"


def test_hub_cli_public_json_excludes_project_harnesses(monkeypatch):
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [
            _item(),
            _item(id="private", group="Project harnesses", source="file"),
        ],
    )

    result = CliRunner().invoke(hub, ["list", "--public", "--json"])

    assert result.exit_code == 0
    ids = [item["id"] for item in json.loads(result.output)["items"]]
    assert ids[0] == "codex"
    assert "private" not in ids
    assert "ecosystem:zcode" in ids


def test_full_hub_expands_protocol_registry(monkeypatch):
    calls = []

    def fake_items(*_args, **kwargs):
        calls.append(kwargs)
        return [_item()]

    monkeypatch.setattr("superqode.harness.hub.harness_picker_items", fake_items)

    build_hub_index()

    assert calls[0]["expand_protocol_catalog"] is True


def test_full_public_hub_includes_model_access_inference_and_ecosystem(monkeypatch):
    monkeypatch.setattr(
        "superqode.harness.hub.harness_picker_items",
        lambda *_args, **_kwargs: [_item()],
    )

    payload = build_hub_index(public=True)
    by_id = {item["id"]: item for item in payload["items"]}

    assert by_id["ecosystem:qm"]["readiness"] == "not-supported"
    assert "future integration" in by_id["ecosystem:qm"]["support_note"]
    assert by_id["ecosystem:zcode"]["readiness"] == "not-supported"
    assert by_id["ecosystem:zcode"]["runtime"] == "external"
    assert "GLM-5.3" in by_id["ecosystem:zcode"]["description"]
    assert "ACP server" in by_id["ecosystem:zcode"]["support_note"]
    assert by_id["ecosystem:zcode"]["docs_url"] == "https://zcode.z.ai/en/docs/welcome"


def test_full_hub_covers_every_vendor_subscription_profile():
    hub_ids = {item["id"] for item in build_hub_index(public=True)["items"]}
    vendor_ids = set(connection_profile_ids(menu=CONNECT_MENU_VENDORS))

    assert vendor_ids <= hub_ids


def test_full_hub_exposes_get_started_tools_policies_and_popularity():
    by_id = {item["id"]: item for item in build_hub_index(public=True)["items"]}

    assert ":agy models" in by_id["antigravity"]["tui_commands"]
    assert "read_file" in by_id["workbench"]["tools"]
    assert "Sandbox: local" in by_id["workbench"]["policies"]
    assert by_id["workbench"]["based_on"] == "workbench"
    assert by_id["codex"]["popularity_rank"] < by_id["core"]["popularity_rank"]
    assert [step["title"] for step in by_id["copilot"]["setup_steps"]] == [
        "Recommended: install the SuperQode Copilot SDK integration",
        "Alternative: install the official GitHub Copilot CLI",
        "Authenticate with GitHub Copilot",
    ]
    assert by_id["copilot"]["setup_steps"][2]["command"] == "copilot login"


def test_openness_is_resolved_from_the_most_specific_source_that_knows():
    """Openness describes the harness implementation, never SuperQode's route.

    Four sources answer this, in order: a license SuperQode has verified, the
    ACP registry's own tag, the vendor profile that already curates it, and
    SuperQode's own Apache-2.0 code.
    """
    by_id = {item["id"]: item for item in build_hub_index(public=True)["items"]}

    verified = by_id["deepagents"]
    assert (verified["openness"], verified["license"]) == ("open", "MIT")
    assert verified["repository"] == "https://github.com/langchain-ai/deepagents"

    # Tagged in the ACP registry but not license-checked by hand: open, with
    # the license left blank rather than invented.
    assert by_id["acp:bub"]["openness"] == "open"
    assert by_id["acp:bub"]["license"] == ""

    # Curated on the vendor connection profile.
    assert by_id["cursor"]["openness"] == "closed"

    # SuperQode's own harnesses and presets.
    assert (by_id["workbench"]["openness"], by_id["workbench"]["license"]) == (
        "open",
        "Apache-2.0",
    )
    assert by_id["glm-coding"]["openness"] == "open"


def test_a_harness_is_never_reported_as_open_on_a_guess():
    """Source-available and unverified entries must not read as open source.

    Charm ships Crush under the Functional Source License, so an open-source
    filter that included it would be telling the user something false.
    """
    by_id = {item["id"]: item for item in build_hub_index(public=True)["items"]}

    assert by_id["ecosystem:crush"]["openness"] == ""
    assert by_id["ecosystem:crush"]["license"] == ""
    assert all(
        record["openness"] in {"open", "closed", ""}
        for record in build_hub_index(public=True)["items"]
    )


def test_project_harnesses_never_claim_a_licence_superqode_cannot_know():
    payload = build_hub_index(
        items=[_item(id="mine", group="Project harnesses", source="file", kind="harness")]
    )

    assert payload["items"][0]["integration_level"] == "custom"
    assert payload["items"][0]["openness"] == ""
    assert payload["items"][0]["license"] == ""


def test_openness_filter_selects_only_entries_known_to_be_open():
    records = build_hub_index(public=True)["items"]

    matched = filter_hub_records(records, openness="open")

    assert matched
    assert {record["openness"] for record in matched} == {"open"}
    ids = {record["id"] for record in matched}
    assert {"deepagents", "deepagents-code", "acp:opencode", "workbench"} <= ids
    assert not ids & {"cursor", "devin", "ecosystem:crush"}


def test_hub_list_filters_by_openness_from_the_cli():
    result = CliRunner().invoke(hub, ["list", "--openness", "open", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["count"] > 0
    assert {item["openness"] for item in payload["items"]} == {"open"}


def test_every_hub_entry_has_a_unique_id():
    """Native, vendor, ACP, and ecosystem routes are merged into one list.

    A repeated id would make two different harnesses collide in the Hub, in
    `hub show`, and in the published catalog. DeepAgents ships as four separate
    routes, which is exactly the shape that would trip over this.
    """
    ids = [item["id"] for item in build_hub_index(public=True)["items"]]

    assert len(ids) == len(set(ids))
    assert {"deepagents", "deepagents-code", "acp:deepagents", "acp:deepagents-code"} <= set(ids)


def test_published_snapshot_lists_every_hub_record():
    """`docs/assets/harness-hub.json` is generated, so it goes stale silently.

    The 0.2.99 snapshot shipped without the Junie record because the export was
    run before the profile landed. Ids and openness are compared rather than
    the whole payload: `generated_at` changes on every run, and readiness is
    normalized per machine by `_publication_readiness`.

    Regenerate with `uv run python scripts/export_hub_catalog.py`.
    """
    root = Path(__file__).resolve().parents[1]
    published = json.loads(
        (root / "docs" / "assets" / "harness-hub.json").read_text(encoding="utf-8")
    )
    current = build_hub_index(root, public=True)

    published_openness = {item["id"]: item.get("openness", "") for item in published["items"]}
    current_openness = {item["id"]: item.get("openness", "") for item in current["items"]}

    assert published_openness == current_openness
    assert published["count"] == current["count"]
    assert published["schema_version"] == current["schema_version"]
