"""Small editable starting points, sharing one factory runtime."""

import re

TEMPLATE_NAMES = (
    "fix-and-verify",
    "triage-spec-build",
    "continuous-outcomes",
    "build-test-deploy",
    "kanban",
    "scrum",
    "xp",
    "lean",
)


def _stage(stage_id, goal, role, *, depends_on=(), gate=False):
    stage = {"id": stage_id, "goal": goal, "role": role, "harness": "coder"}
    if depends_on:
        stage["depends_on"] = list(depends_on)
        stage["checks"] = ["regression"]
    if gate:
        stage["human_gate"] = True
        stage["checks"] = ["regression"]
    return stage


def _factory(name, description, stages):
    return {
        "apiVersion": "superqode.dev/v1alpha1",
        "kind": "Factory",
        "metadata": {"name": name, "description": description},
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
        "orchestration": {"stages": stages, "acceptance_checks": ["regression"]},
        "access": {"interfaces": ["macos", "cli", "tui", "api"]},
        "governance": {
            "permissions": {
                "allow_read": True,
                "allow_write": True,
                "allow_shell": True,
                "allow_network": False,
            },
            "budget": {"max_workers": 1, "max_seconds": 14400, "max_tool_calls": 400},
            "release": "human",
        },
    }


def factory_template(name="fix-and-verify"):
    if name not in TEMPLATE_NAMES:
        raise ValueError("Choose a built-in factory workflow")
    if name == "triage-spec-build":
        return _factory(
            name,
            "Triage incoming work, gate ambiguous features with a human-approved spec, implement, and verify before shipping.",
            [
                {
                    "id": "triage",
                    "goal": (
                        "Research the request, identify open product or architecture decisions, "
                        "and decide whether a spec with human sign-off is needed before coding. "
                        "End with exactly one line and no Markdown fence. The only output name is "
                        "decision, and complexity, needs-spec, and summary go inside it: "
                        'SUPERQODE_OUTPUT: {"decision":{"complexity":"small","needs-spec":false,"summary":"one sentence"}} '
                        "complexity is small, medium, or large. needs-spec is true or false."
                    ),
                    "role": "investigator",
                    "harness": "coder",
                    "outputs": {
                        "decision": {
                            "type": "json",
                            "fields": {
                                "complexity": {
                                    "type": "string",
                                    "enum": ["small", "medium", "large"],
                                },
                                "needs-spec": {"type": "boolean"},
                                "summary": {"type": "string"},
                            },
                        }
                    },
                },
                {
                    "id": "spec",
                    "goal": (
                        "Ask clarifying questions on open product choices, write the agreed "
                        "product behavior, technical approach, and verification checklist, "
                        "then wait for human approval."
                    ),
                    "role": "investigator",
                    "harness": "coder",
                    "depends_on": ["triage"],
                    "human_gate": True,
                    "inputs": {"triage": {"stage": "triage", "output": "decision"}},
                    "when": {"input": "triage", "field": "needs-spec", "equals": True},
                    "outputs": {"plan": {"type": "text"}},
                },
                {
                    "id": "implement",
                    "goal": (
                        "Implement the bounded change following triage and any approved spec, "
                        "add regression tests, and mitigate merge risks before handoff."
                    ),
                    "role": "implementer",
                    "harness": "coder",
                    "depends_on": ["triage", "spec"],
                    "checks": ["regression"],
                    "inputs": {
                        "triage": {"stage": "triage", "output": "decision"},
                        "spec": {"stage": "spec", "output": "plan", "optional": True},
                    },
                },
                {
                    "id": "verify",
                    "goal": (
                        "Verify behavior with checks and visual proof where applicable, "
                        "summarize impact and rollback cost, and wait for human sign-off."
                    ),
                    "role": "tester",
                    "harness": "coder",
                    "depends_on": ["implement"],
                    "human_gate": True,
                    "checks": ["regression"],
                },
            ],
        )
    if name == "continuous-outcomes":
        return _factory(
            name,
            "Investigate an outcome, deliver a small change and retain feedback.",
            [
                _stage(
                    "investigate",
                    "Clarify the accountable owner's desired outcome and inspect permitted signals.",
                    "investigator",
                ),
                _stage(
                    "implement",
                    "Implement a small change and its regression case.",
                    "implementer",
                    depends_on=["investigate"],
                ),
                _stage(
                    "verify",
                    "Exercise the failing path, report evidence and identify follow-up signals.",
                    "tester",
                    depends_on=["implement"],
                    gate=True,
                ),
            ],
        )
    if name == "build-test-deploy":
        return _factory(
            name,
            "Build the change, test it, and stop before a person releases the deployment.",
            [
                _stage("build", "Produce the change the owner described.", "implementer"),
                _stage(
                    "test",
                    "Run the project checks and record what failed.",
                    "tester",
                    depends_on=["build"],
                ),
                _stage(
                    "deploy",
                    "Prepare the reviewed delivery and wait for a person.",
                    "reviewer",
                    depends_on=["test"],
                    gate=True,
                ),
            ],
        )
    if name == "kanban":
        return _factory(
            name,
            "Move one work item across a Kanban board, from selection to a reviewed finish.",
            [
                _stage("select", "Choose the next item and write its acceptance.", "investigator"),
                _stage(
                    "build",
                    "Implement that item and nothing beyond it.",
                    "implementer",
                    depends_on=["select"],
                ),
                _stage(
                    "review",
                    "Show the change and its check, then wait for a person.",
                    "reviewer",
                    depends_on=["build"],
                    gate=True,
                ),
            ],
        )
    if name == "scrum":
        return _factory(
            name,
            "Run one Scrum slice: refine the goal, build it, review it, and note the next improvement.",
            [
                _stage(
                    "refine", "Turn the sprint goal into one bounded backlog item.", "investigator"
                ),
                _stage(
                    "build",
                    "Implement the item agreed in refinement.",
                    "implementer",
                    depends_on=["refine"],
                ),
                _stage(
                    "review",
                    "Show the increment and wait for a person.",
                    "reviewer",
                    depends_on=["build"],
                    gate=True,
                ),
                _stage(
                    "retro",
                    "Record one improvement for the next slice.",
                    "investigator",
                    depends_on=["review"],
                ),
            ],
        )
    if name == "xp":
        return _factory(
            name,
            "Use an XP loop: name the story, write the check, implement it, then integrate.",
            [
                _stage("story", "Write the story and the example that proves it.", "investigator"),
                _stage(
                    "test",
                    "Add the failing check before the implementation.",
                    "tester",
                    depends_on=["story"],
                ),
                _stage(
                    "implement",
                    "Make that check pass with a small change.",
                    "implementer",
                    depends_on=["test"],
                ),
                _stage(
                    "integrate",
                    "Integrate the change and wait for a person.",
                    "reviewer",
                    depends_on=["implement"],
                    gate=True,
                ),
            ],
        )
    if name == "lean":
        return _factory(
            name,
            "Keep one lean slice: name the value, build only that, check it, then improve the flow.",
            [
                _stage("value", "Name the value this slice must deliver.", "investigator"),
                _stage(
                    "build",
                    "Build only the named value.",
                    "implementer",
                    depends_on=["value"],
                ),
                _stage(
                    "check",
                    "Check the result and wait for a person.",
                    "reviewer",
                    depends_on=["build"],
                    gate=True,
                ),
                _stage(
                    "improve",
                    "Record one waste to remove next time.",
                    "investigator",
                    depends_on=["check"],
                ),
            ],
        )
    return _factory(
        "fix-and-verify",
        "Investigate, implement and verify a small repository fix.",
        [
            _stage(
                "investigate",
                "Reproduce the reported problem and identify a bounded fix.",
                "investigator",
            ),
            _stage(
                "implement",
                "Implement a small change and its regression case.",
                "implementer",
                depends_on=["investigate"],
            ),
            _stage(
                "verify",
                "Exercise the failing path, report evidence and identify follow-up signals.",
                "tester",
                depends_on=["implement"],
                gate=True,
            ),
        ],
    )


