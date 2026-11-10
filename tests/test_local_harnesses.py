"""Advanced launcher boundaries. All model/agent traffic uses mocks or local fixtures."""

import hashlib
import json
from pathlib import Path
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import SimpleNamespace

import pytest

from test_desktop_service import desktop, wait_job  # noqa: F401
from superqode.desktop_service import local_harnesses as lh
from superqode.local import context_contract as cc
from superqode.local.hardware import HardwareProfile

MODEL = "fixture-model"
META = {"size_bytes": 4 * 1024**3, "max_context_length": 8192}


@pytest.fixture
def loaded(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("SUPERQODE_LOCAL_CONTEXT_CONTRACT", raising=False)
    monkeypatch.setattr(
        lh,
        "detect_hardware",
        lambda: HardwareProfile(platform="darwin", is_apple_silicon=True, unified_memory_gb=32),
    )
    monkeypatch.setattr(lh, "read_metadata", lambda *args: META)
    monkeypatch.setattr(lh, "requested_context", lambda *args: 8192)
    monkeypatch.setattr(lh.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(
        lh.subprocess,
        "run",
        lambda argv, **kwargs: SimpleNamespace(
            returncode=0, stdout="goose 1.58.0\n" if argv[0].endswith("goose") else "1.19.5\n"
        ),
    )

    def get(url):
        if url.endswith("/api/ps"):
            return {"models": [{"name": MODEL, "context_length": 8192}]}
        if url.endswith("/api/v1/models"):
            return {
                "models": [
                    {
                        "key": "qwen3.5:4b",
                        **META,
                        "loaded_instances": [{"id": MODEL, "config": {"context_length": 8192}}],
                    }
                ]
            }
        if url.endswith("/v1/models"):
            return {"data": [{"id": MODEL}]}
        raise AssertionError(url)

    monkeypatch.setattr(lh, "_get", get)
    return get


def params(project, harness="superqode", engine="ollama"):
    return {"project": project["id"], "harness": harness, "engine": engine, "model": MODEL}


@pytest.mark.parametrize("engine", ["ollama", "lmstudio"])
@pytest.mark.parametrize("harness", ["superqode", "opencode", "goose"])
def test_generators_use_exact_local_endpoint_and_contract(desktop, loaded, engine, harness):
    service, project, _ = desktop
    plan = service.dispatch("local.harnesses.preflight", params(project, harness, engine))
    assert plan["ready"], plan
    config, contract = plan["config"], plan["contract"]
    assert contract["context"] <= contract["actual_context"] == 8192
    assert contract["max_tokens"] <= contract["context"] // 4
    assert contract["fit"]["rating"] == "Fits"
    env = config["env"]
    if harness == "opencode":
        payload = json.loads(env["OPENCODE_CONFIG_CONTENT"])
        assert payload["model"] == payload["small_model"] == "sq-local/" + MODEL
        assert payload["enabled_providers"] == ["sq-local"]
        provider = payload["provider"]["sq-local"]
        assert provider["options"]["baseURL"] == lh.ENDPOINTS[engine]
        assert provider["models"][MODEL]["limit"] == {
            "context": contract["context"],
            "output": contract["max_tokens"],
        }
        assert provider["models"][MODEL]["tool_call"] is True
        assert payload["permission"] == "ask"
    elif harness == "goose":
        assert env["GOOSE_PROVIDER"] == env["GOOSE_SUBAGENT_PROVIDER"] == engine
        host_key = "OLLAMA_HOST" if engine == "ollama" else "LMSTUDIO_HOST"
        assert env[host_key] + "/v1" == lh.ENDPOINTS[engine]
        assert "OPENAI_HOST" not in env and "OPENAI_API_KEY" not in env
        if engine == "ollama":
            assert int(env["GOOSE_INPUT_LIMIT"]) == contract["context"]
        else:
            assert "GOOSE_INPUT_LIMIT" not in env
        assert env["GOOSE_MODEL"] == env["GOOSE_SUBAGENT_MODEL"] == MODEL
        assert int(env["GOOSE_CONTEXT_LIMIT"]) == contract["context"]
        assert int(env["GOOSE_MAX_TOKENS"]) == contract["max_tokens"]
        assert env["GOOSE_MODE"] == "approve"
        assert env["GOOSE_TOOLSHIM"] == "false"
    else:
        assert config["model"] == MODEL
        assert config["tools"] == "native"
    assert not service._all("SELECT * FROM settings WHERE key LIKE 'local-harness:%'")
    assert not service._all("SELECT * FROM jobs")


def test_only_documented_and_wired_harnesses_are_offered(desktop, loaded, monkeypatch):
    service, project, _ = desktop
    expected = {"superqode", "opencode", "goose"}
    assert set(lh.HARNESSES) == set(lh.DOCUMENTED_LOCAL_SUPPORT) == expected
    for installed in [True, False]:
        monkeypatch.setattr(
            lh.shutil, "which", lambda name: "/usr/bin/" + name if installed else None
        )
        rows = lh.catalog(service, project["id"])["harnesses"]
        assert {row["id"] for row in rows} == expected
        for row in rows:
            assert row["local_support"] == "documented"
            assert row["source_urls"] == list(lh.DOCUMENTED_LOCAL_SUPPORT[row["id"]])
            assert all(url.startswith("https://") for url in row["source_urls"])
            assert row["status"] in {"Configured", "Not installed"}
            if row["status"] == "Not installed":
                assert row["install_url"].startswith("https://")
                assert not lh.preflight(service, params(project, row["id"]))["ready"]


def test_adding_an_acp_or_catalog_entry_does_not_allow_local_launch(desktop, loaded, monkeypatch):
    service, project, _ = desktop
    monkeypatch.setitem(
        lh.HARNESSES, "unreviewed", ("Unreviewed", "unreviewed", "https://example.com")
    )
    assert "unreviewed" not in {r["id"] for r in lh.catalog(service, project["id"])["harnesses"]}
    with pytest.raises(ValueError, match="not supported"):
        lh.preflight(service, params(project, "unreviewed"))
    with pytest.raises(ValueError, match="no documented and wired"):
        lh.generate_config("unreviewed", "ollama", MODEL, {"context": 8192, "max_tokens": 2048})


@pytest.mark.parametrize("identity", ["codex", "claude", "gemini", "aider", "qwen", "crush"])
def test_unwired_integrations_are_hidden_and_rejected(desktop, loaded, identity):
    service, project, _ = desktop
    assert identity not in {r["id"] for r in lh.catalog(service, project["id"])["harnesses"]}
    with pytest.raises(ValueError, match="not supported"):
        lh.preflight(service, params(project, identity))
    with pytest.raises(ValueError, match="no documented and wired"):
        lh.generate_config(identity, "ollama", MODEL, {"context": 8192, "max_tokens": 2048})
    reference = lh.PREFIX + identity
    service._write(
        "INSERT INTO settings VALUES(?,?)",
        (
            reference,
            json.dumps(
                {
                    "project": project["id"],
                    "harness": identity,
                    "engine": "ollama",
                    "model": MODEL,
                    "digest": "old-profile",
                }
            ),
        ),
    )
    assert all(row["id"] != reference for row in lh.selections(service, project["id"]))
    with pytest.raises(ValueError, match="not supported"):
        lh.apply_route(service, project["id"], {"harness": reference})


@pytest.mark.parametrize("version", ["2.0.1", "dev", "", "1.2.3\nextra", "1.19.4", "1.19.5-dev"])
def test_unverified_opencode_versions_are_not_launched(desktop, loaded, monkeypatch, version):
    service, project, _ = desktop
    monkeypatch.setattr(
        lh.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=version)
    )
    plan = lh.preflight(service, params(project, "opencode"))
    assert plan["status"] == "Unavailable" and not plan["ready"]
    assert "opencode" not in {r["id"] for r in lh.catalog(service, project["id"])["harnesses"]}


@pytest.mark.parametrize("version", ["1.57.9", "2.0.0", "1.58.0-dev", "", "unknown"])
def test_unreviewed_goose_versions_are_hidden(desktop, loaded, monkeypatch, version):
    service, project, _ = desktop
    monkeypatch.setattr(
        lh.subprocess, "run", lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout=version)
    )
    assert not lh.preflight(service, params(project, "goose"))["ready"]
    assert "goose" not in {r["id"] for r in lh.catalog(service, project["id"])["harnesses"]}


