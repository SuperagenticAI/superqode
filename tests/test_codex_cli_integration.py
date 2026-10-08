"""Pinned real-CLI protocol checks with isolated storage and no inference."""

import json
import asyncio
import os
import subprocess
import socket
import uuid
from pathlib import Path

import pytest
from jsonschema import Draft7Validator

from superqode.agent.loop import AgentConfig
from superqode.runtime.codex_cli import CodexCLIRuntime, codex_binary


def test_real_sdk_pins_reviewer_and_app_overrides(installed_codex, tmp_path):
    pytest.importorskip("openai_codex")
    from superqode.runtime.codex_sdk import CodexSDKRuntime

    runtime = CodexSDKRuntime(
        config=AgentConfig(
            provider="fixture",
            model="protocol-test",
            working_directory=tmp_path,
            tools_enabled=False,
        )
    )
    try:
        runtime._ensure_started_sync()
        assert runtime.thread_id
        assert runtime.effective_policy["approvalsReviewer"] == "user"
        assert runtime._reviewer_overrides['apps."example".approvals_reviewer'] == "user"
    finally:
        runtime.close()


@pytest.mark.asyncio
async def test_real_cli_loopback_attach_preserves_user_listener(installed_codex, tmp_path):
    with socket.socket() as port_picker:
        port_picker.bind(("127.0.0.1", 0))
        port = port_picker.getsockname()[1]
    endpoint = f"ws://127.0.0.1:{port}"
    process = await asyncio.create_subprocess_exec(
        installed_codex,
        "app-server",
        "--listen",
        endpoint,
        cwd=tmp_path,
        env=dict(os.environ),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.DEVNULL,
    )
    runtime = CodexCLIRuntime(
        config=AgentConfig(provider="fixture", model="protocol-test", working_directory=tmp_path),
        codex_bin=installed_codex,
        codex_server=endpoint,
        request_timeout=20,
    )
    try:
        async with asyncio.timeout(10):
            while True:
                try:
                    _, writer = await asyncio.open_connection("127.0.0.1", port)
                    writer.close()
                    await writer.wait_closed()
                    break
                except OSError:
                    if process.returncode is not None:
                        pytest.fail("The installed Codex daemon exited before listening")
                    await asyncio.sleep(0.05)
        await runtime.ensure_thread()
        assert runtime.thread_id
        assert runtime.effective_policy["approvalsReviewer"] == "user"
        await runtime.aclose()
        assert process.returncode is None
    finally:
        await runtime.aclose()
        if process.returncode is None:
            process.terminate()
        await process.wait()


