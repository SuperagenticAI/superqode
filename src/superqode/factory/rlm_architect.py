"""On-Demand Software Factory architect powered by SuperQode's RLM context engine.

Mounts a repository lazily as read-only data (``RLMContext``), inspects manifests,
test suites, workflows, and high-risk areas inside the Monty sandboxed REPL when
available (falling back to the same read-only ``RLMContext`` API otherwise), and
optionally issues bounded recursive ``llm_query`` sub-calls to synthesize a
repo-native, schema-validated 7-layer ``FactorySpec`` proposal.

Nothing is written to disk and no agent executes during inspection: output is
always a reviewable Factories-as-Code proposal that preserves ``release_authority``.
"""

from __future__ import annotations

import ast
import asyncio
from dataclasses import asdict
import json
from pathlib import Path
import re
import time
from typing import Any

import yaml

from superqode.rlm.context import ContextPolicy, RLMContext
from superqode.rlm.subcalls import SubcallPolicy, SubcallUsage

from .definition import SCHEMA, read_mapping, validate_definition
from .generation import check_generation_route
from .templates import TEMPLATE_NAMES, explicit_workflow, factory_template

DEFAULT_GOAL = (
    "Build a safe, verified Software Factory tailored to this repository's stack, "
    "tests, and risk profile."
)

#: Sensitive directory/path tokens that raise merge risk and favor a two-gate workflow.
_SENSITIVE_HINTS = (
    "auth",
    "security",
    "permission",
    "credential",
    "secret",
    "migration",
    "schema",
    "billing",
    "payment",
    "deploy",
    "infra",
    "terraform",
    ".github/workflows",
)

#: Excluded from read-only inspection so secrets, lockfiles, and protected evaluators stay masked.
_INSPECT_EXCLUDES = (
    ".superqode/**",
    ".git/**",
    ".env",
    ".env.*",
    "**/.env",
    "**/.env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.lock",
    "package-lock.json",
    "uv.lock",
    "yarn.lock",
    "pnpm-lock.yaml",
)

#: Manifest files read selectively via ``context.read(...)`` (never dumping the full repo).
_MANIFEST_CANDIDATES = (
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "package.json",
    "Package.swift",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "README.md",
    "self_check.py",
)

#: Monty-compatible inspection script using only the standard ``RLMContext`` methods.
_MONTY_INSPECT_PROGRAM = """
stats = context.stats()
files = context.files()
top_dirs = []
seen_dirs = set()
for item in files:
    if "/" in item:
        head = item.split("/", 1)[0]
        if head not in seen_dirs:
            seen_dirs.add(head)
            top_dirs.append(head)
top_dirs = sorted(top_dirs)[:30]
manifests = {}
wanted = [
    "pyproject.toml",
    "setup.py",
    "requirements.txt",
    "package.json",
    "Package.swift",
    "Cargo.toml",
    "go.mod",
    "Makefile",
    "README.md",
    "self_check.py",
]
file_set = set(files)
for name in wanted:
    if name in file_set:
        manifests[name] = context.read(name)[:4000]
workflows = [f for f in files if f.startswith(".github/workflows/") and (f.endswith(".yml") or f.endswith(".yaml"))][:3]
for wf in workflows:
    manifests[wf] = context.read(wf)[:3000]
{"stats": stats, "files": files[:400], "total_files": len(files), "top_dirs": top_dirs, "manifests": manifests}
"""


def _slugify_factory_name(raw: str) -> str:
    slug = re.sub(r"[^a-z0-9-]+", "-", raw.lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)
    if not slug or not slug[0].isalpha():
        slug = f"repo-{slug}" if slug else "repo-factory"
    return slug[:64].rstrip("-") or "repo-factory"


