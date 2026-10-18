from __future__ import annotations

import json
import sys
from dataclasses import replace

import httpx
import pytest

from superqode.codegem.provider import CodeGemStream
from superqode.harness.refinement import RefinementCoordinator, RefinementRequest
from superqode.harness.templates import codegem_template


@pytest.mark.parametrize("tool_mode", ["native", "json"])
async def test_real_kernel_tools_prompt_and_isolated_resources(tmp_path, monkeypatch, tool_mode):
    source = tmp_path / "source"
    source.mkdir()
    (source / "answer.py").write_text("def answer():\n    return -1\n")
    (source / "AGENTS.md").write_text("FROZEN_PROJECT_SENTINEL")
    captured = []
    from superqode.pipy.coding_session import load_skills

    def frozen_skills(*args, **kwargs):
        assert kwargs["directories"] == []
        return load_skills(*args, **kwargs)

    def no_ambient_templates(*args, **kwargs):
        raise AssertionError("Refinement must not discover ambient prompt templates")

    monkeypatch.setattr("superqode.pipy.coding_session.load_skills", frozen_skills)
    monkeypatch.setattr("superqode.pipy.coding_session.load_prompt_templates", no_ambient_templates)

    def factory(config):
        count = 0

        def handler(request):
            nonlocal count
            body = json.loads(request.content)
            captured.append(body)
            count += 1
            user = next(
                message["content"] for message in body["messages"] if message["role"] == "user"
            )
            if user.startswith("You are a harness editor"):
                message = {
                    "content": json.dumps(
                        {
                            "files": {"instructions.md": "Check the edge case before finishing."},
                            "notes": "The execution provides file and check evidence.",
                        }
                    )
                }
            elif count == 1:
                message = {
                    "content": "",
                    "tool_calls": [
                        {
                            "function": {
                                "name": "python",
                                "arguments": {
                                    "code": "from pathlib import Path\nPath('answer.py').write_text('def answer():\\n    return 42\\n')"
                                },
                            }
                        }
                    ],
                }
            else:
                message = {"content": "Updated answer.py and finished."}
            if tool_mode == "json" and not user.startswith("You are a harness editor"):
                message = {
                    "content": json.dumps(
                        {
                            "content": message["content"],
                            "tool_calls": [
                                call["function"] for call in message.get("tool_calls", [])
                            ],
                        }
                    )
                }
            return httpx.Response(
                200,
                json={"done": True, "message": message, "prompt_eval_count": 30, "eval_count": 10},
            )

        return CodeGemStream(config, transport=httpx.MockTransport(handler))

    monkeypatch.setattr("superqode.codegem.provider.CodeGemStream", factory)
    spec = codegem_template()
    spec = replace(
        spec,
        agents=(replace(spec.agents[0], system_prompt="AGENT_PROMPT_SENTINEL"),),
        runtime=replace(spec.runtime, config={"tool_mode": tool_mode, "context_window": 8192}),
    )
    request = RefinementRequest(
        task="Fix answer() to return 42",
        source=source,
        output=tmp_path / "job",
        spec=spec,
        provider="ollama",
        model="gemma4:12b",
        checks=((sys.executable, "-c", "from answer import answer; assert answer() == 42"),),
    )
    result = await RefinementCoordinator(request).run()
    assert result["status"] == "succeeded", result
    assert result["validation"] == "passed"
    assert result["new_sessions"] == 7
    assert len(captured) == 11
    solver = [
        body
        for body in captured
        if not next(m["content"] for m in body["messages"] if m["role"] == "user").startswith(
            "You are a harness editor"
        )
    ]
    editors = [body for body in captured if body not in solver]
    assert all("AGENT_PROMPT_SENTINEL" in body["messages"][0]["content"] for body in solver)
    assert all(
        body["messages"][0]["content"].count("FROZEN_PROJECT_SENTINEL") == 1 for body in solver
    )
    assert all(not body.get("tools") for body in editors)
    assert "return -1" in (source / "answer.py").read_text()
    assert len(list((request.output / "stages").glob("*/native/runs/*"))) >= 7