@pytest.fixture
def installed_codex(tmp_path, monkeypatch):
    binary = codex_binary()
    if not binary:
        if os.getenv("SUPERQODE_REQUIRE_CODEX_INTEGRATION"):
            pytest.fail("The release gate requires the pinned Codex CLI")
        pytest.skip("Codex CLI is not installed")
    home = tmp_path / "codex-home"
    home.mkdir()
    (home / "config.toml").write_text(
        'model = "protocol-test"\nmodel_provider = "fixture"\napprovals_reviewer = "auto_review"\n[apps._default]\napprovals_reviewer = "auto_review"\n[apps.example]\napprovals_reviewer = "auto_review"\n[model_providers.fixture]\nname = "Local protocol fixture"\nbase_url = "http://127.0.0.1:9/v1"\nwire_api = "responses"\nrequires_openai_auth = false\n'
    )
    monkeypatch.setenv("CODEX_HOME", str(home))
    monkeypatch.delenv("SUPERQODE_ORG_POLICY", raising=False)
    return binary


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode", ["read-only", "workspace-write", "danger-full-access", "tools-off"]
)
async def test_real_cli_thread_start_resume_and_fork(installed_codex, tmp_path, mode):
    runtime = CodexCLIRuntime(
        config=AgentConfig(
            provider="fixture",
            model="protocol-test",
            working_directory=tmp_path,
            tools_enabled=mode != "tools-off",
        ),
        codex_bin=installed_codex,
        request_timeout=20,
    )
    if mode != "tools-off":
        runtime.set_sandbox_backend(mode)
    try:
        await runtime.ensure_thread()
        original = runtime.thread_id
        assert original
        assert runtime.effective_policy["approvalsReviewer"] == "user"
        assert runtime._reviewer_overrides['apps."example".approvals_reviewer'] == "user"
        assert runtime.effective_policy["sandbox"]["type"] == runtime._sandbox(
            "read-only" if mode == "tools-off" else mode
        )
        # Codex only persists a new thread after its first turn. Seed a public
        # rollout fixture for resume/fork checks without contacting a model.
        saved = str(uuid.uuid4())
        timestamp = "2026-10-08T00:00:00Z"
        rollout = (
            Path(os.environ["CODEX_HOME"])
            / "sessions/2026/10/08"
            / f"rollout-2026-10-08T00-00-00-{saved}.jsonl"
        )
        rollout.parent.mkdir(parents=True, exist_ok=True)
        rows = [
            {
                "timestamp": timestamp,
                "type": "session_meta",
                "payload": {
                    "id": saved,
                    "timestamp": timestamp,
                    "cwd": str(tmp_path),
                    "originator": "codex",
                    "cli_version": "0.160.0",
                    "source": "cli",
                    "model_provider": "fixture",
                },
            },
            {
                "timestamp": timestamp,
                "type": "response_item",
                "payload": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": "Protocol fixture"}],
                },
            },
            {
                "timestamp": timestamp,
                "type": "event_msg",
                "payload": {"type": "user_message", "message": "Protocol fixture", "kind": "plain"},
            },
        ]
        rollout.write_text("".join(json.dumps(row) + "\n" for row in rows))
        resumed = await runtime.resume_thread(saved)
        assert resumed["thread"]["id"] == saved
        assert resumed["approvalsReviewer"] == "user"
        forked = await runtime.fork_thread(saved)
        assert forked["thread"]["id"] != saved
        assert forked["approvalsReviewer"] == "user"
        await runtime.aclose()
        runtime = CodexCLIRuntime(
            config=AgentConfig(
                provider="fixture",
                model="protocol-test",
                working_directory=tmp_path,
                session_id=saved,
            ),
            codex_bin=installed_codex,
            sandbox_backend="read-only",
            request_timeout=20,
        )
        await runtime.ensure_thread()
        assert runtime.thread_id == saved
    finally:
        await runtime.aclose()


def test_emitted_sandbox_params_match_installed_schema(installed_codex, tmp_path):
    schemas = tmp_path / "schemas"
    subprocess.run(
        [
            installed_codex,
            "app-server",
            "generate-json-schema",
            "--experimental",
            "--out",
            str(schemas),
        ],
        check=True,
        capture_output=True,
        timeout=30,
    )
    for method in ("ThreadStart", "ThreadResume", "ThreadFork"):
        validator = Draft7Validator(
            json.loads((schemas / "v2" / f"{method}Params.json").read_text())
        )
        for mode in ("read-only", "workspace-write", "danger-full-access"):
            runtime = CodexCLIRuntime(
                config=AgentConfig(
                    provider="fixture", model="protocol-test", working_directory=tmp_path
                ),
                codex_bin=installed_codex,
                sandbox_backend=mode,
            )
            params = runtime._thread_params()
            if method != "ThreadStart":
                params["threadId"] = "test-thread"
            validator.validate(params)
    turn_validator = Draft7Validator(json.loads((schemas / "v2/TurnStartParams.json").read_text()))
    for mode in ("read-only", "workspace-write", "danger-full-access"):
        turn_validator.validate(
            {
                "threadId": "test-thread",
                "input": [{"type": "text", "text": "test", "text_elements": []}],
                "sandboxPolicy": runtime._turn_sandbox_policy(mode),
            }
        )