def _inspect_with_context(context: RLMContext) -> dict[str, Any]:
    stats = context.stats()
    files = context.files()
    top_dirs = sorted({item.split("/", 1)[0] for item in files if "/" in item})[:30]
    file_set = set(files)
    manifests: dict[str, str] = {}
    for name in _MANIFEST_CANDIDATES:
        if name in file_set:
            try:
                manifests[name] = context.read(name)[:4000]
            except (OSError, ValueError):
                continue
    workflows = [
        item
        for item in files
        if item.startswith(".github/workflows/") and item.endswith((".yml", ".yaml"))
    ][:3]
    for wf in workflows:
        try:
            manifests[wf] = context.read(wf)[:3000]
        except (OSError, ValueError):
            continue
    return {
        "engine": "rlm-context",
        "stats": stats,
        "files": files[:400],
        "total_files": len(files),
        "top_dirs": top_dirs,
        "manifests": manifests,
    }


async def _inspect_with_monty(root: Path, context: RLMContext) -> dict[str, Any] | None:
    """Run the read-only inspection script inside SuperQode's Monty sandbox when available."""
    try:
        from superqode.rlm.kernel_monty import MontyKernelBackend, MontyUnavailableError, load_monty
        from superqode.rlm.sandbox import RLMSandboxConfig
    except Exception:  # noqa: BLE001
        return None
    try:
        load_monty()
    except MontyUnavailableError:
        return None

    import tempfile

    with tempfile.TemporaryDirectory(prefix="sq-rlm-architect-") as state_dir:
        backend = MontyKernelBackend(
            root,
            config=RLMSandboxConfig(backend="monty", python_timeout=15.0),
            session_id="factory-architect",
            state_dir=state_dir,
            context=context,
            loop=asyncio.get_running_loop(),
        )
        try:
            await asyncio.wait_for(backend.start(), timeout=10.0)
            result = await asyncio.wait_for(
                backend.execute("architect", _MONTY_INSPECT_PROGRAM),
                timeout=20.0,
            )
            if result.error:
                return None
            value = ast.literal_eval(result.value_repr) if result.value_repr else None
            if isinstance(value, dict) and "stats" in value and "manifests" in value:
                return {"engine": "monty-repl", **value}
        except Exception:  # noqa: BLE001
            return None
        finally:
            try:
                await backend.close()
            except Exception:  # noqa: BLE001
                pass
    return None


