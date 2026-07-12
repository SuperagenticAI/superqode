"""SuperQode 'models' CLI: list/show/download/convert local & provider models."""

import json
from pathlib import Path
import click
import click

import click


@click.group(invoke_without_command=True)
@click.pass_context
@click.option("--search", "-s", default=None, help="Filter by name/id/provider substring")
@click.option("--provider", "-p", default=None, help="Only this provider id")
@click.option(
    "--cap", default=None, help="Capability filter: tools|vision|reasoning|code|long|json"
)
@click.option("--free", is_flag=True, help="Only free models ($0 in/out)")
@click.option("--max-price", type=float, default=None, help="Max input price ($/1M tokens)")
@click.option("--curated", is_flag=True, help="Only curated/recommended providers")
@click.option("--sort", type=click.Choice(["provider", "price", "context"]), default="provider")
@click.option("--limit", type=int, default=50, help="Max rows (0 = all)")
@click.option("--refresh", is_flag=True, help="Force-refresh the models.dev catalog")
@click.option(
    "--live",
    is_flag=True,
    help="Query the provider's own /v1/models endpoint (freshest; needs --provider)",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def models(
    ctx, search, provider, cap, free, max_price, curated, sort, limit, refresh, live, json_output
):
    """Browse the full models.dev catalog (5000+ models, 130+ providers).

    With no subcommand this lists/searches models. See `models providers`.
    """
    if ctx.invoked_subcommand is not None:
        return

    import asyncio as _asyncio
    from superqode.providers.catalog import (
        load_models_catalog,
        filter_models,
        parse_capability,
        render_models_table,
        caps_str,
    )

    if cap and parse_capability(cap) is None:
        raise click.ClickException(
            f"Unknown capability '{cap}'. Use: tools, vision, reasoning, code, long, json."
        )

    if live:
        if not provider:
            raise click.ClickException("--live requires --provider <id>.")
        from superqode.providers.live_models import discover_provider_models

        result = _asyncio.run(discover_provider_models(provider))
        all_models = result.models
        if not json_output:
            note = {
                "live": f"live from {result.endpoint}",
                "models.dev": "models.dev catalog (live endpoint unavailable)",
                "none": "no models found",
            }.get(result.source, result.source)
            click.echo(f"# {provider}: {note}\n")
    else:
        all_models = _asyncio.run(load_models_catalog(force=refresh))
    matched = filter_models(
        all_models,
        search=search,
        provider=provider,
        capability=parse_capability(cap),
        free=free,
        max_input_price=max_price,
        curated_only=curated,
        sort=sort,
        limit=None,
    )
    total = len(matched)
    shown = matched if (limit or 0) <= 0 else matched[:limit]

    if json_output:
        click.echo(
            json.dumps(
                [
                    {
                        "id": m.id,
                        "provider": m.provider,
                        "name": m.name,
                        "context_window": m.context_window,
                        "input_price": m.input_price,
                        "output_price": m.output_price,
                        "capabilities": caps_str(m).split(",") if caps_str(m) else [],
                    }
                    for m in shown
                ],
                indent=2,
            )
        )
        return

    click.echo(render_models_table(shown, total=total))


@models.command("providers")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def models_providers(json_output):
    """List every provider in the catalog (curated marked with *)."""
    from superqode.providers.catalog import render_providers_table
    from superqode.providers.models_dev import get_models_dev
    from superqode.providers.dynamic import is_curated_provider

    if json_output:
        client = get_models_dev()
        client.ensure_cache_loaded()
        providers = client.get_providers()
        click.echo(
            json.dumps(
                [
                    {
                        "id": pid,
                        "name": info.name,
                        "curated": is_curated_provider(pid),
                        "env_vars": info.env_vars,
                        "models": len(client.get_models_for_provider(pid)),
                    }
                    for pid, info in sorted(providers.items())
                ],
                indent=2,
            )
        )
        return
    click.echo(render_providers_table())


@models.command("show")
@click.argument("model_ref")
def models_show(model_ref):
    """Show details for a model. MODEL_REF is `provider/model` or a model id."""
    import asyncio as _asyncio
    from superqode.providers.catalog import load_models_catalog, caps_str
    from superqode.providers.model_specs import split_provider_model_ref

    all_models = _asyncio.run(load_models_catalog())
    provider_hint = None
    needle = model_ref
    parsed_model_ref = split_provider_model_ref(model_ref)
    if parsed_model_ref.provider:
        provider_hint, needle = parsed_model_ref.provider, parsed_model_ref.model

    matches = [
        m
        for m in all_models
        if m.id == needle and (provider_hint is None or m.provider == provider_hint)
    ]
    if not matches:
        matches = [m for m in all_models if needle.lower() in m.id.lower()]
    if not matches:
        raise click.ClickException(f"No model matching '{model_ref}'.")

    m = matches[0]
    from superqode.providers.dynamic import is_curated_provider, resolve_provider_def

    pdef = resolve_provider_def(m.provider)
    click.echo(f"Model:     {m.id}")
    click.echo(f"Name:      {m.name}")
    click.echo(
        f"Provider:  {m.provider}" + ("  (curated)" if is_curated_provider(m.provider) else "")
    )
    click.echo(f"Context:   {m.context_window:,} tokens   Max output: {m.max_output:,}")
    click.echo(f"Price:     ${m.input_price}/1M in, ${m.output_price}/1M out")
    click.echo(f"Caps:      {caps_str(m) or '-'}")
    if pdef and pdef.env_vars:
        click.echo(f"API key:   set {' or '.join(pdef.env_vars)}")
    if pdef and pdef.docs_url:
        click.echo(f"Docs:      {pdef.docs_url}")
    if len(matches) > 1:
        click.echo(
            f"\n({len(matches)} models matched; showing first. Use provider/model to disambiguate.)"
        )


def _fmt_bytes(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}" if unit != "B" else f"{n}B"
        n /= 1024
    return f"{n:.1f}TB"


@models.command("hub")
@click.argument("query", required=False, default="")
@click.option("--gguf", is_flag=True, help="Only GGUF models (Ollama / llama.cpp)")
@click.option("--mlx", is_flag=True, help="Only MLX models (Apple Silicon)")
@click.option(
    "--sort",
    type=click.Choice(["downloads", "likes", "trending_score", "created_at"]),
    default="downloads",
)
@click.option("--limit", type=int, default=25)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def models_hub(query, gguf, mlx, sort, limit, json_output):
    """Search the Hugging Face Hub for downloadable models.

    Example: superqode models hub qwen3 --gguf
    """
    from superqode.providers.huggingface.fetch import search_hub, HFNotInstalled

    kind = "gguf" if gguf else ("mlx" if mlx else None)
    try:
        results = search_hub(query, kind=kind, sort=sort, limit=limit)
    except HFNotInstalled as exc:
        raise click.ClickException(str(exc))

    if json_output:
        click.echo(
            json.dumps(
                [
                    {
                        "id": m.id,
                        "downloads": m.downloads,
                        "likes": m.likes,
                        "library": m.library,
                        "gated": m.gated,
                        "gguf": m.is_gguf,
                        "mlx": m.is_mlx,
                    }
                    for m in results
                ],
                indent=2,
            )
        )
        return

    if not results:
        click.echo("No models found.")
        return
    rows = [
        (m.id[:52], f"{m.downloads:,}", str(m.likes), m.library or "-", "🔒" if m.gated else "")
        for m in results
    ]
    headers = ("MODEL", "DOWNLOADS", "LIKES", "LIBRARY", "")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    click.echo("  ".join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    click.echo("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in rows:
        click.echo("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(row)))
    click.echo(f"\n{len(rows)} model(s). Download: superqode models download <model-id>")


@models.command("download")
@click.argument("repo_id", metavar="REPO_ID")
@click.option(
    "--to",
    "target",
    type=click.Choice(["auto", "ollama", "mlx", "transformers"]),
    default="auto",
    help="Where to make the model usable (auto-detected by default)",
)
@click.option(
    "--quant", default="Q4_K_M", show_default=True, help="GGUF quantization to pick (ollama target)"
)
@click.option(
    "--dir",
    "target_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Download into this directory",
)
@click.option("--name", "ollama_name", default=None, help="Ollama model name to register as")
@click.option(
    "--register/--no-register", default=True, help="Register GGUF with Ollama (ollama target)"
)
@click.option("--yes", "-y", is_flag=True, help="Skip the size confirmation prompt")
def models_download(repo_id, target, quant, target_dir, ollama_name, register, yes):
    """Download a model from the Hugging Face Hub and make it locally usable.

    Examples:
      superqode models download mlx-community/Qwen3-8B-4bit
      superqode models download bartowski/Qwen2.5-Coder-7B-GGUF --to ollama --quant Q4_K_M
    """
    import asyncio as _asyncio
    from superqode.providers.huggingface import fetch as hf
    from superqode.providers.huggingface.fetch import HFNotInstalled

    try:
        # Resolve target.
        if target == "auto":
            target = hf.detect_target(None, repo_id)
            click.echo(f"Detected target: {target}")

        # Pick the file set (GGUF needs a single quant file; others snapshot all).
        gguf_file = None
        allow_patterns = None
        if target == "ollama":
            gguf_file = hf.pick_gguf_file(repo_id, quant)
            if not gguf_file:
                raise click.ClickException(
                    f"No GGUF files in '{repo_id}'. Try --to mlx/transformers, or pick a *-GGUF repo."
                )
            allow_patterns = [gguf_file]
            click.echo(f"GGUF file: {gguf_file}")
        elif target == "mlx":
            # Only pull what MLX needs (skip GGUF/other formats) -> smaller download.
            allow_patterns = hf.MLX_ALLOW_PATTERNS

        # Size preview via dry-run, then confirm.
        est = hf.estimate_size(repo_id, allow_patterns=allow_patterns)
        if est is not None:
            click.echo(
                f"Download size: {_fmt_bytes(est.to_download_bytes)}"
                + (f" ({_fmt_bytes(est.cached_bytes)} already cached)" if est.cached_bytes else "")
                + f"  across {est.file_count} file(s)"
            )
        if not yes:
            click.confirm("Proceed with download?", abort=True, default=True)
        if not hf.hf_xet_available():
            click.echo("(tip: pip install hf_xet for faster downloads)")

        # Download.
        if target == "ollama":
            path = hf.download_file(repo_id, gguf_file, target_dir=target_dir)
            click.echo(f"Downloaded: {path}")
            if register:
                from superqode.providers.huggingface.downloader import get_hf_downloader

                name = ollama_name or "hf-" + repo_id.split("/")[-1].lower().replace("-gguf", "")
                click.echo(f"Registering with Ollama as '{name}'...")
                ok = _asyncio.run(get_hf_downloader().register_with_ollama(path, name))
                if ok:
                    click.echo(f"✓ Registered. Run it: ollama run {name}")
                    click.echo(f"  In SuperQode: connect to ollama and select '{name}'.")
                else:
                    click.echo(
                        "⚠ Could not register (is Ollama installed/running?). "
                        f"Register manually: ollama create {name} -f <Modelfile>"
                    )
        else:
            path = hf.download_repo(repo_id, target_dir=target_dir, allow_patterns=allow_patterns)
            click.echo(f"✓ Downloaded to: {path}")
            if target == "mlx":
                click.echo(f"  Serve it: mlx_lm.server --model {repo_id}  (or --model {path})")
                click.echo(f"  Then in SuperQode: connect to mlx.")
            else:
                click.echo(f"  Use via the transformers/HF-local provider, or serve with vLLM/TGI.")
    except HFNotInstalled as exc:
        raise click.ClickException(str(exc))


@models.command("convert-mlx")
@click.argument("hf_path", metavar="HF_PATH")
@click.option("--q-bits", type=click.Choice(["4", "8"]), default="8", show_default=True)
@click.option("--no-quantize", is_flag=True, help="Convert without quantizing (full precision)")
@click.option("--out", "out_dir", type=click.Path(path_type=Path), default=None, help="Output dir")
@click.option(
    "--upload", "upload_repo", default=None, help="Push to this HF repo (needs write token)"
)
def models_convert_mlx(hf_path, q_bits, no_quantize, out_dir, upload_repo):
    """Convert a Hugging Face model to MLX (optionally upload to your repo).

    Example:
      superqode models convert-mlx google/gemma-4-31b-it --q-bits 8 --upload SuperagenticAI/gemma-4-31b-it-8bit-mlx
    """
    from superqode.providers.huggingface.convert import convert_to_mlx, MlxConvertUnavailable

    click.echo(f"Converting {hf_path} -> MLX ({'no-quant' if no_quantize else q_bits + '-bit'})…")
    if upload_repo:
        click.echo(f"Will upload to: {upload_repo} (requires HF write token)")
    try:
        path = convert_to_mlx(
            hf_path,
            out_dir=out_dir,
            q_bits=int(q_bits),
            quantize=not no_quantize,
            upload_repo=upload_repo,
        )
    except MlxConvertUnavailable as exc:
        raise click.ClickException(str(exc))
    click.echo(f"✓ MLX model written to: {path}")
    if upload_repo:
        click.echo(f"✓ Uploaded to https://huggingface.co/{upload_repo}")
    click.echo(
        f"  Use it: superqode models download {upload_repo or path} --to mlx  (then connect to mlx)"
    )


@models.command("cached")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def models_cached(json_output):
    """List models in the local Hugging Face cache (largest first)."""
    from superqode.providers.huggingface.fetch import scan_cache, HFNotInstalled

    try:
        repos = scan_cache()
    except HFNotInstalled as exc:
        raise click.ClickException(str(exc))
    if json_output:
        click.echo(
            json.dumps(
                [
                    {
                        "repo_id": r.repo_id,
                        "size_bytes": r.size_bytes,
                        "files": r.nb_files,
                        "path": r.path,
                    }
                    for r in repos
                ],
                indent=2,
            )
        )
        return
    if not repos:
        click.echo("HF cache is empty.")
        return
    width = max((len(r.repo_id) for r in repos), default=10)
    total = 0
    for r in repos:
        total += r.size_bytes
        click.echo(f"  {r.repo_id.ljust(width)}  {r.size_display:>9}  ({r.nb_files} files)")
    click.echo(f"\n{len(repos)} repo(s).  Remove with: superqode models rm <substring>")


@models.command("rm")
@click.argument("pattern", metavar="PATTERN")
@click.option("--yes", "-y", is_flag=True, help="Skip confirmation")
def models_rm(pattern, yes):
    """Delete cached models whose id contains PATTERN (frees disk)."""
    from superqode.providers.huggingface.fetch import scan_cache, delete_cached, HFNotInstalled

    try:
        matches = [r for r in scan_cache() if pattern.lower() in r.repo_id.lower()]
    except HFNotInstalled as exc:
        raise click.ClickException(str(exc))
    if not matches:
        click.echo(f"No cached models match '{pattern}'.")
        return
    click.echo("Will delete:")
    for r in matches:
        click.echo(f"  {r.repo_id}  ({r.size_display})")
    if not yes:
        click.confirm("Proceed?", abort=True, default=False)
    count, freed = delete_cached(pattern)
    freed_gb = freed / 1_000_000_000
    click.echo(f"✓ Deleted {count} repo(s), freed ~{freed_gb:.1f} GB.")
