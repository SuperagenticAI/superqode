"""SuperQode 'harness' CLI command group: create/validate/run/optimize harness specs."""

import os
import json
import time
from pathlib import Path
import click
import click

import click



# Harness/workflow CLI choice constants (moved verbatim from main.py)
HARNESS_TEMPLATE_CHOICES = (
    "coding",
    "no-tool",
    "qwen-coding",
    "glm-coding",
    "gemma4-coding",
    "gemma4-no-tool",
    "ds4-coding",
    "ds4-fast-local",
)
WORKFLOW_PRESET_CHOICES = (
    "single",
    "plan-implement-review",
    "fix-and-verify",
    "parallel-review",
    "security-review",
    "release-check",
    "router",
    "evaluator-optimizer",
)

# Global variables for interactive mode


@click.group()
def harness():
    """Create, validate, and run SuperQode harness specs."""
    pass
@harness.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_list(json_output):
    """List selectable built-in, project, and registry harnesses."""
    from superqode.harness import list_harnesses

    rows = [entry.to_dict() for entry in list_harnesses(Path.cwd())]
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return
    click.echo(f"{'ID':<20} {'DEFAULT':<8} {'SOURCE':<10} {'RUNTIME':<16} {'TOOLS':>5}  STATUS")
    for row in rows:
        status = "ready" if row["available"] else str(row["issue"] or "unavailable")
        click.echo(
            f"{str(row['id']):<20} "
            f"{('*' if row['default'] else ''):<8} "
            f"{str(row['source']):<10} "
            f"{str(row['runtime']):<16} "
            f"{int(row['tool_count']):>5}  {status}"
        )
@harness.command("show")
@click.argument("reference")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_show(reference, json_output):
    """Show one selectable harness by name or spec path."""
    from superqode.harness import harness_spec_to_dict, resolve_harness

    try:
        entry = resolve_harness(reference, root=Path.cwd())
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {**entry.to_dict(), "spec": harness_spec_to_dict(entry.spec)}
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Harness: {entry.id}{' (default)' if entry.default else ''}")
    click.echo(f"Description: {entry.description}")
    click.echo(f"Source: {entry.source}")
    click.echo(f"Runtime: {entry.runtime}")
    click.echo(f"Tools ({len(entry.tools)}): {', '.join(entry.tools) or 'none'}")
    click.echo(f"Digest: {entry.digest}")
@harness.command("use")
@click.argument("reference")
@click.option(
    "--config",
    "config_path",
    type=click.Path(path_type=Path),
    default=Path("superqode.yaml"),
    show_default=True,
    help="Project configuration to update",
)
def harness_use(reference, config_path):
    """Set the project's default harness."""
    import yaml

    from superqode.harness import resolve_harness

    try:
        entry = resolve_harness(reference, root=Path.cwd())
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    data = {}
    if config_path.is_file():
        loaded = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
        if not isinstance(loaded, dict):
            raise click.ClickException(f"{config_path} must contain a YAML mapping")
        data = loaded
    superqode_config = data.setdefault("superqode", {})
    if not isinstance(superqode_config, dict):
        raise click.ClickException("superqode config section must be a mapping")
    superqode_config["harness"] = str(entry.path or entry.id)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    click.echo(f"Project default harness: {entry.id} ({config_path})")
@harness.command("list-templates")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_list_templates(json_output):
    """List built-in harness templates."""
    from superqode.harness import BUILTIN_TEMPLATES, get_harness_template, harness_spec_to_dict

    rows = []
    for name in sorted(BUILTIN_TEMPLATES):
        if "_" in name:
            continue
        spec = get_harness_template(name)
        rows.append(
            {
                "name": name,
                "flavor": spec.flavor.value,
                "runtime": spec.runtime.backend,
                "description": spec.description,
            }
        )

    if json_output:
        payload = [
            {**row, "spec": harness_spec_to_dict(get_harness_template(row["name"]))} for row in rows
        ]
        click.echo(json.dumps(payload, indent=2))
        return

    for row in rows:
        click.echo(f"{row['name']}  {row['flavor']}  {row['runtime']}  {row['description']}")
@harness.command("list-backends")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_list_backends(json_output):
    """List available harness runtime backends."""
    from superqode.harness import backend_capabilities, known_harness_backend_names

    rows = [backend_capabilities(name).to_dict() for name in known_harness_backend_names()]
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return

    for row in rows:
        install = f" install: {row['install_hint']}" if row["install_hint"] else ""
        click.echo(
            f"{row['backend']}  {row['availability']}  "
            f"coding={'yes' if row['supports_coding'] else 'no'}  "
            f"no_tool={'yes' if row['supports_no_tool'] else 'no'}  "
            f"streaming={'yes' if row['supports_streaming'] else 'no'}  "
            f"approvals={'yes' if row['supports_approvals'] else 'no'}  "
            f"workflow={'yes' if row['supports_workflow_children'] else 'no'}  "
            f"events={row['event_detail']}"
            f"{install}"
        )
