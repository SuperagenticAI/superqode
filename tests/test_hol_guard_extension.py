from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess

import pytest

from superqode.agent.hooks import ALLOW, DENY


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = (
    ROOT
    / "examples"
    / "extensions"
    / "packages"
    / "hol-guard-extension"
    / "src"
    / "superqode_hol_guard"
    / "__init__.py"
)
spec = importlib.util.spec_from_file_location("superqode_hol_guard_fixture", MODULE_PATH)
assert spec is not None and spec.loader is not None
hol_guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hol_guard)


@pytest.fixture(autouse=True)
def _use_fixed_guard_path_for_stub_runner_tests(monkeypatch):
    """Stubbed CLI tests use a predictable resolved executable path."""
    monkeypatch.delenv("HOL_GUARD_BIN", raising=False)
    real_which = hol_guard.shutil.which
    monkeypatch.setattr(
        hol_guard.shutil, "which",
        lambda name: "/__hol_guard_test__/bin/hol-guard" if name == "hol-guard" else real_which(name),
    )


def test_guard_allows_only_explicitly_benign_commands() -> None:
    allowed = hol_guard.decision_from_guard_payload(
        {"minimum_action": "allow", "classification": {"explicitly_benign": True}}
    )
    assert allowed.action == ALLOW

    unproven_allow = hol_guard.decision_from_guard_payload(
        {"minimum_action": "allow", "classification": {"explicitly_benign": False}}
    )
    assert unproven_allow.action == DENY


def test_inspection_only_status_allows_only_explicitly_benign_commands() -> None:
    """Command inspection can be safe without evaluating a runtime policy."""
    allow = {
        "policy_action": "not_run",
        "minimum_action": "allow",
        "classification": {"explicitly_benign": True},
    }
    assert hol_guard.decision_from_guard_payload(allow).action == ALLOW

    for unsafe in (
        {"minimum_action": "review"},
        {"classification": {"explicitly_benign": False}},
        {"continue": False},
        {"decision": "deny"},
        {"hookSpecificOutput": {"permissionDecision": "deny"}},
        {"policy_action": "warn"},
        {"policy_action": "not_run "},
    ):
        assert hol_guard.decision_from_guard_payload({**allow, **unsafe}).action == DENY


def test_guard_blocks_review_monitor_block_and_unknown() -> None:
    for action in ("review", "monitor", "block"):
        decision = hol_guard.decision_from_guard_payload({"minimum_action": action})
        assert decision.action == DENY
    assert hol_guard.decision_from_guard_payload({"minimum_action": "other"}).action == DENY
    assert hol_guard.decision_from_guard_payload(None).action == DENY


def test_guard_explicit_deny_overrides_benign_classification() -> None:
    """An explicit stop signal cannot be overridden by an allow-shaped classifier."""
    for stopped in (
        {"continue": False},
        {"continue": "false"},
        {"continue": 0},
        {"decision": "deny"},
        {"decision": "review"},
        {"decision": "block"},
        {"decision": ""},
        {"decision": None},
        {"policy_action": None},
        {"policy_action": []},
        {"policy_action": {}},
        {"policy_action": "review"},
        {"policy_action": "block"},
        {"hookSpecificOutput": {"permissionDecision": "deny"}},
        {"hookSpecificOutput": {"permissionDecision": "ask"}},
        {"hookSpecificOutput": {"permissionDecision": "allow", "hookEventName": "PostToolUse"}},
        {"hookSpecificOutput": "malformed"},
        {"hookSpecificOutput": None},
    ):
        payload = {
            "minimum_action": "allow",
            "classification": {"explicitly_benign": True},
            **stopped,
        }
        assert hol_guard.decision_from_guard_payload(payload).action == DENY


def test_guard_invocation_is_shell_free_and_parses_single_json_line(tmp_path: Path) -> None:
    def runner(argv, **kwargs):
        assert argv == ["/__hol_guard_test__/bin/hol-guard", "command", "test", "--json", "--", "printf safe"]
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='{"minimum_action":"allow","classification":{"explicitly_benign":true}}\n',
            stderr="",
        )

    decision = hol_guard.evaluate_command("printf safe", tmp_path, runner=runner)
    assert decision.action == ALLOW



def test_guard_rejects_conflicting_machine_verdicts(tmp_path: Path) -> None:
    """A diagnostic or echoed JSON line must not override a deny verdict."""
    allowed = '{"minimum_action":"allow","classification":{"explicitly_benign":true}}'
    denied = '{"minimum_action":"review","classification":{"explicitly_benign":false}}'
    for stdout in (f"{denied}\n{allowed}", f"{allowed}\n{denied}", f"{allowed}\n{allowed}", f"diagnostic\n{allowed}", f"{allowed}\ndiagnostic"):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        decision = hol_guard.evaluate_command("echo guarded", tmp_path, runner=runner)
        assert decision.action == DENY