def test_ui_uses_the_same_documented_allowlist():
    root = Path(__file__).resolve().parents[1]
    source = (root / "apps/macos/Sources/SuperQode/LocalHarnessesView.swift").read_text()
    import re

    identifiers = re.search(r"static let documentedIDs: Set<String> = \[(.*?)\]", source).group(1)
    assert set(re.findall(r'"([^"]+)"', identifiers)) == set(lh.DOCUMENTED_LOCAL_SUPPORT)
    assert "LocalHarnessSupport.visibleRows(catalog[" in source
    assert 'row["local_support"] as? String == "documented"' in source
    assert 'row["source_urls"] as? [String]' in source


def test_version_timeout_is_reported(desktop, loaded, monkeypatch):
    service, project, _ = desktop

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired("opencode --version", 3)

    monkeypatch.setattr(lh.subprocess, "run", timeout)
    assert lh.preflight(service, params(project, "opencode"))["status"] == "Unavailable"


@pytest.mark.parametrize(
    "condition", ["unloaded", "offline", "wrong-api-id", "no-context", "large", "unknown"]
)
def test_preflight_fails_closed(desktop, loaded, monkeypatch, condition):
    service, project, _ = desktop
    if condition == "unloaded":
        monkeypatch.setattr(lh, "running_models", lambda engine: [])
    elif condition == "offline":

        def offline(*args):
            raise OSError("Endpoint offline")

        monkeypatch.setattr(lh, "_get", offline)
    elif condition == "wrong-api-id":
        monkeypatch.setattr(lh, "_get", lambda url: {"data": [{"id": "other-model"}]})
        monkeypatch.setattr(
            lh, "running_models", lambda engine: [dict(model=MODEL, actual_context=8192)]
        )
    elif condition == "no-context":
        monkeypatch.setattr(lh, "running_models", lambda engine: [dict(model=MODEL)])
    elif condition == "large":
        monkeypatch.setattr(lh, "read_metadata", lambda *args: {"size_bytes": 60 * 1024**3})
    elif condition == "unknown":
        monkeypatch.setattr(lh, "read_metadata", lambda *args: {})
    result = lh.preflight(service, params(project))
    assert not result["ready"], result
    assert result["reason"]
    assert not service._all("SELECT * FROM jobs")


