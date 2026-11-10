"""Small reproducible local coding evaluation, with real fixture/test execution.

This is not an OS sandbox or a benchmark certification. Model-written Python
runs with the invoking user's permissions, only after explicit CLI consent.
"""

import ast
import json
import math
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import asdict
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from superqode.agent.local_reliability import (
    LEAN_INSTRUCTIONS,
    ToolRetryBudget,
    compact_schema,
    extract_local_calls,
    lean_profile,
    repair_arguments,
)

from .context_contract import choose_contract, guard_request, memory_fit
from .hardware import detect_hardware
from .starter_registry import SUITE_VERSION, TASK_IDS, memory_tier, registry

_INITIAL = "def add(a, b):\n    return a - b\n"
_FIXED = "def add(a, b):\n    return a + b\n"
_TASKS = {
    "edit_file": (
        "def greeting():\n    return 'hello'\n",
        "Read solution.py, then use edit_file to make greeting() return exactly 'Hello, SuperQode!'.",
    ),
    "run_test": (_FIXED, "Run the fixed tests with run_test. Do not edit solution.py."),
    "fix_test": (
        _INITIAL,
        "Run run_test first. Fix the failing add(a,b) implementation in solution.py, then run run_test again.",
    ),
    "multi_step": (
        _INITIAL,
        "Read solution.py with read_file, edit add(a,b) to add its arguments, then verify with run_test.",
    ),
    "json_tool_call": (
        "",
        "Call submit_json with answer 42 and labels exactly ['local', 'tools']. Use a JSON tool call, not a prose answer.",
    ),
}


def local_endpoint(engine, base_url=None):
    """Literal loopback only. No credentials, proxy, query string or redirects."""
    if engine not in {"ollama", "lmstudio"}:
        raise ValueError("Evaluation supports only Ollama and LM Studio.")
    url = base_url or ("http://127.0.0.1:11434" if engine == "ollama" else "http://127.0.0.1:1234")
    parsed = urlsplit(url)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname not in {"127.0.0.1", "::1"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/") not in {"", "/v1"}
    ):
        raise ValueError(
            "Use a literal loopback endpoint, optionally ending in /v1, without credentials."
        )
    return f"{parsed.scheme}://{parsed.netloc}"


def _request(client, method, url, **kwargs):
    response = client.request(method, url, **kwargs)
    response.raise_for_status()
    return response.json()


def _identity(client, root, engine, runtime, tag):
    if engine == "ollama":
        models = _request(client, "GET", root + "/api/tags").get("models", [])
        model = next((m for m in models if runtime in {m.get("name"), m.get("model")}), None)
        if model is None:
            raise ValueError("The requested Ollama model is not installed.")
        artifact = {
            "digest": model.get("digest"),
            "size_bytes": model.get("size"),
            "details": model.get("details"),
        }
        return artifact, runtime == tag and bool(model.get("digest")), None
    models = _request(client, "GET", root + "/api/v1/models").get("models", [])
    for model in models:
        for instance in model.get("loaded_instances", []):
            if instance.get("id") != runtime:
                continue
            context = (instance.get("config") or {}).get("context_length")
            if type(context) is not int or context < 512:
                raise ValueError("LM Studio did not report the loaded instance's context length.")
            key = model.get("key", "")
            artifact = {
                key: model.get(key)
                for key in ("key", "size_bytes", "quantization", "selected_variant", "format")
            }
            return artifact, key == tag, context
    raise ValueError("Load the requested LM Studio model first and use its loaded instance id.")


def _tools(task):
    path = {"type": "string", "enum": ["solution.py"]}
    specs = {
        "read_file": ("Read the fixture file.", {"path": path}),
        "write_file": ("Replace the fixture file.", {"path": path, "content": {"type": "string"}}),
        "edit_file": (
            "Replace one exact occurrence in the fixture file.",
            {
                "path": path,
                "old_text": {"type": "string", "minLength": 1},
                "new_text": {"type": "string"},
            },
        ),
        "run_test": ("Run the fixed tests. No shell command is accepted.", {}),
        "submit_json": (
            "Submit the requested structured result.",
            {
                "answer": {"type": "integer", "const": 42},
                "labels": {"type": "array", "const": ["local", "tools"]},
            },
        ),
    }
    names = (
        ["submit_json"]
        if task == "json_tool_call"
        else ["read_file", "write_file", "edit_file", "run_test"]
    )
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": specs[name][0],
                "parameters": {
                    "type": "object",
                    "properties": specs[name][1],
                    "required": list(specs[name][1]),
                    "additionalProperties": False,
                },
            },
        }
        for name in names
    ]