def test_guard_keeps_option_like_quoted_and_multiline_text_positional(tmp_path: Path) -> None:
    for command in ("-n", 'printf "%s" "two words"', "printf 'one\ntwo'"):
        captured = []

        def runner(argv, **kwargs):
            captured.append(argv)
            assert kwargs["cwd"] == str(tmp_path)
            assert kwargs["check"] is False
            return subprocess.CompletedProcess(
                argv,
                0,
                stdout='{"minimum_action":"allow","classification":{"explicitly_benign":true}}',
                stderr="",
            )

        decision = hol_guard.evaluate_command(command, tmp_path, runner=runner)
        assert decision.action == ALLOW
        assert captured == [["/__hol_guard_test__/bin/hol-guard", "command", "test", "--json", "--", command]]


def test_guard_process_failures_deny(tmp_path: Path) -> None:
    def nonzero(argv, **kwargs):
        return subprocess.CompletedProcess(argv, 7, stdout="", stderr="failed")

    assert hol_guard.evaluate_command("echo x", tmp_path, runner=nonzero).action == DENY

    def timeout(argv, **kwargs):
        raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

    assert hol_guard.evaluate_command("echo x", tmp_path, runner=timeout).action == DENY

    def missing(argv, **kwargs):
        raise FileNotFoundError("hol-guard")

    assert hol_guard.evaluate_command("echo x", tmp_path, runner=missing).action == DENY

    def invalid_argv(argv, **kwargs):
        raise ValueError("embedded null byte")

    assert hol_guard.evaluate_command("echo x", tmp_path, runner=invalid_argv).action == DENY

    def invalid_decode(argv, **kwargs):
        raise UnicodeDecodeError("utf-8", b"\xff", 0, 1, "invalid start byte")

    assert hol_guard.evaluate_command("echo x", tmp_path, runner=invalid_decode).action == DENY
    # Real subprocess argument validation, not a mocked runner.
    assert hol_guard.evaluate_command("echo \x00unsafe", tmp_path).action == DENY


def test_before_tool_abstains_outside_bash_and_denies_bad_bash_input(tmp_path: Path) -> None:
    class Context:
        working_directory = tmp_path

    assert hol_guard.hol_guard_before_tool(Context(), "read", {"path": "README.md"}) is None
    assert hol_guard.hol_guard_before_tool(Context(), "bash", None).action == DENY
    assert hol_guard.hol_guard_before_tool(Context(), "bash", {}).action == DENY


@pytest.mark.parametrize("tool_name", [None, "", "   ", 42, [], {}])
def test_before_tool_denies_missing_or_malformed_tool_identity(tool_name, tmp_path: Path) -> None:
    class Context:
        working_directory = tmp_path

    result = hol_guard.hol_guard_before_tool(
        Context(), tool_name, {"command": "git status"}
    )
    assert result is not None
    assert result.action == DENY
    assert result.reason == "HOL Guard gate input failure"


def test_before_tool_inspects_exact_bash_input(monkeypatch, tmp_path: Path) -> None:
    class Context:
        working_directory = tmp_path

    # The shell receives these bytes verbatim. Guard must inspect the same bytes.
    command = "  cat <<\'EOF\'\nexample\nEOF\n"
    received = []

    def fake_evaluate(value, cwd):
        received.append((value, cwd))
        return hol_guard.HookDecision(action=ALLOW)

    monkeypatch.setattr(hol_guard, "evaluate_command", fake_evaluate)
    decision = hol_guard.hol_guard_before_tool(Context(), "bash", {"command": command})
    assert decision.action == ALLOW
    assert received == [(command, tmp_path)]

