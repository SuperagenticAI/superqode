"""The `superqode local` command group: Local Agentic Coding on this machine."""

from __future__ import annotations

import json
from pathlib import Path

import click


@click.group("local")
def local():
    """Local Agentic Coding: tune SuperQode for the machine in front of you."""


@local.command("doctor")
@click.option("--json", "json_output", is_flag=True, help="Emit the full report as JSON")
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Repository to size for local model and harness recommendations",
)
@click.option(
    "--guardrails",
    is_flag=True,
    help="Include conservative local runtime guardrails in the report and generated harness",
)
@click.option(
    "--generate",
    "generate_path",
    default=None,
    metavar="PATH",
    help="Write a tuned harness spec for the recommended stack",
)
@click.option(
    "--name", default="local-coder", show_default=True, help="Name for the generated harness"
)
def local_doctor(json_output, repo_path, guardrails, generate_path, name):
    """Detect hardware, engines, and downloaded models; recommend a local stack.

    Reads the shipped recommendation matrix (override it with
    ~/.superqode/stack_matrix.yaml) and tells you the best engine and model
    for this machine, preferring what is already installed and downloaded.
    """
    from dataclasses import asdict

    from superqode.local.doctor import generate_harness_yaml, render_report, run_doctor

    report = run_doctor(str(repo_path) if repo_path else None, include_guardrails=guardrails)

    if json_output:
        payload = {
            "hardware": asdict(report.hardware),
            "tier": report.hardware.tier,
            "engines": {k: asdict(v) for k, v in report.engines.items()},
            "inventory": [asdict(m) for m in report.inventory],
            "recommendation": asdict(report.recommendation),
            "matrix_version": report.matrix_version,
            "apple_fm_available": report.apple_fm_available,
            "repo": report.repo.to_dict() if report.repo is not None else None,
            "guardrails": report.guardrails.to_dict() if report.guardrails is not None else None,
        }
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_report(report))

    if generate_path:
        target = Path(generate_path)
        if target.exists():
            raise click.ClickException(f"{target} already exists; choose another path")
        target.write_text(generate_harness_yaml(report, name=name), encoding="utf-8")
        click.echo(f"\nWrote tuned harness to {target}")
        click.echo(f"Run it with: superqode --harness {target} -p 'your task'")


@local.command("guardrails")
@click.option("--json", "json_output", is_flag=True, help="Emit guardrails as JSON")
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Repository to include when capping context and concurrency",
)
def local_guardrails(json_output, repo_path):
    """Recommend conservative local runtime limits for this machine."""
    from superqode.local.guardrails import build_guardrails, render_guardrails
    from superqode.local.hardware import detect_hardware
    from superqode.local.repo import analyze_repository

    repo_profile = analyze_repository(repo_path) if repo_path else None
    guardrails = build_guardrails(detect_hardware(), repo_profile=repo_profile)
    if json_output:
        payload = guardrails.to_dict()
        payload["repo"] = repo_profile.to_dict() if repo_profile is not None else None
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_guardrails(guardrails))


@local.command("packs")
@click.option("--json", "json_output", is_flag=True, help="Emit packs as JSON")
def local_packs(json_output):
    """List model policy packs (shipped plus ~/.superqode/model-packs/).

    A pack carries tuned defaults for one open-model family. Reference one
    from a harness with model_policy.pack, or let SuperQode auto-detect it
    from the model id.
    """
    from dataclasses import asdict

    from superqode.local.packs import USER_PACKS_DIR, list_packs

    packs = list_packs()
    if json_output:
        click.echo(json.dumps([asdict(p) for p in packs], indent=2))
        return
    for pack in packs:
        click.echo(f"{pack.name:<12} {pack.description}")
        if pack.match:
            click.echo(f"{'':<12} matches: {', '.join(pack.match)}")
    click.echo(f"\nOverride or add packs in {USER_PACKS_DIR}")