def _detect_signals(raw: dict[str, Any], *, root: Path, description: str) -> dict[str, Any]:
    files: list[str] = list(raw.get("files") or [])
    manifests: dict[str, str] = dict(raw.get("manifests") or {})
    total_files = int(raw.get("total_files") or len(files))
    stats = dict(raw.get("stats") or {})

    stacks: list[str] = []
    has_py = (
        "pyproject.toml" in manifests
        or "setup.py" in manifests
        or "requirements.txt" in manifests
        or any(f.endswith(".py") for f in files)
    )
    has_node = "package.json" in manifests or any(
        f.endswith((".ts", ".tsx", ".js", ".jsx")) for f in files
    )
    has_swift = (
        "Package.swift" in manifests
        or any(f.endswith(".swift") for f in files)
        or any(".xcodeproj" in f for f in files)
    )
    has_rust = "Cargo.toml" in manifests or any(f.endswith(".rs") for f in files)
    has_go = "go.mod" in manifests or any(f.endswith(".go") for f in files)

    for label, flag in (
        ("python", has_py),
        ("node", has_node),
        ("swift", has_swift),
        ("rust", has_rust),
        ("go", has_go),
    ):
        if flag:
            stacks.append(label)

    # Detect test and build commands from real manifests.
    test_command = ""
    build_command = ""
    gotchas: list[str] = []

    pkg_text = manifests.get("package.json", "")
    pkg_json: dict[str, Any] = {}
    if pkg_text:
        try:
            parsed = json.loads(pkg_text)
            if isinstance(parsed, dict):
                pkg_json = parsed
        except json.JSONDecodeError:
            pkg_json = {}
    pkg_scripts = pkg_json.get("scripts") if isinstance(pkg_json.get("scripts"), dict) else {}
    pkg_deps = {
        **(pkg_json.get("dependencies") if isinstance(pkg_json.get("dependencies"), dict) else {}),
        **(
            pkg_json.get("devDependencies")
            if isinstance(pkg_json.get("devDependencies"), dict)
            else {}
        ),
    }

    pyproject = manifests.get("pyproject.toml", "")
    if "self_check.py" in manifests and not pyproject:
        test_command = "python3 self_check.py"
    elif has_py:
        if "pytest" in pyproject.lower() or any(
            f.startswith("tests/") or Path(f).name.startswith("test_") for f in files
        ):
            test_command = "pytest -q"
        else:
            test_command = "python3 -m unittest discover"
        if "uv" in pyproject.lower() or "tool.uv" in pyproject.lower():
            gotchas.append("Python project uses uv/pyproject.toml; verify with the active venv.")

    if has_node:
        if isinstance(pkg_scripts.get("test"), str) and pkg_scripts["test"].strip():
            if not test_command:
                test_command = "npm test"
        if isinstance(pkg_scripts.get("build"), str) and pkg_scripts["build"].strip():
            build_command = "npm run build"

    if has_swift:
        if not test_command:
            test_command = "swift test"
        if not build_command:
            build_command = "swift build"
        gotchas.append(
            "Swift/macOS targets should keep build artifacts inside the isolated worktree."
        )

    if has_rust:
        if not test_command:
            test_command = "cargo test"
        if not build_command:
            build_command = "cargo build"

    if has_go:
        if not test_command:
            test_command = "go test ./..."
        if not build_command:
            build_command = "go build ./..."

    if not test_command:
        test_command = "pytest -q" if has_py else "echo 'Configure project regression command'"

    # Detect UI verification preset (`web`, `macos`, or `cli`).
    web_markers = {"react", "next", "vite", "vue", "svelte", "@playwright/test", "playwright"}
    is_web = bool(web_markers & set(pkg_deps)) or any(
        f.endswith((".tsx", ".jsx", ".vue", ".svelte", ".html")) for f in files
    )
    is_macos = has_swift and (
        any("SwiftUI" in manifests.get(k, "") for k in manifests)
        or any("apps/macos" in f or f.endswith("View.swift") for f in files)
    )
    if is_web:
        ui_preset = "web"
        gotchas.append(
            "Capture Playwright screenshots into .superqode/factory-proof/ for UI changes."
        )
    elif is_macos:
        ui_preset = "macos"
        gotchas.append("Verify SwiftUI changes via swift test and macOS visual proof captures.")
    else:
        ui_preset = "cli"

    # Detect sensitive / high-impact areas.
    sensitive_areas: list[str] = []
    seen_sensitive: set[str] = set()
    for path in files:
        lower = path.lower()
        for hint in _SENSITIVE_HINTS:
            if hint in lower:
                area = path.split("/", 2)[:2]
                label = "/".join(area) if len(area) > 1 else area[0]
                if label not in seen_sensitive:
                    seen_sensitive.add(label)
                    sensitive_areas.append(label)
                break
        if len(sensitive_areas) >= 8:
            break

    # Choose best-fit workflow from user description + repo complexity.
    chosen_workflow = explicit_workflow(description) if description.strip() else ""
    if not chosen_workflow:
        if total_files >= 15 or len(stacks) > 1 or bool(sensitive_areas):
            chosen_workflow = "triage-spec-build"
        else:
            chosen_workflow = "fix-and-verify"

    recommended_skills = [
        {
            "name": "merge-risk",
            "preset": "",
            "reason": (
                f"Flags blast radius across sensitive paths ({', '.join(sensitive_areas[:3])})"
                if sensitive_areas
                else "Evaluates 5-dimension merge risk and rollback cost before handoff"
            ),
        },
        {
            "name": "ui-verification",
            "preset": ui_preset,
            "reason": f"Matches detected {ui_preset.upper()} surface and collects Visual Proof",
        },
    ]

    return {
        "repo_name": root.name or "repo",
        "repo_files": total_files,
        "repo_bytes": int(stats.get("bytes") or 0),
        "top_dirs": list(raw.get("top_dirs") or []),
        "files_inspected": sorted(manifests.keys()),
        "detected_stacks": stacks or ["general"],
        "detected_test_command": test_command,
        "detected_build_command": build_command,
        "ui_preset": ui_preset,
        "sensitive_areas": sensitive_areas,
        "recommended_workflow": chosen_workflow,
        "recommended_skills": recommended_skills,
        "gotchas": gotchas,
        "manifests": manifests,
    }


