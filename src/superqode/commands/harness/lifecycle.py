"""Harness discovery, authoring, validation, and diagnostics."""

import json
from pathlib import Path

import click

from ._group import HARNESS_TEMPLATE_CHOICES, WORKFLOW_PRESET_CHOICES, harness
from ._helpers import _diff_dicts, _permission_config_to_dict


@harness.command("list")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
@click.option(
    "--recommended",
    is_flag=True,
    help="Show the curated picker view instead of the complete compatibility catalog",
)
def harness_list(json_output, recommended):
    """List built-in, file, registry, and installed Python harnesses."""
    from superqode.harness import (
        discover_harness_adapters,
        list_harnesses,
        recommended_harnesses,
    )

    entries = recommended_harnesses(Path.cwd()) if recommended else list_harnesses(Path.cwd())
    rows = [{**entry.to_dict(), "kind": "spec"} for entry in entries]
    known = {str(row["id"]) for row in rows}
    for entry in discover_harness_adapters(include_builtins=False):
        if entry.id in known:
            continue
        rows.append(
            {
                **entry.to_dict(),
                "display_name": entry.name,
                "runtime": "protocol",
                "default": False,
                "tools": [],
                "tool_count": 0,
                "digest": "",
                "path": None,
                "kind": "python",
                "continuity": (
                    "exact-resume"
                    if entry.descriptor and entry.descriptor.capabilities.resume
                    else "fresh-session"
                ),
            }
        )
    if json_output:
        click.echo(json.dumps(rows, indent=2))
        return
    click.echo(
        f"{'ID':<20} {'TYPE':<8} {'RUNTIME':<12} {'STATUS':<14} {'CONTINUITY':<16} {'TOOLS':>5}"
    )
    for row in rows:
        status = "available" if row["available"] else str(row["issue"] or "unavailable")
        click.echo(
            f"{str(row['id']):<20} "
            f"{str(row['kind']):<8} "
            f"{str(row['runtime']):<12} "
            f"{status:<14} "
            f"{str(row['continuity']):<16} "
            f"{int(row['tool_count']):>5}"
        )


@harness.command("current")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_current(json_output):
    """Show the effective harness for the current project."""
    import os

    from superqode.harness import resolve_harness

    reference = ""
    try:
        from superqode.config.loader import load_config

        reference = str(load_config().superqode.harness or "")
    except Exception:
        reference = ""
    if not reference:
        reference = os.getenv("SUPERQODE_HARNESS", "").strip()
    reference = reference or "core"
    try:
        entry = resolve_harness(reference, root=Path.cwd())
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc
    payload = entry.to_dict()
    if json_output:
        click.echo(json.dumps(payload, indent=2))
        return
    click.echo(f"Harness: {entry.id}")
    click.echo(f"Runtime: {entry.runtime}")
    click.echo(f"Source: {entry.source}")
    click.echo(f"Switch continuity: {entry.continuity}")


@harness.command("show")
@click.argument("reference")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def harness_show(reference, json_output):
    """Show one selectable harness by name or spec path."""
    from superqode.harness import (
        harness_spec_to_dict,
        load_harness_adapter,
        resolve_harness,
    )

    try:
        entry = resolve_harness(reference, root=Path.cwd())
    except Exception:
        try:
            adapter = load_harness_adapter(reference)
        except Exception as exc:
            raise click.ClickException(str(exc)) from exc
        payload = {
            **adapter.descriptor.to_dict(),
            "source": "python-package",
            "kind": "python",
        }
        if json_output:
            click.echo(json.dumps(payload, indent=2))
            return
        click.echo(f"Harness: {adapter.descriptor.id}")
        click.echo(f"Description: {adapter.descriptor.description}")
        click.echo("Source: Python package")
        enabled = [
            name
            for name, supported in adapter.descriptor.capabilities.to_dict().items()
            if supported
        ]
        click.echo(f"Capabilities: {', '.join(enabled) or 'none'}")
        return
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
        get_harness_template,
        get_workflow_preset,
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