@local.command("bench")
@click.option(
    "--endpoint",
    default=None,
    metavar="URL",
    help="OpenAI-compatible base URL (default: every running engine the doctor finds)",
)
@click.option("--model", "models", multiple=True, help="Model id to bench (repeatable)")
@click.option("--max-tokens", default=256, show_default=True, type=int)
@click.option("--api-key", default="", help="Bearer token if the endpoint needs one")
@click.option(
    "--agentic",
    is_flag=True,
    help="Also probe tool-call, edit-format, shell-call, and context-recall behavior",
)
@click.option("--json", "json_output", is_flag=True, help="Emit results as JSON")
def local_bench(endpoint, models, max_tokens, api_key, agentic, json_output):
    """Measure TTFT and decode speed on local endpoints with a coding prompt.

    Without --endpoint, benches the first model of every engine the doctor
    finds running. TTFT (prefill) matters most: agent loops resend a growing
    context every turn.
    """
    from dataclasses import asdict

    from superqode.local.bench import (
        list_endpoint_models,
        render_bench,
        run_agentic_bench,
        run_bench,
    )

    targets: list[tuple[str, str]] = []
    if endpoint:
        ids = list(models) or list_endpoint_models(endpoint)[:1]
        if not ids:
            raise click.ClickException(f"No models found at {endpoint}; pass --model explicitly")
        targets = [(endpoint, m) for m in ids]
    else:
        from superqode.local.engines import detect_engines

        for status in detect_engines().values():
            if not status.running or not status.endpoint:
                continue
            wanted = list(models) or list_endpoint_models(status.endpoint)[:1]
            targets.extend((status.endpoint, m) for m in wanted)
        if not targets:
            raise click.ClickException(
                "No running engines found. Start one (ollama serve, lms server start, "
                "superqode providers mlx server) or pass --endpoint."
            )

    results = []
    for target_endpoint, model in targets:
        click.echo(f"Benching {model} at {target_endpoint} ...", err=True)
        if agentic:
            results.append(
                run_agentic_bench(
                    target_endpoint,
                    model,
                    max_tokens=max_tokens,
                    api_key=api_key,
                )
            )
        else:
            results.append(
                run_bench(target_endpoint, model, max_tokens=max_tokens, api_key=api_key)
            )

    if json_output:
        click.echo(json.dumps([asdict(r) for r in results], indent=2))
    else:
        click.echo(render_bench(results))


@local.command("optimize")
@click.option(
    "--endpoint",
    default=None,
    metavar="URL",
    help="OpenAI-compatible base URL (default: every running engine the doctor finds)",
)
@click.option("--model", "models", multiple=True, help="Candidate model id (repeatable)")
@click.option(
    "--role",
    "roles",
    multiple=True,
    help="Workflow role to optimize (default: planner, implementer, reviewer, utility)",
)
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Repository to size when scoring local model routes",
)
@click.option("--max-tokens", default=384, show_default=True, type=int)
@click.option("--api-key", default="", help="Bearer token if the endpoint needs one")
@click.option(
    "--generate",
    "generate_path",
    default=None,
    metavar="PATH",
    help="Write a role-routed harness spec from the recommendations",
)
@click.option(
    "--name",
    default="local-optimized",
    show_default=True,
    help="Name for the generated harness",
)
@click.option("--json", "json_output", is_flag=True, help="Emit report as JSON")
def local_optimize(
    endpoint,
    models,
    roles,
    repo_path,
    max_tokens,
    api_key,
    generate_path,
    name,
    json_output,
):
    """Benchmark candidates and recommend role-specific local model routing."""
    from dataclasses import asdict

    from superqode.local.optimize import (
        DEFAULT_ROLES,
        discover_targets,
        optimization_harness_yaml,
        render_optimization,
        run_optimization,
    )
    from superqode.local.repo import analyze_repository

    targets = discover_targets(endpoint, models)
    if not targets:
        raise click.ClickException(
            "No candidate models found. Start a local engine or pass --endpoint and --model."
        )

    for target_endpoint, model in targets:
        click.echo(f"Optimizing {model} at {target_endpoint} ...", err=True)
    repo_profile = analyze_repository(repo_path) if repo_path else None
    report = run_optimization(
        targets,
        roles=roles or DEFAULT_ROLES,
        max_tokens=max_tokens,
        api_key=api_key,
        repo_profile=repo_profile,
    )

    if json_output:
        click.echo(
            json.dumps(
                {
                    "results": [asdict(r) for r in report.results],
                    "recommendations": [asdict(r) for r in report.recommendations],
                    "notes": list(report.notes),
                    "repo": repo_profile.to_dict() if repo_profile is not None else None,
                },
                indent=2,
            )
        )
    else:
        click.echo(render_optimization(report))

    if generate_path:
        target = Path(generate_path)
        if target.exists():
            raise click.ClickException(f"{target} already exists; choose another path")
        target.write_text(optimization_harness_yaml(report, name=name), encoding="utf-8")
        click.echo(f"\nWrote role-routed harness to {target}")
        click.echo(f"Run it with: superqode harness run --spec {target} --prompt 'your task'")