def _extract_json_object(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1] if "\n" in cleaned else cleaned[3:]
        if cleaned.endswith("```"):
            cleaned = cleaned.rsplit("```", 1)[0].strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1 and end > start:
        cleaned = cleaned[start : end + 1]
    parsed = json.loads(cleaned)
    if not isinstance(parsed, dict):
        raise ValueError("Expected JSON object from RLM sub-call")
    return parsed


async def _run_bounded_subcalls(
    *,
    signals: dict[str, Any],
    description: str,
    provider: str,
    model: str,
    gateway: Any,
    policy: SubcallPolicy,
) -> tuple[dict[str, Any], list[dict[str, Any]], SubcallUsage]:
    """Issue up to two bounded recursive sub-calls over compact repo slices."""
    from superqode.providers.gateway import GatewayFactory, Message

    client = gateway or GatewayFactory.create(timeout=min(int(policy.timeout), 45))
    usage = SubcallUsage()
    subcalls: list[dict[str, Any]] = []
    refinements: dict[str, Any] = {}

    manifest_summary = {
        name: content[:1400] for name, content in list(signals["manifests"].items())[:4]
    }
    base_slice = {
        "repo_name": signals["repo_name"],
        "repo_files": signals["repo_files"],
        "top_dirs": signals["top_dirs"][:16],
        "detected_stacks": signals["detected_stacks"],
        "detected_test_command": signals["detected_test_command"],
        "detected_build_command": signals["detected_build_command"],
        "sensitive_areas": signals["sensitive_areas"],
        "default_workflow": signals["recommended_workflow"],
        "available_workflows": list(TEMPLATE_NAMES),
        "manifests": manifest_summary,
    }

    tasks = [
        (
            "subcall-1",
            "architecture-and-stages",
            list(manifest_summary.keys()),
            (
                "You are an RLM sub-call inspecting a compact repository slice to design a "
                "SuperQode Software Factory. Return ONLY compact JSON with keys: "
                "workflow (one of available_workflows), stage_guidance (object mapping stage id "
                "to one concise sentence tailored to this repo), and assumptions (list of up to 4 "
                "short grounded observations). Never invent files or commands not supported by "
                "the slice."
            ),
            json.dumps({"goal": description, "slice": base_slice}, ensure_ascii=False)[
                : policy.max_prompt_chars
            ],
        ),
        (
            "subcall-2",
            "verification-and-risk",
            list(manifest_summary.keys()),
            (
                "You are an RLM sub-call designing verification checks and merge-risk requirements "
                "for a SuperQode Software Factory. Return ONLY compact JSON with keys: "
                "test_command (short shell command string grounded in the repo, or empty string), "
                "ui_preset ('web', 'macos', or 'cli'), requirements (object mapping short kebab-case "
                "id to concise requirement text, max 4 items), and gotchas (list of up to 3 repo "
                "verification gotchas)."
            ),
            json.dumps(
                {
                    "goal": description,
                    "detected_test_command": signals["detected_test_command"],
                    "ui_preset": signals["ui_preset"],
                    "sensitive_areas": signals["sensitive_areas"],
                    "manifests": manifest_summary,
                },
                ensure_ascii=False,
            )[: policy.max_prompt_chars],
        ),
    ]

    for call_id, topic, files_used, system_prompt, user_prompt in tasks[: policy.max_calls]:
        started = time.monotonic()
        record: dict[str, Any] = {
            "id": call_id,
            "topic": topic,
            "files": files_used,
            "prompt_chars": len(user_prompt),
            "ok": False,
            "input_tokens": 0,
            "output_tokens": 0,
            "duration_ms": 0,
            "error": "",
        }
        try:
            response = await asyncio.wait_for(
                client.chat_completion(
                    messages=[
                        Message(role="system", content=system_prompt),
                        Message(role="user", content=user_prompt),
                    ],
                    model=model,
                    provider=provider,
                    max_tokens=1200,
                    temperature=0.1,
                    tools=[],
                ),
                timeout=min(policy.timeout, 45.0),
            )
            usage.calls += 1
            raw_usage = getattr(response, "usage", None)
            if raw_usage is not None:
                in_tok = int(
                    getattr(raw_usage, "prompt_tokens", 0) or getattr(raw_usage, "input", 0) or 0
                )
                out_tok = int(
                    getattr(raw_usage, "completion_tokens", 0)
                    or getattr(raw_usage, "output", 0)
                    or 0
                )
                usage.input_tokens += in_tok
                usage.output_tokens += out_tok
                usage.total_tokens += in_tok + out_tok
                record["input_tokens"] = in_tok
                record["output_tokens"] = out_tok
            parsed = _extract_json_object(response.content or "")
            refinements[topic] = parsed
            record["ok"] = True
        except Exception as exc:  # noqa: BLE001 - bounded sub-calls fall back cleanly
            usage.failures += 1
            record["error"] = str(exc)[:200]
        record["duration_ms"] = int((time.monotonic() - started) * 1000)
        subcalls.append(record)

    return refinements, subcalls, usage


