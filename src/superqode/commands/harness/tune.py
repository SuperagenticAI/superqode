"""Guided SystemOne Tune, backed by the same service as the TUI."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from ._group import harness
from superqode.systemone import tune


@harness.command("tune")
@click.option(
    "--setup",
    is_flag=True,
    help="Install tested tuning support into SuperQode's Python environment; makes no model calls.",
)
@click.option("--spec", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option(
    "--pack", default="factory_route", show_default=True, help="Built-in pack ID or pack file."
)
@click.option("--data", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--input", "input_column", default="state", help="Input column in the example file.")
@click.option(
    "--label",
    "label_column",
    default="label",
    help="Expected-answer column; empty values are reviewed interactively.",
)
@click.option(
    "--demo",
    is_flag=True,
    help="Use a small synthetic routing dataset (live experiment, not a benchmark).",
)
@click.option(
    "--resume",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Resume annotation or inspect a completed experiment.",
)
@click.option("--output", type=click.Path(path_type=Path))
@click.option(
    "--reflection-lm",
    default=None,
    help="Optional provider/model override; configured API providers are detected.",
)
@click.option("--max-evals", type=click.IntRange(min=1), default=120, show_default=True)
@click.option(
    "--max-reflection-cost",
    type=click.FloatRange(min=0, min_open=True, max=1000),
    default=2.0,
    show_default=True,
)
@click.option("--seed", type=int, default=0)
@click.option(
    "--live", is_flag=True, help="Start model calls without the interactive start prompt."
)
@click.option(
    "--json",
    "json_output",
    is_flag=True,
    help="Machine-readable result; requires labeled examples and --live for new runs.",
)
def harness_tune(
    setup,
    spec,
    pack,
    data,
    input_column,
    label_column,
    demo,
    resume,
    output,
    reflection_lm,
    max_evals,
    max_reflection_cost,
    seed,
    live,
    json_output,
):
    """Improve SystemOne decisions from examples you review.

    With no arguments, guide setup and labeling. A candidate is staged separately;
    tuning never changes the active harness. GEPA and Jev require API access.
    """
    interactive = sys.stdin.isatty() and not json_output
    try:
        if setup:
            message = tune.install_support()
            click.echo(
                json.dumps({"status": "installed", "message": message}) if json_output else message
            )
            return
        if resume:
            if data or spec or demo or output:
                raise ValueError("Use --resume without --data, --spec, --demo or --output.")
            output = resume
            manifest = tune.load_run(output)
            if manifest["status"] == "review":
                from click.core import ParameterSource

                manifest["options"]["reflection_lm"] = (
                    reflection_lm
                    or manifest["options"]["reflection_lm"]
                    or tune.default_reflection_model()
                )
                for name, value in (
                    ("max_evals", max_evals),
                    ("max_reflection_cost", max_reflection_cost),
                ):
                    if (
                        click.get_current_context().get_parameter_source(name)
                        == ParameterSource.COMMANDLINE
                    ):
                        manifest["options"][name] = value
                tune.write_json(output / "run.json", manifest)
        else:
            if demo and (data or spec or pack != "factory_route"):
                raise ValueError(
                    "The demo uses the built-in factory_route pack; omit --data, --spec and --pack."
                )
            if data is None and not demo:
                if not interactive:
                    raise ValueError(
                        "Supply --data FILE or --demo. Run in a terminal for guided setup."
                    )
                click.echo(
                    "SystemOne Tune · Improve decisions\nStart with your examples, or try a small routing demo."
                )
                source = click.prompt("CSV/JSONL/JSON/YAML file, or demo", default="demo")
                if source == "demo":
                    if spec or pack != "factory_route":
                        raise ValueError(
                            "The demo requires factory_route; restart without --spec/--pack."
                        )
                    demo = True
                else:
                    data = Path(source).expanduser()
                    input_column = click.prompt("Input column", default=input_column)
                    label_column = click.prompt("Expected-answer column", default=label_column)
            reflection_lm = reflection_lm or tune.default_reflection_model()
            if not reflection_lm and interactive:
                reflection_lm = click.prompt(
                    "Model to improve criteria (provider/model)", default="openai/gpt-4.1-mini"
                )
            options = tune.TuneOptions(
                pack=pack,
                spec=str(spec or ""),
                reflection_lm=reflection_lm,
                max_evals=max_evals,
                max_reflection_cost=max_reflection_cost,
                seed=seed,
            )
            rows = (
                tune.demo_examples()
                if demo
                else tune.read_examples(data, input_column=input_column, label_column=label_column)
            )
            output = output or tune.new_output()
            manifest = tune.prepare_run(options, rows, output)
        if manifest["status"] == "completed":
            report = json.loads((output / "report.json").read_text())
            click.echo(json.dumps(report) if json_output else tune.render_report(report))
            return
        if manifest["status"] != "review":
            raise ValueError(
                f"Experiment is {manifest['status']}. Evidence is in {output}; start a new experiment for a new budget."
            )
        question = next(iter(manifest["pack"]["questions"].values()))
        labels = list(question["criteria"])
        for row in manifest["examples"]:
            if row.get("label") is not None:
                continue
            if not interactive:
                raise ValueError(
                    f"Unlabeled examples saved. Resume in a terminal: superqode harness tune --resume {output}"
                )
            click.echo(
                f"\nExample {row['id']} · {'reserved test' if row['split'] == 'test' else 'development'}"
            )
            click.echo(json.dumps(row["state"], ensure_ascii=False, indent=2))
            label = click.prompt("Which decision is correct?", type=click.Choice(labels))
            rationale = click.prompt("Why? (optional)", default="", show_default=False)
            tune.save_label(output, row["id"], label, rationale)
        manifest = tune.load_run(output)
        details = tune.preflight(manifest)
        if not json_output:
            click.echo(
                f"\nJev: {details['model']} at {details['endpoint']}\nReflection: {details['reflection_model']}"
            )
            click.echo(
                f"Up to {max_evals if not resume else details['max_evals']} optimization evaluations + {details['final_test_evals']} final test evaluations."
            )
            click.echo(
                f"Reflection ceiling: ${details['max_reflection_cost']:.2f}; Jev usage and retries are additional."
            )
            click.echo(
                "Example inputs and criteria go to Jev; development examples and rationales also go to the reflection provider."
            )
            click.echo(f"Saved experiment: {output}")
        if not live:
            if not interactive:
                raise ValueError(
                    f"Prepared without model calls. Add --live to --resume {output} to start."
                )
            if not click.confirm("Start this experiment?", default=True):
                return
        report = tune.run_tune(
            output,
            progress=(lambda message: click.echo(message, err=True))
            if not json_output
            else lambda _: None,
        )
        click.echo(json.dumps(report) if json_output else tune.render_report(report))
    except KeyboardInterrupt:
        raise click.ClickException(f"Stopped. Saved work: {output}") from None
    except (ValueError, OSError, RuntimeError, tune.TuneCancelled) as exc:
        if json_output:
            click.echo(
                json.dumps({"status": "error", "error": str(exc), "output": str(output or "")})
            )
            raise click.exceptions.Exit(2) from exc
        raise click.ClickException(str(exc)) from exc