def _local_client_for(engine: str):
    from superqode.providers.local import (
        DS4Client,
        LMStudioClient,
        MLXClient,
        OllamaClient,
        SGLangClient,
        TGIClient,
        VLLMClient,
    )

    return {
        "ds4": DS4Client,
        "ollama": OllamaClient,
        "lmstudio": LMStudioClient,
        "mlx": MLXClient,
        "vllm": VLLMClient,
        "sglang": SGLangClient,
        "tgi": TGIClient,
    }.get(engine)


@local.command("serve")
@click.argument("engine", type=click.Choice(["ollama", "lmstudio", "mlx", "ds4", "llama.cpp"]))
@click.option(
    "--model", "-m", default=None, help="Model id / weight path (required for mlx and llama.cpp)"
)
@click.option("--port", "-p", default=None, type=int, help="Port (default: engine default)")
@click.option("--host", default=None, help="Bind host (default: 127.0.0.1)")
@click.option("--ctx", default=None, type=int, help="Context window (where the engine supports it)")
@click.option("--no-wait", is_flag=True, help="Return immediately, do not wait for readiness")
@click.option("--build", is_flag=True, help="(ds4) Build the ds4-server binary first if missing")
@click.option(
    "--allow-download",
    is_flag=True,
    help="(mlx) Permit downloading the model from Hugging Face if not cached",
)
@click.option(
    "--extra", "extra_args", multiple=True, help="Extra flag passed to the server (repeatable)"
)
def local_serve(engine, model, port, host, ctx, no_wait, build, allow_download, extra_args):
    """Start a local model server as a managed background daemon.

    The server keeps running after SuperQode exits; manage it later with
    `superqode local servers` and `superqode local stop <engine>`. An
    already-running server on the target port is adopted, not restarted.
    """
    from superqode.local.servers import ServerError, ds4_build, ds4_build_plan, get_manager

    manager = get_manager()

    if engine == "ds4" and build and not manager.is_installed("ds4"):
        plan = ds4_build_plan()
        click.echo(f"Building ds4-server in {plan['checkout']} ...", err=True)
        try:
            ds4_build()
        except Exception as exc:  # noqa: BLE001
            raise click.ClickException(f"ds4 build failed: {exc}") from exc
        click.echo(
            "Built ds4-server. The model weights are a separate (large) download:\n"
            f"  cd {plan['checkout']} && ./download_model.sh"
        )

    try:
        handle = manager.start(
            engine,
            host=host,
            port=port,
            model=model,
            ctx=ctx,
            extra_args=list(extra_args),
            wait=not no_wait,
            allow_download=allow_download,
        )
    except ServerError as exc:
        raise click.ClickException(str(exc)) from exc

    verb = "Adopted running" if handle.adopted else "Started"
    click.echo(f"{verb} {engine} at {handle.base_url}")
    if handle.pid:
        click.echo(f"  pid {handle.pid} · log {handle.log_path}")
    for note in handle.notes:
        click.echo(f"  • {note}")
    if no_wait and not handle.adopted:
        click.echo("  (not waiting for readiness; check with: superqode local servers)")
    click.echo(f"  point SuperQode at it with provider [{engine}] or that base URL")


