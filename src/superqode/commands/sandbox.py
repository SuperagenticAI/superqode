"""SuperQode 'sandbox' CLI: sandbox doctor/run."""

import json
from pathlib import Path
import click
import click

import click


@click.group()
def sandbox():
    """Inspect and run sandbox execution backends."""
    pass


@sandbox.command("doctor")
@click.argument("backend", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sandbox_doctor(backend, json_output):
    """Show setup status for sandbox providers."""
    from superqode.sandbox import (
        get_sandbox_capabilities,
        sandbox_provider_status,
        supported_sandbox_backends,
    )

    backends = [backend] if backend else supported_sandbox_backends(include_cloud=True)
    payload = []
    for name in backends:
        status = sandbox_provider_status(name).to_dict()
        try:
            caps = get_sandbox_capabilities(name)
            status["capabilities"] = {
                "can_read": caps.can_read,
                "can_write": caps.can_write,
                "can_shell": caps.can_shell,
                "can_network": caps.can_network,
                "description": caps.description,
            }
        except ValueError:
            status["capabilities"] = None
        payload.append(status)

    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    for item in payload:
        marker = "ready" if item["available"] else "missing"
        click.echo(f"{item['backend']}  {marker}  {item['detail']}")


@sandbox.command("run", context_settings={"ignore_unknown_options": True})
@click.argument(
    "backend",
    type=click.Choice(
        [
            "local",
            "local-os",
            "docker",
            "podman",
            "apple-container",
            "e2b",
            "daytona",
            "modal",
            "vercel",
        ]
    ),
)
@click.argument("command", nargs=-1, required=True)
@click.option("--cwd", type=click.Path(file_okay=False, path_type=Path), default=Path.cwd)
@click.option("--timeout", type=int, default=300, show_default=True)
@click.option("--image", default="python:3.12-slim", show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def sandbox_run(backend, command, cwd, timeout, image, json_output):
    """Run a command in a local or explicitly configured cloud sandbox provider."""
    from superqode.sandbox import run_in_sandbox

    shell_command = " ".join(command).strip()
    if not shell_command:
        raise click.UsageError("sandbox run requires a command")

    try:
        result = run_in_sandbox(backend, shell_command, cwd, timeout=timeout, image=image)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(result.to_dict(), indent=2))
        raise SystemExit(result.exit_code)

    if result.stdout:
        click.echo(result.stdout, nl=not result.stdout.endswith("\n"))
    if result.stderr:
        click.echo(result.stderr, err=True, nl=not result.stderr.endswith("\n"))
    raise SystemExit(result.exit_code)
