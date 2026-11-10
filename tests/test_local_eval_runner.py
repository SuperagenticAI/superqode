"""Fake local endpoints only. The runner really edits fixtures and executes tests."""

import json

import httpx
import pytest
from click.testing import CliRunner

from superqode.commands.local import local
from superqode.local import eval_runner as ev
from superqode.local.hardware import HardwareProfile
from superqode.local.starter_registry import validate_report


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/v1",
        "http://localhost:1234/v1",
        "http://127.0.0.1:1234/other",
        "http://user:pass@127.0.0.1:1234",
        "http://127.0.0.1:1234?key=secret",
    ],
)
def test_endpoint_is_literal_loopback_without_private_values(url):
    with pytest.raises(ValueError):
        ev.local_endpoint("lmstudio", url)


def test_consent_is_required_before_endpoint_calls(tmp_path):
    with pytest.raises(ValueError, match="allow-execution"):
        ev.run_evaluation("ollama", "qwen3.5:4b", output=tmp_path / "report.json")
    result = CliRunner().invoke(
        local,
        [
            "eval",
            "--engine",
            "ollama",
            "--registry-model",
            "qwen3.5:4b",
            "--output",
            str(tmp_path / "report.json"),
        ],
    )
    assert result.exit_code != 0 and "not sandboxed" in result.output
    assert not (tmp_path / "report.json").exists()


def fake_endpoint(engine, *, usage=True, broken=False):
    requests = []
    tag = "qwen3.5:4b" if engine == "ollama" else "qwen/qwen3.5-4b"

    def handler(request):
        if request.method == "GET":
            if engine == "ollama":
                return httpx.Response(
                    200, json={"models": [{"name": tag, "digest": "real-endpoint-digest-shape"}]}
                )
            return httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "key": tag,
                            "loaded_instances": [{"id": tag, "config": {"context_length": 4096}}],
                        }
                    ]
                },
            )
        data = json.loads(request.content)
        requests.append(data)
        prompt = data["messages"][1]["content"]
        turn = sum(m["role"] == "assistant" for m in data["messages"])
        if broken:
            name, args = "read_file", "invalid json"
        elif "greeting()" in prompt:
            name, args = (
                ("read_file", {"path": "solution.py"})
                if turn == 0
                else (
                    "edit_file",
                    {
                        "path": "solution.py",
                        "old_text": "'hello'",
                        "new_text": "'Hello, SuperQode!'",
                    },
                )
            )
        elif "Do not edit" in prompt:
            name, args = "run_test", {}
        elif "Run run_test first" in prompt:
            name, args = (
                ("edit_file", {"path": "solution.py", "old_text": "a - b", "new_text": "a + b"})
                if turn == 1
                else ("run_test", {})
            )
        elif "Read solution.py with read_file" in prompt:
            name, args = [
                ("read_file", {"path": "solution.py"}),
                ("edit_file", {"path": "solution.py", "old_text": "a - b", "new_text": "a + b"}),
                ("run_test", {}),
            ][min(turn, 2)]
        else:
            name, args = "submit_json", {"answer": 42, "labels": ["local", "tools"]}
        message = {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"call-{len(requests)}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": args
                        if engine == "ollama" or isinstance(args, str)
                        else json.dumps(args),
                    },
                }
            ],
        }
        if engine == "ollama":
            return httpx.Response(
                200, json={"message": message, **({"eval_count": 12} if usage else {})}
            )
        return httpx.Response(
            200,
            json={
                "choices": [{"message": message}],
                **({"usage": {"completion_tokens": 12}} if usage else {}),
            },
        )

    return httpx.Client(transport=httpx.MockTransport(handler)), requests