def test_fit_uses_loaded_window_and_unquantized_cache(desktop, loaded, monkeypatch):
    service, project, _ = desktop
    monkeypatch.setattr(
        lh, "running_models", lambda engine: [dict(model=MODEL, actual_context=262144)]
    )
    plan = lh.preflight(service, params(project))
    assert plan["contract"]["context"] <= 8192
    assert plan["contract"]["actual_context"] == 262144
    assert not plan["ready"]
    assert plan["contract"]["fit"]["rating"] == "Too large"


@pytest.mark.parametrize(
    "model", ["{file:/private/key}", "{env:KEY}", "x\ny", "--option", "", "x" * 513]
)
def test_model_ids_cannot_be_config_interpolation_or_flags(desktop, loaded, model):
    service, project, _ = desktop
    with pytest.raises(ValueError, match="running Ollama"):
        lh.preflight(service, {**params(project), "model": model})


@pytest.mark.parametrize("identity", ["aider", "arbitrary-agent"])
def test_reference_only_and_unknown_harnesses_not_runnable(desktop, loaded, identity):
    service, project, _ = desktop
    with pytest.raises(ValueError, match="not supported"):
        lh.preflight(service, params(project, identity))
    assert identity not in {r["id"] for r in lh.catalog(service, project["id"])["harnesses"]}


def test_loaded_lmstudio_instance_ids_and_minimum_context(loaded, monkeypatch):
    monkeypatch.setattr(
        lh,
        "_get",
        lambda url: {
            "models": [
                {"key": "unloaded", "loaded_instances": []},
                {"key": "embedding", "type": "embedding", "loaded_instances": [{"id": "embed"}]},
                {
                    "key": "artifact",
                    "loaded_instances": [
                        {"id": "instance-1", "config": {"context_length": 4096}},
                        {"id": "instance-2", "config": {"context_length": 8192}},
                    ],
                },
            ]
        },
    )
    rows = lh.running_models("lmstudio")
    assert [r["model"] for r in rows] == ["instance-1", "instance-2"]
    assert [r["actual_context"] for r in rows] == [4096, 8192]
    assert all(r["artifact"] == "artifact" for r in rows)


