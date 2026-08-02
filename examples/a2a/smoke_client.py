#!/usr/bin/env python3
"""Smoke-test the SuperQode A2A client against a live discovery URL.

Usage (from repo root, fish or bash):

  set -x SUPERQODE_A2A_TOKEN 'your-token'   # fish
  export SUPERQODE_A2A_TOKEN=your-token    # bash

  uv run --extra a2a python examples/a2a/smoke_client.py
  uv run --extra a2a python examples/a2a/smoke_client.py https://superqode.onrender.com
  uv run --extra a2a python examples/a2a/smoke_client.py https://super-agentic.ai "custom message"
"""

from __future__ import annotations

import asyncio
import os
import sys


async def main() -> int:
    discovery = sys.argv[1] if len(sys.argv) > 1 else "https://super-agentic.ai"
    message = (
        sys.argv[2]
        if len(sys.argv) > 2
        else "Reply with exactly: python-client-ok"
    )
    token = os.environ.get("SUPERQODE_A2A_TOKEN") or os.environ.get("TOKEN")
    if not token:
        print(
            "Missing SUPERQODE_A2A_TOKEN (or TOKEN).\n"
            "fish:  set -x SUPERQODE_A2A_TOKEN 'your-token'\n"
            "bash:  export SUPERQODE_A2A_TOKEN=your-token",
            file=sys.stderr,
        )
        return 2

    from superqode.a2a import A2AClient

    print(f"discovery: {discovery}")
    async with A2AClient(discovery, bearer_token=token, timeout=180.0) as client:
        card = await client.get_agent_card()
        print(f"agent:     {card.name}")
        print(f"version:   {card.version}")
        print(f"interface: {card.url}")
        print(f"message:   {message}")
        task = await client.send_message(message)
        text = ""
        if task.artifacts and task.artifacts[0].parts:
            text = task.artifacts[0].parts[0].text or ""
        print(f"task_id:   {task.task_id}")
        print(f"state:     {task.status.state}")
        print(f"text:      {text}")
        if str(task.status.state).endswith("completed") or str(task.status.state) == "completed":
            return 0
        # TaskStatusValue enum may print as "completed"
        from superqode.a2a.types import TaskStatusValue

        return 0 if task.status.state == TaskStatusValue.COMPLETED else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
