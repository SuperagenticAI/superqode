"""SuperQE CLI entrypoint.

Exposes the QE automation commands as a dedicated CLI while keeping
SuperQode focused on the developer TUI experience.
"""

from __future__ import annotations

import click

from superqode import __version__
import shutil
from pathlib import Path

from superqode.commands.qe import qe as qe_group
from superqode.commands.superqe import superqe as advanced_group


@click.group()
@click.version_option(version=__version__)
def superqe() -> None:
    """SuperQE - Quality Engineering automation CLI.

    Use `superqode` for the interactive developer TUI.
    """


def _attach_commands(target: click.Group, source: click.Group) -> None:
    for name, command in source.commands.items():
        target.add_command(command, name=name)


_attach_commands(superqe, qe_group)


@superqe.command("init")
@click.argument("path", type=click.Path(), default=".")
@click.option("--force", "-f", is_flag=True, help="Overwrite existing configuration")
@click.option("--guided", "-g", is_flag=True, help="Run guided setup wizard")
def init_command(path: str, force: bool, guided: bool) -> None:
    """Initialize superqode.yaml using the full template (non-interactive)."""
    if guided:
        from superqode.commands.init import init as guided_init

        guided_init(path=path, force=force, minimal=False, guided=True)
        return

    project_root = Path(path).resolve()
    config_path = project_root / "superqode.yaml"

    if config_path.exists() and not force:
        click.echo(f"Configuration already exists at {config_path}")
        click.echo("Use --force to overwrite")
        return

    template_path = Path(__file__).resolve().parents[2] / "superqode-template.yaml"
    if template_path.exists():
        shutil.copy2(template_path, config_path)
        click.echo(f"✓ Created {config_path} with all roles available")
    else:
        click.echo("Template not found; falling back to guided setup.")
        from superqode.commands.init import init as guided_init

        guided_init(path=path, force=force, minimal=False, guided=True)


superqe.add_command(advanced_group, name="advanced")


def main() -> None:
    """Run the SuperQE CLI."""
    superqe()


if __name__ == "__main__":
    main()