@pytest.fixture(autouse=True)
def no_real_hardware(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(
        ev,
        "detect_hardware",
        lambda: HardwareProfile(
            platform="darwin", is_apple_silicon=True, unified_memory_gb=16, chip="Fixture Mac"
        ),
    )
    # Keep all generated fixtures in the pytest directory, with no model inference.
    original = ev.tempfile.mkdtemp
    monkeypatch.setattr(ev.tempfile, "mkdtemp", lambda **kw: original(dir=tmp_path, **kw))


@pytest.mark.parametrize("engine", ["ollama", "lmstudio"])
def test_real_fixture_edits_tests_metrics_and_simulation_cannot_promote(tmp_path, engine):
    client, requests = fake_endpoint(engine)
    output = tmp_path / "results.json"
    report = ev.run_evaluation(
        engine, "qwen3.5:4b", output=output, allow_execution=True, client=client
    )
    assert report["passed"] and report["completed"]
    assert report["execution_mode"] == "simulated"
    assert len(report["tasks"]) == 5
    assert all(
        t["passed"] and t["tool_calls_valid"] and t["tool_calls"] > 0 for t in report["tasks"]
    )
    assert all(t["tokens_per_second"] > 0 and t["elapsed_seconds"] > 0 for t in report["tasks"])
    fix = next(t for t in report["tasks"] if t["id"] == "fix_test")
    assert fix["tools_executed"][0] == {"name": "run_test", "success": False}
    assert fix["tools_executed"][-1] == {"name": "run_test", "success": True}
    assert json.loads(output.read_text())["suite"] == "local-coding-v1"
    with pytest.raises(ValueError, match="real local endpoint"):
        validate_report(report)
    assert all(r["tools"] for r in requests)
    if engine == "ollama":
        assert all(r["options"]["num_ctx"] == report["context"] for r in requests)
    else:
        assert report["context"] == 4096 and report["requested_context"] == 8192
        assert all(0 < r["max_tokens"] < 4096 for r in requests)


def test_unknown_token_usage_stays_null(tmp_path):
    client, _ = fake_endpoint("ollama", usage=False)
    report = ev.run_evaluation(
        "ollama", "qwen3.5:4b", output=tmp_path / "report.json", allow_execution=True, client=client
    )
    assert all(
        t["completion_tokens"] is None and t["tokens_per_second"] is None for t in report["tasks"]
    )


def test_invalid_tool_retry_cap_is_recorded_and_cannot_promote(tmp_path):
    client, requests = fake_endpoint("ollama", broken=True)
    report = ev.run_evaluation(
        "ollama", "qwen3.5:4b", output=tmp_path / "report.json", allow_execution=True, client=client
    )
    assert not report["passed"] and len(requests) == 15
    assert all(t["corrective_retries"] == 2 and t["invalid_calls"] == 3 for t in report["tasks"])
    assert all(not t["tools_executed"] for t in report["tasks"])


def test_lm_identity_requires_loaded_instance_and_does_not_guess_aliases():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200,
                json={
                    "models": [
                        {
                            "key": "other/catalog",
                            "loaded_instances": [
                                {"id": "alias", "config": {"context_length": 8192}}
                            ],
                        }
                    ]
                },
            )
        )
    )
    artifact, verified, context = ev._identity(
        client, "http://127.0.0.1:1234", "lmstudio", "alias", "qwen/qwen3.5-4b"
    )
    assert artifact["key"] == "other/catalog" and not verified and context == 8192
    with pytest.raises(ValueError, match="Load the requested"):
        ev._identity(client, "http://127.0.0.1:1234", "lmstudio", "not-loaded", "qwen/qwen3.5-4b")


def test_existing_reports_are_never_overwritten(tmp_path):
    output = tmp_path / "report.json"
    output.write_text("retain me")
    with pytest.raises(ValueError, match="not overwritten"):
        ev.run_evaluation("ollama", "qwen3.5:4b", output=output, allow_execution=True)
    assert output.read_text() == "retain me"


def test_unfitting_loaded_context_blocks_model_requests(tmp_path):
    requests = []

    def handler(request):
        if request.method == "POST":
            requests.append(request)
        return httpx.Response(
            200,
            json={
                "models": [
                    {
                        "key": "qwen/qwen3.5-4b",
                        "loaded_instances": [
                            {"id": "qwen/qwen3.5-4b", "config": {"context_length": 262144}}
                        ],
                    }
                ]
            },
        )

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="not marked Fits"):
        ev.run_evaluation(
            "lmstudio",
            "qwen3.5:4b",
            output=tmp_path / "report.json",
            allow_execution=True,
            client=client,
        )
    assert not requests


def test_unverified_identity_blocks_generation_and_never_writes_promotable_results(tmp_path):
    client, requests = fake_endpoint("ollama")
    with pytest.raises(ValueError, match="exact curated catalog model"):
        ev.run_evaluation(
            "ollama",
            "qwen3-coder-next:q4_K_M",
            runtime_model="qwen3.5:4b",
            output=tmp_path / "report.json",
            allow_execution=True,
            client=client,
        )
    assert not requests and not (tmp_path / "report.json").exists()
