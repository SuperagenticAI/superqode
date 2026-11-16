"""Picker fields on desktop harness rows: profile, source and Apple compatibility."""

import textwrap

from test_desktop_service import desktop  # noqa: F401

DEMO = textwrap.dedent(
    """\
    version: 1
    name: silicon-demo
    inherits: silicon
    description: Project harness that extends Silicon.
    checks:
      enabled: true
      custom_steps:
        - name: verify
          command: python3 -c "print('ok')"
    """
)

USER = textwrap.dedent(
    """\
    version: 1
    name: my-core
    inherits: core
    description: A user harness.
    """
)


def _rows(service, method, project):
    return {row["id"]: row for row in service.dispatch(method, {"project": project["id"]})}


def test_harnesses_list_marks_project_user_and_builtin_sources(desktop, tmp_path, monkeypatch):
    service, project, root = desktop
    home = tmp_path / "home"
    (home / ".superqode" / "harnesses").mkdir(parents=True)
    (home / ".superqode" / "harnesses" / "my-core.yaml").write_text(USER)
    monkeypatch.setenv("HOME", str(home))
    (root / "harness.yaml").write_text(DEMO)

    rows = _rows(service, "harnesses.list", project)

    demo = rows["silicon-demo"]
    assert demo["source"] == "project"
    assert demo["profile"] == "silicon"
    assert demo["apple_compatible"] is True
    assert demo["based_on"] == "silicon"
    assert demo["based_on_name"] == "Silicon Harness"
    assert demo["path"] == str(root / "harness.yaml")

    assert rows["my-core"]["source"] == "user"
    assert rows["my-core"]["based_on_name"] == "Core"
    assert rows["my-core"]["apple_compatible"] is False

    assert rows["silicon"]["source"] == "built-in"
    assert rows["silicon"]["apple_compatible"] is True
    assert rows["apple-local"]["apple_compatible"] is True
    assert rows["core"]["source"] == "built-in"
    assert rows["core"]["profile"] == "core"
    assert rows["core"]["apple_compatible"] is False
    assert rows["core"]["based_on"] == ""
    assert rows["core"]["path"] is None


def test_local_model_harnesses_include_project_silicon_harness(desktop, tmp_path, monkeypatch):
    service, project, root = desktop
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    (root / ".superqode" / "harnesses").mkdir(parents=True)
    (root / ".superqode" / "harnesses" / "silicon-demo.yaml").write_text(DEMO)

    rows = _rows(service, "local.models.harnesses", project)

    demo = rows["silicon-demo"]
    assert demo["selectable"] is True
    assert demo["source"] == "project"
    assert demo["apple_compatible"] is True
    assert demo["based_on_name"] == "Silicon Harness"
    assert demo["path"].endswith("silicon-demo.yaml")
    assert rows["silicon"]["apple_compatible"] is True
    assert rows["core"]["apple_compatible"] is False
    assert all("profile" in row and "source" in row for row in rows.values())