def _execute(name, args, folder):
    path = folder / "solution.py"
    if name == "read_file":
        return path.read_text(), True
    if name == "write_file":
        path.write_text(args["content"])
        return "File written.", True
    if name == "edit_file":
        text = path.read_text()
        if text.count(args["old_text"]) != 1:
            return "Old text must match exactly once.", False
        path.write_text(text.replace(args["old_text"], args["new_text"], 1))
        return "File edited.", True
    if name == "run_test":
        marker = "SQ_EVAL_PASS_" + uuid.uuid4().hex
        program = (
            "import runpy\n"
            "m=runpy.run_path('solution.py')\n"
            "assert m['add'](2,3)==5\n"
            "assert m['add'](-4,7)==3\n"
            "assert m['add'](0,0)==0\n"
            f"print({marker!r})\n"
        )
        try:
            proc = subprocess.run(
                [sys.executable, "-I", "-B", "-c", program],
                cwd=folder,
                capture_output=True,
                text=True,
                timeout=15,
                check=False,
            )
            passed = proc.returncode == 0 and proc.stdout.strip().endswith(marker)
            return (
                "Fixed tests passed." if passed else "Fixed tests failed.\n" + proc.stderr[-2000:]
            ), passed
        except subprocess.TimeoutExpired:
            return "Fixed tests timed out after 15 seconds.", False
    if name == "submit_json":
        return "Structured result accepted.", True
    return "Unknown tool.", False


def _passed(task, folder, history):
    successful = [name for name, ok in history if ok]
    if task == "json_tool_call":
        return "submit_json" in successful
    if task == "edit_file":
        if "edit_file" not in successful:
            return False
        try:
            tree = ast.parse((folder / "solution.py").read_text())
            function = next(
                n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "greeting"
            )
            return (
                len(function.body) == 1
                and isinstance(function.body[0], ast.Return)
                and ast.literal_eval(function.body[0].value) == "Hello, SuperQode!"
            )
        except (ValueError, SyntaxError, StopIteration, TypeError):
            return False
    if task == "run_test":
        return "run_test" in successful and (folder / "solution.py").read_text() == _FIXED
    if task == "fix_test":
        return (
            len(history) >= 3
            and history[0] == ("run_test", False)
            and any(n in {"edit_file", "write_file"} for n in successful)
            and history[-1] == ("run_test", True)
        )
    if task == "multi_step":
        return (
            len(history) >= 3
            and history[0] == ("read_file", True)
            and "edit_file" in successful
            and history[-1] == ("run_test", True)
        )
    return False


def _chat(client, root, engine, model, messages, tools, context, max_tokens):
    kept, output = guard_request(messages, tools, context, max_tokens)
    payload = {
        "model": model,
        "messages": [messages[i] for i in kept],
        "tools": tools,
        "stream": False,
    }
    if engine == "ollama":
        payload["options"] = {"num_ctx": context, "num_predict": output, "temperature": 0}
        response = _request(client, "POST", root + "/api/chat", json=payload)
        return response["message"], response.get("eval_count")
    payload.update(max_tokens=output, temperature=0)
    response = _request(client, "POST", root + "/v1/chat/completions", json=payload)
    return response["choices"][0]["message"], (response.get("usage") or {}).get("completion_tokens")


def _run_task(client, root, engine, runtime, task, folder, context, max_tokens):
    source, prompt = _TASKS[task]
    (folder / "solution.py").write_text(source)
    tools = _tools(task)
    lean = lean_profile(engine, runtime, context)
    if lean:
        for tool in tools:
            function = tool["function"]
            function["parameters"] = compact_schema(function["parameters"])
    system = "You are a coding assistant. Use the supplied tools to complete the task."
    if lean:
        system += " " + LEAN_INSTRUCTIONS
    messages = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    history = []
    valid = repaired = invalid = text_calls = 0
    token_total = 0
    token_usage_complete = True
    request_seconds = 0
    budget = ToolRetryBudget()
    error = None
    started = time.perf_counter()
    try:
        for _ in range(10):
            request_start = time.perf_counter()
            message, tokens = _chat(
                client, root, engine, runtime, messages, tools, context, max_tokens
            )
            request_seconds += time.perf_counter() - request_start
            if type(tokens) is int and tokens >= 0:
                token_total += tokens
            else:
                token_usage_complete = False
            content = message.get("content") or ""
            calls = message.get("tool_calls") or []
            from_text = not calls
            if from_text:
                content, calls = extract_local_calls(content)
                text_calls += len(calls)
            if not calls:
                break
            parsed = []
            for index, call in enumerate(calls):
                function = call.get("function") or {}
                if not isinstance(function, dict):
                    function = {}
                name = function.get("name", "")
                definition = next(
                    (t["function"] for t in tools if t["function"]["name"] == name), None
                )
                if definition:
                    args, problem, fixed = repair_arguments(
                        function.get("arguments"), definition["parameters"]
                    )
                else:
                    args, problem, fixed = {}, "Use only the listed tools.", False
                repaired += int(fixed or from_text)
                invalid += int(problem is not None)
                valid += int(problem is None)
                call_id = call.get("id") or f"eval-{index}-{uuid.uuid4().hex[:8]}"
                parsed.append((name, call_id, args, problem))
            problems = [p for _, _, _, p in parsed if p]
            if problems and not budget.correction():
                error = "Invalid tool calls after two corrective retries."
                break
            assistant = {"role": "assistant", "content": content, "tool_calls": []}
            for name, call_id, args, _problem in parsed:
                # Preserve native Ollama argument objects, OpenAI uses JSON strings.
                assistant["tool_calls"].append(
                    {
                        "id": call_id,
                        "type": "function",
                        "function": {
                            "name": name,
                            "arguments": args if engine == "ollama" else json.dumps(args),
                        },
                    }
                )
            messages.append(assistant)
            for name, call_id, args, _problem in parsed:
                if problems:
                    result = "Batch not executed. Correct the JSON tool arguments: " + problems[0]
                else:
                    result, ok = _execute(name, args, folder)
                    history.append((name, ok))
                tool_message = {"role": "tool", "content": result}
                tool_message.update(
                    {"tool_name": name} if engine == "ollama" else {"tool_call_id": call_id}
                )
                messages.append(tool_message)
            if _passed(task, folder, history):
                break
    except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError) as exc:
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started
    measured_tokens = token_total if token_usage_complete else None
    return {
        "id": task,
        "passed": not error and _passed(task, folder, history),
        "tool_calls_valid": invalid == 0 and valid > 0,
        "native_tool_calls_valid": invalid == 0 and repaired == 0 and valid > 0,
        "tool_calls": valid + invalid,
        "repaired_calls": repaired,
        "text_calls": text_calls,
        "invalid_calls": invalid,
        "corrective_retries": budget.used,
        "lean_mode": lean,
        "completion_tokens": measured_tokens,
        "elapsed_seconds": round(elapsed, 6),
        "request_seconds": round(request_seconds, 6),
        "tokens_per_second": (
            round(measured_tokens / request_seconds, 3)
            if measured_tokens is not None and request_seconds > 0
            else None
        ),
        "tools_executed": [{"name": n, "success": ok} for n, ok in history],
        "error": error,
    }


