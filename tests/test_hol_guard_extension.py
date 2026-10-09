from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

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


def test_guard_allows_only_explicitly_benign_commands() -> None:
    allowed = hol_guard.decision_from_guard_payload(
        {"minimum_action": "allow", "classification": {"explicitly_benign": True}}
    )
    assert allowed.action == ALLOW

    unproven_allow = hol_guard.decision_from_guard_payload(
        {"minimum_action": "allow", "classification": {"explicitly_benign": False}}
    )
    assert unproven_allow.action == DENY


def test_guard_blocks_review_monitor_block_and_unknown() -> None:
    for action in ("review", "monitor", "block"):
        decision = hol_guard.decision_from_guard_payload({"minimum_action": action})
        assert decision.action == DENY
    assert hol_guard.decision_from_guard_payload({"minimum_action": "other"}).action == DENY
    assert hol_guard.decision_from_guard_payload(None).action == DENY


def test_guard_invocation_is_shell_free_and_parses_last_json_line(tmp_path: Path) -> None:
    def runner(argv, **kwargs):
        assert argv[:3] == ["hol-guard", "command", "test"]
        assert argv[3] == "printf safe"
        assert argv[4] == "--json"
        assert kwargs["cwd"] == str(tmp_path)
        assert kwargs["capture_output"] is True
        assert kwargs["text"] is True
        assert kwargs["check"] is False
        return subprocess.CompletedProcess(
            argv,
            0,
            stdout='diagnostic\n{"minimum_action":"allow","classification":{"explicitly_benign":true}}\n',
            stderr="",
        )

    decision = hol_guard.evaluate_command("printf safe", tmp_path, runner=runner)
    assert decision.action == ALLOW


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


def test_before_tool_abstains_outside_bash_and_denies_bad_bash_input(tmp_path: Path) -> None:
    class Context:
        working_directory = tmp_path

    assert hol_guard.hol_guard_before_tool(Context(), "read", {"path": "README.md"}) is None
    assert hol_guard.hol_guard_before_tool(Context(), "bash", None).action == DENY
    assert hol_guard.hol_guard_before_tool(Context(), "bash", {}).action == DENY


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
