"""SuperQode 'skillopt' CLI: skill optimization export/check."""

import json
from pathlib import Path
import click
import click

import click


@click.group()
def skillopt():
    """Optimize markdown skills with bounded edits and eval gates."""
    pass
@skillopt.command("export")
@click.argument("skill")
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--project", "project_dir", type=click.Path(path_type=Path), required=True)
@click.option("--root", type=click.Path(path_type=Path), default=Path("."), show_default=True)
@click.option("--harness", "harness_path", type=click.Path(exists=True, path_type=Path))
@click.option("--max-edits", default=4, show_default=True, type=int)
@click.option("--live-eval", is_flag=True, help="Put --live in the generated harness eval gate")
@click.option("--force", is_flag=True, help="Overwrite an existing project directory")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def skillopt_export(
    skill,
    tasks_path,
    project_dir,
    root,
    harness_path,
    max_edits,
    live_eval,
    force,
    json_output,
):
    """Export a SkillOpt-style workspace for one SuperQode skill."""
    from superqode.skillopt import export_skillopt_project, render_skillopt_export

    try:
        export = export_skillopt_project(
            skill=skill,
            tasks_path=tasks_path,
            project_dir=project_dir,
            root=root,
            harness_path=harness_path,
            max_edits=max_edits,
            live_eval=live_eval,
            force=force,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(export.to_dict(), indent=2))
        return
    click.echo(render_skillopt_export(export))
@skillopt.command("check")
@click.option(
    "--baseline", "baseline_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option(
    "--candidate", "candidate_path", type=click.Path(exists=True, path_type=Path), required=True
)
@click.option("--max-edits", default=4, show_default=True, type=int)
@click.option("--max-bytes", default=50_000, show_default=True, type=int)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def skillopt_check(baseline_path, candidate_path, max_edits, max_bytes, json_output):
    """Check a candidate skill against the bounded-edit safety gate."""
    from superqode.skillopt import check_skill_candidate, render_skillopt_check

    payload = check_skill_candidate(
        baseline_path=baseline_path,
        candidate_path=candidate_path,
        max_edits=max_edits,
        max_bytes=max_bytes,
    )
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_skillopt_check(payload))
    if not payload["ok"]:
        raise click.exceptions.Exit(1)
