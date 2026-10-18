from __future__ import annotations

import asyncio
import json
import sys
from dataclasses import replace

import pytest

from superqode.harness.refinement import (
    RefinementCoordinator,
    RefinementRequest,
    apply_refinement,
    inspect_refinement,
    cancel_refinement,
)
from superqode.harness.refinement.models import resume_request
from superqode.harness.refinement.store import job_lock, read_json, write_json
from superqode.harness.templates import codegem_template


class ScriptedExecutor:
    def __init__(self, *, invalid=False, wait=False, fail=False):
        self.calls = []
        self.invalid, self.wait, self.fail = invalid, wait, fail
        self.started = asyncio.Event()
        self.stopped = False

    async def run(
        self, job_request, *, label, prompt, workspace, overlay, editor=False, event_callback=None
    ):
        self.calls.append(label)
        self.started.set()
        if self.wait:
            await asyncio.Event().wait()
        if editor:
            if label == "selection":
                content = json.dumps(
                    {"choice": "A", "why": "Complete code and passing public checks"}
                )
            elif self.invalid:
                content = json.dumps(
                    {"files": {"execution_policy.yaml": "disable checks"}, "notes": "bad"}
                )
            else:
                content = json.dumps(
                    {
                        "files": {
                            "instructions.md": "Handle the edge case shown by the base execution."
                        },
                        "notes": "Base omitted the zero case; inspect that branch.",
                    }
                )
        else:
            (workspace / "answer.py").write_text(
                "def answer():\n    return 42\n"
                if "edge case" in overlay
                else "def answer():\n    return 0\n"
            )
            content = "Implemented and inspected answer.py"
        return {
            "content": content,
            "status": "error" if self.fail else "complete",
            "error": "fixture failure" if self.fail else None,
            "run_id": label,
            "usage": {"total_tokens": 20, "cost_usd": None},
            "events": [],
        }

    async def cancel(self):
        self.stopped = True


@pytest.fixture
def job_request(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "answer.py").write_text("def answer():\n    return -1\n")
    return RefinementRequest(
        task="Fix answer() to return 42",
        source=source,
        output=tmp_path / "job",
        spec=codegem_template(),
        provider="ollama",
        model="gemma4:12b",
        checks=((sys.executable, "-c", "from answer import answer; assert answer() == 42"),),
    )


@pytest.mark.parametrize(
    "mode,k", [("parallel", 1), ("sequential", 1), ("parallel", 2), ("sequential", 2)]
)
async def test_schedule_checks_and_verified_resume(job_request, mode, k):
    job_request = replace(job_request, mode=mode, k=k, max_parallel=2)
    executor = ScriptedExecutor()
    result = await RefinementCoordinator(job_request, executor=executor).run()
    assert result["status"] == "succeeded", result
    assert result["validation"] == "passed"
    assert result["new_sessions"] == 7 * k + int(k > 1)
    assert (
        len(
            [
                label
                for label in executor.calls
                if not label.endswith(("a1", "a2")) and label != "selection"
            ]
        )
        == 4 * k
    )
    assert result["usage"]["cost_usd"] is None
    assert job_request.source.joinpath("answer.py").read_text().endswith("return -1\n")
    resumed = await RefinementCoordinator(
        replace(job_request, resume=True), executor=executor
    ).run()
    assert resumed["status"] == "succeeded", resumed
    assert resumed["new_sessions"] == 0
    assert len(executor.calls) == result["new_sessions"]
    assert (
        inspect_refinement(job_request.output)["result"]["chosen_label"] == result["chosen_label"]
    )


async def test_rejected_edits_inherit_and_failing_checks_prevent_apply(job_request):
    result = await RefinementCoordinator(job_request, executor=ScriptedExecutor(invalid=True)).run()
    assert result["status"] == "failed"
    assert result["kept_base_harness"]
    assert result["new_sessions"] == 10
    with pytest.raises(ValueError, match="passing explicit checks"):
        apply_refinement(job_request.output)