@harness.command("wizard")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("harness.yaml"),
    show_default=True,
    help="Harness spec file to write",
)
@click.option("--force", is_flag=True, help="Overwrite an existing spec file")
def harness_wizard(output, force):
    """Build a harness.yaml interactively (no hand-editing YAML required)."""
    from superqode.harness import (
        APPROVAL_PROFILES,
        TOOL_CALL_FORMATS,
        WIZARD_STARTERS,
        WizardAnswers,
        build_wizard_spec,
        explain_harness,
        render_explanation,
        save_harness_spec,
    )

    if output.exists() and not force:
        raise click.ClickException(f"{output} already exists. Use --force to overwrite.")

    def _choose(title, options, default_key):
        click.echo(f"\n{title}")
        keys = [key for key, _ in options]
        for index, (key, label) in enumerate(options, start=1):
            marker = " (default)" if key == default_key else ""
            click.echo(f"  {index}. {label}{marker}")
        raw = click.prompt("Choose", default=str(keys.index(default_key) + 1))
        try:
            return keys[int(raw) - 1]
        except (ValueError, IndexError):
            return raw if raw in keys else default_key

    click.echo("SuperQode harness wizard")
    click.echo("Answer a few questions; press Enter to accept the default.")

    name = click.prompt("\nHarness name", default="my-harness")
    starter = _choose("Starting point (model family)", WIZARD_STARTERS, "qwen-coding")
    no_tool = starter == "no-tool"

    provider = click.prompt(
        "Provider (e.g. ollama, lmstudio, mlx, ds4; blank to keep template)",
        default="",
        show_default=False,
    )
    model = click.prompt(
        "Model id (blank to keep the template's model)", default="", show_default=False
    )

    if no_tool:
        answers = WizardAnswers(name=name, starter=starter, provider=provider, model=model)
    else:
        allow_write = click.confirm("Allow the agent to write/edit files?", default=True)
        allow_shell = click.confirm("Allow the agent to run shell commands?", default=True)
        allow_network = click.confirm("Allow network access?", default=False)
        approval_profile = _choose("Approval profile", APPROVAL_PROFILES, "balanced")
        tool_call_format = _choose("Tool-call format", TOOL_CALL_FORMATS, "auto")
        workflow_preset = _choose(
            "Workflow",
            (
                ("single", "One agent handles the whole task"),
                ("plan-implement-review", "Planner, implementer, reviewer chain"),
                ("fix-and-verify", "Fix then verify with checks"),
                ("parallel-review", "Multiple reviewers in parallel"),
                ("security-review", "Security-focused review chain"),
            ),
            "single",
        )
        answers = WizardAnswers(
            name=name,
            starter=starter,
            provider=provider,
            model=model,
            allow_write=allow_write,
            allow_shell=allow_shell,
            allow_network=allow_network,
            approval_profile=approval_profile,
            tool_call_format=tool_call_format,
            workflow_preset=workflow_preset,
        )

    spec = build_wizard_spec(answers)
    save_harness_spec(spec, output)
    (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
    (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)

    click.echo(f"\nWrote {output}\n")
    click.echo(render_explanation(explain_harness(spec, provider=provider, model=model)))
    click.echo("Next steps:")
    click.echo(f"  Edit if needed:   {output}")
    click.echo(f"  Run it:           superqode --harness {output}")
    click.echo(f"  Re-explain:       superqode harness explain --spec {output}")
@harness.command("init")
@click.argument("name", required=False, default="superqode-coding")
@click.option(
    "--template",
    "-t",
    type=click.Choice(HARNESS_TEMPLATE_CHOICES),
    default="coding",
    show_default=True,
    help="Built-in template name",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("harness.yaml"),
    show_default=True,
    help="Harness spec file to write",
)
@click.option(
    "--preset",
    "workflow_preset",
    type=click.Choice(WORKFLOW_PRESET_CHOICES),
    default=None,
    help="Apply a workflow preset to the generated HarnessSpec",
)
@click.option("--force", is_flag=True, help="Overwrite an existing spec file")
@click.option(
    "--minimal",
    is_flag=True,
    help="Write a small spec that inherits from the selected template",
)
def harness_init(name, template, output, workflow_preset, force, minimal):
    """Scaffold a harness spec and local agent directories."""
    from dataclasses import replace

    from superqode.harness import (
        WorkflowSpec,
        apply_workflow_preset,
        get_workflow_preset,
        get_harness_template,
        save_harness_spec,
    )

    if output.exists() and not force:
        raise click.ClickException(f"{output} already exists. Use --force to overwrite.")

    if minimal:
        import yaml

        payload = {
            "version": 1,
            "name": name,
            "inherits": template,
        }
        if workflow_preset:
            payload["workflow"] = {"preset": workflow_preset}
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
        (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
        (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
        click.echo(f"Created {output}")
        click.echo(f"Inherits template: {template}")
        if workflow_preset:
            click.echo(f"Applied workflow preset: {workflow_preset}")
        click.echo("Created .agents/skills and .agents/roles")
        return

    spec = replace(get_harness_template(template), name=name)
    if workflow_preset:
        preset = get_workflow_preset(workflow_preset)
        base_agent = spec.agents[0] if spec.agents else None
        inherited_tools = base_agent.tools if base_agent and spec.is_coding else ()
        inherited_skills = base_agent.skills if base_agent and spec.is_coding else ()
        preset_agents = tuple(
            replace(
                agent,
                tools=agent.tools or inherited_tools,
                skills=agent.skills or inherited_skills,
            )
            for agent in preset.agents
        )
        spec = replace(
            spec,
            workflow=WorkflowSpec(preset=preset.name),
            agents=preset_agents,
        )
        spec = apply_workflow_preset(spec)
    save_harness_spec(spec, output)
    (Path(".agents") / "skills").mkdir(parents=True, exist_ok=True)
    (Path(".agents") / "roles").mkdir(parents=True, exist_ok=True)
    click.echo(f"Created {output}")
    if workflow_preset:
        click.echo(f"Applied workflow preset: {workflow_preset}")
    click.echo("Created .agents/skills and .agents/roles")
@harness.command("import-omnigent")
@click.argument("agent_yaml", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("harness.yaml"),
    show_default=True,
    help="Harness spec file to write",
)
@click.option("--name", default=None, help="Override the generated HarnessSpec name")
@click.option("--force", is_flag=True, help="Overwrite an existing spec file")
def harness_import_omnigent(agent_yaml, output, name, force):
    """Convert an Omnigent agent.yaml into a SuperQode HarnessSpec."""
    from superqode.harness import import_omnigent_agent, load_harness_spec

    if output.exists() and not force:
        raise click.ClickException(f"{output} already exists. Use --force to overwrite.")
    written = import_omnigent_agent(agent_yaml, output=output, name=name)
    spec = load_harness_spec(written)
    click.echo(f"Imported Omnigent agent: {agent_yaml}")
    click.echo(f"Created {written}")
    click.echo(
        f"Harness: {spec.name} "
        f"(runtime={spec.runtime.backend}, workflow={spec.workflow.mode.value})"
    )
@harness.command("import-agent")
@click.argument("agent_yaml", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("harness.yaml"),
    show_default=True,
    help="Harness spec file to write",
)
@click.option("--name", default=None, help="Override the generated HarnessSpec name")
@click.option("--force", is_flag=True, help="Overwrite an existing spec file")
def harness_import_agent(agent_yaml, output, name, force):
    """Compile a concise SuperQode agent.yaml into a HarnessSpec."""
    from superqode.harness import import_agent_yaml, load_harness_spec

    if output.exists() and not force:
        raise click.ClickException(f"{output} already exists. Use --force to overwrite.")
    written = import_agent_yaml(agent_yaml, output=output, name=name)
    spec = load_harness_spec(written)
    click.echo(f"Imported SuperQode agent: {agent_yaml}")
    click.echo(f"Created {written}")
    click.echo(
        f"Harness: {spec.name} "
        f"(runtime={spec.runtime.backend}, workflow={spec.workflow.mode.value})"
    )
@harness.command("validate")
@click.argument("spec_arg", required=False, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--spec", "spec_option", type=click.Path(exists=True, path_type=Path), help="Harness spec file"
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.option("--schema", "schema_output", is_flag=True, help="Emit HarnessSpec JSON Schema")
def harness_validate(spec_arg, spec_option, json_output, schema_output):
    """Validate a harness spec file."""
    from superqode.harness import harness_spec_json_schema, harness_spec_to_dict, load_harness_spec

    if schema_output:
        click.echo(json.dumps(harness_spec_json_schema(), indent=2))
        return
    spec_path = spec_option or spec_arg
    if spec_path is None:
        raise click.ClickException("Missing harness spec. Pass --spec <path>.")
    if spec_option is not None and spec_arg is not None and spec_option != spec_arg:
        raise click.ClickException(
            "Pass the harness spec either as --spec or positional path, not both."
        )

    try:
        spec = load_harness_spec(spec_path)
    except Exception as exc:
        payload = {"valid": False, "error": str(exc)}
        if json_output:
            click.echo(json.dumps(payload, indent=2))
            return
        raise click.ClickException(str(exc)) from exc

    payload = {
        "valid": True,
        "name": spec.name,
        "flavor": spec.flavor.value,
        "runtime": spec.runtime.backend,
        "workflow": spec.workflow.mode.value,
        "spec": harness_spec_to_dict(spec),
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(
        f"Valid harness: {spec.name} "
        f"({spec.flavor.value}, runtime={spec.runtime.backend}, workflow={spec.workflow.mode.value})"
    )
@harness.command("inspect")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option("--sandbox", "sandbox_backend", default=None, help="Override sandbox backend")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_inspect(spec_path, runtime_name, sandbox_backend, json_output):
    """Inspect a HarnessSpec and backend capability compatibility."""
    from superqode.harness import (
        inspect_harness,
        load_harness_spec,
        render_harness_inspect,
    )

    spec = load_harness_spec(spec_path)
    payload = inspect_harness(spec, runtime=runtime_name, sandbox=sandbox_backend)
    payload["runtime_details"] = payload["runtime"]
    payload["workflow_details"] = payload["workflow"]
    payload["runtime"] = payload["runtime"]["backend"]
    payload["workflow"] = payload["workflow"]["mode"]
    payload["sandbox"] = payload["permissions"]["sandbox"]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    rendered_payload = inspect_harness(spec, runtime=runtime_name, sandbox=sandbox_backend)
    click.echo(render_harness_inspect(rendered_payload))
@harness.command("compile")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--provider", default=None, help="Provider used to resolve model policy")
@click.option("--model", "model_name", default=None, help="Model used to resolve model policy")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_compile(spec_path, provider, model_name, json_output):
    """Print the effective HarnessSpec and resolved runtime policy."""
    from superqode.harness import (
        compile_to_headless_profile,
        harness_spec_to_dict,
        load_harness_spec,
        resolve_harness_model_policy,
    )

    spec = load_harness_spec(spec_path)
    effective_policy = resolve_harness_model_policy(
        spec,
        provider=provider or spec.model_policy.config.get("provider", ""),
        model=model_name or spec.model_policy.primary or "",
    )
    profile = compile_to_headless_profile(spec)
    payload = {
        "spec": harness_spec_to_dict(spec),
        "effective_model_policy": {
            "profile": effective_policy.profile,
            "family": effective_policy.family,
            "temperature": effective_policy.temperature,
            "system_level": effective_policy.system_level.value,
            "tool_profile": effective_policy.tool_profile,
            "tool_call_format": effective_policy.tool_call_format,
            "reasoning": effective_policy.reasoning,
            "parallel_tools": effective_policy.parallel_tools,
            "max_iterations": effective_policy.max_iterations,
            "session_history_limit": effective_policy.session_history_limit,
        },
        "headless_profile": {
            "name": profile.name,
            "description": profile.description,
            "system_level": profile.system_level.value,
            "tools": profile.tools,
            "permissions": _permission_config_to_dict(profile.permissions),
            "job_description": profile.job_description,
        },
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(json.dumps(payload, indent=2))
@harness.command("explain")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--provider", default=None, help="Provider used to resolve model policy")
@click.option("--model", "model_name", default=None, help="Model used to resolve model policy")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_explain(spec_path, provider, model_name, json_output):
    """Explain in plain English what a harness lets the model do, and why."""
    from superqode.harness import explain_harness, load_harness_spec, render_explanation

    spec = load_harness_spec(spec_path)
    explanation = explain_harness(spec, provider=provider or "", model=model_name or "")
    if json_output:
        click.echo(json.dumps(explanation.to_dict(), indent=2))
        return
    click.echo(render_explanation(explanation))
@harness.command("diff")
@click.argument("left", type=click.Path(exists=True, path_type=Path))
@click.argument("right", type=click.Path(exists=True, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_diff(left, right, json_output):
    """Show policy, tool, and agent differences between two HarnessSpecs."""
    from superqode.harness import harness_spec_to_dict, load_harness_spec

    left_payload = harness_spec_to_dict(load_harness_spec(left))
    right_payload = harness_spec_to_dict(load_harness_spec(right))
    changes = _diff_dicts(left_payload, right_payload)
    payload = {
        "left": str(left),
        "right": str(right),
        "changed": bool(changes),
        "changes": changes,
    }
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not changes:
        click.echo("No differences.")
        return
    for change in changes:
        click.echo(f"{change['path']}: {change.get('left')!r} -> {change.get('right')!r}")
@harness.command("doctor")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option("--sandbox", "sandbox_backend", default=None, help="Override sandbox backend")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Override harness event store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_doctor(spec_path, runtime_name, sandbox_backend, store_path, json_output):
    """Diagnose a harness spec before running it."""
    from superqode.harness import (
        doctor_harness,
        load_harness_spec,
        render_harness_doctor,
    )

    spec = load_harness_spec(spec_path)
    report = doctor_harness(
        spec,
        runtime=runtime_name,
        sandbox=sandbox_backend,
        store_root=store_path,
    )
    payload = report.to_dict()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        if report.status == "error":
            raise click.exceptions.Exit(1)
        return

    click.echo(render_harness_doctor(report))
    if report.status == "error":
        raise click.Abort()
@harness.command("test")
@click.argument("spec_arg", required=False, type=click.Path(exists=True, path_type=Path))
@click.option(
    "--spec", "spec_option", type=click.Path(exists=True, path_type=Path), help="Harness spec file"
)
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option("--prompt", default="Reply with exactly: superqode harness ok", show_default=True)
@click.option("--live", is_flag=True, help="Actually call the configured model endpoint")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_test(
    spec_arg,
    spec_option,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    prompt,
    live,
    json_output,
):
    """Run a fast HarnessSpec smoke test with a failure digest."""
    import asyncio

    from superqode.harness import render_harness_smoke_test, run_harness_smoke_test

    spec_path = spec_option or spec_arg
    if spec_path is None:
        raise click.ClickException("Missing harness spec. Pass --spec <path>.")
    payload = asyncio.run(
        run_harness_smoke_test(
            spec_path,
            provider=provider,
            model=model_name,
            runtime=runtime_name,
            working_dir=working_dir,
            sandbox_backend=sandbox_backend,
            prompt=prompt,
            live=live,
        )
    )
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_harness_smoke_test(payload))
    if payload["status"] == "failed":
        raise click.exceptions.Exit(1)
@harness.command("eval")
@click.option(
    "--spec",
    "spec_paths",
    type=click.Path(exists=True, path_type=Path),
    multiple=True,
    required=True,
)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--variant", "variant_paths", type=click.Path(exists=True, path_type=Path), multiple=True
)
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option(
    "--split",
    "eval_split",
    type=click.Choice(["all", "held-in", "held-out"]),
    default="all",
    show_default=True,
    help="Run all tasks, held-in tasks, or held-out tasks",
)
@click.option("--live", is_flag=True, help="Execute tasks against the model endpoint")
@click.option(
    "--allow-regressions",
    is_flag=True,
    help="Do not fail when a variant regresses a task the baseline solved (seesaw gate)",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_eval(
    spec_paths,
    tasks_path,
    variant_paths,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    eval_split,
    live,
    allow_regressions,
    json_output,
):
    """Run a HarnessSpec eval scorecard across tasks and variants.

    Acts as a seesaw gate: if any variant regresses a task the baseline solved,
    the command exits non-zero unless --allow-regressions is set.
    """
    import asyncio

    from superqode.harness import render_harness_eval, run_harness_eval

    payload = asyncio.run(
        run_harness_eval(
            spec_paths=[*spec_paths, *variant_paths],
            tasks_path=tasks_path,
            provider=provider,
            model=model_name,
            runtime=runtime_name,
            working_dir=working_dir,
            sandbox_backend=sandbox_backend,
            live=live,
            eval_split=eval_split,
        )
    )
    if json_output:
        click.echo(json.dumps(payload, indent=2))
    else:
        click.echo(render_harness_eval(payload))
        if payload.get("regressed") and not allow_regressions:
            click.echo(
                "REGRESSION: "
                + ", ".join(payload.get("regressed_variants") or [])
                + " regressed a task the baseline solved. "
                + "Pass --allow-regressions to override.",
                err=True,
            )
    if payload["status"] == "failed":
        raise click.exceptions.Exit(1)
    if payload.get("regressed") and not allow_regressions:
        raise click.exceptions.Exit(2)
@harness.command("eval-packs")
@click.argument("pack", required=False)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_eval_packs(pack, json_output):
    """List bundled HarnessSpec eval packs, or show one pack path."""
    from superqode.harness import eval_pack_path, list_eval_packs

    if pack:
        path = eval_pack_path(pack)
        payload = {"id": pack, "path": str(path)}
        if json_output:
            click.echo(json.dumps(payload, indent=2))
        else:
            click.echo(str(path))
        return

    payload = list_eval_packs()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not payload:
        click.echo("No bundled eval packs found.")
        return
    for item in payload:
        click.echo(f"{item['id']}  tasks={item['tasks']}  {item['description']}\n  {item['path']}")
@harness.command("auto-bench")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option("--live", is_flag=True, help="Call the configured model endpoint")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_auto_bench(
    spec_path,
    tasks_path,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    live,
    json_output,
):
    """Probe a model-backed harness and recommend next settings."""
    import asyncio

    from superqode.harness import run_harness_eval, run_harness_smoke_test

    if tasks_path:
        payload = asyncio.run(
            run_harness_eval(
                spec_paths=[spec_path],
                tasks_path=tasks_path,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_dir=working_dir,
                sandbox_backend=sandbox_backend,
                live=live,
            )
        )
        status = payload["status"]
        recommendation = _auto_bench_recommendation(status, payload, live=live)
        result = {
            "mode": "eval",
            "status": status,
            "scorecard": payload,
            "recommendation": recommendation,
        }
    else:
        payload = asyncio.run(
            run_harness_smoke_test(
                spec_path,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_dir=working_dir,
                sandbox_backend=sandbox_backend,
                live=live,
            )
        )
        status = payload["status"]
        recommendation = _auto_bench_recommendation(status, payload, live=live)
        result = {
            "mode": "test",
            "status": status,
            "test": payload,
            "recommendation": recommendation,
        }

    if json_output:
        click.echo(json.dumps(result, indent=2))
        return
    click.echo(f"Harness auto-bench: {result['status']}")
    click.echo(f"Recommendation: {result['recommendation']['summary']}")
    for item in result["recommendation"]["next_steps"]:
        click.echo(f"  next: {item}")
def _auto_bench_recommendation(status: str, payload: dict, *, live: bool) -> dict:
    if not live:
        return {
            "summary": "Dry run completed. Re-run with --live to benchmark the model endpoint.",
            "next_steps": ["Pass --live once the local endpoint is running."],
        }
    if status == "passed":
        return {
            "summary": "Harness/model path is usable with the current settings.",
            "next_steps": [
                "Keep the current model_policy settings as a baseline.",
                "Run `superqode harness eval` with task-specific variants before widening permissions.",
            ],
        }
    digest = payload.get("failure_digest") or {}
    if payload.get("variants"):
        failed = [variant for variant in payload["variants"] if variant.get("failed")]
        digest = (
            failed[0]["tasks"][0].get("failure_digest") if failed and failed[0]["tasks"] else {}
        ) or {}
    return {
        "summary": f"Benchmark failed: {digest.get('failure_category') or 'unknown'}",
        "next_steps": digest.get("suggested_next_checks")
        or ["Run `superqode harness test --live --json` and inspect the failure digest."],
    }
def _csv_tuple(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())
@harness.command("mine-failures")
@click.option(
    "--test-result",
    "test_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness test --json` output to mine",
)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness eval --json` output to mine",
)
@click.option(
    "--harbor-run",
    "harbor_runs",
    type=click.Path(exists=True, path_type=Path),
    multiple=True,
    help="Harbor/Terminal-Bench style run JSON, JSONL, or directory to mine",
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "failures.json",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_mine_failures(test_results, eval_results, harbor_runs, output_path, json_output):
    """Mine structured failure records from harness test/eval JSON outputs."""
    from superqode.harness import (
        mine_harness_failures,
        render_failure_report,
        write_failure_report,
    )

    if not test_results and not eval_results and not harbor_runs:
        raise click.ClickException(
            "Pass at least one --test-result, --eval-result, or --harbor-run file."
        )
    try:
        report = mine_harness_failures(
            test_result_paths=test_results,
            eval_result_paths=eval_results,
            harbor_run_paths=harbor_runs,
        )
        written = write_failure_report(report, output_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {**report, "output": str(written)}
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_failure_report(report))
    click.echo(f"Wrote: {written}")
@harness.group("logbook")
def harness_logbook():
    """Manage the file-backed self-improvement logbook."""
@harness_logbook.command("update")
@click.option(
    "--from-failures",
    "failure_reports",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Failure report from `harness mine-failures`",
)
@click.option(
    "--dir",
    "logbook_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_logbook_update(failure_reports, logbook_dir, json_output):
    """Merge mined failures into the self-improvement logbook."""
    from superqode.harness import update_logbook_from_failures

    if not failure_reports:
        raise click.ClickException("Pass at least one --from-failures report.")
    try:
        payload = update_logbook_from_failures(
            failure_report_paths=failure_reports,
            logbook_dir=logbook_dir,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(
        "Logbook updated: "
        f"patterns={payload['patterns']} added={payload['added']} updated={payload['updated']}"
    )
    click.echo(f"Wrote: {payload['failure_patterns_path']}")
@harness_logbook.command("show")
@click.option(
    "--dir",
    "logbook_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_logbook_show(logbook_dir, json_output):
    """Show the self-improvement logbook."""
    from superqode.harness import read_logbook, render_logbook

    try:
        payload = read_logbook(logbook_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_logbook(payload))
@harness_logbook.command("export")
@click.option(
    "--dir",
    "logbook_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option(
    "--output",
    "output_path",
    type=click.Path(path_type=Path),
    default=None,
    help="Write markdown evidence to this file instead of stdout",
)
def harness_logbook_export(logbook_dir, output_path):
    """Export the logbook as optimizer trace-evidence markdown."""
    from superqode.harness import logbook_to_markdown, read_logbook

    try:
        markdown = logbook_to_markdown(read_logbook(logbook_dir))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if output_path:
        target = Path(output_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        click.echo(f"Wrote: {target}")
        return
    click.echo(markdown.rstrip())
@harness_logbook.command("prune")
@click.option(
    "--dir",
    "logbook_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option("--min-count", default=1, show_default=True, type=int)
@click.option("--max-patterns", default=None, type=int)
@click.option(
    "--keep-status",
    "keep_statuses",
    multiple=True,
    default=("active", "pinned"),
    show_default=True,
    help="Status to retain; repeatable",
)
@click.option("--dry-run", is_flag=True, help="Report pruning without writing")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_logbook_prune(
    logbook_dir, min_count, max_patterns, keep_statuses, dry_run, json_output
):
    """Prune stale or low-confidence self-improvement memory."""
    from superqode.harness import prune_logbook

    try:
        payload = prune_logbook(
            logbook_dir=logbook_dir,
            min_count=min_count,
            max_patterns=max_patterns,
            keep_statuses=tuple(keep_statuses),
            dry_run=dry_run,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    action = "Would prune" if dry_run else "Pruned"
    click.echo(f"{action}: {payload['pruned']} pattern(s); kept {payload['after']}.")
@harness.command("audit-candidate")
@click.option("--base", "base_spec", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--candidate",
    "candidate_spec",
    type=click.Path(exists=True, path_type=Path),
    required=True,
)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Candidate `harness eval --json` result for held-in/held-out gates",
)
@click.option("--surfaces", default=None, help="Comma-separated editable surfaces")
@click.option("--protected-surfaces", default=None, help="Comma-separated protected surfaces")
@click.option("--max-candidate-edits", default=None, type=int)
@click.option(
    "--ledger",
    "ledger_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
)
@click.option("--require-heldout", is_flag=True, help="Require a passing held-out eval gate")
@click.option(
    "--allow-protected-changes",
    is_flag=True,
    help="Do not reject solely because protected surfaces changed",
)
@click.option("--allow-ungated", is_flag=True, help="Allow apply decisions without eval gates")
@click.option("--record", is_flag=True, help="Append the audit decision to the candidate ledger")
@click.option("--notes", default="", help="Notes to store when --record is used")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_audit_candidate(
    base_spec,
    candidate_spec,
    tasks_path,
    eval_results,
    surfaces,
    protected_surfaces,
    max_candidate_edits,
    ledger_path,
    require_heldout,
    allow_protected_changes,
    allow_ungated,
    record,
    notes,
    json_output,
):
    """Audit a candidate HarnessSpec before accepting it."""
    from superqode.harness import (
        audit_harness_candidate,
        record_candidate_audit,
        render_candidate_audit,
    )

    try:
        audit = audit_harness_candidate(
            base_spec_path=base_spec,
            candidate_spec_path=candidate_spec,
            tasks_path=tasks_path,
            eval_result_paths=eval_results,
            editable_surfaces=_csv_tuple(surfaces),
            protected_surfaces=_csv_tuple(protected_surfaces),
            max_candidate_edits=max_candidate_edits,
            ledger_path=ledger_path,
            require_heldout=require_heldout,
            allow_protected_changes=allow_protected_changes,
            allow_ungated=allow_ungated,
        )
        recorded = (
            record_candidate_audit(audit, ledger_path=ledger_path, notes=notes) if record else None
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = {**audit, "recorded": recorded}
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_candidate_audit(audit))
    if recorded:
        click.echo(f"Recorded: {recorded['ledger_path']}")
@harness.group("candidates")
def harness_candidates():
    """Manage native self-improvement candidate attempts."""
@harness_candidates.command("list")
@click.option(
    "--ledger",
    "ledger_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_candidates_list(ledger_path, json_output):
    """List recorded self-improvement candidates."""
    from superqode.harness import read_candidate_ledger, render_candidate_ledger

    try:
        ledger = read_candidate_ledger(ledger_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(ledger, indent=2))
        return
    click.echo(render_candidate_ledger(ledger))
@harness_candidates.command("show")
@click.argument("candidate_id")
@click.option(
    "--ledger",
    "ledger_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_candidates_show(candidate_id, ledger_path, json_output):
    """Show one recorded self-improvement candidate."""
    from superqode.harness import read_candidate_ledger

    try:
        ledger = read_candidate_ledger(ledger_path)
        matches = [
            item
            for item in ledger.get("candidates") or []
            if item.get("candidate_id") == candidate_id or item.get("attempt_id") == candidate_id
        ]
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if not matches:
        raise click.ClickException(f"Candidate not found: {candidate_id}")
    payload = matches[-1]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Candidate: {payload.get('candidate_id') or '-'}")
    click.echo(f"Decision: {payload.get('decision') or '-'}")
    click.echo(f"Surfaces: {', '.join(payload.get('changed_surfaces') or []) or '-'}")
    for violation in payload.get("violations") or []:
        click.echo(f"- {violation.get('code')}: {violation.get('message')}")
@harness_candidates.command("export")
@click.option(
    "--ledger",
    "ledger_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
)
@click.option("--output", "output_path", type=click.Path(path_type=Path), default=None)
def harness_candidates_export(ledger_path, output_path):
    """Export candidate history as optimizer trace-evidence markdown."""
    from superqode.harness import candidate_ledger_to_markdown, read_candidate_ledger

    try:
        markdown = candidate_ledger_to_markdown(read_candidate_ledger(ledger_path))
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if output_path:
        target = Path(output_path).expanduser()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        click.echo(f"Wrote: {target}")
        return
    click.echo(markdown.rstrip())
@harness.command("improve")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--from-failures",
    "failure_reports",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Failure report from `harness mine-failures`",
)
@click.option(
    "--logbook-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path(".superqode") / "self-improve" / "logbook",
    show_default=True,
)
@click.option(
    "--candidate-ledger",
    "candidate_ledger",
    type=click.Path(path_type=Path),
    default=Path(".superqode") / "self-improve" / "candidates.jsonl",
    show_default=True,
    help="JSONL ledger for accepted and rejected harness candidates",
)
@click.option(
    "--surfaces",
    default=None,
    help="Comma-separated harness surfaces the optimizer may edit",
)
@click.option(
    "--protected-surfaces",
    default=None,
    help="Comma-separated surfaces requiring explicit human review",
)
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Self-improvement meta-harness project directory to create",
)
@click.option("--backend", default="fake", show_default=True, help="Meta-harness backend")
@click.option("--budget", default=1, show_default=True, type=int, help="Proposal budget")
@click.option("--run-name", default="superqode-improve", show_default=True)
@click.option("--metaharness-bin", default="metaharness", show_default=True)
@click.option("--export-only", is_flag=True, help="Only create the meta-harness project")
@click.option("--apply", "apply_best", is_flag=True, help="Apply the best candidate harness.yaml")
@click.option(
    "--allow-protected-changes",
    is_flag=True,
    help="Allow audited protected-surface changes during --apply",
)
@click.option(
    "--allow-ungated-apply",
    is_flag=True,
    help="Allow --apply without a passing held-out eval gate",
)
@click.option(
    "--output",
    "output_spec",
    type=click.Path(path_type=Path),
    default=None,
    help="Where --apply writes the improved spec (default: --spec path)",
)
@click.option("--force", is_flag=True, help="Overwrite project dir or output spec when needed")
@click.option("--trace-evidence", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--test-result",
    "test_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness test --json` output to include as trace evidence",
)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness eval --json` output to include as trace evidence",
)
@click.option("--objective", default=None, help="Override the meta-harness objective")
@click.option(
    "--hosted", is_flag=True, help="Pass --hosted to metaharness backends that support it"
)
@click.option("--oss", is_flag=True, help="Pass --oss to metaharness backends that support it")
@click.option("--local-provider", type=click.Choice(["ollama", "lmstudio"]), default=None)
@click.option("--model", "model_name", default=None)
@click.option("--proposal-timeout", type=float, default=None)
@click.option("--search-mode", type=click.Choice(["hill-climb", "frontier"]), default="hill-climb")
@click.option("--proposal-batch-size", default=1, show_default=True, type=int)
@click.option("--selection-policy", type=click.Choice(["single", "pareto"]), default="single")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_improve(
    spec_path,
    tasks_path,
    failure_reports,
    logbook_dir,
    candidate_ledger,
    surfaces,
    protected_surfaces,
    project_dir,
    backend,
    budget,
    run_name,
    metaharness_bin,
    export_only,
    apply_best,
    allow_protected_changes,
    allow_ungated_apply,
    output_spec,
    force,
    trace_evidence,
    test_results,
    eval_results,
    objective,
    hosted,
    oss,
    local_provider,
    model_name,
    proposal_timeout,
    search_mode,
    proposal_batch_size,
    selection_policy,
    json_output,
):
    """Improve a HarnessSpec using mined failures, logbook memory, and regression gates."""
    from superqode.harness import (
        append_self_improve_evidence,
        apply_metaharness_best_spec,
        audit_harness_candidate,
        export_metaharness_project,
        load_eval_tasks,
        load_harness_spec,
        record_candidate_audit,
        render_optimize_payload,
        run_metaharness_project,
        summarize_metaharness_run,
    )

    if hosted and oss:
        raise click.ClickException("--hosted cannot be combined with --oss")
    try:
        source_spec = load_harness_spec(spec_path)
        task_file = load_eval_tasks(tasks_path)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    editable = _csv_tuple(surfaces) or source_spec.optimization.editable_surfaces
    protected = _csv_tuple(protected_surfaces) or source_spec.optimization.protected_surfaces
    optimization_policy = {
        "enabled": source_spec.optimization.enabled,
        "require_human_apply": source_spec.optimization.require_human_apply,
        "editable_surfaces": list(editable),
        "protected_surfaces": list(protected),
        "heldout_fraction": source_spec.optimization.heldout_fraction,
        "max_candidate_edits": source_spec.optimization.max_candidate_edits,
    }
    resolved_project_dir = project_dir or (
        Path(".superqode") / "self-improve" / Path(spec_path).stem
    )
    try:
        export = export_metaharness_project(
            spec_path=spec_path,
            tasks_path=tasks_path,
            project_dir=resolved_project_dir,
            backend=backend,
            budget=budget,
            objective=objective
            or (
                "Improve this SuperQode HarnessSpec using the supplied mined "
                "failures and logbook. Keep the candidate valid and do not "
                "regress the eval task contract."
            ),
            model=model_name,
            hosted=hosted,
            oss=oss,
            local_provider=local_provider,
            proposal_timeout=proposal_timeout,
            search_mode=search_mode,
            proposal_batch_size=proposal_batch_size,
            selection_policy=selection_policy,
            trace_evidence_path=trace_evidence,
            test_result_paths=test_results,
            eval_result_paths=eval_results,
            force=force,
        )
        self_improve = append_self_improve_evidence(
            evidence_path=export.trace_evidence_path,
            failure_report_paths=failure_reports,
            logbook_dir=logbook_dir,
            candidate_ledger_path=candidate_ledger,
            editable_surfaces=editable,
            protected_surfaces=protected,
            optimization_policy=optimization_policy,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "export": export.to_dict(),
        "self_improve": self_improve,
        "optimization_policy": optimization_policy,
        "task_split_counts": task_file.get("split_counts") or {},
        "run": None,
        "summary": None,
        "candidate_audit": None,
        "candidate_record": None,
        "applied": None,
        "next_steps": [
            f"Inspect evidence: {export.trace_evidence_path}",
            f"Run regression gate: superqode harness eval --spec {spec_path} --tasks {tasks_path}",
            "Audit candidate: "
            f"superqode harness audit-candidate --base {spec_path} "
            f"--candidate <candidate.yaml> --tasks {tasks_path} --require-heldout",
            f"Inspect candidates: {metaharness_bin} inspect {Path(export.project_dir) / 'runs' / run_name}",
        ],
    }
    if int((task_file.get("split_counts") or {}).get("held-out") or 0) > 0:
        payload["next_steps"].insert(
            2,
            "Gate held-out candidate: "
            f"superqode harness eval --spec {spec_path} --variant <candidate.yaml> "
            f"--tasks {tasks_path} --split held-out",
        )
    if not export_only:
        try:
            run = run_metaharness_project(
                project_dir=export.project_dir,
                backend=backend,
                budget=budget,
                run_name=run_name,
                metaharness_bin=metaharness_bin,
                trace_evidence_path=export.trace_evidence_path,
                hosted=hosted,
                oss=oss,
                local_provider=local_provider,
                model=model_name,
                proposal_timeout=proposal_timeout,
                search_mode=search_mode,
                proposal_batch_size=proposal_batch_size,
                selection_policy=selection_policy,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        payload["run"] = run
        if not run["ok"]:
            if json_output:
                click.echo(json.dumps(payload, indent=2))
            else:
                click.echo(render_optimize_payload(payload))
                if run.get("stderr"):
                    click.echo(run["stderr"], err=True)
            raise click.exceptions.Exit(1)
        try:
            payload["summary"] = summarize_metaharness_run(run["run_dir"])
        except Exception as exc:
            raise click.ClickException(
                f"Meta-harness run completed but summary failed: {exc}"
            ) from exc
        if apply_best:
            best_spec_path = payload["summary"].get("best_spec_path")
            if not best_spec_path:
                raise click.ClickException("No best candidate harness.yaml found to audit/apply.")
            try:
                payload["candidate_audit"] = audit_harness_candidate(
                    base_spec_path=spec_path,
                    candidate_spec_path=best_spec_path,
                    tasks_path=tasks_path,
                    eval_result_paths=eval_results,
                    editable_surfaces=editable,
                    protected_surfaces=protected,
                    max_candidate_edits=source_spec.optimization.max_candidate_edits,
                    ledger_path=candidate_ledger,
                    require_heldout=bool(
                        int((task_file.get("split_counts") or {}).get("held-out") or 0)
                    ),
                    allow_protected_changes=allow_protected_changes,
                    allow_ungated=allow_ungated_apply,
                )
                payload["candidate_record"] = record_candidate_audit(
                    payload["candidate_audit"],
                    ledger_path=candidate_ledger,
                    notes=f"recorded by harness improve run {run_name}",
                )
            except Exception as exc:
                raise click.ClickException(str(exc)) from exc
            if not payload["candidate_audit"]["accepted"]:
                if json_output:
                    click.echo(json.dumps(payload, indent=2))
                    raise click.exceptions.Exit(1)
                raise click.ClickException(
                    "Best candidate failed self-improvement audit; "
                    "inspect candidate_audit or rerun with explicit overrides."
                )
            try:
                payload["applied"] = apply_metaharness_best_spec(
                    run_dir=run["run_dir"],
                    output_spec=output_spec or spec_path,
                    force=force or output_spec is None,
                )
            except Exception as exc:
                raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_optimize_payload(payload))
@harness.command("optimize")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--tasks", "tasks_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option(
    "--project-dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Meta-harness project directory to create",
)
@click.option("--backend", default="fake", show_default=True, help="Meta-harness backend")
@click.option("--budget", default=1, show_default=True, type=int, help="Proposal budget")
@click.option("--run-name", default="superqode-optimize", show_default=True)
@click.option("--metaharness-bin", default="metaharness", show_default=True)
@click.option("--export-only", is_flag=True, help="Only create the meta-harness project")
@click.option("--apply", "apply_best", is_flag=True, help="Apply the best candidate harness.yaml")
@click.option(
    "--output",
    "output_spec",
    type=click.Path(path_type=Path),
    default=None,
    help="Where --apply writes the optimized spec (default: --spec path)",
)
@click.option("--force", is_flag=True, help="Overwrite project dir or output spec when needed")
@click.option("--trace-evidence", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--test-result",
    "test_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness test --json` output to include as trace evidence",
)
@click.option(
    "--eval-result",
    "eval_results",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    multiple=True,
    help="Previous `harness eval --json` output to include as trace evidence",
)
@click.option("--objective", default=None, help="Override the meta-harness objective")
@click.option(
    "--hosted", is_flag=True, help="Pass --hosted to metaharness backends that support it"
)
@click.option("--oss", is_flag=True, help="Pass --oss to metaharness backends that support it")
@click.option("--local-provider", type=click.Choice(["ollama", "lmstudio"]), default=None)
@click.option("--model", "model_name", default=None)
@click.option("--proposal-timeout", type=float, default=None)
@click.option("--search-mode", type=click.Choice(["hill-climb", "frontier"]), default="hill-climb")
@click.option("--proposal-batch-size", default=1, show_default=True, type=int)
@click.option("--selection-policy", type=click.Choice(["single", "pareto"]), default="single")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_optimize(
    spec_path,
    tasks_path,
    project_dir,
    backend,
    budget,
    run_name,
    metaharness_bin,
    export_only,
    apply_best,
    output_spec,
    force,
    trace_evidence,
    test_results,
    eval_results,
    objective,
    hosted,
    oss,
    local_provider,
    model_name,
    proposal_timeout,
    search_mode,
    proposal_batch_size,
    selection_policy,
    json_output,
):
    """Optimize a HarnessSpec through an optional meta-harness project."""
    from superqode.harness import (
        apply_metaharness_best_spec,
        export_metaharness_project,
        render_optimize_payload,
        run_metaharness_project,
        summarize_metaharness_run,
    )

    if hosted and oss:
        raise click.ClickException("--hosted cannot be combined with --oss")
    resolved_project_dir = project_dir or (
        Path(".superqode") / "metaharness" / Path(spec_path).stem
    )
    try:
        export = export_metaharness_project(
            spec_path=spec_path,
            tasks_path=tasks_path,
            project_dir=resolved_project_dir,
            backend=backend,
            budget=budget,
            objective=objective,
            model=model_name,
            hosted=hosted,
            oss=oss,
            local_provider=local_provider,
            proposal_timeout=proposal_timeout,
            search_mode=search_mode,
            proposal_batch_size=proposal_batch_size,
            selection_policy=selection_policy,
            trace_evidence_path=trace_evidence,
            test_result_paths=test_results,
            eval_result_paths=eval_results,
            force=force,
        )
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    payload = {
        "export": export.to_dict(),
        "run": None,
        "summary": None,
        "applied": None,
        "next_steps": [
            f"Run: superqode harness optimize --spec {spec_path} --tasks {tasks_path} --backend codex",
            f"Inspect: {metaharness_bin} inspect {Path(export.project_dir) / 'runs' / run_name}",
        ],
    }
    if not export_only:
        try:
            run = run_metaharness_project(
                project_dir=export.project_dir,
                backend=backend,
                budget=budget,
                run_name=run_name,
                metaharness_bin=metaharness_bin,
                trace_evidence_path=export.trace_evidence_path,
                hosted=hosted,
                oss=oss,
                local_provider=local_provider,
                model=model_name,
                proposal_timeout=proposal_timeout,
                search_mode=search_mode,
                proposal_batch_size=proposal_batch_size,
                selection_policy=selection_policy,
            )
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        payload["run"] = run
        if not run["ok"]:
            if json_output:
                click.echo(json.dumps(payload, indent=2))
            else:
                click.echo(render_optimize_payload(payload))
                if run.get("stderr"):
                    click.echo(run["stderr"], err=True)
            raise click.exceptions.Exit(1)
        try:
            payload["summary"] = summarize_metaharness_run(run["run_dir"])
        except Exception as exc:
            raise click.ClickException(
                f"Meta-harness run completed but summary failed: {exc}"
            ) from exc
        if apply_best:
            try:
                payload["applied"] = apply_metaharness_best_spec(
                    run_dir=run["run_dir"],
                    output_spec=output_spec or spec_path,
                    force=force or output_spec is None,
                )
            except Exception as exc:
                raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_optimize_payload(payload))
@harness.command("optimize-inspect")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_optimize_inspect(run_dir, json_output):
    """Inspect a meta-harness optimization run summary."""
    from superqode.harness import render_metaharness_summary, summarize_metaharness_run

    try:
        summary = summarize_metaharness_run(run_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(summary, indent=2))
        return
    click.echo(render_metaharness_summary(summary))
@harness.command("optimize-ledger")
@click.argument("run_dir", type=click.Path(exists=True, file_okay=False, path_type=Path))
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_optimize_ledger(run_dir, json_output):
    """Show the candidate ledger from a meta-harness optimization run."""
    from superqode.harness import metaharness_candidate_ledger, render_metaharness_ledger

    try:
        rows = metaharness_candidate_ledger(run_dir)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return
    click.echo(render_metaharness_ledger(rows))
@harness.group("registry")
def harness_registry():
    """Publish, list, and install local HarnessSpec registry entries."""
@harness_registry.command("publish")
@click.argument("spec_path", type=click.Path(exists=True, path_type=Path))
@click.option("--name", default=None, help="Registry entry name")
@click.option("--registry", "registry_path", type=click.Path(path_type=Path), default=None)
@click.option("--force", is_flag=True, help="Replace an existing registry entry")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_registry_publish(spec_path, name, registry_path, force, json_output):
    """Publish a validated HarnessSpec to the local registry."""
    from superqode.harness import publish_harness_spec

    try:
        payload = publish_harness_spec(spec_path, root=registry_path, name=name, force=force)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Published {payload['name']} -> {payload['spec']}")
@harness_registry.command("list")
@click.option("--registry", "registry_path", type=click.Path(path_type=Path), default=None)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_registry_list(registry_path, json_output):
    """List local registry entries."""
    from superqode.harness import list_registry_specs

    payload = list_registry_specs(root=registry_path)
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not payload:
        click.echo("No harness registry entries found.")
        return
    for item in payload:
        click.echo(
            f"{item['name']}  {item.get('flavor', '-')}  "
            f"{item.get('runtime', '-')}  {item.get('model', '-')}"
        )
@harness_registry.command("install")
@click.argument("name")
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=Path("harness.yaml"),
    show_default=True,
)
@click.option("--registry", "registry_path", type=click.Path(path_type=Path), default=None)
@click.option("--force", is_flag=True, help="Overwrite output")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_registry_install(name, output, registry_path, force, json_output):
    """Install a local registry HarnessSpec into this project."""
    from superqode.harness import install_registry_spec

    try:
        payload = install_registry_spec(name, output, root=registry_path, force=force)
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Installed {name} -> {payload['installed_to']}")
@harness.command("run")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--prompt", "-p", required=True, help="Prompt to run")
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option("--session", "session_id", default=None, help="Reuse a harness session id")
@click.option(
    "--store",
    "store_kind",
    type=click.Choice(["memory", "file", "sqlite"]),
    default=None,
    help="Override observability.run_store",
)
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option("--stream", is_flag=True, help="Print normalized stream events")
@click.option(
    "--single-step",
    is_flag=True,
    help="Force one prompt through the harness kernel, ignoring non-single workflow topology",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_run(
    spec_path,
    prompt,
    provider,
    model_name,
    runtime_name,
    session_id,
    store_kind,
    working_dir,
    sandbox_backend,
    stream,
    single_step,
    json_output,
):
    """Run a task through a HarnessSpec."""
    import asyncio

    from superqode.harness import (
        WorkflowMode,
        create_harness_store,
        init_harness,
        load_harness_spec,
        run_workflow,
        workflow_steps_from_spec,
    )

    async def _run():
        spec = load_harness_spec(spec_path)
        store = create_harness_store(
            store_kind or spec.observability.run_store,
            (
                Path(spec.context.session_storage) / "store.sqlite3"
                if (store_kind or spec.observability.run_store) == "sqlite"
                else Path(spec.context.session_storage)
            ),
        )
        kernel = await init_harness(spec, store=store)
        run_as_workflow = (not single_step) and spec.workflow.mode != WorkflowMode.SINGLE
        if run_as_workflow and stream:
            raise click.ClickException(
                "--stream is only available for single-step harness runs; "
                "omit --stream or pass --single-step."
            )
        if run_as_workflow:
            steps = workflow_steps_from_spec(spec, prompt)
            workflow_result = await run_workflow(
                kernel,
                steps,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
                session_id=session_id,
            )
            if json_output:
                click.echo(
                    json.dumps(
                        {
                            "content": workflow_result.content,
                            "session_id": workflow_result.session_id,
                            "run_id": workflow_result.run_id,
                            "harness": spec.name,
                            "workflow": {
                                "mode": workflow_result.mode.value,
                                "result_count": len(workflow_result.results),
                                "result_run_ids": [item.run_id for item in workflow_result.results],
                                "failures": list(workflow_result.failures),
                            },
                            "results": [
                                {
                                    "content": item.content,
                                    "session_id": item.session_id,
                                    "run_id": item.run_id,
                                    "tool_calls_made": item.tool_calls_made,
                                    "iterations": item.iterations,
                                    "stopped_reason": item.response.stopped_reason,
                                }
                                for item in workflow_result.results
                            ],
                        },
                        indent=2,
                    )
                )
            else:
                click.echo(workflow_result.content)
                click.echo(
                    f"\nWorkflow run: {workflow_result.run_id} "
                    f"({workflow_result.mode.value}, {len(workflow_result.results)} result(s))"
                )
            return workflow_result
        session_obj = await kernel.session(session_id)
        if stream:
            events = []
            async for event in session_obj.stream(
                prompt,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
            ):
                item = {
                    "type": event.type,
                    "data": event.data,
                    "session_id": event.session_id,
                    "run_id": event.run_id,
                }
                events.append(item)
                if json_output:
                    click.echo(json.dumps(item))
                elif event.type == "delta":
                    click.echo(event.data.get("text", ""), nl=False)
            if json_output:
                return None
            click.echo()
            return {"events": events}
        result = await session_obj.prompt(
            prompt,
            provider=provider,
            model=model_name,
            runtime=runtime_name,
            working_directory=working_dir,
            sandbox_backend=sandbox_backend,
        )
        pending_approvals = list(session_obj.pending_approvals())
        if json_output:
            click.echo(
                json.dumps(
                    {
                        "content": result.content,
                        "session_id": result.session_id,
                        "run_id": result.run_id,
                        "tool_calls_made": result.tool_calls_made,
                        "iterations": result.iterations,
                        "harness": result.spec.name,
                        "stopped_reason": result.response.stopped_reason,
                        "pending_approvals": pending_approvals,
                    },
                    indent=2,
                )
            )
        else:
            click.echo(result.content)
            if result.response.stopped_reason == "needs_approval" and pending_approvals:
                click.echo("Approval required:")
                for entry in pending_approvals:
                    tool = entry.get("tool_name") or "<unknown>"
                    args_preview = str(entry.get("arguments", {}))
                    if len(args_preview) > 120:
                        args_preview = args_preview[:117] + "..."
                    click.echo(f"  [{entry.get('index', 0)}] {tool} {args_preview}")
                click.echo("Use the TUI to approve or reject the paused tool call.")
        return result

    try:
        asyncio.run(_run())
    except Exception as exc:
        if json_output:
            click.echo(json.dumps({"error": str(exc), "success": False}, indent=2))
        else:
            click.echo(f"Error: {exc}", err=True)
        raise click.Abort() from exc
@harness.command("events")
@click.argument("run_id")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--after", type=int, default=0, show_default=True, help="First event index")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_events(run_id, store_path, after, json_output):
    """Show normalized events for a harness run."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    try:
        events = store.get_events(run_id, after=after)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    payload = [event.to_dict() for event in events]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return

    for index, event in enumerate(events, start=after):
        preview = (
            event.data.get("text") or event.data.get("status") or event.data.get("error") or ""
        )
        preview = str(preview).replace("\n", " ")
        if len(preview) > 100:
            preview = preview[:97] + "..."
        suffix = f"  {preview}" if preview else ""
        click.echo(f"{index:04d}  {event.type}{suffix}")
@harness.command("runs")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--session", "session_id", default=None, help="Filter by session id")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_runs(store_path, session_id, json_output):
    """List persisted harness runs."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    runs = store.list_runs(session_id=session_id)
    payload = [run.to_dict() for run in runs]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not runs:
        click.echo("No harness runs found.")
        return
    for run in runs[:25]:
        workflow = " workflow" if run.metadata.get("workflow") else ""
        click.echo(
            f"{run.run_id}  {run.status:<14}  {run.harness:<22}  "
            f"{run.runtime:<14}  {run.prompt_preview}{workflow}"
        )
@harness.group("inbox")
def harness_inbox():
    """Manage durable harness session inputs."""
@harness_inbox.command("add")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--session", "session_id", required=True, help="Harness session id")
@click.option("--prompt", required=True, help="Prompt to admit")
@click.option(
    "--delivery",
    type=click.Choice(["queue", "steer", "admit-only"]),
    default="queue",
    show_default=True,
    help="How the input should be delivered by a future drain",
)
@click.option("--id", "input_id", default=None, help="Stable input id for exact retry")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_inbox_add(store_path, session_id, prompt, delivery, input_id, json_output):
    """Admit a prompt to a durable harness session inbox."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    try:
        record = store.admit_input(
            session_id=session_id,
            input_id=input_id,
            prompt=prompt,
            delivery=delivery,
        )
    except ValueError as exc:
        raise click.ClickException(str(exc)) from exc
    payload = record.to_dict()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Admitted {record.input_id} to {record.session_id} ({record.delivery})")
@harness_inbox.command("list")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--session", "session_id", default=None, help="Filter by harness session id")
@click.option(
    "--status",
    "status_filter",
    type=click.Choice(["pending", "running", "done", "failed"]),
    default=None,
    help="Filter by input status",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_inbox_list(store_path, session_id, status_filter, json_output):
    """List durable harness session inputs."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    inputs = store.list_inputs(session_id=session_id, status=status_filter)
    payload = [item.to_dict() for item in inputs]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not inputs:
        click.echo("No harness inbox inputs found.")
        return
    for item in inputs[:50]:
        preview = " ".join(item.prompt.split())
        if len(preview) > 80:
            preview = preview[:77] + "..."
        run = f" run={item.run_id}" if item.run_id else ""
        click.echo(
            f"{item.input_id}  {item.status:<8}  {item.delivery:<10}  "
            f"{item.session_id}  {preview}{run}"
        )
@harness_inbox.command("recover")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--session", "session_id", default=None, help="Filter by harness session id")
@click.option(
    "--stale-after",
    "stale_after_seconds",
    default=300,
    show_default=True,
    type=int,
    help="Recover running inputs older than this many seconds",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_inbox_recover(store_path, session_id, stale_after_seconds, json_output):
    """Recover stale running inbox inputs back to pending."""
    from superqode.harness import FileHarnessStore

    store = FileHarnessStore(store_path)
    recovered = store.recover_stale_inputs(
        session_id=session_id,
        stale_after_seconds=stale_after_seconds,
    )
    payload = [item.to_dict() for item in recovered]
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not recovered:
        click.echo("No stale running harness inbox inputs found.")
        return
    for item in recovered:
        click.echo(f"recovered {item.input_id} for {item.session_id}")
async def _execute_claimed_harness_input(
    *,
    item,
    spec,
    kernel,
    store,
    owner,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    session_id,
    lease_seconds,
):
    import asyncio
    import contextlib

    from superqode.harness import WorkflowMode, run_workflow, workflow_steps_from_spec

    async def _heartbeat(stop_event):
        interval = max(1.0, lease_seconds / 2)
        while not stop_event.is_set():
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval)
            except TimeoutError:
                with contextlib.suppress(Exception):
                    store.renew_input_lease(
                        item.input_id,
                        owner_id=owner,
                        lease_seconds=lease_seconds,
                    )

    stop = asyncio.Event()
    heartbeat = asyncio.create_task(_heartbeat(stop))
    try:
        try:
            if spec.workflow.mode != WorkflowMode.SINGLE:
                workflow_result = await run_workflow(
                    kernel,
                    workflow_steps_from_spec(spec, item.prompt),
                    provider=provider,
                    model=model_name,
                    runtime=runtime_name,
                    working_directory=working_dir,
                    sandbox_backend=sandbox_backend,
                    session_id=session_id,
                )
                store.mark_input_done(
                    item.input_id,
                    run_id=workflow_result.run_id,
                    owner_id=owner,
                )
                return {
                    "input_id": item.input_id,
                    "status": "done",
                    "run_id": workflow_result.run_id,
                    "owner_id": owner,
                    "content": workflow_result.content,
                }
            session_obj = await kernel.session(session_id)
            result = await session_obj.prompt(
                item.prompt,
                provider=provider,
                model=model_name,
                runtime=runtime_name,
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
                metadata={"admitted_input_id": item.input_id},
            )
            store.mark_input_done(item.input_id, run_id=result.run_id, owner_id=owner)
            return {
                "input_id": item.input_id,
                "status": "done",
                "run_id": result.run_id,
                "owner_id": owner,
                "content": result.content,
            }
        except Exception as exc:  # noqa: BLE001
            store.mark_input_failed(item.input_id, error=str(exc), owner_id=owner)
            return {
                "input_id": item.input_id,
                "status": "failed",
                "owner_id": owner,
                "error": str(exc),
            }
    finally:
        stop.set()
        with contextlib.suppress(Exception):
            await heartbeat
@harness.command("drain")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--session", "session_id", required=True, help="Harness session id to drain")
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--limit", default=1, show_default=True, type=int, help="Maximum inputs to drain")
@click.option("--owner-id", default=None, help="Drain worker owner id")
@click.option(
    "--lease-seconds", default=300, show_default=True, type=int, help="Claim lease duration"
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_drain(
    spec_path,
    session_id,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    store_path,
    limit,
    owner_id,
    lease_seconds,
    json_output,
):
    """Execute pending durable inputs for one harness session."""
    import asyncio

    from superqode.harness import (
        FileHarnessStore,
        init_harness,
        load_harness_spec,
    )

    async def _drain():
        spec = load_harness_spec(spec_path)
        store = FileHarnessStore(store_path)
        kernel = await init_harness(spec, store=store)
        owner = owner_id or f"drain-{os.getpid()}-{int(time.time() * 1000)}"
        drained = []
        for _ in range(max(0, limit)):
            item = store.claim_next_input(
                session_id=session_id,
                owner_id=owner,
                lease_seconds=lease_seconds,
            )
            if item is None:
                break
            drained.append(
                await _execute_claimed_harness_input(
                    item=item,
                    spec=spec,
                    kernel=kernel,
                    store=store,
                    owner=owner,
                    provider=provider,
                    model_name=model_name,
                    runtime_name=runtime_name,
                    working_dir=working_dir,
                    sandbox_backend=sandbox_backend,
                    session_id=session_id,
                    lease_seconds=lease_seconds,
                )
            )
        return drained

    payload = asyncio.run(_drain())
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if not payload:
        click.echo("No pending harness inbox inputs to drain.")
        return
    for item in payload:
        if item["status"] == "done":
            click.echo(f"drained {item['input_id']} -> {item['run_id']}")
        else:
            click.echo(f"failed {item['input_id']}: {item['error']}")
@harness.command("worker")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), required=True)
@click.option("--session", "session_id", required=True, help="Harness session id to drain")
@click.option("--provider", envvar="SUPERQODE_PROVIDER", default="openai", show_default=True)
@click.option(
    "--model", "model_name", envvar="SUPERQODE_MODEL", default="gpt-4o-mini", show_default=True
)
@click.option("--runtime", "runtime_name", default=None, help="Override runtime or backend")
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--owner-id", default=None, help="Worker owner id")
@click.option(
    "--lease-seconds", default=300, show_default=True, type=int, help="Claim lease duration"
)
@click.option(
    "--concurrency", default=1, show_default=True, type=int, help="Concurrent worker loops"
)
@click.option("--poll-seconds", default=2.0, show_default=True, type=float, help="Idle poll delay")
@click.option("--max-runs", default=None, type=int, help="Stop after this many claimed inputs")
@click.option("--once", is_flag=True, help="Exit when no pending input is available")
@click.option("--recover-stale/--no-recover-stale", default=True, show_default=True)
@click.option(
    "--stale-after",
    "stale_after_seconds",
    default=300,
    show_default=True,
    type=int,
    help="Recover running inputs older than this many seconds on startup",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON when the worker exits")
def harness_worker(
    spec_path,
    session_id,
    provider,
    model_name,
    runtime_name,
    working_dir,
    sandbox_backend,
    store_path,
    owner_id,
    lease_seconds,
    concurrency,
    poll_seconds,
    max_runs,
    once,
    recover_stale,
    stale_after_seconds,
    json_output,
):
    """Run a durable harness inbox worker."""
    import asyncio

    from superqode.harness import FileHarnessStore, init_harness, load_harness_spec

    async def _worker():
        spec = load_harness_spec(spec_path)
        store = FileHarnessStore(store_path)
        recovered = (
            store.recover_stale_inputs(
                session_id=session_id,
                stale_after_seconds=stale_after_seconds,
            )
            if recover_stale
            else []
        )
        kernel = await init_harness(spec, store=store)
        owner = owner_id or f"worker-{os.getpid()}-{int(time.time() * 1000)}"
        processed = []
        claim_lock = asyncio.Lock()
        processed_lock = asyncio.Lock()
        claimed_count = 0

        async def _claim_one():
            nonlocal claimed_count
            async with claim_lock:
                if max_runs is not None and claimed_count >= max(0, max_runs):
                    return None, True
                item = store.claim_next_input(
                    session_id=session_id,
                    owner_id=owner,
                    lease_seconds=lease_seconds,
                )
                if item is None:
                    return None, once
                claimed_count += 1
                return item, False

        async def _loop(worker_index):
            while True:
                item, should_stop = await _claim_one()
                if item is None:
                    if should_stop:
                        return
                    await asyncio.sleep(max(0.0, poll_seconds))
                    continue
                result = await _execute_claimed_harness_input(
                    item=item,
                    spec=spec,
                    kernel=kernel,
                    store=store,
                    owner=owner,
                    provider=provider,
                    model_name=model_name,
                    runtime_name=runtime_name,
                    working_dir=working_dir,
                    sandbox_backend=sandbox_backend,
                    session_id=session_id,
                    lease_seconds=lease_seconds,
                )
                result["worker_index"] = worker_index
                async with processed_lock:
                    processed.append(result)

        await asyncio.gather(*(_loop(index) for index in range(max(1, concurrency))))
        return {
            "owner_id": owner,
            "session_id": session_id,
            "recovered": [item.to_dict() for item in recovered],
            "processed": processed,
        }

    payload = asyncio.run(_worker())
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    if payload["recovered"]:
        click.echo(f"Recovered {len(payload['recovered'])} stale inbox input(s).")
    if not payload["processed"]:
        click.echo("No harness inbox inputs processed.")
        return
    for item in payload["processed"]:
        if item["status"] == "done":
            click.echo(f"worker drained {item['input_id']} -> {item['run_id']}")
        else:
            click.echo(f"worker failed {item['input_id']}: {item['error']}")
@harness.command("evidence")
@click.argument("run_id")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_evidence(run_id, store_path, json_output):
    """Show a readable evidence report for a harness run."""
    from superqode.harness import (
        FileHarnessStore,
        build_harness_evidence,
        render_harness_evidence,
    )

    store = FileHarnessStore(store_path)
    try:
        evidence = build_harness_evidence(store, run_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(evidence, indent=2))
        return
    click.echo(render_harness_evidence(evidence))
@harness.group("observability")
def harness_observability():
    """Inspect and export harness observability artifacts."""
@harness_observability.command("status")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_observability_status(spec_path, json_output):
    """Show local and optional external observability sink status."""
    from superqode.harness import (
        load_harness_spec,
        observability_status,
        render_observability_status,
    )

    spec = load_harness_spec(spec_path) if spec_path else None
    rows = observability_status(spec)
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return
    click.echo(render_observability_status(rows))
@harness_observability.command("export")
@click.argument("run_id")
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(path_type=Path),
    default=None,
    help="Output directory for JSON/JSONL observability artifacts",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_observability_export(run_id, spec_path, store_path, output_dir, json_output):
    """Export a harness run tree to local JSONL and optional configured sinks."""
    from superqode.harness import (
        FileHarnessStore,
        export_harness_observability,
        load_harness_spec,
        render_observability_export,
    )

    store = FileHarnessStore(store_path)
    spec = load_harness_spec(spec_path) if spec_path else None
    try:
        payload = export_harness_observability(
            store,
            run_id,
            output_dir=output_dir,
            spec=spec,
        )
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(render_observability_export(payload))
@harness.command("replay")
@click.argument("run_id")
@click.option(
    "--execute", is_flag=True, help="Re-run the prompt instead of only showing the replay plan"
)
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--prompt", default=None, help="Exact prompt to replay when the run did not store one"
)
@click.option("--provider", default=None, help="Provider override for --execute")
@click.option("--model", "model_name", default=None, help="Model override for --execute")
@click.option("--runtime", "runtime_name", default=None, help="Runtime override for --execute")
@click.option("--sandbox", "sandbox_backend", default="local", show_default=True)
@click.option(
    "--working-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=Path("."),
    show_default=False,
)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_replay(
    run_id,
    execute,
    spec_path,
    prompt,
    provider,
    model_name,
    runtime_name,
    sandbox_backend,
    working_dir,
    store_path,
    json_output,
):
    """Show a replay plan for a persisted harness run."""
    import asyncio

    from superqode.harness import (
        FileHarnessStore,
        build_harness_replay_plan,
        create_harness_store,
        init_harness,
        load_harness_spec,
        render_harness_replay_plan,
    )

    store = FileHarnessStore(store_path)
    try:
        plan = build_harness_replay_plan(store, run_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if execute:
        if spec_path is None:
            raise click.ClickException("--execute requires --spec <harness.yaml>")
        exact_prompt = prompt or plan.get("prompt") or ""
        if not exact_prompt:
            raise click.ClickException(
                "No full prompt is stored for this run. Pass --prompt or use context.prompt_persistence: full."
            )

        async def _execute():
            spec = load_harness_spec(spec_path)
            replay_store = create_harness_store(
                spec.observability.run_store,
                (
                    Path(spec.context.session_storage) / "store.sqlite3"
                    if spec.observability.run_store == "sqlite"
                    else Path(spec.context.session_storage)
                ),
            )
            kernel = await init_harness(spec, store=replay_store)
            session_obj = await kernel.session()
            run = plan["run"]
            result = await session_obj.prompt(
                exact_prompt,
                provider=provider or run["provider"],
                model=model_name or run["model"],
                runtime=runtime_name or run["runtime"],
                working_directory=working_dir,
                sandbox_backend=sandbox_backend,
                metadata={"replay_of": run_id},
            )
            payload = {
                "replay_of": run_id,
                "run_id": result.run_id,
                "session_id": result.session_id,
                "content": result.content,
                "stopped_reason": result.response.stopped_reason,
                "tool_calls_made": result.tool_calls_made,
                "iterations": result.iterations,
            }
            if json_output:
                click.echo(json.dumps(payload, indent=2))
            else:
                click.echo(result.content)
                click.echo(f"Replayed {run_id} -> {result.run_id}")

        asyncio.run(_execute())
        return
    if json_output:
        click.echo(json.dumps(plan, indent=2))
        return
    click.echo(render_harness_replay_plan(plan))
@harness.command("fork")
@click.argument("run_id")
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--after", type=int, default=None, help="Copy events through this event index")
@click.option("--session", "session_id", default=None, help="Session id for the forked run")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_fork(run_id, store_path, after, session_id, json_output):
    """Fork a persisted harness run by copying its event prefix."""
    from superqode.harness import FileHarnessStore, fork_harness_run

    store = FileHarnessStore(store_path)
    try:
        fork = fork_harness_run(store, run_id, after=after, session_id=session_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc
    if json_output:
        click.echo(json.dumps(fork, indent=2))
        return
    click.echo(f"Forked {run_id} -> {fork['run_id']}")
    click.echo(f"Events copied: {fork['events']}")
    click.echo(f"Next: superqode harness events {fork['run_id']}")
@harness.command("graph")
@click.argument("run_id", required=False)
@click.option("--spec", "spec_path", type=click.Path(exists=True, path_type=Path), default=None)
@click.option(
    "--store",
    "store_path",
    type=click.Path(path_type=Path),
    default=Path(".superqode/sessions"),
    show_default=True,
    help="Harness store directory",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_graph(run_id, spec_path, store_path, json_output):
    """Show a planned HarnessSpec graph or persisted event graph for a run."""
    from superqode.harness import (
        FileHarnessStore,
        load_harness_spec,
        plan_harness_graph,
        render_harness_graph,
    )

    if spec_path is not None:
        graph = plan_harness_graph(load_harness_spec(spec_path))
        if json_output:
            click.echo(json.dumps(graph.to_dict(), indent=2))
            return
        click.echo("Planned graph:")
        click.echo(render_harness_graph(graph))
        return

    if not run_id:
        raise click.ClickException("Pass a run_id or --spec <harness.yaml>.")

    store = FileHarnessStore(store_path)
    try:
        graph = store.get_event_graph(run_id)
    except KeyError as exc:
        raise click.ClickException(str(exc)) from exc

    if json_output:
        click.echo(json.dumps(graph.to_dict(), indent=2))
        return

    click.echo(f"Run: {graph.run_id}")
    click.echo(render_harness_graph(graph))
def _harness_mcp_config_path(spec) -> Path | None:
    runtime_config = spec.runtime.config
    pydanticai_config = runtime_config.get("pydanticai", {})
    if isinstance(pydanticai_config, dict):
        configured = pydanticai_config.get("mcp_config_path") or pydanticai_config.get("mcp_config")
        if configured:
            return Path(configured)
    configured = runtime_config.get("mcp_config_path") or runtime_config.get("mcp_config")
    return Path(configured) if configured else None
def _harness_model_registry_check(spec) -> dict:
    provider = str(spec.model_policy.config.get("provider") or "").strip().lower()
    models = [item for item in (spec.model_policy.primary, *spec.model_policy.fallbacks) if item]
    if not models:
        return {
            "status": "ok",
            "message": "No model policy models are configured.",
            "provider": provider,
            "models": [],
            "unknown_models": [],
        }

    from superqode.providers.registry import PROVIDERS

    normalized = [_normalize_harness_model_id(model) for model in models]
    if not provider and ":" in str(models[0]):
        provider = str(models[0]).split(":", 1)[0].lower()
    if provider == "local":
        unknown = [
            model
            for model, normalized_model in zip(models, normalized)
            if not (
                normalized_model.endswith("-local")
                or normalized_model == "local-model"
                or "/" in normalized_model
            )
        ]
        status = "warning" if unknown else "ok"
        return {
            "status": status,
            "message": (
                "Local model aliases look usable."
                if not unknown
                else "Some local model aliases are not recognized by SuperQode's static hints."
            ),
            "provider": provider,
            "models": models,
            "unknown_models": unknown,
        }
    provider_def = PROVIDERS.get(provider)
    if provider_def is None:
        return {
            "status": "warning",
            "message": (
                "Model availability was not checked because no known provider is configured."
            ),
            "provider": provider,
            "models": models,
            "unknown_models": [],
        }
    known = {
        _normalize_harness_model_id(model)
        for model in (*provider_def.example_models, *provider_def.free_models)
    }
    unknown = [
        model
        for model, normalized_model in zip(models, normalized)
        if normalized_model not in known
    ]
    return {
        "status": "warning" if unknown else "ok",
        "message": (
            f"Model policy models are listed for provider '{provider}'."
            if not unknown
            else f"Some model policy models are not listed for provider '{provider}'."
        ),
        "provider": provider,
        "models": models,
        "unknown_models": unknown,
    }
def _normalize_harness_model_id(model: str) -> str:
    from superqode.providers.model_specs import split_provider_model_ref

    value = str(model).strip()
    if ":" in value and "/" not in value.split(":", 1)[0]:
        value = value.split(":", 1)[1]
    parsed = split_provider_model_ref(value)
    if parsed.provider in {"openai", "anthropic", "google", "gemini", "ollama", "huggingface"}:
        return parsed.model
    return value
def _diff_dicts(left: object, right: object, path: str = "") -> list[dict]:
    if isinstance(left, dict) and isinstance(right, dict):
        changes: list[dict] = []
        for key in sorted(set(left) | set(right)):
            child_path = f"{path}.{key}" if path else str(key)
            if key not in left:
                changes.append({"path": child_path, "left": None, "right": right[key]})
            elif key not in right:
                changes.append({"path": child_path, "left": left[key], "right": None})
            else:
                changes.extend(_diff_dicts(left[key], right[key], child_path))
        return changes
    if isinstance(left, list) and isinstance(right, list):
        if left == right:
            return []
        if all(isinstance(item, dict) and "id" in item for item in left + right):
            left_by_id = {item["id"]: item for item in left}
            right_by_id = {item["id"]: item for item in right}
            return _diff_dicts(left_by_id, right_by_id, path)
        return [{"path": path, "left": left, "right": right}]
    if left != right:
        return [{"path": path, "left": left, "right": right}]
    return []
def _permission_config_to_dict(config) -> dict:
    return {
        "default": config.default.value,
        "groups": {group.value: permission.value for group, permission in config.groups.items()},
        "tools": {tool: permission.value for tool, permission in config.tools.items()},
        "allow_patterns": list(config.allow_patterns),
        "deny_patterns": list(config.deny_patterns),
    }