def _compose_factory_spec(
    *,
    signals: dict[str, Any],
    refinements: dict[str, Any],
    base_data: dict[str, Any] | None,
    description: str,
    workflow_override: str,
    provider: str,
    model: str,
) -> tuple[dict[str, Any], list[str], list[str], list[dict[str, str]]]:
    arch = refinements.get("architecture-and-stages") or {}
    verif = refinements.get("verification-and-risk") or {}

    chosen_workflow = (
        workflow_override
        if workflow_override in TEMPLATE_NAMES
        else str(arch.get("workflow") or "").strip()
    )
    if chosen_workflow not in TEMPLATE_NAMES:
        chosen_workflow = signals["recommended_workflow"]

    spec = factory_template(chosen_workflow)
    spec["metadata"]["name"] = _slugify_factory_name(signals["repo_name"])
    spec["metadata"]["description"] = (
        description.strip()[:240]
        if description.strip()
        else f"RLM-architected {chosen_workflow} factory for {signals['repo_name']}."
    )

    # Preserve existing route policy and immutable release_authority from current draft.
    if base_data:
        for key in ("default_route", "routes"):
            if key in base_data:
                spec[key] = base_data[key]
        if isinstance(base_data.get("governance"), dict) and base_data["governance"].get(
            "release_authority"
        ):
            spec["governance"]["release_authority"] = base_data["governance"]["release_authority"]

    # Wire real detected test command into the regression check.
    test_command = str(verif.get("test_command") or "").strip() or signals["detected_test_command"]
    if len(test_command) > 240 or "\n" in test_command:
        test_command = signals["detected_test_command"]
    checks = spec.setdefault("improvement", {}).setdefault("checks", {})
    if "regression" in checks and isinstance(checks["regression"], dict):
        checks["regression"]["command"] = test_command
    else:
        checks["regression"] = {"command": test_command, "files": []}

    # Optionally bind the explicitly chosen model ref to harnesses.
    if provider and model:
        model_ref = f"{provider}/{model}"
        for harness in spec.get("inference", {}).get("harnesses", {}).values():
            if isinstance(harness, dict):
                harness["model"] = model_ref

    # Tailor stage goals lightly with grounded repo context (keeping contracts valid).
    stage_guidance = (
        arch.get("stage_guidance") if isinstance(arch.get("stage_guidance"), dict) else {}
    )
    for stage in spec.get("orchestration", {}).get("stages", []):
        stage_id = str(stage.get("id") or "")
        extra = str(stage_guidance.get(stage_id) or "").strip()
        if extra and len(extra) <= 280:
            base_goal = str(stage.get("goal") or "").strip()
            stage["goal"] = f"{base_goal} Repo note: {extra}" if base_goal else extra

    # Add grounded requirements bound to real stage and acceptance check IDs.
    stage_ids = [
        str(s["id"]) for s in spec.get("orchestration", {}).get("stages", []) if s.get("id")
    ]
    acceptance_checks = list(spec.get("orchestration", {}).get("acceptance_checks") or [])
    req_stages = [stage_ids[-1]] if stage_ids else []
    reqs: dict[str, dict[str, Any]] = {}
    raw_reqs = verif.get("requirements") if isinstance(verif.get("requirements"), dict) else {}
    if req_stages and acceptance_checks:
        for key, val in list(raw_reqs.items())[:4]:
            k = _slugify_factory_name(str(key))[:48]
            v = str(val).strip()[:240]
            if k and v:
                reqs[k] = {
                    "description": v,
                    "stages": req_stages,
                    "checks": acceptance_checks,
                }
        if not reqs:
            reqs["regression-green"] = {
                "description": f"Run `{test_command}` and report real pass/fail evidence.",
                "stages": req_stages,
                "checks": acceptance_checks,
            }
            if signals["sensitive_areas"]:
                reqs["risk-review"] = {
                    "description": (
                        f"Assess blast radius and rollback cost for sensitive paths "
                        f"({', '.join(signals['sensitive_areas'][:3])})."
                    ),
                    "stages": req_stages,
                    "checks": acceptance_checks,
                }
    spec.setdefault("data_context", {})["requirements"] = reqs

    # Finalize recommended skills with refined ui_preset.
    ui_preset = str(verif.get("ui_preset") or "").strip().lower()
    if ui_preset not in {"web", "macos", "cli"}:
        ui_preset = signals["ui_preset"]
    recommended_skills = [
        {
            "name": "merge-risk",
            "preset": "",
            "reason": (
                f"Guards sensitive paths ({', '.join(signals['sensitive_areas'][:3])})"
                if signals["sensitive_areas"]
                else "Adds 5-dimension Merge Risk self-mitigation before handoff"
            ),
        },
        {
            "name": "ui-verification",
            "preset": ui_preset,
            "reason": f"Matches detected {ui_preset.upper()} surface and captures Visual Proof",
        },
    ]

    assumptions: list[str] = [
        (
            f"Inspected {signals['repo_files']} repository files lazily via RLMContext "
            f"(read {len(signals['files_inspected'])} manifests/workflows; stack: "
            f"{', '.join(signals['detected_stacks'])})."
        ),
        f"Selected `{chosen_workflow}` workflow with regression check `{test_command}`.",
        (
            f"Recommended built-in skills: `merge-risk` and `ui-verification` "
            f"(`{ui_preset}` preset)."
        ),
    ]
    for item in arch.get("assumptions") if isinstance(arch.get("assumptions"), list) else []:
        text = str(item).strip()
        if text and len(assumptions) < 8:
            assumptions.append(text[:300])

    missing_capabilities: list[str] = []
    if not spec.get("governance", {}).get("release_authority"):
        missing_capabilities.append(
            "Enroll a Touch ID / P-256 release signing key before applying verified candidates."
        )
    missing_capabilities.append(
        "Add protected acceptance probes in Build -> Acceptance checks for deterministic SuperGauge gating."
    )

    # Validate strictly against the 7-layer FactorySpec schema and credential guard.
    from superqode.desktop_service.studio import _credentials

    validate_definition(spec)
    _credentials(spec)
    # Double-check SCHEMA keys exist.
    for required_key in SCHEMA.get("required", ()):
        if required_key not in spec:
            raise ValueError(f"Generated FactorySpec missing required layer: {required_key}")

    return spec, assumptions, missing_capabilities, recommended_skills