def test_profiles_are_scoped_rebuilt_and_cannot_accept_client_env(desktop, loaded, monkeypatch):
    service, project, _ = desktop
    selection = params(project)
    plan = lh.preflight(service, selection)
    monkeypatch.setattr(service, "start", lambda project, kind, request: request)
    request = lh.launch(
        service, {**selection, "digest": plan["digest"], "prompt": "hello", "command_id": "one"}
    )
    reference = request["harness"]
    assert reference.startswith(lh.PREFIX)
    request.update(
        _local_harness={"config": {"env": {"OPENAI_HOST": "https://wrong.invalid"}}},
        model="cloud-model",
        provider="openai",
        context_window=1_000_000,
        acp_options={"model": "cloud-model"},
    )
    lh.apply_route(service, project["id"], request)
    assert request["provider"] == "ollama" and request["model"] == MODEL
    assert request["context_window"] == plan["contract"]["context"]
    assert "acp_options" not in request
    assert request["_local_harness"]["config"] == plan["config"]
    with pytest.raises(ValueError, match="in this project"):
        lh._profile(service, "other-project", reference)
    monkeypatch.setattr(lh, "running_models", lambda engine: [])
    with pytest.raises(ValueError, match="not loaded"):
        lh.apply_route(service, project["id"], request)


def test_launch_requires_reviewed_revision_and_message(desktop, loaded, monkeypatch):
    service, project, _ = desktop
    selected = params(project)
    plan = lh.preflight(service, selected)
    monkeypatch.setattr(service, "start", lambda *args: pytest.fail("Unreviewed launch"))
    for extra in [
        {"digest": "stale", "prompt": "hello"},
        {"digest": plan["digest"], "prompt": " "},
    ]:
        with pytest.raises(ValueError):
            lh.launch(service, {**selected, **extra, "command_id": "one"})
    assert not service._all("SELECT * FROM settings WHERE key LIKE 'local-harness:%'")


def test_no_global_files_or_bindings_changed(desktop, loaded, tmp_path, monkeypatch):
    service, project, _ = desktop
    config = tmp_path / ".config" / "opencode" / "opencode.json"
    config.parent.mkdir(parents=True)
    config.write_text('{"model":"user-owned"}')
    monkeypatch.setattr(service, "start", lambda *args: {"id": "fixture"})
    for identity in ["superqode", "opencode", "goose"]:
        selection = params(project, identity)
        plan = lh.preflight(service, selection)
        lh.launch(
            service,
            {**selection, "digest": plan["digest"], "prompt": "hello", "command_id": identity},
        )
    assert config.read_text() == '{"model":"user-owned"}'
    assert not service._all("SELECT * FROM local_model_bindings")
    assert not (tmp_path / ".superqode" / "local-context").exists()


@pytest.mark.parametrize("harness", ["superqode", "opencode", "goose"])
def test_worker_environment_isolated_and_contract_not_global(desktop, loaded, harness, monkeypatch):
    service, project, _ = desktop
    plan = lh.preflight(service, params(project, harness))
    original = {
        "HOME": "/tmp/home",
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "cloud-secret",
        "GOOSE_MODEL": "cloud",
        "OPENCODE_CONFIG_CONTENT": "untrusted",
        "LMSTUDIO_HOST": "https://wrong.invalid",
        "OLLAMA_API_BASE": "https://wrong.invalid",
        "SUPERQODE_LOCAL_CONTEXT_CONTRACT": "untrusted",
    }
    env = lh.worker_environment(original, plan)
    assert "cloud-secret" not in env.values() and "untrusted" not in env.values()
    assert "https://wrong.invalid" not in env.values()
    assert original["OPENAI_API_KEY"] == "cloud-secret"
    if harness == "superqode":
        monkeypatch.setenv(
            "SUPERQODE_LOCAL_CONTEXT_CONTRACT", env["SUPERQODE_LOCAL_CONTEXT_CONTRACT"]
        )
        assert cc.requested_context("ollama", MODEL) == plan["contract"]["context"]
        assert cc.output_limit("ollama", MODEL) == plan["contract"]["max_tokens"]
        assert cc._launch_contract_value("lmstudio", MODEL, "context", 512, 262144) is None
        assert cc._launch_contract_value("ollama", "other", "context", 512, 262144) is None
    else:
        assert "SUPERQODE_LOCAL_CONTEXT_CONTRACT" not in env


