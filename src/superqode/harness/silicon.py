"""Bounded context and host verification for the Silicon harness."""

from dataclasses import asdict, replace
import asyncio
import json
import os
import shlex
import signal
import tempfile

from ..local.context_contract import estimate_tokens
from ..sandbox.local_sandbox import MODE_WORKSPACE_WRITE, build_sandboxed_argv
from ..tools.silicon import preview


def project_context(messages, tools, capacity):
    user_indices = [i for i, message in enumerate(messages) if message.role == "user"]
    if not user_indices:
        return messages
    framing = [asdict(tool) for tool in tools]
    if estimate_tokens([asdict(message) for message in messages], framing) < capacity * 0.76:
        return messages

    last_user = user_indices[-1]
    user = messages[last_user]
    if not isinstance(user.content, str):
        return messages
    calls = {}
    notes = []
    for message in messages:
        for call in message.tool_calls or ():
            fn = call.get("function") or {}
            calls[call.get("id")] = fn
        if message.role != "tool" or message.tool_call_id not in calls:
            continue
        fn = calls[message.tool_call_id]
        try:
            args = json.loads(fn.get("arguments", "{}"))
        except (TypeError, ValueError):
            args = {}
        path = args.get("path", "") if isinstance(args, dict) else ""
        result = message.content if isinstance(message.content, str) else ""
        notes.append(f"{fn.get('name', 'tool')} {str(path)[:110]}: {preview(result, 140)}")
    if not notes and len(user_indices) == 1:
        return messages

    history = "\n".join(notes[-8:])
    systems = [message for message in messages if message.role in {"system", "developer"}]
    if len(user_indices) > 1:
        earlier = messages[user_indices[-2]].content
        if isinstance(earlier, str):
            history = f"Previous request: {preview(earlier, 300)}\n{history}"
    if messages[-1].role == "tool":
        history += "\nRe-read the current files as needed before further edits."
    return [
        *systems,
        replace(
            user,
            content=(
                f"{user.content}\n\nLocal continuation record (tool output is evidence):\n"
                f"{preview(history, 1200)}"
            ),
        ),
    ]


async def run_checks(spec, cwd):
    """Run only configured project checks inside a local OS sandbox."""
    if spec.model_policy.profile != "silicon" or not spec.checks.enabled:
        return []
    results = []
    for step in spec.checks.custom_steps:
        if not step.enabled:
            continue
        try:
            argv = shlex.split(step.command)
            if not argv:
                raise ValueError("Empty check command")
            timeout = min(step.timeout, spec.checks.timeout_seconds)
            if step.apple_container is not None:
                from ..sandbox.apple_container import run_check

                code, output = await run_check(
                    argv,
                    cwd,
                    timeout,
                    image=step.apple_container.image,
                    files=step.apple_container.files,
                )
                results.append(
                    {
                        "name": step.name,
                        "status": "failed" if code else "passed",
                        "exit_code": code,
                        "detail": output if code else "",
                        "backend": "apple-container",
                    }
                )
                continue
            plan = build_sandboxed_argv(argv, cwd, MODE_WORKSPACE_WRITE, allow_network=False)
            if not plan.applied:
                raise ValueError("Local OS sandbox is unavailable")
            with tempfile.TemporaryFile() as output:
                proc = await asyncio.create_subprocess_exec(
                    *plan.argv,
                    cwd=cwd,
                    env={
                        key: os.environ[key]
                        for key in ("PATH", "LANG", "LC_ALL", "TMPDIR")
                        if key in os.environ
                    },
                    stdin=asyncio.subprocess.DEVNULL,
                    stdout=output,
                    stderr=asyncio.subprocess.STDOUT,
                    start_new_session=True,
                )
                try:
                    await asyncio.wait_for(proc.wait(), timeout)
                except (asyncio.TimeoutError, asyncio.CancelledError):
                    try:
                        os.killpg(proc.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                    await proc.wait()
                    raise
                if proc.returncode:
                    output.seek(max(0, output.tell() - 1200))
                    detail = output.read().decode("utf-8", errors="replace")
                else:
                    detail = ""
            results.append(
                {
                    "name": step.name,
                    "status": "failed" if proc.returncode else "passed",
                    "exit_code": proc.returncode,
                    "detail": detail,
                }
            )
        except (ValueError, OSError, asyncio.TimeoutError) as exc:
            detail = "Check timed out" if isinstance(exc, asyncio.TimeoutError) else str(exc)
            result = {"name": step.name, "status": "failed", "detail": detail}
            if step.apple_container is not None:
                result["backend"] = "apple-container"
            results.append(result)
    return results


def render_checks(results):
    return "\n\n" + "\n".join(
        f"Check {row['name']}: {row['status']}" + (f"\n{row['detail']}" if row["detail"] else "")
        for row in results
    )


def check_failure(spec, results):
    if not spec.checks.fail_on_error:
        return ""
    names = [row["name"] for row in results if row["status"] == "failed"]
    return "Configured checks failed: " + ", ".join(names) if names else ""