@local.command("servers")
@click.option("--json", "json_output", is_flag=True, help="Emit status as JSON")
def local_servers(json_output):
    """Show the status of every known local server (running, managed, pid)."""
    from superqode.local.servers import get_manager

    manager = get_manager()
    rows = manager.list_all()
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return

    click.echo("Local servers")
    for row in rows:
        if row["running"]:
            mark = "●"
            state = "managed" if row["managed"] else "running"
            extra = f" pid {row['pid']}" if row["pid"] else " (adopted)"
        else:
            mark = "○"
            readiness = manager.precheck(row["engine"])
            state = "stopped" if readiness.installed else "missing"
            extra = ""
        click.echo(f"{mark} {row['engine']:<10} {state:<8} {row['base_url']}{extra}")
        if not row["running"]:
            readiness = manager.precheck(row["engine"])
            if readiness.installed:
                click.echo(f"  start: {readiness.start_hint}")
            else:
                guide = readiness.install_guide[0] if readiness.install_guide else "install first"
                click.echo(f"  setup: {guide}")


@local.command("models")
@click.argument("engine", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit models as JSON")
def local_models(engine, json_output):
    """List chat-capable models for local providers.

    If ENGINE is omitted, every running local server known to SuperQode is
    scanned. Embedding and reranker models are hidden because they cannot drive
    the coding harness.
    """
    import asyncio
    from dataclasses import asdict

    from superqode.local.servers import get_manager
    from superqode.providers.local.base import is_embedding_model

    manager = get_manager()
    engines = (
        [engine] if engine else [row["engine"] for row in manager.list_all() if row["running"]]
    )
    if not engines:
        raise click.ClickException(
            "No running local servers found. Start one with: superqode local serve <engine>"
        )

    async def collect() -> list[dict]:
        rows: list[dict] = []
        for engine_id in engines:
            client_class = _local_client_for(engine_id)
            if client_class is None and engine_id == "llama.cpp":
                from superqode.local.bench import list_endpoint_models

                status = manager.status(engine_id)
                for model_id in list_endpoint_models(status["base_url"]):
                    rows.append(
                        {
                            "engine": engine_id,
                            "id": model_id,
                            "name": model_id,
                            "running": status["running"],
                            "context_window": 0,
                            "size_bytes": 0,
                            "quantization": "unknown",
                            "supports_tools": False,
                        }
                    )
                continue
            if client_class is None:
                rows.append({"engine": engine_id, "error": "model listing is not supported"})
                continue
            client = client_class()
            try:
                models = await client.list_models()
            except Exception as exc:  # noqa: BLE001
                rows.append({"engine": engine_id, "error": str(exc)})
                continue
            for model in models:
                if is_embedding_model(model.id, model.name):
                    continue
                item = asdict(model)
                item["engine"] = engine_id
                rows.append(item)
        return rows

    rows = asyncio.run(collect())
    if json_output:
        click.echo(json.dumps(rows, indent=2, default=str))
        return

    if not rows:
        click.echo("No chat models found.")
        click.echo("Use `superqode local servers` to check which server is running.")
        return
    for row in rows:
        if row.get("error"):
            click.echo(f"{row['engine']:<10} error: {row['error']}")
            continue
        running = "●" if row.get("running") else "○"
        ctx = row.get("context_window") or 0
        details = []
        if row.get("size_bytes"):
            details.append(f"{row['size_bytes'] / (1024**3):.1f}GB")
        if row.get("quantization") and row["quantization"] != "unknown":
            details.append(str(row["quantization"]))
        if ctx:
            details.append(f"{ctx:,} ctx")
        if row.get("supports_tools"):
            details.append("tools")
        suffix = f"  {' • '.join(details)}" if details else ""
        click.echo(f"{running} {row['engine']:<10} {row['id']}{suffix}")


@local.command("labs")
@click.argument("lab", required=False)
@click.option("--limit", default=12, show_default=True, type=int, help="Maximum models to show")
@click.option("--refresh", is_flag=True, help="Refresh the models.dev cache")
@click.option("--json", "json_output", is_flag=True, help="Emit labs or models as JSON")
def local_labs(lab, limit, refresh, json_output):
    """Discover local-friendly model labs from models.dev.

    Use this before downloading weights from Hugging Face or pointing
    SuperQode at a free/provider-hosted route. The curated list favors model
    families that are useful for local agentic coding.
    """
    from dataclasses import asdict

    from superqode.local.labs import list_curated_labs, list_lab_models

    if not lab:
        labs = list_curated_labs()
        if json_output:
            click.echo(json.dumps([asdict(item) for item in labs], indent=2))
            return
        click.echo("Local model labs")
        for item in labs:
            mark = "*" if item.recommended else " "
            click.echo(f"{mark} {item.id:<10} {item.name}")
            click.echo(f"  {item.description}")
        click.echo("\nOpen one with: superqode local labs zhipuai")
        return

    try:
        rows = list_lab_models(lab, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise click.ClickException(f"Could not load models.dev Labs data: {exc}") from exc

    rows = rows[: max(limit, 0)]
    if json_output:
        click.echo(json.dumps([row.to_dict() for row in rows], indent=2))
        return
    if not rows:
        raise click.ClickException(f"No models found for lab '{lab}' in models.dev")

    click.echo(f"models.dev lab: {lab}")
    for row in rows:
        mark = "*" if row.recommended_for_local else " "
        traits = []
        if row.open_weights:
            traits.append("open")
        if row.free_route:
            traits.append("free-route")
        if row.supports_tools:
            traits.append("tools")
        if row.supports_reasoning:
            traits.append("reasoning")
        if row.supports_structured:
            traits.append("structured")
        if row.supports_vision:
            traits.append("vision")
        if row.context_window:
            traits.append(f"{row.context_window:,} ctx")
        suffix = f"  {' • '.join(traits)}" if traits else ""
        click.echo(f"{mark} {row.id}{suffix}")
        if row.recommended_for_local and row.install_hint:
            click.echo(f"  install: {row.install_hint}")


@local.command("search")
@click.argument("query")
@click.option("--hub", is_flag=True, help="Also search Hugging Face live (trusted publishers)")
@click.option("--gguf", is_flag=True, help="With --hub: only GGUF (Ollama / llama.cpp)")
@click.option("--mlx", is_flag=True, help="With --hub: only MLX (Apple Silicon)")
@click.option("--json", "json_output", is_flag=True, help="Emit results as JSON")
def local_search(query, hub, gguf, mlx, json_output):
    """Search the trusted catalog for a model and how to get it.

    Finds models matching QUERY from SuperQode's vetted stack matrix, shows the
    exact download command per engine, whether you already have it, and whether
    it fits your hardware. With --hub it also queries the Hugging Face Hub live,
    filtered to trusted publishers, so you see the latest releases.
    """
    from superqode.local.hardware import detect_hardware
    from superqode.local.matrix import search_models

    from superqode.local.matrix import augment_commands_with_hub

    hw = detect_hardware()
    tier = hw.tier
    ram_gb = hw.available_memory_gb
    hits = search_models(query, tier=tier)

    # Always look up the trusted Hub so each model lists EVERY engine it can run
    # on (Ollama from the catalog, MLX + GGUF from the Hub), not just Ollama.
    # Graceful: offline / no huggingface_hub falls back to catalog commands.
    hub_models = []
    hub_error = ""
    from superqode.local.labs import search_hub_trusted

    kind = "gguf" if gguf else ("mlx" if mlx else None)
    try:
        hub_models = search_hub_trusted(query, kind=kind, limit=25)
    except Exception as exc:  # noqa: BLE001 - includes HFNotInstalled / network
        hub_error = str(exc)
    augment_commands_with_hub(hits, hub_models)

    # Hub models not matched to a curated row are the "newest releases" tail.
    matched_ids = {cmd.split()[-1] for h in hits for _, cmd in h.commands}
    hub_extra = [m for m in hub_models if m.id not in matched_ids]

    if json_output:
        click.echo(
            json.dumps(
                {
                    "query": query,
                    "tier": tier,
                    "results": [h.to_dict() for h in hits],
                    "hub": [
                        {
                            "id": m.id,
                            "downloads": m.downloads,
                            "format": "gguf"
                            if m.is_gguf
                            else ("mlx" if m.is_mlx else "safetensors"),
                            "command": f"superqode models download {m.id}",
                        }
                        for m in hub_models
                    ],
                    "hub_error": hub_error,
                },
                indent=2,
            )
        )
        return

    if not hits and not hub_models:
        click.echo(f"No trusted-catalog models match {query!r}.")
        if hub_error:
            click.echo(f"Hugging Face search unavailable: {hub_error}")
        click.echo("Browse families with: superqode local labs  ·  live: add --hub")
        return

    from superqode.local.matrix import estimate_model_memory_gb, memory_fit_phrase

    ram_note = f" · your RAM: ~{ram_gb:g} GB" if ram_gb else ""
    if hits:
        click.echo(f"Curated matches for {query!r}  (hardware: {tier}{ram_note})\n")
    for hit in hits:
        badges = []
        if hit.downloaded_as:
            badges.append("● downloaded")
        badges.append(memory_fit_phrase(hit.est_memory_gb, ram_gb))
        if hit.role and hit.role != "main":
            badges.append(hit.role)
        click.echo(f"{hit.name}  [{', '.join(badges)}]")
        if hit.downloaded_as:
            click.echo(f"    you already have: {hit.downloaded_as}")
        for engine, command in hit.commands:
            click.echo(f"    {engine:<11} {command}")
        if hit.hub_repo:
            click.echo(
                f"    {'SuperQode':<11} superqode models download {hit.hub_repo}  (any engine)"
            )
        meta = []
        if hit.sources:
            meta.append("source: " + ", ".join(hit.sources))
        if hit.tiers:
            meta.append("tuned for: " + ", ".join(hit.tiers))
        if meta:
            click.echo(f"    ({'  ·  '.join(meta)})")
        click.echo("")

    tail = hub_extra if hub else hub_extra[:3]
    if tail:
        click.echo(f"Newer / other on Hugging Face (trusted publishers) for {query!r}\n")
        for m in tail:
            fmt = "GGUF" if m.is_gguf else ("MLX" if m.is_mlx else "safetensors")
            est = estimate_model_memory_gb(m.id, quantized_default=(m.is_gguf or m.is_mlx))
            fit = memory_fit_phrase(est, ram_gb)
            click.echo(f"{m.id}  [{fmt}, {m.downloads:,} downloads, {fit}]")
            click.echo(f"    superqode models download {m.id}")
        click.echo("")
    elif hub_error:
        click.echo(f"(Hugging Face options unavailable: {hub_error})\n")

    click.echo("Sizes are rough estimates (params x quant), not a guarantee.")
    if not hub and len(hub_extra) > 3:
        click.echo(f"Add --hub to see all {len(hub_extra)} Hugging Face matches.")
    click.echo("After downloading: superqode local serve <engine>  or  :connect local")


@local.command("warm")
@click.argument("engine", type=click.Choice(["ollama", "lmstudio", "mlx", "ds4", "llama.cpp"]))
@click.option(
    "--model", "-m", default=None, help="Model id to preload (default: first served model)"
)
@click.option("--max-tokens", default=8, show_default=True, type=int)
def local_warm(engine, model, max_tokens):
    """Preload a local model and report first-token latency.

    This sends one tiny streamed request. It is useful before a coding session:
    the first real prompt should not pay model-load cost, and a high TTFT here
    usually means the selected context window is too large for the hardware.
    """
    from superqode.local.bench import list_endpoint_models, run_bench
    from superqode.local.servers import get_manager

    manager = get_manager()
    status = manager.status(engine)
    if not status["running"]:
        raise click.ClickException(
            f"{engine} is not running. Start it with: superqode local serve {engine}"
        )

    endpoint = status["base_url"]
    chosen = model
    if not chosen:
        models = list_endpoint_models(endpoint)
        if not models:
            raise click.ClickException(f"No models found at {endpoint}; pass --model explicitly")
        chosen = models[0]

    click.echo(f"Warming {chosen} at {endpoint} ...", err=True)
    result = run_bench(
        endpoint,
        chosen,
        prompt="Reply with exactly: ok",
        max_tokens=max_tokens,
    )
    if not result.ok:
        raise click.ClickException(result.error or "warmup request failed")

    tps = f"{result.decode_tps} tok/s" if result.decode_tps is not None else "n/a"
    click.echo(f"ready: {chosen}")
    click.echo(f"  TTFT {result.ttft_s}s · decode {tps} · total {result.total_s}s")
    if result.ttft_s is not None and result.ttft_s > 5:
        click.echo(
            "  note: high TTFT is usually prefill/context pressure; restart with a smaller --ctx "
            "or use a smaller quantized model for interactive coding."
        )


@local.command("smoke")
@click.option("--engine", default="", help="Local engine id (default: first running server)")
@click.option("--endpoint", default="", help="OpenAI-compatible base URL")
@click.option("--model", default="", help="Model id (default: first served chat model)")
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Repository to label in the report",
)
@click.option("--api-key", default="", help="Bearer token if the endpoint needs one")
@click.option("--max-tokens", default=384, show_default=True, type=int)
@click.option("--json", "json_output", is_flag=True, help="Emit report as JSON")
def local_smoke(engine, endpoint, model, repo_path, api_key, max_tokens, json_output):
    """Run a non-destructive local coding readiness smoke test."""
    from superqode.local.smoke import render_smoke, run_smoke

    report = run_smoke(
        engine=engine,
        endpoint=endpoint,
        model=model,
        repo_path=repo_path,
        api_key=api_key,
        max_tokens=max_tokens,
    )
    if json_output:
        click.echo(json.dumps(report.to_dict(), indent=2))
    else:
        click.echo(render_smoke(report))
    if report.status == "failed":
        raise click.exceptions.Exit(1)


@local.command("init")
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Repository to tune the harness for",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(dir_okay=False, path_type=Path),
    default=Path("superqode.local.yaml"),
    show_default=True,
    help="Harness file to write",
)
@click.option("--engine", default="", help="Local engine to smoke test")
@click.option("--model", default="", help="Model id to smoke test")
@click.option("--skip-smoke", is_flag=True, help="Generate the harness without running smoke")
@click.option("--yes", "-y", is_flag=True, help="Overwrite existing harness file")
@click.option("--json", "json_output", is_flag=True, help="Emit summary as JSON")
def local_init(repo_path, output_path, engine, model, skip_smoke, yes, json_output):
    """Initialize a local coding harness for this repository."""
    from dataclasses import asdict

    from superqode.local.doctor import generate_harness_yaml, render_report, run_doctor
    from superqode.local.smoke import render_smoke, run_smoke

    if output_path.exists() and not yes:
        raise click.ClickException(f"{output_path} already exists; pass --yes to overwrite")

    report = run_doctor(str(repo_path), include_guardrails=True)
    smoke = None
    if not skip_smoke:
        best = report.recommendation.best_model
        chosen_engine = engine or report.recommendation.engine or ""
        chosen_model = model
        if not chosen_model and best is not None:
            chosen_model = best.downloaded.bare_id if best.downloaded else best.pull.split()[-1]
        smoke = run_smoke(engine=chosen_engine, model=chosen_model, repo_path=repo_path)

    output_path.write_text(generate_harness_yaml(report, name="local-coder"), encoding="utf-8")

    payload = {
        "harness": str(output_path),
        "doctor": {
            "tier": report.hardware.tier,
            "engine": report.recommendation.engine,
            "best_model": asdict(report.recommendation.best_model)
            if report.recommendation.best_model
            else None,
        },
        "smoke": smoke.to_dict() if smoke else None,
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2, default=str))
        return

    click.echo(render_report(report))
    if smoke:
        click.echo("")
        click.echo(render_smoke(smoke))
    click.echo("")
    click.echo(f"Wrote local harness: {output_path}")
    if smoke and smoke.status == "failed":
        click.echo("Not ready yet. Follow the smoke test next steps, then rerun:")
        click.echo(f"  superqode local smoke --repo {repo_path}")
    else:
        click.echo("Start coding with:")
        click.echo(f"  superqode --harness {output_path}")
    click.echo("")
    click.echo("Own your harness (no hand-written YAML needed):")
    click.echo(f"  See what it does:   superqode harness explain --spec {output_path}")
    click.echo("  Build a custom one: superqode harness wizard")


@local.command("stop")
@click.argument("engine", type=click.Choice(["ollama", "lmstudio", "mlx", "ds4", "llama.cpp"]))
def local_stop(engine):
    """Stop a server SuperQode started (adopted servers are left untouched)."""
    from superqode.local.servers import get_manager

    if get_manager().stop(engine):
        click.echo(f"Stopped {engine}")
    else:
        click.echo(f"Nothing to stop for {engine} (not managed by SuperQode)")


__all__ = ["local"]