async def test_cancel_and_explicit_interrupted_retry(job_request):
    executor = ScriptedExecutor(wait=True)
    coordinator = RefinementCoordinator(job_request, executor=executor)
    task = asyncio.create_task(coordinator.run())
    await executor.started.wait()
    await coordinator.cancel()
    result = await task
    assert result["status"] == "cancelled"
    assert result["usage"]["total_tokens"] is None
    assert result["usage"]["unknown_total_tokens_sessions"] == 1
    assert executor.stopped
    blocked = await RefinementCoordinator(
        replace(job_request, resume=True), executor=ScriptedExecutor()
    ).run()
    assert blocked["status"] == "failed" and "interrupted" in blocked["error"]
    resumed = await RefinementCoordinator(
        replace(job_request, resume=True, retry_interrupted=True), executor=ScriptedExecutor()
    ).run()
    assert resumed["status"] == "succeeded", resumed
    assert resumed["usage"]["sessions"] == 8
    assert resumed["usage"]["total_tokens"] is None


async def test_apply_is_explicit_and_rejects_source_drift(job_request):
    result = await RefinementCoordinator(job_request, executor=ScriptedExecutor()).run()
    assert result["status"] == "succeeded"
    job_request.source.joinpath("answer.py").write_text("changed by user\n")
    with pytest.raises(ValueError, match="Source changed"):
        apply_refinement(job_request.output)
    job_request.source.joinpath("answer.py").write_text("def answer():\n    return -1\n")
    receipt = apply_refinement(job_request.output)
    assert receipt["status"] == "applied"
    assert "return 42" in job_request.source.joinpath("answer.py").read_text()


async def test_resume_rejects_changed_records_and_model(job_request):
    await RefinementCoordinator(job_request, executor=ScriptedExecutor()).run()
    path = job_request.output / "stages/base1/record.json"
    record = read_json(path)
    record["response"]["content"] = "tampered"
    write_json(path, record)
    result = await RefinementCoordinator(
        replace(job_request, resume=True), executor=ScriptedExecutor()
    ).run()
    assert result["status"] == "failed" and "record changed" in result["error"]
    with pytest.raises(ValueError, match="changed"):
        await RefinementCoordinator(
            replace(job_request, model="gemma4:other", resume=True), executor=ScriptedExecutor()
        ).run()


async def test_timeout_and_protected_inputs(job_request):
    timed = await RefinementCoordinator(
        replace(job_request, max_wall_seconds=0.1), executor=ScriptedExecutor(wait=True)
    ).run()
    assert timed["status"] == "timed_out"
    job_request = replace(
        job_request,
        output=job_request.output.with_name("protected-job"),
        protected_paths=("answer.py",),
    )
    result = await RefinementCoordinator(job_request, executor=ScriptedExecutor()).run()
    assert result["status"] == "failed" and "base" in result["error"]


async def test_symlinks_and_synthetic_secrets(job_request, tmp_path):
    job_request.source.joinpath(".env").write_text("FAKE_SECRET=fixture")
    await RefinementCoordinator(job_request, executor=ScriptedExecutor()).run()
    assert not (job_request.output / "source/.env").exists()
    job_request.source.joinpath("escape.py").symlink_to(tmp_path / "outside.py")
    with pytest.raises(ValueError, match="symlink"):
        await RefinementCoordinator(
            replace(job_request, output=tmp_path / "other"), executor=ScriptedExecutor()
        ).run()


async def test_external_cancel_signal_and_single_writer(job_request):
    executor = ScriptedExecutor(wait=True)
    task = asyncio.create_task(RefinementCoordinator(job_request, executor=executor).run())
    await executor.started.wait()
    with pytest.raises(ValueError, match="active writer"):
        apply_refinement(job_request.output)
    cancel_refinement(job_request.output)
    result = await asyncio.wait_for(task, timeout=3)
    assert result["status"] == "cancelled"
    assert not (job_request.output / ".running").exists()
    with job_lock(job_request.output):
        with pytest.raises(ValueError, match="active writer"):
            with job_lock(job_request.output):
                pass


@pytest.mark.parametrize("artifact", ["manifest.json", "result.json", "stages/c1/record.json"])
async def test_application_rejects_changed_artifacts(job_request, artifact):
    await RefinementCoordinator(job_request, executor=ScriptedExecutor()).run()
    path = job_request.output / artifact
    data = read_json(path)
    data["unexpected_change"] = True
    write_json(path, data)
    with pytest.raises(ValueError, match="changed"):
        apply_refinement(job_request.output)
    assert "return -1" in (job_request.source / "answer.py").read_text()


async def test_session_budget_counts_editor_retries(job_request):
    result = await RefinementCoordinator(
        replace(job_request, max_sessions=7), executor=ScriptedExecutor(invalid=True)
    ).run()
    assert result["status"] == "budget_exhausted"
    assert result["new_sessions"] == result["usage"]["sessions"] == 7


