"""Standalone ACP worker, executed by the separate Pydantic AI v2 interpreter.

Keep this file independent of SuperQode imports: the host engine may use v1.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import tempfile
from typing import get_args


def check() -> dict[str, str]:
    from pydantic_ai import Agent  # noqa: F401
    from pydantic_ai_harness import Coder, Permissions  # noqa: F401
    from pydantic_ai.mcp import MCPToolset  # noqa: F401
    from pydantic_ai.models.openai import OpenAIChatModel  # noqa: F401
    from pydantic_ai.models.anthropic import AnthropicModel  # noqa: F401
    from pydantic_ai.models.google import GoogleModel  # noqa: F401

    return {
        name: version(name)
        for name in ("pydantic-ai-harness", "pydantic-ai-slim", "agent-client-protocol")
    }


class FileSessionStore:
    """Private atomic session files, scoped to the worker's opened project."""

    def __init__(self, directory: Path):
        from pydantic import TypeAdapter
        from pydantic_ai_harness.experimental.acp import StoredSession

        self.directory = directory
        self.adapter = TypeAdapter(StoredSession)

    def _path(self, session_id):
        return self.directory / (hashlib.sha256(session_id.encode()).hexdigest() + ".json")

    async def save(self, session_id, session):
        data = self.adapter.dump_json(session)
        if len(data) > 32_000_000:
            raise ValueError("ACP session exceeds the storage limit")

        def write():
            self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            handle, temporary = tempfile.mkstemp(prefix=".session-", dir=self.directory)
            try:
                with os.fdopen(handle, "wb") as output:
                    output.write(data)
                os.replace(temporary, self._path(session_id))
            finally:
                Path(temporary).unlink(missing_ok=True)

        await asyncio.to_thread(write)

    async def load(self, session_id):
        path = self._path(session_id)
        if not path.exists():
            return None
        if path.stat().st_size > 32_000_000:
            raise ValueError("ACP session exceeds the storage limit")
        return self.adapter.validate_json(await asyncio.to_thread(path.read_bytes))


def mcp_toolsets(session):
    """Consume client-supplied MCP servers and require approval for their tools."""
    from fastmcp.client.transports import StdioTransport, StreamableHttpTransport, SSETransport
    from pydantic_ai.mcp import MCPToolset

    toolsets = []
    for index, server in enumerate(session.mcp_servers):
        if hasattr(server, "command"):
            transport = StdioTransport(
                command=server.command,
                args=list(server.args or []),
                env={entry.name: entry.value for entry in (server.env or [])},
                cwd=session.cwd,
            )
        else:
            transport_type = SSETransport if server.type == "sse" else StreamableHttpTransport
            transport = transport_type(
                server.url, headers={entry.name: entry.value for entry in (server.headers or [])}
            )
        toolset = (
            MCPToolset(transport, id=f"mcp_{index}").prefixed(f"mcp_{index}").approval_required()
        )
        toolsets.append(toolset)
    return toolsets


def model_ids(default: str) -> list[str]:
    from pydantic_ai.models import KnownModelName

    if default.split(":", 1)[0] not in {"openai", "anthropic", "google"}:
        raise ValueError("Choose an openai:, anthropic: or google: model for Pydantic Coder")
    known = get_args(getattr(KnownModelName, "__value__", KnownModelName))
    return [
        default,
        *sorted(
            {name for name in known if name.split(":", 1)[0] in {"openai", "anthropic", "google"}}
            - {default}
        ),
    ]


def serve(directory: Path, default_model: str, *, model=None):
    from acp import schema
    from pydantic_ai import Agent
    from pydantic_ai.usage import UsageLimits
    from pydantic_ai.workspaces import LocalWorkspaceBackend
    from pydantic_ai_harness import Coder, Permissions
    from pydantic_ai_harness.experimental.acp import ACPSessionConfig, run_acp_stdio_sync

    project = Path.cwd().resolve()
    store = FileSessionStore(
        directory / "sessions" / hashlib.sha256(os.fsencode(project)).hexdigest()
    )
    agent = Agent(
        model if model is not None else default_model,
        name="superqode-pydantic-coder",
        defer_model_check=True,
        capabilities=[Coder(sub_agents=False), Permissions(mode="read-only")],
    )

    def session_config(session):
        if Path(session.cwd).resolve() != project:
            raise ValueError("Start a separate Pydantic Coder connection for this project")
        return ACPSessionConfig(
            deps=None,
            workspace=LocalWorkspaceBackend(project),
            toolsets=mcp_toolsets(session),
        )

    run_acp_stdio_sync(
        agent,
        name="superqode-pydantic-coder",
        version="0.75.0",
        session_config=session_config,
        session_store=store,
        models=model_ids(default_model),
        model_resolver=(lambda selected: model if model is not None else selected),
        mcp_capabilities=schema.McpCapabilities(http=True, sse=True),
        usage_limits=UsageLimits(request_limit=40, tool_calls_limit=80),
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument(
        "--model", default=os.environ.get("SUPERQODE_PYDANTIC_CODER_MODEL", "openai:gpt-4.1")
    )
    args = parser.parse_args()
    if args.check:
        print(json.dumps(check(), sort_keys=True))
        return
    if args.state_dir is None:
        parser.error("--state-dir is required")
    serve(args.state_dir, args.model)


if __name__ == "__main__":
    main()