async def architect_factory(
    root: str | Path,
    *,
    description: str = "",
    yaml_text: str = "",
    workflow: str = "",
    provider: str = "",
    model: str = "",
    gateway: Any = None,
    use_monty: bool = True,
) -> dict[str, Any]:
    """Inspect a repository with SuperQode's RLM context engine and propose a FactorySpec."""
    started = time.monotonic()
    repo_root = Path(root).expanduser().resolve()
    if not repo_root.is_dir():
        raise ValueError(f"Repository path does not exist: {repo_root}")
    if len(description) > 8000:
        raise ValueError("Factory description exceeds 8000 characters")

    base_data: dict[str, Any] | None = None
    if yaml_text.strip():
        candidate = read_mapping(yaml_text)
        if "apiVersion" in candidate:
            validate_definition(candidate)
            base_data = candidate

    policy = ContextPolicy(
        max_files=2000,
        max_file_bytes=200_000,
        max_total_bytes=6_000_000,
        exclude=_INSPECT_EXCLUDES,
    )
    context = RLMContext(repo_root, policy=policy)

    raw: dict[str, Any] | None = None
    if use_monty:
        raw = await _inspect_with_monty(repo_root, context)
    if raw is None:
        raw = await asyncio.to_thread(_inspect_with_context, context)

    goal = description.strip() or DEFAULT_GOAL
    signals = _detect_signals(raw, root=repo_root, description=goal)

    # Respect private route policy before issuing any model sub-calls.
    allow_live_subcalls = bool(provider and model)
    route_note = ""
    if allow_live_subcalls and base_data:
        try:
            check_generation_route(base_data, provider, model)
        except ValueError as exc:
            if "local drafting model" not in str(exc):
                raise
            allow_live_subcalls = False
            route_note = (
                "Private route prevented cloud RLM sub-calls; built proposal from local RLM "
                "repository inspection only."
            )

    subcall_policy = SubcallPolicy(
        max_calls=4,
        max_batch=3,
        max_concurrency=2,
        max_prompt_chars=24_000,
        max_response_chars=12_000,
        timeout=45.0,
    )
    refinements: dict[str, Any] = {}
    subcalls: list[dict[str, Any]] = []
    usage = SubcallUsage()

    if allow_live_subcalls:
        refinements, subcalls, usage = await _run_bounded_subcalls(
            signals=signals,
            description=goal,
            provider=provider,
            model=model,
            gateway=gateway,
            policy=subcall_policy,
        )

    spec, assumptions, missing_capabilities, recommended_skills = _compose_factory_spec(
        signals=signals,
        refinements=refinements,
        base_data=base_data,
        description=goal,
        workflow_override=workflow if workflow in TEMPLATE_NAMES else "",
        provider=provider if allow_live_subcalls else "",
        model=model if allow_live_subcalls else "",
    )
    if route_note:
        assumptions.insert(0, route_note)
    if not allow_live_subcalls and not route_note:
        assumptions.append(
            "Built locally from RLM repository inspection with no model calls; connect a model "
            "to enable recursive sub-call refinement."
        )

    duration_ms = int((time.monotonic() - started) * 1000)
    mode = (
        "rlm-live"
        if allow_live_subcalls and any(item["ok"] for item in subcalls)
        else "rlm-local-inspect"
    )
    rlm_lineage = {
        "engine": raw["engine"],
        "mode": mode,
        "repo_files": signals["repo_files"],
        "repo_bytes": signals["repo_bytes"],
        "files_inspected": signals["files_inspected"],
        "detected_stacks": signals["detected_stacks"],
        "detected_test_command": spec["improvement"]["checks"]["regression"]["command"],
        "detected_build_command": signals["detected_build_command"],
        "sensitive_areas": signals["sensitive_areas"],
        "recommended_workflow": (
            workflow
            if workflow in TEMPLATE_NAMES
            else (
                refinements.get("architecture-and-stages", {}).get("workflow")
                if refinements.get("architecture-and-stages", {}).get("workflow") in TEMPLATE_NAMES
                else signals["recommended_workflow"]
            )
        ),
        "recommended_skills": recommended_skills,
        "gotchas": signals["gotchas"],
        "subcalls": subcalls,
        "subcall_budget": {
            "max_calls": subcall_policy.max_calls,
            "used_calls": usage.calls,
            "failures": usage.failures,
            "total_tokens": usage.total_tokens,
        },
        "duration_ms": duration_ms,
    }

    return {
        "yaml": yaml.safe_dump(spec, sort_keys=False),
        "assumptions": assumptions,
        "missing_capabilities": missing_capabilities,
        "recommended_skills": recommended_skills,
        "rlm_lineage": rlm_lineage,
        "usage": asdict(usage) if usage.calls else None,
        "cost": {"total": usage.cost_usd} if usage.calls else None,
        "proposal_only": True,
    }