def explicit_workflow(description):
    """Return a workflow the description names, or an empty string."""
    words = set(re.findall(r"[a-z0-9]+", description.casefold()))
    if "triage" in words or "spec" in words:
        return "triage-spec-build"
    if "kanban" in words:
        return "kanban"
    if "scrum" in words or "sprint" in words:
        return "scrum"
    if "xp" in words or {"extreme", "programming"} <= words:
        return "xp"
    if "lean" in words:
        return "lean"
    if "deploy" in words or {"build", "test"} <= words:
        return "build-test-deploy"
    return ""


def workflow_for_description(description):
    """Pick a built-in workflow from the words the user already wrote."""
    return explicit_workflow(description) or "fix-and-verify"


def compose_from_description(description, workflow=""):
    text = " ".join(description.split())
    if not text or len(text) > 8000:
        raise ValueError("Describe the factory in 8,000 characters or fewer")
    named = explicit_workflow(text)
    if named:
        choice = named
    elif workflow in TEMPLATE_NAMES:
        choice = workflow
    else:
        choice = "fix-and-verify"
    data = factory_template(choice)
    data["metadata"]["description"] = text[:500]
    return data


def workflow_catalog():
    """Name, summary and stage ids for every built-in starter."""
    rows = []
    for name in TEMPLATE_NAMES:
        data = factory_template(name)
        rows.append(
            {
                "name": name,
                "summary": data["metadata"]["description"],
                "stages": [stage["id"] for stage in data["orchestration"]["stages"]],
            }
        )
    return rows
