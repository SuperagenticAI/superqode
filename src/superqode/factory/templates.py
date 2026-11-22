"""Small editable starting points, sharing one factory runtime."""


def factory_template(name="fix-and-verify"):
    if name not in {"fix-and-verify", "continuous-outcomes"}:
        raise ValueError("Choose Fix and verify or Continuous outcomes")
    outcome = name == "continuous-outcomes"
    return {
        "apiVersion": "superqode.dev/v1alpha1",
        "kind": "Factory",
        "metadata": {
            "name": name,
            "description": "Investigate an outcome, deliver a small change and retain feedback."
            if outcome
            else "Investigate, implement and verify a small repository fix.",
        },
        "default_route": "no-subscription",
        "data_context": {"repository": ".", "files": {}},
        "compute": {"runner": "worktree"},
        "inference": {"harnesses": {"coder": {"template": "core", "model": "ollama/qwen3-coder"}}},
        "improvement": {
            "checks": {"regression": {"command": "python -m pytest -q", "files": []}},
            "optimization": {
                "automatic_experiments": False,
                "editable": ["skills", "harnesses", "routes", "workflow"],
                "protected": [
                    "governance",
                    "improvement.checks",
                    "orchestration.acceptance_checks",
                ],
            },
        },
        "orchestration": {
            "stages": [
                {
                    "id": "investigate",
                    "goal": "Clarify the accountable owner's desired outcome and inspect permitted signals."
                    if outcome
                    else "Reproduce the reported problem and identify a bounded fix.",
                    "role": "investigator",
                    "harness": "coder",
                },
                {
                    "id": "implement",
                    "goal": "Implement a small change and its regression case.",
                    "role": "implementer",
                    "harness": "coder",
                    "depends_on": ["investigate"],
                    "checks": ["regression"],
                },
                {
                    "id": "verify",
                    "goal": "Exercise the failing path, report evidence and identify follow-up signals.",
                    "role": "tester",
                    "harness": "coder",
                    "depends_on": ["implement"],
                    "human_gate": True,
                    "checks": ["regression"],
                },
            ],
            "acceptance_checks": ["regression"],
        },
        "access": {"interfaces": ["macos", "cli", "tui", "api"]},
        "governance": {
            "permissions": {
                "allow_read": True,
                "allow_write": True,
                "allow_shell": True,
                "allow_network": False,
            },
            "budget": {"max_workers": 1, "max_seconds": 1800, "max_tool_calls": 100},
            "release": "human",
        },
    }