def test_native_thread_executes_fixture_endpoint_and_continues(desktop, loaded, monkeypatch):
    service, project, _ = desktop
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            value = loaded(self.path)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(value).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            for delta, finish in [
                ({"role": "assistant", "content": "Local fixture done."}, None),
                ({}, "stop"),
            ]:
                packet = {
                    "id": "fixture",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": MODEL,
                    "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
                }
                self.wfile.write(("data: " + json.dumps(packet) + "\n\n").encode())
            self.wfile.write(b"data: [DONE]\n\n")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setitem(lh.ENDPOINTS, "lmstudio", f"http://127.0.0.1:{server.server_port}/v1")
    monkeypatch.setenv("LITELLM_LOCAL_MODEL_COST_MAP", "True")
    service.credentials["openai"] = "never-forward-this-cloud-key"
    try:
        selected = params(project, engine="lmstudio")
        plan = lh.preflight(service, selected)
        launch_params = {
            **selected,
            "digest": plan["digest"],
            "prompt": "Reply briefly.",
            "command_id": "fixture-launch",
        }
        started = service.dispatch("local.harnesses.launch", launch_params)
        job = wait_job(service, started["id"])
        assert job["status"] == "completed", job
        assert job["request"]["_local_harness"]["digest"] == plan["digest"]
        assert service.dispatch("local.harnesses.launch", launch_params)["id"] == started["id"]
        reference = job["request"]["harness"]
        assert any(
            r["id"] == reference
            for r in service.dispatch("harnesses.list", {"project": project["id"]})
        )
        assert service.dispatch(
            "local.harnesses.status", {"project": project["id"], "harness": reference}
        )["ready"]
        assert (
            service.dispatch(
                "harnesses.inspect", {"project": project["id"], "reference": reference}
            )["digest"]
            == plan["digest"]
        )
        service.dispatch("routes.list", {"project": project["id"]})
        next_job = service.dispatch(
            "tasks.start",
            {
                "project": project["id"],
                "harness": reference,
                "provider": "openai",
                "model": "cloud-model",
                "prompt": "Continue briefly.",
                "parent_id": started["id"],
                "_local_harness": {"untrusted": True},
                "_desktop_route": {"command": "false"},
            },
        )
        continued = wait_job(service, next_job["id"])
        assert continued["status"] == "completed", continued
        assert continued["request"]["_continuity"]["mode"] == "resume"
        assert continued["request"]["provider"] == "lmstudio"
        assert continued["request"]["model"] == MODEL
        assert len(requests) == 2
        assert all(
            r["model"] == MODEL and r["max_tokens"] <= plan["contract"]["max_tokens"]
            for r in requests
        )
    finally:
        server.shutdown()
        server.server_close()


@pytest.mark.parametrize("identity", ["opencode", "goose"])
def test_acp_thread_uses_fixture_and_continues(desktop, loaded, monkeypatch, identity):
    service, project, _ = desktop
    original_installed = lh.installed_harness

    def installed(key):
        return {**original_installed(key), "binary": sys.executable}

    original_generate = lh.generate_config
    fixture = str(Path(__file__).parent / "fixtures" / "desktop_acp_agent.py")

    def generate(*args):
        return {**original_generate(*args), "argv": [fixture]}

    monkeypatch.setattr(lh, "installed_harness", installed)
    monkeypatch.setattr(lh, "generate_config", generate)
    selected = params(project, identity)
    plan = lh.preflight(service, selected)
    started = lh.launch(
        service,
        {**selected, "digest": plan["digest"], "prompt": "controls", "command_id": identity},
    )
    job = wait_job(service, started["id"])
    assert job["status"] == "completed", job
    route = job["request"]["_desktop_route"]
    assert route["extra_env"] == plan["config"]["env"]
    assert job["result"]["acp_continuity"]
    continued = service.start(
        project["id"],
        "task",
        {
            "harness": job["request"]["harness"],
            "prompt": "controls",
            "parent_id": started["id"],
            "acp_options": {"model": "cloud-model"},
        },
    )
    result = wait_job(service, continued["id"])
    assert result["status"] == "completed", result
    assert result["request"]["_continuity"]["mode"] == "resume"
    assert "acp_options" not in result["request"]
    if identity == "opencode":
        assert "sq-local/" + MODEL in json.dumps(result["events"])


