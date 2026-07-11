from superqode.harness import DEFAULT_HARNESS_ID, list_harnesses, resolve_harness


def test_catalogue_has_core_default_and_preserved_workbench(tmp_path):
    entries = {entry.id: entry for entry in list_harnesses(tmp_path)}

    assert DEFAULT_HARNESS_ID == "core"
    assert entries["core"].default is True
    assert entries["core"].tools == ("read", "write", "edit", "bash")
    assert entries["workbench"].default is False
    assert "patch" in entries["workbench"].tools
    assert len(entries["workbench"].tools) > len(entries["core"].tools)


def test_catalogue_resolves_compatibility_aliases(tmp_path):
    assert resolve_harness("minimal", root=tmp_path).id == "core"
    assert resolve_harness("native", root=tmp_path).id == "workbench"
    assert resolve_harness("coding", root=tmp_path).id == "workbench"