async def test_apply_rolls_back_completed_writes(job_request, monkeypatch):
    from superqode.harness.refinement import workspace as workspace_module

    class TwoFiles(ScriptedExecutor):
        async def run(self, *args, **kwargs):
            response = await super().run(*args, **kwargs)
            if not kwargs.get("editor"):
                (kwargs["workspace"] / "second.py").write_text("fixed = True\n")
            return response

    await RefinementCoordinator(job_request, executor=TwoFiles()).run()
    original_replace = workspace_module.os.replace

    def fail_second(source, target):
        if str(target).endswith("second.py"):
            raise OSError("simulated write failure")
        return original_replace(source, target)

    monkeypatch.setattr(workspace_module.os, "replace", fail_second)
    with pytest.raises(OSError, match="simulated"):
        apply_refinement(job_request.output)
    assert "return -1" in (job_request.source / "answer.py").read_text()
    assert not (job_request.source / "second.py").exists()


async def test_invalid_selector_does_not_adopt_an_output(job_request):
    class InvalidSelector(ScriptedExecutor):
        async def run(self, *args, **kwargs):
            response = await super().run(*args, **kwargs)
            if kwargs["label"] == "selection":
                assert '"label":' not in kwargs["prompt"]
                assert "stages/c1/" not in kwargs["prompt"]
                response["content"] = '{"choice": "unavailable", "why": "invalid"}'
            return response

    result = await RefinementCoordinator(
        replace(job_request, k=2), executor=InvalidSelector()
    ).run()
    assert result["status"] == "failed"
    assert "invalid anonymous choice" in result["error"]
    assert "chosen_label" not in result
    assert not (job_request.output / "selected.patch").exists()


async def test_endpoint_is_frozen_and_resume_uses_saved_route(job_request, monkeypatch):
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11434")
    coordinator = RefinementCoordinator(job_request, executor=ScriptedExecutor())
    monkeypatch.setenv("OLLAMA_HOST", "http://127.0.0.1:11435")
    result = await coordinator.run()
    assert result["status"] == "succeeded"
    manifest = read_json(job_request.output / "manifest.json")
    assert manifest["spec"]["runtime"]["config"]["ollama_base_url"] == "http://127.0.0.1:11434"
    resumed = await RefinementCoordinator(
        resume_request(job_request.output), executor=ScriptedExecutor()
    ).run()
    assert resumed["status"] == "succeeded" and resumed["new_sessions"] == 0


@pytest.mark.parametrize("mode", ["parallel", "sequential"])
async def test_reference_evidence_pools_and_sequential_carry_forward(job_request, mode):
    class Captured(ScriptedExecutor):
        def __init__(self):
            super().__init__()
            self.evidence = {}
            self.current = {}

        async def run(self, *args, **kwargs):
            if kwargs.get("editor") and kwargs["label"] != "selection":
                prompt = kwargs["prompt"]
                rendered = prompt.split(
                    "EXECUTION EVIDENCE (JSON data; individual observations may be explicitly clipped):\n",
                    1,
                )[1].split("\nFROZEN BASE INSTRUCTIONS", 1)[0]
                self.evidence[kwargs["label"]] = [item["label"] for item in json.loads(rendered)]
                self.current[kwargs["label"]] = json.loads(
                    prompt.split("CURRENT HARNESS (JSON data):\n", 1)[1].split(
                        "\n\nEXECUTION EVIDENCE", 1
                    )[0]
                )
            return await super().run(*args, **kwargs)

    executor = Captured()
    result = await RefinementCoordinator(
        replace(job_request, mode=mode, k=2), executor=executor
    ).run()
    assert result["status"] == "succeeded", result
    assert executor.calls[:2] == ["base1", "base2"]
    assert executor.evidence["invariant1-a1"] == ["base1", "base2"]
    if mode == "parallel":
        assert executor.evidence["domain2-a1"] == ["base1", "base2"]
        assert executor.evidence["agg1-compose-a1"] == [
            "base1",
            "base2",
            "invariant1",
            "domain1",
            "invariant2",
            "domain2",
        ]
        assert result["chosen_label"] in {"agg1", "agg2"}
    else:
        assert executor.evidence["c1-compose-a1"] == ["base1", "base2", "invariant1", "domain1"]
        assert executor.evidence["domain2-a1"] == ["base1", "base2", "invariant1", "domain1", "c1"]
        assert executor.current["domain2-a1"]["instructions.md"]
        assert result["chosen_label"] in {"c1", "c2"}