def run_evaluation(
    engine,
    registry_model,
    runtime_model=None,
    *,
    output,
    base_url=None,
    context=None,
    allow_execution=False,
    client=None,
):
    """Run five bounded tasks and write evidence. Injected transports are simulated."""
    if not allow_execution:
        raise ValueError(
            "Explicit --allow-execution consent is required: model-written Python is not sandboxed."
        )
    root = local_endpoint(engine, base_url)
    entry = next((r for r in registry() if r["id"] == registry_model), None)
    if entry is None:
        raise ValueError("Select a curated registry model id.")
    output = Path(output)
    if output.exists():
        raise ValueError(
            "Choose a new output file; existing evaluation reports are not overwritten."
        )
    runtime = runtime_model or entry["engines"][engine]
    hardware = detect_hardware()
    contract = choose_contract(entry["engines"][engine], hardware, provider=engine, context=context)
    owned = client is None
    client = client or httpx.Client(timeout=180, trust_env=False, follow_redirects=False)
    try:
        artifact, identified, actual = _identity(
            client, root, engine, runtime, entry["engines"][engine]
        )
        if not identified:
            raise ValueError(
                "The endpoint did not identify this exact curated catalog model. "
                "Review its native model listing before evaluating or promoting an alias."
            )
        size = artifact.get("size_bytes")
        fit = memory_fit(
            entry["engines"][engine],
            hardware.available_memory_gb,
            actual or contract.context,
            weights_gb=size / 1024**3 if isinstance(size, (int, float)) and size > 0 else None,
            kv_cache="f16",
            apple=hardware.is_apple_silicon,
        )
        if fit["rating"] != "Fits":
            raise ValueError(
                "This model's loaded/requested context is not marked Fits for this Mac. "
                "Choose a smaller model or reload with a lower context before evaluating."
            )
        effective_context = min(contract.context, actual) if actual else contract.context
        workspace = Path(tempfile.mkdtemp(prefix="superqode-local-eval-"))
        report = {
            "suite": SUITE_VERSION,
            "execution_mode": "local-model" if owned else "simulated",
            "completed": False,
            "engine": engine,
            "registry_model": registry_model,
            "catalog_tag": entry["engines"][engine],
            "runtime_model": runtime,
            "artifact": artifact,
            "identity_verified": identified,
            "hardware": asdict(hardware),
            "memory_tier": memory_tier(hardware.available_memory_gb or 0),
            "context": effective_context,
            "requested_context": contract.context,
            "loaded_context": actual,
            "max_tokens": contract.max_tokens,
            "fit": fit,
            "workspace": str(workspace),
            "endpoint": root,
            "speed_measure": "reported completion tokens / request wall time, including prompt processing",
            "tasks": [],
        }
        for task in TASK_IDS:
            folder = workspace / task
            folder.mkdir()
            report["tasks"].append(
                _run_task(
                    client,
                    root,
                    engine,
                    runtime,
                    task,
                    folder,
                    effective_context,
                    contract.max_tokens,
                )
            )
        report["completed"] = True
        report["passed"] = all(t["passed"] and t["tool_calls_valid"] for t in report["tasks"])
        # Strict JSON: no non-finite timing or speed values can enter evidence.
        assert all(math.isfinite(t["elapsed_seconds"]) for t in report["tasks"])
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x") as stream:
            json.dump(report, stream, indent=2, allow_nan=False)
            stream.write("\n")
        return report
    finally:
        if owned:
            client.close()
