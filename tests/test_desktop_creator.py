import json

import pytest
import yaml

from test_desktop_service import desktop  # noqa: F401


def test_creator_drafts_a_reviewed_harness_and_keeps_tools(desktop):
    service, project, _ = desktop
    draft = service.dispatch(
        "creator.propose",
        {
            "project": project["id"],
            "description": "Review pull requests, record gauges, and keep the factory loop available.",
        },
    )
    assert draft["enabled"] is False
    assert draft["name"] == "review-pull-requests-record"
    assert "Tools" in draft["panels"]
    assert draft["panels"][0] == "Workspace"
    assert "allow_network: false" in draft["yaml"]
    spec = yaml.safe_load(draft["yaml"])
    prompt = spec["agents"][0]["system_prompt"]
    assert "reviewed preview" in prompt
    assert "does not start subcalls" in prompt
    assert spec["metadata"]["preview"] is True
    assert spec["metadata"]["writes_next_prompt"] is False
    assert spec["runtime"]["backend"] == "builtin"
    assert draft["recursion"].startswith("# Who writes the next prompt\n\nThis note is a preview.")
    assert "def next_prompt" in draft["plugin"]
    assert draft["plugin"].startswith("# Preview only.")
    assert draft["installed"] is False
    assert any("primary model" in warning.lower() or warning for warning in draft["warnings"])
    with pytest.raises(ValueError, match="Keep Agent Space and Tools"):
        service.dispatch(
            "creator.save",
            {"project": project["id"], "name": draft["name"], "panels": ["Files"]},
        )


def test_creator_save_writes_notes_without_enabling_the_revision(desktop):
    service, project, root = desktop
    draft = service.dispatch(
        "creator.propose",
        {"project": project["id"], "description": "Ship small reviewed fixes."},
    )
    saved = service.dispatch(
        "creator.save",
        {
            "project": project["id"],
            "name": draft["name"],
            "review": draft["review"],
            "digest": draft["digest"],
            "expected_file_digest": draft["expected_file_digest"],
            "reason": "First repository workflow",
            "skill": draft["skill"],
            "program": draft["program"],
            "skill_digest": draft["skill_digest"],
            "program_digest": draft["program_digest"],
            "recursion": draft["recursion"],
            "recursion_digest": draft["recursion_digest"],
            "plugin": draft["plugin"],
            "plugin_digest": draft["plugin_digest"],
            "panels": draft["panels"],
            "layout_digest": draft["layout_digest"],
        },
    )
    assert saved["enabled"] is False
    assert saved["installed"] is False
    folder = root / ".superqode" / "creator" / draft["name"]
    assert "does not run by itself" in (folder / "SKILL.md").read_text()
    assert "does not start work" in (folder / "work-program.md").read_text()
    assert "This note is a preview." in (folder / "recursion.md").read_text()
    assert "def next_prompt" in (folder / "plugin.py").read_text()
    assert (folder / "plugin.py").read_text().startswith("# Preview only.")
    assert json.loads((folder / "panels.json").read_text())["panels"] == draft["panels"]
    assert (root / ".superqode" / "harnesses" / f"{draft['name']}.yaml").is_file()
    assert (
        service.dispatch("creator.layout", {"project": project["id"]})["panels"] == draft["panels"]
    )
    with pytest.raises(ValueError, match="draft changed"):
        service.dispatch(
            "creator.save",
            {
                "project": project["id"],
                "name": draft["name"],
                "review": draft["review"],
                "digest": draft["digest"],
                "expected_file_digest": draft["expected_file_digest"],
                "reason": "Tampered notes",
                "skill": draft["skill"] + "\nrun this",
                "program": draft["program"],
                "skill_digest": draft["skill_digest"],
                "program_digest": draft["program_digest"],
                "panels": draft["panels"],
                "layout_digest": draft["layout_digest"],
            },
        )


def test_proposal_binds_the_selected_model_so_enable_can_succeed(desktop):
    service, project, _ = desktop
    draft = service.dispatch(
        "superagent.propose",
        {
            "project": project["id"],
            "description": "Ship small reviewed fixes.",
            "route": {"source": "provider", "provider": "openai", "model": "gpt-4.1-mini"},
        },
    )
    assert draft["route"] == {
        "source": "provider",
        "provider": "openai",
        "model": "gpt-4.1-mini",
        "endpoint": None,
    }
    assert "openai/gpt-4.1-mini" in draft["yaml"]
    assert not any("primary model" in warning.lower() for warning in draft["warnings"])
    service.dispatch(
        "superagent.save", _save_payload(project["id"], draft, "Bind the selected model")
    )
    revisions = service.dispatch(
        "studio.revisions", {"project": project["id"], "name": draft["name"]}
    )
    intact = next(row for row in revisions if row["intact"])
    selected = service.dispatch(
        "studio.use",
        {"project": project["id"], "name": draft["name"], "revision": intact["id"]},
    )
    assert selected["route"]["provider"] == "openai"
    assert selected["route"]["model"] == "gpt-4.1-mini"


