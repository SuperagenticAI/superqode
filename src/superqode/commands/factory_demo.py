"""Explicit first-run demo commands over the shared Factory engine."""

import click

from .factory_operations import output, project_option


@click.group()
def demo():
    """Create a disposable sample and reproduce its defect before a real trial."""


@demo.command("create")
@click.argument("destination", type=click.Path())
@click.option("--confirm", is_flag=True)
@click.option("--model", default="ollama/qwen3-coder", show_default=True)
@click.option(
    "--allow-cloud", is_flag=True, help="Explicitly permit cloud execution models in this sample"
)
@output
def create(destination, confirm, model, allow_cloud):
    from superqode.factory.demo import create

    return create(destination, confirmed=confirm, model=model, allow_cloud=allow_cloud)


@demo.command("check")
@project_option
@click.option("--execute", is_flag=True, help="Run isolated sample probes without inference")
@output
def check(project, execute):
    from superqode.factory.demo import check

    return check(project, execute=execute)


@click.group()
def draft():
    """Keep and inspect a local Factory draft without activating it."""


@draft.command("keep")
@project_option
@click.option("--file", "filename", required=True, help="Project-relative Factory draft YAML")
@click.option("--confirm", is_flag=True)
@output
def keep(project, filename, confirm):
    from pathlib import Path
    from superqode.factory.definition import project_path
    from superqode.factory.operations import read
    from superqode.factory.onboarding import save_draft

    return save_draft(
        project,
        yaml_text=read(project_path(Path(project).resolve(), filename), 250000).decode("utf-8"),
        confirmed=confirm,
    )


@draft.command("show")
@project_option
@output
def show(project):
    from superqode.factory.onboarding import load_draft

    return load_draft(project)
