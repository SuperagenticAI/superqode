"""Connection descriptions respect route ownership and negotiated support."""

from types import SimpleNamespace

import pytest

from superqode.app.connection_capabilities import connection_capabilities, profile_capabilities
from superqode.runtime.codex_capabilities import CodexCapabilities


def states(**kwargs):
    return {row.label: row.state for row in connection_capabilities(**kwargs)}


@pytest.mark.parametrize(
    "caps,resume",
    [(None, "Not negotiated"), ({}, "Context replay"), ({"loadSession": True}, "Advertised")],
)
def test_acp_does_not_inherit_native_controls(caps, resume):
    values = states(connector="acp", runtime="builtin", acp_capabilities=caps)
    assert values["Continue"] == resume
    assert values["Live steering"] == "Unavailable"
    assert values["Compaction"] == "Agent-owned"


def test_codex_unknown_and_unsupported_are_distinct():
    assert states(runtime="codex-cli", codex=CodexCapabilities())["Fork"] == "Not verified"
    installed = CodexCapabilities(methods={"thread/resume": {}, "turn/steer": {}})
    values = states(runtime="codex-cli", codex=installed)
    assert values["Continue"] == values["Live steering"] == "Supported"
    assert values["Fork"] == values["Compaction"] == "Unavailable"


@pytest.mark.parametrize("connector", ["byok", "local"])
def test_model_source_does_not_override_selected_harness(connector):
    assert states(connector=connector, runtime="another-sdk")["Compaction"] == "Harness-owned"
    assert states(connector=connector, runtime="builtin")["Compaction"] == "SuperQode"


def test_external_cli_is_not_presented_as_host_supervised():
    rows = connection_capabilities(connector="external-cli", runtime="builtin")
    assert all(row.state == "Vendor-owned" for row in rows)


def test_builtin_backend_without_native_loop_does_not_claim_native_controls():
    values = states(runtime="builtin", native_loop=False)
    assert values["Live steering"] == "Unavailable"
    assert values["Compaction"] == "Harness-owned"


def test_model_picker_explains_harness_is_retained():
    rows = profile_capabilities(SimpleNamespace(connector="local", runtime="builtin"))
    assert rows[0].state == "Selected harness"


@pytest.mark.parametrize("connector", ["acp-picker", "harness-picker", "protocols-menu"])
def test_navigation_profiles_do_not_claim_execution_capabilities(connector):
    assert profile_capabilities(SimpleNamespace(connector=connector)) == ()
