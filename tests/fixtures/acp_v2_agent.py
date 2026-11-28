"""Deterministic stdio harness for ACP integration tests; never calls a model."""

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

from acp import run_agent, NewSessionResponse
from superqode.acp.server import SuperQodeAcpAgent, _AcpSessionState
from superqode.acp.server_v2 import SuperQodeAcpV2Agent
from superqode.acp.transport import run_dual_agent
from superqode.harness.events import HarnessEvent
from superqode.harness.templates import coding_template


class HarnessSession:
    def __init__(self, identity, owner=None):
        self.session_id = identity
        self.owner = owner

    async def stream(self, prompt, **kwargs):
        if prompt == "background" and self.owner:
            await self.owner.register_background(
                self.session_id, "fixture-bg", asyncio.create_task(asyncio.sleep(3600))
            )
        if prompt == "error":
            raise RuntimeError("fixture failure")
        if prompt == "child":
            yield HarnessEvent(
                type="subagent_start", data={"agent_id": "research", "prompt": "look"}
            )
            yield HarnessEvent(
                type="subagent_result", data={"agent_id": "research", "result": "child result"}
            )
        yield HarnessEvent(type="model_delta", data={"text": "answer:" + prompt})
        if prompt == "slow":
            await asyncio.Event().wait()
        yield HarnessEvent(
            type="tool_call", data={"tool_name": "read", "arguments": {"path": "test.txt"}}
        )
        yield HarnessEvent(
            type="tool_result", data={"tool_name": "read", "success": True, "output": "read result"}
        )

    def pending_approvals(self):
        return ()

    async def cancel(self):
        pass


class V1Agent(SuperQodeAcpAgent):
    async def new_session(self, cwd, **kwargs):
        identity = "test-" + uuid.uuid4().hex
        session = HarnessSession(identity, getattr(self, "owner", None))
        self._sessions[identity] = _AcpSessionState(
            session, coding_template(), "test", "fixture", Path(cwd)
        )
        return NewSessionResponse(session_id=identity)


def v2_factory():
    agent = SuperQodeAcpV2Agent(ledger_path=Path(sys.argv[1]))
    agent.core = V1Agent()
    agent.core.owner = agent
    return agent


if __name__ == "__main__":
    if "--v1-only" in sys.argv:
        asyncio.run(run_agent(V1Agent()))
    else:
        asyncio.run(run_dual_agent(V1Agent(), v2_factory))