def test_before_tool_inspects_in_bash_effective_working_dir(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    nested = project / "nested"
    nested.mkdir(parents=True)

    class Context:
        working_directory = project

    received = []

    def fake_evaluate(command, cwd):
        received.append((command, cwd))
        return hol_guard.HookDecision(action=ALLOW)

    monkeypatch.setattr(hol_guard, "evaluate_command", fake_evaluate)
    explicit = hol_guard.hol_guard_before_tool(
        Context(), "bash", {"command": "cat settings.json", "working_dir": "nested"}
    )
    implicit = hol_guard.hol_guard_before_tool(
        Context(), "bash", {"command": "pwd"}
    )

    assert explicit.action == ALLOW
    assert implicit.action == ALLOW
    assert received == [
        ("cat settings.json", nested.resolve()),
        ("pwd", project.resolve()),
    ]


def test_before_tool_denies_out_of_scope_bash_working_dir(monkeypatch, tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()

    class Context:
        working_directory = project

    def must_not_inspect(*_args, **_kwargs):
        pytest.fail("Guard must not inspect a command in a different directory")

    monkeypatch.setattr(hol_guard, "evaluate_command", must_not_inspect)
    for invalid in ("../outside", str(tmp_path / "outside"), 42):
        result = hol_guard.hol_guard_before_tool(
            Context(), "bash", {"command": "cat settings.json", "working_dir": invalid}
        )
        assert result.action == DENY


def test_before_tool_converts_unexpected_adapter_failure_to_deny(
    monkeypatch, tmp_path: Path
) -> None:
    class Context:
        working_directory = tmp_path

    def boom(*args, **kwargs):
        raise RuntimeError("unexpected")

    monkeypatch.setattr(hol_guard, "evaluate_command", boom)
    decision = hol_guard.hol_guard_before_tool(Context(), "bash", {"command": "echo x"})
    assert decision.action == DENY


def test_guard_rejects_duplicate_machine_verdicts(tmp_path: Path) -> None:
    """A repeated member must not replace an earlier stop with a benign allow."""
    for stdout in (
        '{"minimum_action":"review","minimum_action":"allow","classification":{"explicitly_benign":true}}',
        '{"minimum_action":"allow","classification":{"explicitly_benign":false,"explicitly_benign":true}}',
        '{"continue":false,"continue":true,"minimum_action":"allow","classification":{"explicitly_benign":true}}',
    ):
        def runner(argv, **kwargs):
            return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr="")

        result = hol_guard.evaluate_command("git status", tmp_path, runner=runner)
        assert result.action == DENY



@pytest.mark.skipif(os.name == "nt", reason="POSIX executable script fixture")
def test_real_guard_subprocess_blocks_launch_and_review(tmp_path: Path) -> None:
    """Run a fake CLI process to verify the actual subprocess boundary."""
    fake_guard = tmp_path / "hol-guard"
    fake_guard.write_text(
        "#!/usr/bin/env python3\n"
        "import json, sys\n"
        "if sys.argv[1:] == ['command', 'test', '--json', '--', 'git status']:\n"
        "    print(json.dumps({'minimum_action': 'allow', "
        "'classification': {'explicitly_benign': True}}))\n"
        "else:\n"
        "    print(json.dumps({'minimum_action': 'review', "
        "'classification': {'explicitly_benign': False}}))\n"
    )
    fake_guard.chmod(0o755)

    # The test command travels as argv to the fake CLI; no shell runs it.
    safe = hol_guard.evaluate_command("git status", tmp_path, binary=str(fake_guard))
    risky = hol_guard.evaluate_command(
        "rm -rf /tmp/hol-guard-fixture-never-run", tmp_path, binary=str(fake_guard)
    )
    assert safe.action == ALLOW
    assert risky.action == DENY

    # The real operating system refuses launch, and the gate must deny.
    fake_guard.chmod(0o644)
    unavailable = hol_guard.evaluate_command("git status", tmp_path, binary=str(fake_guard))
    assert unavailable.action == DENY


def test_binary_lookup_is_bound_before_changing_working_directory(
    monkeypatch, tmp_path: Path
) -> None:
    """A relative PATH entry must not point to a new binary in the tool cwd."""
    previous_dir_binary = "./bin/hol-guard"
    expected_binary = os.path.realpath(previous_dir_binary)
    seen = {}

    monkeypatch.setattr(hol_guard.shutil, "which", lambda name: previous_dir_binary)

    def runner(argv, **kwargs):
        seen["argv"] = argv
        seen["cwd"] = kwargs["cwd"]
        return subprocess.CompletedProcess(
            argv, 0,
            stdout='{"minimum_action":"allow","classification":{"explicitly_benign":true}}',
            stderr="",
        )

    decision = hol_guard.evaluate_command("pwd", tmp_path, runner=runner)
    assert decision.action == ALLOW
    assert seen["argv"][0] == expected_binary
    assert seen["cwd"] == str(tmp_path)


def test_missing_binary_lookup_blocks_without_launch(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(hol_guard.shutil, "which", lambda name: None)

    def never_run(argv, **kwargs):
        pytest.fail("Unresolved Guard executable must never run")

    decision = hol_guard.evaluate_command("pwd", tmp_path, runner=never_run)
    assert decision.action == DENY
    assert decision.reason == "HOL Guard gate launch failure"
