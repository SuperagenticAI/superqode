"""Tests for the optional RLM Code v0.1.11 integration."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from superqode.harness import (
    HarnessBackendRequest,
    HarnessCreateRequest,
    HarnessProtocolController,
    ExecutionPolicySpec,
    ModelPolicySpec,
    RLMCodeHarnessBackend,
    RLMCodeHarnessProtocolAdapter,
    RLMCodeSettings,
    RuntimeSpec,
    get_harness_template,
    known_harness_backend_names,
    run_harness_conformance,
)


class FakeRLMRunner:
    def __init__(self, run_path: Path) -> None:
        self.run_path = run_path
        self.calls = []
        self.cancelled = False

    async def arun_task(self, prompt, **kwargs):
        self.calls.append((prompt, kwargs))
        events = [
            {
                "type": "context",
                "run_id": "rlm-123",
                "context_profile": "explicit" if kwargs.get("context") else "evidence",
                "context_source": "caller" if kwargs.get("context") else "repository",
                "context_files": ["src/example.py"],
                "context_chars": 321,
                "pure_rlm_profile": kwargs.get("pure_rlm_profile"),
            },
            {
                "type": "step",
                "run_id": "rlm-123",
                "step": 1,
                "depth": 0,
                "action": {"action": "run_python", "code": "answer = llm_query('inspect')"},
                "observation": {"success": True, "stdout": "bounded"},
                "reward": 0.8,
                "usage": {"prompt_tokens": 5, "completion_tokens": 3},
                "role_usage": {
                    "root": {"total_calls": 1},
                    "sub": {"total_calls": 1},
                },
                "root_prompt_chars": 900,
                "root_prompt_sha256": "abc123",
            },
            {
                "type": "final",
                "run_id": "rlm-123",
                "completed": True,
                "steps": 1,
                "total_reward": 0.8,
                "final_response": "evidence-backed answer",
                "usage": {
                    "total_calls": 2,
                    "prompt_tokens": 12,
                    "completion_tokens": 8,
                    "roles": {
                        "root": {"total_calls": 1, "prompt_tokens": 7, "completion_tokens": 5},
                        "sub": {"total_calls": 1, "prompt_tokens": 5, "completion_tokens": 3},
                    },
                },
                "harness": {
                    "profile": "lid",
                    "root_observation_mode": "opaque",
                    "history_policy": "offload",
                    "history_offloads": 1,
                    "root_exposed_chars": 120,
                    "root_hidden_chars": 500,
                    "structural_actions": ["answer = llm_query ( <str> )"],
                },
            },
        ]
        self.run_path.parent.mkdir(parents=True, exist_ok=True)
        self.run_path.write_text(
            "".join(json.dumps(event) + "\n" for event in events),
            encoding="utf-8",
        )
        return SimpleNamespace(
            run_id="rlm-123",
            run_path=self.run_path,
            completed=True,
            steps=1,
            total_reward=0.8,
            final_response="evidence-backed answer",
            usage_summary=events[-1]["usage"],
        )

    def load_run_events(self, run_id):
        assert run_id == "rlm-123"
        return [json.loads(line) for line in self.run_path.read_text().splitlines()]

    def request_cancel(self):
        self.cancelled = True


def _runner_factory(tmp_path, captured):
    def create(request, settings):
        captured["request"] = request
        captured["settings"] = settings
        runner = FakeRLMRunner(tmp_path / "rlm-123.jsonl")
        captured["runner"] = runner
        return runner

    return create


@pytest.mark.asyncio
async def test_rlm_code_backend_maps_harnessspec_to_runner_and_evidence(tmp_path):
    captured = {}
    template = get_harness_template("coding")
    spec = template.__class__(
        **{
            **template.__dict__,
            "runtime": RuntimeSpec(
                backend="rlm-code",
                config={
                    "rlm_code": {
                        "profile": "lid",
                        "context_profile": "evidence",
                        "max_steps": 12,
                        "history_policy": "offload",
                        "decomposition_hint": True,
                        "max_root_history_chars": 24000,
                        "history_preserve_last": 3,
                        "max_iteration_output_chars": 8000,
                        "output_mode": "metadata",
                    }
                },
            ),
            "model_policy": ModelPolicySpec(primary="ollama:qwen3:8b"),
        }
    )
    backend = RLMCodeHarnessBackend(runner_factory=_runner_factory(tmp_path, captured))
    result = await backend.run(
        HarnessBackendRequest(
            spec=spec,
            prompt="Map the repository",
            provider="ollama",
            model="qwen3:8b",
            working_directory=tmp_path,
            session_id="session-1",
            sandbox_backend="docker",
            metadata={"rlm_context": {"src/example.py": "def example(): pass"}},
        )
    )

    assert result.response.content == "evidence-backed answer"
    assert result.response.input_tokens == 12
    assert result.response.output_tokens == 8
    assert result.response.total_tokens == 20
    assert result.response.tool_calls_made == 1
    assert result.metadata["rlm_run_id"] == "rlm-123"
    assert result.metadata["rlm_harness_metrics"]["root_observation_mode"] == "opaque"
    assert captured["settings"].profile == "lid"
    assert captured["settings"].context == {"src/example.py": "def example(): pass"}
    assert captured["settings"].max_root_history_chars == 24000
    assert captured["settings"].history_preserve_last == 3
    assert captured["settings"].max_iteration_output_chars == 8000
    assert captured["settings"].output_mode == "metadata"
    prompt, kwargs = captured["runner"].calls[0]
    assert prompt == "Map the repository"
    assert kwargs["pure_rlm_profile"] == "lid"
    assert kwargs["context_profile"] == "evidence"
    assert kwargs["max_steps"] == 12

    event_types = [event.type for event in result.metadata["events"]]
    assert event_types == [
        "model_request",
        "tool_call",
        "tool_result",
        "validation.completed",
        "artifact.created",
        "model_result",
    ]
    validation = next(
        event for event in result.metadata["events"] if event.type == "validation.completed"
    )
    assert validation.data["context"]["source"] == "caller"
    assert validation.data["harness"]["history_offloads"] == 1


@pytest.mark.asyncio
async def test_rlm_code_protocol_adapter_passes_shared_conformance(tmp_path):
    captured = {}
    adapter = RLMCodeHarnessProtocolAdapter(
        config={"profile": "lid", "context_profile": "evidence"},
        runner_factory=_runner_factory(tmp_path, captured),
    )

    report = await run_harness_conformance(
        adapter,
        provider="ollama",
        model="qwen3:8b",
        working_directory=tmp_path,
    )

    assert report.passed
    assert captured["settings"].profile == "lid"


@pytest.mark.asyncio
async def test_rlm_code_protocol_export_contains_trajectory_artifact(tmp_path):
    adapter = RLMCodeHarnessProtocolAdapter(
        runner_factory=_runner_factory(tmp_path, {}),
    )
    controller = HarnessProtocolController([adapter])
    session = await controller.create(
        HarnessCreateRequest(
            harness_id="rlm-code",
            provider="ollama",
            model="qwen3:8b",
            working_directory=tmp_path,
        )
    )

    events = [event async for event in controller.send(session, "Inspect the repository")]
    bundle = controller.export(session)

    assert events[0].type == "run.started"
    assert events[-1].type == "run.completed"
    assert any(event.type == "validation.completed" for event in events)
    assert len(bundle.artifacts) == 1
    assert bundle.artifacts[0].kind == "rlm-trajectory"
    assert bundle.artifacts[0].media_type == "application/x-ndjson"


def test_rlm_code_is_a_known_optional_backend():
    assert "rlm-code" in known_harness_backend_names()
    assert RLMCodeHarnessBackend.capabilities.supports_no_tool is False


def test_rlm_code_settings_cannot_weaken_sandbox_or_network_policy(tmp_path):
    template = get_harness_template("coding")
    locked = replace(
        template,
        runtime=RuntimeSpec(
            backend="rlm-code",
            config={"rlm_code": {"sandbox_backend": "exec", "network_enabled": True}},
        ),
        execution_policy=ExecutionPolicySpec(
            sandbox="docker",
            allow_read=True,
            allow_network=False,
        ),
    )
    request = HarnessBackendRequest(
        spec=locked,
        prompt="inspect",
        provider="ollama",
        model="qwen3:8b",
        working_directory=tmp_path,
    )

    with pytest.raises(ValueError, match="cannot weaken"):
        RLMCodeSettings.from_request(request)

    network_locked = replace(
        locked,
        runtime=RuntimeSpec(
            backend="rlm-code",
            config={"rlm_code": {"sandbox_backend": "docker", "network_enabled": True}},
        ),
    )
    settings = RLMCodeSettings.from_request(replace(request, spec=network_locked))
    assert settings.network_enabled is False
