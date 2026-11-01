"""Packaged setup commands for the isolated Strands runtime."""

from pathlib import Path
import subprocess
import click

from ._group import harness


@harness.group("strands")
def harness_strands():
    """Install or check the separate Strands harness environment."""


def _setup(interpreter, install):
    from superqode.harness.strands_setup import setup_runtime

    try:
        versions = setup_runtime(interpreter, install=install)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        raise click.ClickException(str(exc)) from exc
    click.echo(
        "Strands runtime ready: " + ", ".join(f"{name} {value}" for name, value in versions.items())
    )


@harness_strands.command("setup")
@click.option(
    "--python",
    "interpreter",
    type=click.Path(path_type=Path),
    help="Python in a separate virtual environment",
)
def strands_setup(interpreter):
    """Explicitly install the pinned Strands runtime using uv."""
    _setup(interpreter, True)


@harness_strands.command("doctor")
@click.option("--python", "interpreter", type=click.Path(path_type=Path))
def strands_doctor(interpreter):
    """Check the runtime without installing packages or calling a model."""
    _setup(interpreter, False)
