"""One-command local Jev Tool Routing for external coding harnesses."""

from __future__ import annotations

import json
import asyncio
import os
from pathlib import Path
import shlex
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen

import click
from rich.console import Console
from rich.table import Table

from superqode.optimize.profiles import (
    build_launch_plan,
    get_profile,
    profiles,
    provider_upstream,
)

console = Console()
_PROVIDERS = click.Choice(["openai", "anthropic", "google", "xai"])


@click.group()
def optimize():
    """Jev Tool Routing for local coding harnesses."""


@optimize.command("enable")
@click.argument("harnesses", nargs=-1)
@click.option("--provider", type=_PROVIDERS, default=None, help="Provider for selected harnesses")
@click.option("--model", default="", help="Model id; required for Pi and Google OpenCode")
@click.option(
    "--mode", type=click.Choice(["shadow", "enforce"]), default="shadow", show_default=True
)
@click.option("--threshold", default=0.30, show_default=True, type=click.FloatRange(0.0, 1.0))
@click.option(
    "--bin-dir",
    type=click.Path(path_type=Path, file_okay=False),
    default=None,
    help="Launcher directory (default: ~/.local/bin)",
)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable output")
def enable(
    harnesses: tuple[str, ...],
    provider: str | None,
    model: str,
    mode: str,
    threshold: float,
    bin_dir: Path | None,
    as_json: bool,
) -> None:
    """Create managed *-jev launchers without changing harness configuration."""
    from superqode.optimize.launchers import (
        config_path,
        default_harnesses,
        enable_launchers,
    )

    selected = harnesses or default_harnesses()
    if not selected:
        raise click.ClickException("No supported installed harnesses were detected")
    try:
        enabled, skipped = enable_launchers(
            selected,
            provider=provider,
            model=model,
            mode=mode,
            threshold=threshold,
            bin_dir=bin_dir,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        "feature": "Jev Tool Routing",
        "config": str(config_path()),
        "credentials_written": False,
        "enabled": [entry.as_dict() | {"harness": entry.harness} for entry in enabled],
        "skipped": skipped,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
    else:
        console.print("[bold]Jev Tool Routing · local launchers[/bold]")
        for entry in enabled:
            console.print(
                f"[green]enabled[/green] {entry.harness:<10} → [cyan]{entry.launcher}[/cyan] "
                f"({entry.provider}{('/' + entry.model) if entry.model else ''}, {entry.mode})"
            )
        for item in skipped:
            console.print(f"[yellow]skipped[/yellow] {item['harness']}: {item['reason']}")
        if enabled:
            parent = str(Path(enabled[0].launcher).parent)
            if parent not in os.environ.get("PATH", "").split(os.pathsep):
                console.print(f"[yellow]Add {parent} to PATH to use the launchers.[/yellow]")
            console.print(f"[dim]Preferences: {config_path()} · no credentials written[/dim]")
    if not enabled:
        raise SystemExit(1)


@optimize.command("status")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable output")
def launcher_status(as_json: bool) -> None:
    """Show managed Jev launcher configuration and file health."""
    from superqode.optimize.launchers import config_path, launcher_rows

    rows = launcher_rows()
    payload = {
        "feature": "Jev Tool Routing",
        "config": str(config_path()),
        "typesafe_key_present": bool(os.environ.get("TYPESAFE_API_KEY", "").strip()),
        "enabled": rows,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    table = Table(title="Jev Tool Routing launchers")
    table.add_column("Harness")
    table.add_column("Launcher")
    table.add_column("Route")
    table.add_column("Mode")
    table.add_column("Health")
    for row in rows:
        route = row["provider"] + (("/" + row["model"]) if row["model"] else "")
        healthy = row["launcher_exists"] and row["launcher_managed"]
        table.add_row(
            row["harness"],
            row["launcher"],
            route,
            row["mode"],
            "ready" if healthy else "repair needed",
        )
    console.print(table)
    if not rows:
        console.print("[dim]No managed launchers. Run: superqode optimize enable[/dim]")
    if not payload["typesafe_key_present"]:
        console.print("[yellow]TYPESAFE_API_KEY is not set; routing will fail open.[/yellow]")


def _disable_launchers(harnesses: tuple[str, ...], *, as_json: bool) -> None:
    from superqode.optimize.launchers import config_path, disable_launchers

    removed, retained = disable_launchers(harnesses)
    payload = {
        "feature": "Jev Tool Routing",
        "config": str(config_path()),
        "removed": removed,
        "retained": retained,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    for harness in removed:
        console.print(f"[green]removed[/green] {harness}-jev")
    for item in retained:
        console.print(f"[yellow]retained[/yellow] {item['harness']}: {item['reason']}")
    if not removed and not retained:
        console.print("[dim]No managed launchers were enabled.[/dim]")


@optimize.command("disable")
@click.argument("harnesses", nargs=-1)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable output")
def disable(harnesses: tuple[str, ...], as_json: bool) -> None:
    """Remove selected managed launchers, or all launchers when omitted."""
    _disable_launchers(harnesses, as_json=as_json)


@optimize.command("uninstall")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable output")
def uninstall(as_json: bool) -> None:
    """Remove every managed Jev launcher and its non-secret preferences."""
    _disable_launchers((), as_json=as_json)


@optimize.command("launch", context_settings={"ignore_unknown_options": True}, hidden=True)
@click.argument("harness")
@click.argument("harness_args", nargs=-1, type=click.UNPROCESSED)
def launch(harness: str, harness_args: tuple[str, ...]) -> None:
    """Launch one configured harness (used by managed *-jev commands)."""
    from superqode.optimize.launchers import launch_arguments

    try:
        arguments = launch_arguments(harness, harness_args)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    command = [sys.executable, "-m", "superqode.main", *arguments]
    raise SystemExit(subprocess.run(command, check=False).returncode)


@optimize.command("mcp")
def mcp_server() -> None:
    """Run Jev Tool Routing as a local MCP server over stdio."""
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        raise click.ClickException("TYPESAFE_API_KEY is required")
    from superqode.mcp.jev_router_server import run_jev_mcp_server

    # stdout is the MCP transport; human-facing output belongs on stderr.
    click.echo("SuperQode Jev Tool Routing MCP server listening on stdio", err=True)
    run_jev_mcp_server()


@optimize.command("setup")
@click.argument("harness", required=False)
@click.option("--model", default="", help="Model id used to validate the Pi adapter")
@click.option("--threshold", default=0.30, show_default=True, type=click.FloatRange(0.0, 1.0))
@click.option("--no-live", is_flag=True, help="Skip the one-call Jev connectivity check")
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable output")
def setup(
    harness: str | None,
    model: str,
    threshold: float,
    no_live: bool,
    as_json: bool,
) -> None:
    """Check local readiness and print non-persistent launch commands.

    This developer-preview setup never writes credentials or harness config.
    """
    selected = (_profile(harness),) if harness else profiles()
    key_present = bool(os.environ.get("TYPESAFE_API_KEY", "").strip())
    probe: dict[str, object] = {"status": "skipped"}
    if not no_live and key_present:
        probe = _run_routing_probe(threshold)
    elif not no_live:
        probe = {"status": "missing-key", "error": "TYPESAFE_API_KEY is not set"}

    rows = [_setup_row(profile, model=model) for profile in selected]
    ready = key_present and probe.get("status") == "ok"
    payload = {
        "feature": "Jev Tool Routing",
        "release_stage": "developer-preview",
        "writes_configuration": False,
        "typesafe_key_present": key_present,
        "connectivity": probe,
        "harnesses": rows,
        "ready": ready,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
    else:
        console.print("[bold]Jev Tool Routing · local setup[/bold]")
        console.print(
            "TypeSafe key: " + ("[green]found[/green]" if key_present else "[red]missing[/red]")
        )
        if probe.get("status") == "ok":
            console.print(
                "Jev connectivity: [green]ok[/green] · "
                f"{probe['original_tools']}→{probe['selected_tools']} control tools · "
                f"{probe['latency_ms']}ms"
            )
        elif probe.get("status") == "skipped":
            console.print("Jev connectivity: [yellow]skipped[/yellow]")
        else:
            console.print(f"Jev connectivity: [red]{probe.get('status')}[/red]")
        table = Table(title="Local harness readiness")
        table.add_column("Harness")
        table.add_column("Status")
        table.add_column("Try it")
        for row in rows:
            table.add_row(row["label"], row["status"], row["command"] or "—")
        console.print(table)
        console.print(
            "[dim]No credentials or harness configuration were written. "
            "Start in shadow mode, then use optimize verify before enforce mode.[/dim]"
        )
    if not ready and not no_live:
        raise SystemExit(1)


@optimize.command("verify")
@click.argument("harness")
@click.option("--model", default="", help="Model id required to validate the Pi adapter")
@click.option("--threshold", default=0.30, show_default=True, type=click.FloatRange(0.0, 1.0))
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable output")
def verify(harness: str, model: str, threshold: float, as_json: bool) -> None:
    """Verify the local adapter and Jev decision path for HARNESS.

    This controlled check does not spend coding-model tokens or claim that a
    harness with hidden tools received a reduced catalogue.
    """
    profile = _profile(harness)
    row = _setup_row(profile, model=model)
    key_present = bool(os.environ.get("TYPESAFE_API_KEY", "").strip())
    probe: dict[str, object] = {"status": "missing-key"}
    if key_present:
        probe = _run_routing_probe(threshold)

    adapter_ready = row["status"] not in {"not-installed", "detect-only", "needs-model"}
    catalogue_visible = profile.support in {"gateway", "native"}
    verified = adapter_ready and catalogue_visible and probe.get("status") == "ok"
    if profile.support == "gateway-limited":
        status = "gateway-limited"
    elif profile.support == "detect-only":
        status = "detect-only"
    elif not adapter_ready:
        status = str(row["status"])
    elif probe.get("status") != "ok":
        status = "jev-unavailable"
    else:
        status = "verified"
    payload = {
        "feature": "Jev Tool Routing",
        "harness": profile.id,
        "status": status,
        "verified": verified,
        "installed": row["installed"],
        "support": profile.support,
        "integration": profile.integration,
        "adapter_ready": adapter_ready,
        "tool_catalogue_visible": catalogue_visible,
        "actual_harness_traffic_tested": False,
        "launch_command": row["command"],
        "control_probe": probe,
        "note": profile.note,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
    else:
        color = (
            "green"
            if verified
            else "yellow"
            if status in {"gateway-limited", "detect-only"}
            else "red"
        )
        console.print(f"[bold]Jev Tool Routing · {profile.label}[/bold]")
        console.print(f"Status: [{color}]{status}[/{color}]")
        console.print(f"Adapter: {'ready' if adapter_ready else 'not ready'}")
        console.print(f"Tool catalogue visible: {'yes' if catalogue_visible else 'no'}")
        if probe.get("status") == "ok":
            console.print(
                "Control route: "
                f"{probe['original_tools']}→{probe['selected_tools']} tools · "
                f"schema {probe['original_schema_bytes']}→{probe['selected_schema_bytes']} bytes · "
                f"cache reuse {'yes' if probe['cache_reused'] else 'no'}"
            )
        if row["command"]:
            console.print(f"Next: [cyan]{row['command']}[/cyan]")
        if profile.note:
            console.print(f"[yellow]{profile.note}[/yellow]")
        console.print(
            "[dim]This check validates the adapter and Jev path without invoking the coding model. "
            "The optimize run report verifies actual harness traffic.[/dim]"
        )
    if not verified:
        raise SystemExit(2 if status in {"gateway-limited", "detect-only"} else 1)


@optimize.command("doctor")
@click.argument("harness", required=False)
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable output")
def doctor(harness: str | None, as_json: bool) -> None:
    """Detect harnesses and show their integration method."""
    selected = (_profile(harness),) if harness else profiles()
    rows = []
    for profile in selected:
        executable = profile.executable()
        rows.append(
            {
                "id": profile.id,
                "label": profile.label,
                "installed": executable is not None,
                "executable": executable,
                "support": profile.support,
                "integration": profile.integration,
                "protocol": profile.protocol,
                "note": profile.note,
            }
        )
    if as_json:
        click.echo(json.dumps(rows, indent=2))
        return
    table = Table(title="SuperQode Jev Tool Routing")
    table.add_column("Harness")
    table.add_column("Local")
    table.add_column("Support")
    table.add_column("Integration")
    for row in rows:
        table.add_row(
            row["label"],
            "yes" if row["installed"] else "not found",
            row["support"],
            row["integration"],
        )
    console.print(table)
    if not os.environ.get("TYPESAFE_API_KEY"):
        console.print(
            "[yellow]TYPESAFE_API_KEY is not set; the gateway will pass through unchanged.[/yellow]"
        )


@optimize.command("env")
@click.argument("harness")
@click.option("--provider", type=_PROVIDERS, default=None)
@click.option("--port", default=8787, show_default=True, type=click.IntRange(min=1, max=65535))
@click.option("--model", default="", help="Model id (required by Pi)")
@click.option("--json", "as_json", is_flag=True)
def environment(harness: str, provider: str | None, port: int, model: str, as_json: bool) -> None:
    """Print the ephemeral launch configuration without starting anything."""
    profile = _profile(harness)
    chosen_provider = provider or profile.default_provider
    try:
        with tempfile.TemporaryDirectory(prefix="superqode-optimize-plan-") as raw_dir:
            plan = build_launch_plan(
                profile,
                gateway_url=f"http://127.0.0.1:{port}",
                provider=chosen_provider,
                model=model,
                temp_dir=Path(raw_dir),
            )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {
        "harness": profile.id,
        "provider": chosen_provider,
        "command": list(plan.command),
        "environment": dict(plan.environment),
        "generated_files": dict(plan.generated_files),
        "note": plan.note,
    }
    if as_json:
        click.echo(json.dumps(payload, indent=2))
        return
    console.print(f"[bold]{profile.label}[/bold] via http://127.0.0.1:{port}")
    for key, value in plan.environment.items():
        console.print(f"  {key}={value}")
    console.print("  " + " ".join(plan.command))
    if plan.generated_files:
        console.print(
            "[dim]The run command creates the displayed temporary files and removes them on exit.[/dim]"
        )
    if plan.note:
        console.print(f"[yellow]{plan.note}[/yellow]")


@optimize.command("bench")
@click.option("--threshold", default=0.30, show_default=True, type=click.FloatRange(0.0, 1.0))
@click.option("--json", "as_json", is_flag=True, help="Emit machine-readable results")
def benchmark(threshold: float, as_json: bool) -> None:
    """Run the local labeled Jev Tool Routing benchmark."""
    if not os.environ.get("TYPESAFE_API_KEY", "").strip():
        raise click.ClickException("TYPESAFE_API_KEY is required")
    from superqode.providers.gateway.base import ToolDefinition
    from superqode.systemone.tool_router import ToolRoutingSettings, build_tool_router

    catalogue = [
        ToolDefinition(name=name, description=description, parameters={"type": "object"})
        for name, description in _BENCHMARK_TOOLS
    ]
    router = build_tool_router(
        ToolRoutingSettings(mode="shadow", threshold=threshold, timeout_ms=5000)
    )
    if router is None:
        raise click.ClickException("Jev Tool Routing is unavailable")

    async def evaluate():
        return await asyncio.gather(
            *(router.plan(prompt, catalogue) for _, prompt, _ in _BENCHMARK_SCENARIOS)
        )

    plans = asyncio.run(evaluate())
    rows = []
    for (scenario, _prompt, required), plan in zip(_BENCHMARK_SCENARIOS, plans, strict=True):
        selected = set(plan.selected)
        hits = len(selected.intersection(required))
        rows.append(
            {
                "scenario": scenario,
                "status": plan.status,
                "original_tools": len(plan.original),
                "selected_tools": len(plan.selected),
                "reduction_percent": round(
                    (len(plan.original) - len(plan.selected)) * 100 / len(plan.original), 1
                ),
                "required_recall": round(hits / len(required), 3),
                "missing_required": sorted(set(required) - selected),
                "latency_ms": plan.latency_ms,
            }
        )
    summary = {
        "feature": "Jev Tool Routing",
        "threshold": threshold,
        "scenarios": rows,
        "average_reduction_percent": round(
            sum(row["reduction_percent"] for row in rows) / len(rows), 1
        ),
        "required_tool_recall": round(sum(row["required_recall"] for row in rows) / len(rows), 3),
        "average_latency_ms": round(sum(row["latency_ms"] for row in rows) / len(rows)),
    }
    if as_json:
        click.echo(json.dumps(summary, indent=2))
        return
    table = Table(title="Jev Tool Routing benchmark")
    table.add_column("Scenario")
    table.add_column("Tools")
    table.add_column("Reduction")
    table.add_column("Recall")
    table.add_column("Latency")
    for row in rows:
        table.add_row(
            row["scenario"],
            f"{row['original_tools']}→{row['selected_tools']}",
            f"{row['reduction_percent']}%",
            f"{row['required_recall'] * 100:.0f}%",
            f"{row['latency_ms']}ms",
        )
    console.print(table)
    console.print(
        f"Average reduction: [bold]{summary['average_reduction_percent']}%[/bold] · "
        f"required-tool recall: [bold]{summary['required_tool_recall'] * 100:.1f}%[/bold] · "
        f"average latency: [bold]{summary['average_latency_ms']}ms[/bold]"
    )


@optimize.command("run", context_settings={"ignore_unknown_options": True})
@click.argument("harness")
@click.argument("harness_args", nargs=-1, type=click.UNPROCESSED)
@click.option("--provider", type=_PROVIDERS, default=None, help="Upstream model provider")
@click.option("--model", default="", help="Model id (required by Pi)")
@click.option("--upstream", default="", help="Override the provider API origin")
@click.option(
    "--mode", type=click.Choice(["shadow", "enforce"]), default="shadow", show_default=True
)
@click.option("--threshold", default=0.30, show_default=True, type=click.FloatRange(0.0, 1.0))
@click.option(
    "--port",
    default=0,
    type=click.IntRange(min=0, max=65535),
    help="Gateway port; 0 chooses a free port",
)
def run_harness(
    harness: str,
    harness_args: tuple[str, ...],
    provider: str | None,
    model: str,
    upstream: str,
    mode: str,
    threshold: float,
    port: int,
) -> None:
    """Start the local gateway and run HARNESS; pass harness flags after --."""
    profile = _profile(harness)
    if profile.support == "detect-only":
        raise click.ClickException(profile.note)
    chosen_provider = provider or profile.default_provider
    if profile.id == "superqode":
        plan = build_launch_plan(
            profile,
            gateway_url="http://127.0.0.1",
            provider=chosen_provider,
            extra_args=harness_args,
        )
        child_env = os.environ.copy()
        child_env.update(plan.environment)
        child_env["SUPERQODE_TOOL_ROUTING"] = mode
        child_env["SUPERQODE_TOOL_ROUTING_THRESHOLD"] = str(threshold)
        raise SystemExit(subprocess.run(plan.command, env=child_env, check=False).returncode)

    executable = profile.executable()
    if executable is None:
        raise click.ClickException(
            f"{profile.label} is not installed (looked for {', '.join(profile.executables)})"
        )
    if port == 0:
        port = _free_port()
    default_upstream, key_env = provider_upstream(chosen_provider)
    if profile.id == "codex" and chosen_provider == "openai" and not os.environ.get(key_env):
        # ChatGPT subscription auth is scoped to the Codex backend, not the
        # public API origin. API-key users keep the normal api.openai.com path.
        default_upstream = "https://chatgpt.com/backend-api/codex"
    upstream = upstream or default_upstream
    gateway_url = f"http://127.0.0.1:{port}"

    with tempfile.TemporaryDirectory(prefix=f"superqode-{profile.id}-") as raw_dir:
        try:
            plan = build_launch_plan(
                profile,
                gateway_url=gateway_url,
                provider=chosen_provider,
                model=model,
                extra_args=harness_args,
                temp_dir=Path(raw_dir),
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        for relative, content in plan.generated_files.items():
            target = Path(raw_dir) / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            target.chmod(0o600)

        gateway_command = [
            sys.executable,
            "-m",
            "superqode.main",
            "serve",
            "optimize",
            "--upstream",
            upstream,
            "--port",
            str(port),
            "--mode",
            mode,
            "--threshold",
            str(threshold),
        ]
        if os.environ.get(key_env):
            gateway_command.extend(["--upstream-key-env", key_env])
        gateway = subprocess.Popen(gateway_command)
        try:
            _wait_for_gateway(gateway_url, gateway)
            console.print(
                f"[cyan]Jev Tool Routing · {profile.label} · {chosen_provider} · {mode}[/cyan]"
            )
            if plan.note:
                console.print(f"[yellow]{plan.note}[/yellow]")
            child_env = os.environ.copy()
            child_env.update(plan.environment)
            return_code = subprocess.run(plan.command, env=child_env, check=False).returncode
        finally:
            _print_report(gateway_url, mode=mode)
            gateway.terminate()
            try:
                gateway.wait(timeout=5)
            except subprocess.TimeoutExpired:
                gateway.kill()
                gateway.wait()
        raise SystemExit(return_code)


def _setup_row(profile, *, model: str = "") -> dict[str, object]:
    installed = profile.executable() is not None
    if not installed:
        status = "not-installed"
    elif profile.support == "detect-only":
        status = "detect-only"
    elif profile.id == "pi" and not model:
        status = "needs-model"
    else:
        status = profile.support if profile.support != "gateway" else "ready"

    command: list[str] = ["superqode", "optimize", "run", profile.id]
    if profile.id == "pi":
        command.extend(["--model", model or "MODEL"])
    command.append("--")
    return {
        "id": profile.id,
        "label": profile.label,
        "installed": installed,
        "status": status,
        "support": profile.support,
        "integration": profile.integration,
        "command": shlex.join(command) if installed and profile.support != "detect-only" else "",
        "note": profile.note,
    }


def _run_routing_probe(threshold: float) -> dict[str, object]:
    """Exercise one live decision and prove stable reuse without a coding model."""
    from superqode.jev_tools import JevToolRouting

    tools = [
        {
            "type": "function",
            "name": name,
            "description": description,
            "parameters": {"type": "object"},
        }
        for name, description in (
            ("web_search", "Search official documentation on the public internet"),
            ("web_fetch", "Read a selected public web page"),
            ("image_gen", "Generate or edit an image"),
            ("send_email", "Send an email message"),
            ("database_query", "Query an application database"),
            ("deploy", "Deploy an application"),
        )
    ]
    try:
        router = JevToolRouting(mode="enforce", threshold=threshold, timeout_ms=5000)

        async def probe():
            first = await router.route(
                "Find the current official release notes online and summarize them.",
                tools,
                turn_id="superqode-local-verify",
            )
            second = await router.route(
                "Find the current official release notes online and summarize them.",
                tools,
                turn_id="superqode-local-verify",
            )
            return first, second

        first, second = asyncio.run(probe())
    except Exception as exc:  # noqa: BLE001 - CLI turns transport errors into a status
        return {"status": "error", "error": type(exc).__name__}
    status = "ok" if first.status == "ok" and second.cached else first.status
    return {
        "status": status,
        "original_tools": first.original_count,
        "selected_tools": first.selected_count,
        "dropped": list(first.dropped),
        "original_schema_bytes": first.original_schema_bytes,
        "selected_schema_bytes": first.selected_schema_bytes,
        "latency_ms": first.latency_ms,
        "cache_reused": second.cached,
    }


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _profile(name: str):
    try:
        return get_profile(name)
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc


def _wait_for_gateway(url: str, process: subprocess.Popen, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise click.ClickException("Jev Tool Routing gateway exited during startup")
        try:
            with urlopen(url + "/healthz", timeout=0.25) as response:
                if response.status == 200:
                    return
        except OSError:
            time.sleep(0.05)
    raise click.ClickException("Jev Tool Routing gateway did not become ready")


def _print_report(url: str, *, mode: str = "shadow") -> None:
    try:
        with urlopen(url + "/superqode/status", timeout=0.5) as response:
            report = json.load(response)
    except (OSError, ValueError):
        return
    reduction_label = "applied reduction" if mode == "enforce" else "recommended reduction"
    console.print(
        "[bold]Jev Tool Routing report[/bold] · "
        f"{report['routed_requests']}/{report['model_requests']} routed requests · "
        f"{report['original_tools']}→{report['selected_tools']} tool entries · "
        f"{report['tool_entry_reduction_percent']}% {reduction_label} · "
        f"schema bytes {report['original_schema_bytes']}→{report['selected_schema_bytes']} "
        f"({report['schema_byte_reduction_percent']}%) · "
        f"{report['unroutable_catalogues']} unroutable catalogues · "
        f"{report['cache_hits']} cache hits · {report['fail_open_errors']} fail-open errors"
    )
    if report["model_requests"] and not report["routed_requests"]:
        shape = report.get("last_request_shape") or {}
        console.print(
            "[dim]Unrouted request shape · "
            f"path={shape.get('path', '?')} · tools={shape.get('tools_container', '?')}"
            f"[{shape.get('tool_count', 0)}] · keys={','.join(shape.get('top_level_keys', []))}[/dim]"
        )


__all__ = ["optimize"]


_BENCHMARK_TOOLS = (
    ("read_file", "Read a file from the workspace"),
    ("write_file", "Create or overwrite a workspace file"),
    ("edit_file", "Apply a focused edit to a workspace file"),
    ("run_terminal_command", "Run shell commands and tests"),
    ("grep", "Search text in workspace files"),
    ("list_dir", "List files and directories"),
    ("web_search", "Search the public internet"),
    ("web_fetch", "Download and read a web page"),
    ("browser", "Control an interactive web browser"),
    ("image_gen", "Generate or edit an image"),
    ("reference_to_video", "Generate a video from reference media"),
    ("spawn_subagent", "Delegate independent work to a subagent"),
    ("send_feedback", "Send product feedback"),
    ("workflow", "Create or run a multi-stage workflow"),
    ("scheduler", "Schedule recurring work"),
    ("send_email", "Send an email message"),
    ("database_query", "Query an application database"),
    ("deploy", "Deploy an application"),
    ("slack", "Read or send Slack messages"),
    ("notebook", "Execute notebook cells"),
)

_BENCHMARK_SCENARIOS = (
    (
        "workspace-test",
        "Read the calculator implementation and tests, run the unit tests, and report failures.",
        frozenset({"read_file", "run_terminal_command"}),
    ),
    (
        "web-research",
        "Research the latest official release notes online and summarize the breaking changes.",
        frozenset({"web_search", "web_fetch"}),
    ),
    (
        "image-task",
        "Create a transparent-background product icon and save it for the website.",
        frozenset({"image_gen"}),
    ),
    (
        "database-analysis",
        "Query the orders database for failed checkouts and write a short incident report.",
        frozenset({"database_query", "write_file"}),
    ),
    (
        "browser-form",
        "Open the staging admin site in a browser and submit the release checklist form.",
        frozenset({"browser"}),
    ),
)
