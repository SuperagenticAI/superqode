"""The ship gate for PiPy.

Each check here corresponds to a promise made while building the harness. They
are collected in one file so that breaking any of them is obvious in a diff,
rather than being spread across the phase that introduced it.
"""

from __future__ import annotations

import ast
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
PIPY = ROOT / "src" / "superqode" / "pipy"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, cwd=ROOT).stdout.strip()


# -- nothing else changes ---------------------------------------------------- #


def test_core_is_still_the_default_harness():
    from superqode.harness import DEFAULT_HARNESS_ID

    assert DEFAULT_HARNESS_ID == "core"


def test_existing_native_harnesses_are_unchanged():
    from superqode.harness import list_harnesses

    entries = {entry.id: entry for entry in list_harnesses(".")}

    assert entries["core"].runtime == "builtin"
    assert entries["core"].default is True
    assert entries["core"].tools == ("read", "write", "edit", "bash")
    assert entries["workbench"].runtime == "builtin"
    assert entries["no-tool"].runtime == "builtin"
    assert entries["tau"].runtime == "tau"


def test_tau_source_is_untouched():
    changed = git("diff", "main", "--name-only", "--", "*tau*")
    assert changed == "", f"tau files changed: {changed}"


def test_shared_code_changes_are_limited_to_the_known_set():
    """Anything outside PiPy that changed should be a deliberate, listed edit."""
    changed = {
        line
        for line in git(
            "diff",
            "main",
            "--name-only",
            "--",
            ".",
            # PiPy's own files, wherever they live. What this test guards is
            # changes to code that existed before PiPy.
            ":(exclude)src/superqode/pipy",
            ":(exclude)src/superqode/harness/pipy_adapter.py",
            ":(exclude)src/superqode/harness/pipy_extensions.py",
            ":(exclude)src/superqode/harness/backends/pipy.py",
            ":(exclude)src/superqode/app/mixins/pipy_commands.py",
            ":(exclude)tests/pipy",
            ":(exclude)docs/advanced/pipy.md",
            ":(exclude)NOTICE",
        ).splitlines()
        if line
    }

    expected = {
        # One declared dependency, already present transitively, plus the
        # release version bump. check_release_metadata.py requires these four
        # to agree, so they always move together.
        "pyproject.toml",
        "uv.lock",
        "src/superqode/__init__.py",
        "install/acp-registry/superqode/agent.json",
        "CHANGELOG.md",
        # Registration only.
        "src/superqode/harness/catalog.py",
        "src/superqode/harness/templates.py",
        "src/superqode/harness/backends/registry.py",
        # Two gated behaviour changes, both no-ops for existing harnesses.
        "src/superqode/pure_mode.py",
        # Refuses to run a no-approval harness unattended without an opt in.
        # Only fires for a spec declaring pure_permissions, so nothing else
        # changes.
        "src/superqode/headless.py",
        # A generic, opt-in picker warning field.
        "src/superqode/app/harness_picker.py",
        "src/superqode/app/mixins/commands_impl.py",
        # PiPy added to the :connect harness step, which is a hardcoded list
        # separate from the catalogue that feeds :harness.
        "src/superqode/providers/connection_profiles.py",
        # PiPy is the one harness id whose product name is not the id
        # capitalised, so the label helper needs an override.
        "src/superqode/app/welcome.py",
        # The :connect picker layout. Unrelated to PiPy, requested separately.
        "src/superqode/app/mixins/connect.py",
        "src/superqode/app/mixins/pickers.py",
        "tests/test_tui_smoke.py",
        # Inventory and reference updates required by the coverage tests.
        "docs/getting-started/bring-your-own-harness.md",
        "docs/configuration/environment-variables.md",
        "docs/advanced/harness-system.md",
        "mkdocs.yml",
        "tests/test_tui_smoke.py",
        "tests/test_tui_mounted.py",
        "tests/test_connection_profiles.py",
        "tests/test_connect_harness_screen.py",
        "tests/test_cli_reference_coverage.py",
        "docs/concepts/modes.md",
        # Click-to-run chrome and the discoverable disconnect, requested
        # separately. Additive: a link scheme, a reactive and a sync line.
        "src/superqode/app/mixins/events.py",
        "src/superqode/app/mixins/helper_startup.py",
        "src/superqode/app/mixins/dialogs.py",
        "src/superqode/app/mixins/clickable_commands.py",
        "tests/test_clickable_commands.py",
        "src/superqode/widgets/slash_complete.py",
        "tests/test_connect_harness_screen.py",
        "tests/test_slash_runtime.py",
        "tests/test_status_bar_layout.py",
        # Welcome screen and prompt box polish, requested separately.
        "src/superqode/app/welcome.py",
        "src/superqode/app/css.py",
        "src/superqode/app/inputs.py",
        "src/superqode/app/widgets.py",
        "src/superqode/app/mixins/model_catalog.py",
        "tests/test_catalog_freshness.py",
        # The :pipy command surface. Additive: dispatch, registration, catalogue.
        "src/superqode/app/mixins/slash_commands.py",
        "src/superqode/app_main.py",
        "src/superqode/app/constants.py",
        "docs/advanced/tui.md",
        # NOTICE must reach anyone installing the wheel; LICENSE gained the
        # Apache appendix it was missing.
        "LICENSE",
        "MANIFEST.in",
        # Regenerated artifacts: the agent card carries the version, and the
        # CLI help hash moves when --connect gains a choice.
        "examples/a2a/agent-card.json",
        "tests/test_cli_contract.py",
        "tests/test_a2a_bridge.py",
    }

    unexpected = changed - expected
    assert unexpected == set(), f"unreviewed shared-code changes: {sorted(unexpected)}"