def test_newcomer_files_are_unchanged_from_023c6ecc():
    # Pin the approved newcomer UI. Only its catalog may read the new tested registry.
    root = Path(__file__).resolve().parents[1]
    hashes = {
        "apps/macos/Sources/SuperQode/LocalQuickStartView.swift": "ff5a74b0c1d0f3cf44927402364e6416000cac1ccd4505d01be59013c99ce0a5",
        "apps/macos/Sources/SuperQode/ConnectionStartGrid.swift": "28b8c2d481c8bb8366c6b74c63b97026a1a57fc0c02eb92c13fc7f863cbbce46",
        "apps/macos/Sources/SuperQode/ConnectionsView.swift": "e7be29a4496e5a7cadb8c59582168c5869c132f7dfed8ad38b7492c4f8e61dd3",
        "apps/macos/Sources/SuperQode/LocalModelsView.swift": "7d82b11ff9fdf41f4a0a7431a75bca23d8be791dfc00a631d643728c414a3f06",
    }
    for name, expected in hashes.items():
        assert hashlib.sha256((root / name).read_bytes()).hexdigest() == expected, name
    import ast

    setup = ast.parse((root / "src/superqode/desktop_service/local_quickstart.py").read_text())
    setup.body = [
        node
        for node in setup.body
        if not (isinstance(node, ast.FunctionDef) and node.name == "catalog")
    ]
    assert (
        hashlib.sha256(ast.dump(setup).encode()).hexdigest()
        == "90aced412569949c610265f1bb6c559fafdf91ec82a7aebe87ef89aa29ab63e3"
    )


@pytest.mark.parametrize("engine", ["ollama", "lmstudio"])
def test_goose_private_config_only_created_on_explicit_worker_launch(desktop, loaded, engine):
    service, project, _ = desktop
    plan = lh.preflight(service, params(project, "goose", engine))
    base = Path(plan["config"]["env"]["GOOSE_PATH_ROOT"])
    target = base / "config" / "config.yaml"
    assert not target.exists()
    assert base.is_relative_to(service.root / "local-harnesses")
    lh.materialize_worker_files(plan, service.root)
    content = target.read_text()
    parsed = json.loads(content)
    assert set(parsed["extensions"]) == {"developer"}
    assert parsed["active_provider"] == engine
    assert set(parsed["providers"]) == {engine}
    assert parsed["providers"][engine]["model"] == MODEL
    assert target.stat().st_mode & 0o777 == 0o600
    lh.materialize_worker_files(plan, service.root)
    assert target.read_text() == content
    import yaml

    target.write_text(yaml.safe_dump({**parsed, "ordinary_preference": True}))
    lh.materialize_worker_files(plan, service.root)
    assert "ordinary_preference" in target.read_text()
    target.write_text("active_provider: cloud\n")
    with pytest.raises(ValueError, match="configuration changed"):
        lh.materialize_worker_files(plan, service.root)
    assert target.read_text() == "active_provider: cloud\n"


def test_private_config_rejects_escape_and_symlinks(desktop, loaded, tmp_path):
    service, project, _ = desktop
    for target in [
        tmp_path / "outside.yaml",
        service.root / "local-harnesses" / ".." / "escape.yaml",
    ]:
        with pytest.raises(ValueError, match="private"):
            lh.materialize_worker_files({"config": {"files": {str(target): "{}"}}}, service.root)
        assert not target.exists()
    plan = lh.preflight(service, params(project, "goose"))
    base = service.root / "local-harnesses"
    base.mkdir()
    parent = Path(plan["config"]["env"]["GOOSE_PATH_ROOT"]).parent
    outside = tmp_path / "private-outside"
    outside.mkdir()
    parent.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink"):
        lh.materialize_worker_files(plan, service.root)
    assert not list(outside.iterdir())


def test_changed_contract_requires_new_review_before_continuation(desktop, loaded, monkeypatch):
    service, project, _ = desktop
    selected = params(project)
    plan = lh.preflight(service, selected)
    monkeypatch.setattr(service, "start", lambda project, kind, request: request)
    request = lh.launch(
        service, {**selected, "digest": plan["digest"], "prompt": "hello", "command_id": "revision"}
    )
    monkeypatch.setattr(lh, "requested_context", lambda *args: 4096)
    with pytest.raises(ValueError, match="configuration changed"):
        lh.apply_route(service, project["id"], request)


