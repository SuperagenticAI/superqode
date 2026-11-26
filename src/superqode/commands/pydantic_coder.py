"""CLI entry points for the optional Pydantic Coder ACP agent."""

from pathlib import Path
import subprocess
import click


@click.group("pydantic-coder")
def pydantic_coder():
    """Install, check or serve the experimental Pydantic Coder ACP agent."""


def _setup(interpreter, install):
    from superqode.pydantic_coder.setup import setup_runtime

    try:
        versions = setup_runtime(interpreter, install=install)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        "Pydantic Coder runtime ready: "
        + ", ".join(f"{name} {version}" for name, version in versions.items())
    )


@pydantic_coder.command("setup")
@click.option(
    "--python",
    "interpreter",
    type=click.Path(path_type=Path),
    help="Python in a separate virtual environment",
)
def setup(interpreter):
    """Explicitly install the pinned SDKs into a private environment."""
    _setup(interpreter, True)


@pydantic_coder.command("doctor")
@click.option("--python", "interpreter", type=click.Path(path_type=Path))
def doctor(interpreter):
    """Verify installed packages without downloading or calling a model."""
    _setup(interpreter, False)


@pydantic_coder.command("serve")
@click.option("--model", help="Default provider:model")
def serve(model):
    """Serve Pydantic Coder over ACP stdio."""
    from superqode.pydantic_coder.launcher import main

    raise SystemExit(main(["--model", model] if model else []))


async def connect_interactive(project_dir=None, *, model=None, resume=None):
    """Use the shared ACP client so CLI permission requests never auto-approve."""
    import asyncio
    from rich.console import Console
    from rich.prompt import Confirm
    from superqode.acp.client import ACPClient
    from superqode.pydantic_coder import COMMAND, SETUP_HINT, installed

    console = Console()
    if not installed():
        console.print("Pydantic Coder runtime is missing. " + SETUP_HINT, markup=False)
        return 1

    async def message(text):
        console.print(text, end="", markup=False, highlight=False)

    async def permission(options, tool):
        console.print(tool.get("title") or "Tool request", markup=False)
        console.print(tool.get("rawInput") or {}, markup=False)
        approved = await asyncio.to_thread(
            Confirm.ask, "Allow this tool call?", default=False, console=console
        )
        wanted = "allow_once" if approved else "reject_once"
        return next((o["optionId"] for o in options if o["kind"] == wanted), "")

    client = ACPClient(
        Path(project_dir or Path.cwd()).resolve(),
        COMMAND,
        model=model,
        resume_session_id=resume,
        require_resume=bool(resume),
        on_message=message,
        on_permission_request=permission,
        traffic_log_enabled=False,
        prompt_timeout=1800,
    )
    try:
        if not await client.start():
            console.print(client.last_startup_error, markup=False)
            return 1
        console.print(
            "Pydantic Coder connected. /models, /model ID, or /quit. API-key billing applies."
        )
        console.print("Session: " + client.get_session_id(), markup=False)
        while True:
            try:
                prompt = (await asyncio.to_thread(console.input, "> ")).strip()
            except EOFError:
                break
            if prompt.lower() in {"exit", "quit", "q", "/quit"}:
                break
            if prompt == "/models":
                option = next(
                    (o for o in client.get_session_config_options() if o.get("id") == "model"), {}
                )
                for item in option.get("options", []):
                    console.print(item["value"], markup=False)
            elif prompt.startswith("/model "):
                if not await client.set_config_option("model", prompt[7:].strip()):
                    console.print("Model selection rejected. Use /models to see available choices.")
            elif prompt:
                reason = await client.send_prompt(prompt)
                console.print()
                if reason != "end_turn":
                    console.print("Turn stopped: " + str(reason), markup=False)
        return 0
    except (OSError, RuntimeError, ValueError) as exc:
        console.print("Pydantic Coder connection failed: " + str(exc), markup=False)
        return 1
    finally:
        await client.stop()


@pydantic_coder.command("chat")
@click.option("--project-dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--model", help="Advertised provider:model")
@click.option("--resume", help="Resume this project's saved ACP session")
def chat(project_dir, model, resume):
    """Chat over ACP with explicit permission prompts."""
    import asyncio

    raise SystemExit(asyncio.run(connect_interactive(project_dir, model=model, resume=resume)))