# -- the permission posture -------------------------------------------------- #


def test_pipy_never_imports_the_policy_stack():
    forbidden = {
        "superqode.approval",
        "superqode.permissions",
        "superqode.sandbox",
        "superqode.tools",
        "superqode.agent",
        "superqode.app",
        "textual",
    }
    offenders: list[str] = []

    for path in sorted(PIPY.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module]
            else:
                continue
            for name in names:
                if any(name == bad or name.startswith(f"{bad}.") for bad in forbidden):
                    offenders.append(f"{path.relative_to(PIPY)} imports {name}")

    assert offenders == []


def test_the_template_declares_the_posture_it_has():
    from superqode.harness.templates import pipy_template

    spec = pipy_template()

    assert spec.execution_policy.approval_profile == "none"
    assert spec.execution_policy.sandbox == "none"
    assert spec.metadata["pure_permissions"] is True
    assert "Pure host permissions" in spec.metadata["selection_warning"]


def test_the_adapter_declares_no_approvals():
    from superqode.harness.pipy_adapter import PiPyHarnessProtocolAdapter

    assert PiPyHarnessProtocolAdapter().descriptor.capabilities.approvals is False


def test_the_backend_declares_no_approvals_or_sandbox():
    from superqode.harness.backends.registry import create_harness_backend

    capabilities = create_harness_backend("pipy").capabilities

    assert capabilities.supports_approvals is False
    assert capabilities.supports_sandbox is False


# -- documentation ----------------------------------------------------------- #


def test_the_harness_is_documented():
    doc = (ROOT / "docs" / "advanced" / "pipy.md").read_text(encoding="utf-8")

    assert "Pure host permissions" in doc
    assert "SUPERQODE_PIPY_SESSION_DIR" in doc
    assert "core" in doc, "the escape hatch must be documented"
    assert "MIT" in doc, "attribution must be documented"


def test_the_doc_is_in_the_navigation():
    assert "advanced/pipy.md" in (ROOT / "mkdocs.yml").read_text(encoding="utf-8")


def test_attribution_is_recorded():
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")

    assert "earendil-works/pi" in notice
    assert "Mario Zechner" in notice
    assert "MIT License" in notice


def test_ported_modules_name_their_upstream_file():
    """A reader should be able to find the pi source any module derives from."""
    ported = [
        "loop.py",
        "harness.py",
        "messages.py",
        "events.py",
        "compaction.py",
        "system_prompt.py",
        "skills.py",
        "resources.py",
        "prompt_templates.py",
        "coding_session.py",
        "validation.py",
        "session/session.py",
        "session/jsonl.py",
        "session/entries.py",
        "tools/base.py",
        "tools/truncate.py",
        "tools/edit_diff.py",
        "tools/files.py",
        "tools/shell.py",
        "tools/search.py",
        "ai/transform.py",
    ]
    missing = [
        name
        for name in ported
        if "earendil-works/pi" not in (PIPY / name).read_text(encoding="utf-8")
    ]
    assert missing == []


# -- the harness actually runs ----------------------------------------------- #


async def test_a_full_turn_runs_end_to_end(tmp_path):
    """One prompt, one real tool, one persisted session, no approvals."""
    from conftest import MODEL

    from superqode.pipy import ToolCall, ToolResultMessage
    from superqode.pipy.ai import FakeStream, text_response, tool_response
    from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession

    (tmp_path / "AGENTS.md").write_text("house rules\n")
    script = [
        tool_response(
            ToolCall(id="c1", name="write", arguments={"path": "out.txt", "content": "done\n"})
        ),
        text_response("wrote the file"),
    ]
    stream = FakeStream(script)
    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=stream,
            session_root=tmp_path / ".sessions",
        )
    )

    message = await session.prompt("write out.txt")

    assert message.text == "wrote the file"
    assert (tmp_path / "out.txt").read_text() == "done\n"
    assert "house rules" in stream.calls[0].system_prompt

    reopened = await PiPyCodingSession.resume(
        CodingSessionOptions(cwd=tmp_path, model=MODEL, session_root=tmp_path / ".sessions"),
        session_path=session.session_path,
    )
    context = await reopened.session.build_context()
    assert any(isinstance(m, ToolResultMessage) for m in context.messages)
    assert [m.text for m in context.messages][0] == "write out.txt"


async def test_switching_harnesses_leaves_both_stores_intact(tmp_path):
    """PiPy writes only under its own root."""
    from conftest import MODEL

    from superqode.pipy.ai import FakeStream, text_response
    from superqode.pipy.coding_session import CodingSessionOptions, PiPyCodingSession

    other_store = tmp_path / ".superqode" / "sessions"
    other_store.mkdir(parents=True)
    (other_store / "workbench.jsonl").write_text("untouched\n")

    session = await PiPyCodingSession.create(
        CodingSessionOptions(
            cwd=tmp_path,
            model=MODEL,
            stream_fn=FakeStream([text_response("ok")]),
            session_root=tmp_path / ".pipy-sessions",
        )
    )
    await session.prompt("hi")

    assert (other_store / "workbench.jsonl").read_text() == "untouched\n"
    assert session.session_path.is_relative_to(tmp_path / ".pipy-sessions")


@pytest.mark.parametrize("alias", ["pipy", "pi", "pi-python"])
def test_every_documented_alias_resolves(alias):
    from superqode.harness import resolve_harness

    assert resolve_harness(alias).id == "pipy"