@pytest.mark.parametrize("engine", ["https://bad.invalid", "mlx", "vllm"])
def test_public_preflight_cannot_choose_an_arbitrary_endpoint(desktop, loaded, engine):
    service, project, _ = desktop
    with pytest.raises(ValueError, match="Choose a running"):
        lh.preflight(service, params(project, engine=engine))


def test_launch_contract_rejects_malformed_or_wrongly_typed_values(monkeypatch):
    for raw in [
        "invalid",
        "null",
        "[]",
        '{"provider":"ollama","model":"fixture-model","context":true}',
        '{"provider":"ollama","model":"fixture-model","context":99999999}',
    ]:
        monkeypatch.setenv("SUPERQODE_LOCAL_CONTEXT_CONTRACT", raw)
        assert cc._launch_contract_value("ollama", MODEL, "context", 512, 262144) is None


def test_project_local_profile_survives_engine_restart(desktop, loaded, monkeypatch):
    from superqode.desktop_service.service import DesktopService

    service, project, _ = desktop
    selection = params(project)
    plan = lh.preflight(service, selection)
    monkeypatch.setattr(service, "start", lambda project, kind, request: request)
    request = lh.launch(
        service, {**selection, "digest": plan["digest"], "prompt": "hello", "command_id": "restart"}
    )
    state = service.root
    reference = request["harness"]
    service.close()
    restarted = DesktopService(state)
    try:
        restored = {"harness": reference, "model": "other", "provider": "other"}
        lh.apply_route(restarted, project["id"], restored)
        assert restored["provider"] == "ollama" and restored["model"] == MODEL
        assert restored["_local_harness"]["digest"] == plan["digest"]
        row = next(r for r in lh.selections(restarted, project["id"]) if r["id"] == reference)
        assert row["local_provider"] == "ollama" and row["local_model"] == MODEL
        assert not lh.selections(restarted, "another-project")
    finally:
        restarted.close()


def test_identical_reviewed_pair_reuses_profile_without_changing_other_threads(
    desktop, loaded, monkeypatch
):
    service, project, _ = desktop
    selected = params(project)
    plan = lh.preflight(service, selected)
    monkeypatch.setattr(service, "start", lambda project, kind, request: request)
    first = lh.launch(
        service, {**selected, "digest": plan["digest"], "prompt": "one", "command_id": "one"}
    )
    second = lh.launch(
        service, {**selected, "digest": plan["digest"], "prompt": "two", "command_id": "two"}
    )
    assert first["harness"] == second["harness"]
    assert first["command_id"] != second["command_id"]
    assert len(lh.selections(service, project["id"])) == 1


def test_official_audit_covers_the_full_bundled_inventory():
    import tomllib
    from superqode.runtime import registry
    from superqode.harness.catalog import builtin_harnesses

    root = Path(__file__).resolve().parents[1]
    audit = json.loads((root / "docs/integrations/local-harness-support.json").read_text())
    entries = {row["id"]: row for row in audit["entries"]}
    assert set(audit["advanced_allowlist"]) == set(lh.DOCUMENTED_LOCAL_SUPPORT)
    for path in (root / "src/superqode/agents/data").glob("*.toml"):
        identity = tomllib.loads(path.read_text())["short_name"]
        assert "acp:" + identity in entries
    assert all("runtime:" + key in entries for key in registry._FACTORIES)
    assert all("harness:" + item.id in entries for item in builtin_harnesses())
    for row in entries.values():
        assert row["source_urls"] and row["mechanism"] and row["tool_calling"]
        assert row["version_requirement"]
        if row["advanced_adapter"]:
            assert row["advanced_adapter"] in lh.DOCUMENTED_LOCAL_SUPPORT
            assert row["verdict"] == "Supported (documented)"
    # Documented support and a runnable app adapter are independent facts.
    assert entries["acp:codex"]["verdict"] == "Supported (documented)"
    assert not entries["acp:codex"]["advanced_adapter"]
    assert not entries["reference:aider"]["advanced_adapter"]
    assert not entries["reference:crush"]["advanced_adapter"]