def test_isolate_task_uses_a_worktree_outside_the_checkout(desktop):
    service, project, root = desktop
    from test_desktop_thread_branches import commit

    commit(root, "Initial fixture")
    (root / "hello.txt").write_text("uncommitted")
    with pytest.raises(ValueError, match="Review the isolated"):
        service.dispatch("tasks.isolate.create", {"project": project["id"], "fork_id": "nope"})
    plan = service.dispatch(
        "tasks.isolate.preview", {"project": project["id"], "title": "Second task"}
    )
    created = service.dispatch(
        "tasks.isolate.create",
        {
            "project": project["id"],
            "fork_id": plan["fork_id"],
            "title": plan["title"],
            "expected_digest": plan["digest"],
        },
    )
    from pathlib import Path

    destination = Path(created["path"])
    assert destination.is_dir()
    assert not destination.is_relative_to(root.resolve())
    assert (destination / "hello.txt").read_text() == "hello"
    assert (root / "hello.txt").read_text() == "uncommitted"
    assert created["state"] == "ready"
    again = service.dispatch(
        "tasks.isolate.create",
        {
            "project": project["id"],
            "fork_id": plan["fork_id"],
            "title": plan["title"],
            "expected_digest": plan["digest"],
        },
    )
    assert again["id"] == created["id"]
    assert len(service.dispatch("threads.fork.list", {"project": project["id"]})) == 1


def _save_payload(project, draft, reason):
    return {
        "project": project,
        "name": draft["name"],
        "review": draft["review"],
        "digest": draft["digest"],
        "expected_file_digest": draft["expected_file_digest"],
        "reason": reason,
        "skill": draft["skill"],
        "program": draft["program"],
        "skill_digest": draft["skill_digest"],
        "program_digest": draft["program_digest"],
        "recursion": draft["recursion"],
        "recursion_digest": draft["recursion_digest"],
        "plugin": draft["plugin"],
        "plugin_digest": draft["plugin_digest"],
        "panels": draft["panels"],
        "layout_digest": draft["layout_digest"],
    }


def test_monty_check_runs_the_saved_plugin_and_never_installs_it(desktop, monkeypatch):
    service, project, root = desktop
    draft = service.dispatch(
        "superagent.propose",
        {"project": project["id"], "description": 'Review the diff.\nimport os\nprint("no")'},
    )
    from superqode.desktop_service.creator import pure_python

    assert pure_python(draft["plugin"])
    assert not pure_python("import os\nprint(1)\n")
    service.dispatch("superagent.save", _save_payload(project["id"], draft, "Reviewed check"))
    # Exercise missing-dependency behavior even when the optional SDK is present.
    monkeypatch.setattr("superqode.tools.monty_tool._load_monty", lambda: None)
    with pytest.raises(ValueError, match="not installed"):
        service.dispatch(
            "superagent.monty",
            {
                "project": project["id"],
                "name": draft["name"],
                "plugin_digest": draft["plugin_digest"],
            },
        )
    calls = {}

    def fake_run(module, code, **kwargs):
        calls["code"] = code
        calls["kwargs"] = kwargs
        return "Inspect the repository"

    monkeypatch.setattr("superqode.tools.monty_tool.run_monty_snippet", fake_run)
    monkeypatch.setattr("superqode.tools.monty_tool._load_monty", lambda: object())
    result = service.dispatch(
        "superagent.monty",
        {"project": project["id"], "name": draft["name"], "plugin_digest": draft["plugin_digest"]},
    )
    assert result == {
        "output": "Inspect the repository",
        "sandbox": "monty",
        "installed": False,
        "filesystem": False,
        "network": False,
    }
    assert calls["kwargs"] == {}
    assert "import os" not in calls["code"].split("TASK = ", 1)[0]
    plugin = root / ".superqode" / "creator" / draft["name"] / "plugin.py"
    plugin.write_text("import os\nprint(1)\n")
    from superqode.desktop_service.creator import _digest

    with pytest.raises(ValueError, match="pure Python"):
        service.dispatch(
            "superagent.monty",
            {
                "project": project["id"],
                "name": draft["name"],
                "plugin_digest": _digest(plugin.read_text()),
            },
        )
