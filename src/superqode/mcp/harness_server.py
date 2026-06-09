"""
Expose SuperQode harnesses over MCP.

Complements the existing A2A (`a2a/server.py`) and ACP (`acp/server`) servers:
any MCP client — Claude Desktop, another agent, an IDE — can now discover and
run a HarnessSpec workflow as an MCP tool. This makes a SuperQode harness a
first-class, callable building block in the wider MCP ecosystem.

Tools exposed:
- ``list_harnesses``     — registered HarnessSpec files.
- ``describe_harness``   — a spec's workflow mode + agents.
- ``run_harness``        — run a harness workflow against a task, return result.

Run it::

    superqode mcp                 # stdio (for Claude Desktop etc.)
    superqode mcp --http --port 8765   # streamable HTTP

Provider/model resolution order: explicit tool args → ``SUPERQODE_MCP_PROVIDER``
/ ``SUPERQODE_MCP_MODEL`` env → the spec's ``model_policy.primary``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Dict, Optional

# Conventional places a project keeps its harness specs.
DEFAULT_HARNESS_DIRS = (".superqode/harness", ".superqode/harnesses", "harness", "harnesses")


def discover_harness_specs(directory: Optional[str] = None) -> Dict[str, Path]:
    """Map harness name → spec path. A single dir overrides the default search."""
    if directory:
        search = [Path(directory).expanduser()]
    else:
        search = [Path.cwd() / d for d in DEFAULT_HARNESS_DIRS]
    specs: Dict[str, Path] = {}
    for d in search:
        if not d.is_dir():
            continue
        for path in sorted([*d.glob("*.yaml"), *d.glob("*.yml")]):
            specs.setdefault(path.stem, path)
    return specs


def _resolve_spec_path(harness: str, directory: Optional[str]) -> Optional[Path]:
    specs = discover_harness_specs(directory)
    if harness in specs:
        return specs[harness]
    candidate = Path(harness).expanduser()
    if candidate.is_file():
        return candidate
    return None


def build_steps_from_spec(spec, prompt: str):
    """Build runnable workflow steps from a HarnessSpec + a task prompt.

    Mirrors the TUI's ``_workflow_steps_from_spec`` so MCP runs behave identically.
    """
    from superqode.harness import WorkflowMode, WorkflowStep, apply_workflow_preset

    spec = apply_workflow_preset(spec)
    mode = spec.workflow.mode
    prompt = prompt.strip()
    agents = list(getattr(spec, "agents", ()) or ())

    def agent_step(agent):
        parts = []
        if getattr(agent, "role", ""):
            parts.append(f"Role: {agent.role}")
        if getattr(agent, "system_prompt", ""):
            parts.append(f"Instructions:\n{agent.system_prompt}")
        parts.append(f"Task:\n{prompt}")
        return WorkflowStep(
            "\n\n".join(parts), id=agent.id, metadata={"role": getattr(agent, "role", "")}
        )

    if agents:
        steps = [agent_step(agent) for agent in agents]
        if mode == WorkflowMode.ROUTER and not (
            steps and str(steps[0].id or "").lower() == "router"
        ):
            steps.insert(
                0,
                WorkflowStep(
                    f"Route this request to the best harness agent.\n\nTask:\n{prompt}",
                    id="router",
                ),
            )
        if mode == WorkflowMode.EVALUATOR_OPTIMIZER:
            defaults = [
                WorkflowStep(f"Create a candidate solution.\n\nTask:\n{prompt}", id="candidate"),
                WorkflowStep(
                    "Evaluate the candidate for correctness and completeness.", id="evaluator"
                ),
                WorkflowStep("Improve the candidate using the evaluator feedback.", id="optimizer"),
            ]
            steps = (steps + defaults[len(steps) :])[:3]
        return steps

    if mode == WorkflowMode.EVALUATOR_OPTIMIZER:
        return [
            WorkflowStep(f"Create a candidate solution.\n\nTask:\n{prompt}", id="candidate"),
            WorkflowStep(
                "Evaluate the candidate for correctness and completeness.", id="evaluator"
            ),
            WorkflowStep("Improve the candidate using the evaluator feedback.", id="optimizer"),
        ]
    if mode == WorkflowMode.ROUTER:
        return [
            WorkflowStep(
                f"Route this request to the best execution path.\n\nTask:\n{prompt}", id="router"
            ),
            WorkflowStep(prompt, id="default"),
        ]
    return [WorkflowStep(prompt, id="step-1")]


def _resolve_provider_model(spec, provider: str, model: str) -> tuple[str, str]:
    provider = provider or os.environ.get("SUPERQODE_MCP_PROVIDER", "").strip()
    model = model or os.environ.get("SUPERQODE_MCP_MODEL", "").strip()
    primary = getattr(getattr(spec, "model_policy", None), "primary", None)
    if (not provider or not model) and primary:
        primary_text = str(primary)
        if "/" in primary_text:
            inferred_provider, inferred_model = primary_text.split("/", 1)
            provider = provider or inferred_provider
            model = model or inferred_model
        else:
            model = model or primary_text
    return provider, model


async def run_harness_workflow(
    spec_path: Path, task: str, provider: str = "", model: str = ""
) -> str:
    """Load a spec, run its workflow against ``task``, and return the final content."""
    from superqode.harness import (
        FileHarnessStore,
        init_harness,
        load_harness_spec,
        run_workflow,
    )

    spec = load_harness_spec(spec_path)
    provider, model = _resolve_provider_model(spec, provider, model)
    if not provider or not model:
        return (
            "Error: no provider/model resolved. Set `model_policy.primary` in the "
            "spec, or pass provider/model, or set SUPERQODE_MCP_PROVIDER / "
            "SUPERQODE_MCP_MODEL."
        )

    steps = build_steps_from_spec(spec, task)
    kernel = await init_harness(spec, store=FileHarnessStore(Path(spec.context.session_storage)))
    result = await run_workflow(
        kernel,
        steps,
        provider=provider,
        model=model,
        working_directory=Path.cwd(),
        runtime=spec.runtime.backend,
        sandbox_backend=spec.execution_policy.sandbox,
    )
    return result.content or "(workflow produced no content)"


def build_harness_mcp_server(harness_dir: Optional[str] = None):
    """Construct a FastMCP server exposing the harness tools."""
    from mcp.server.fastmcp import FastMCP

    server = FastMCP("superqode-harness")

    @server.tool()
    def list_harnesses() -> str:
        """List the HarnessSpec workflows available to run."""
        specs = discover_harness_specs(harness_dir)
        if not specs:
            return (
                "No harness specs found. Add .yaml/.yml HarnessSpec files under "
                f"one of: {', '.join(DEFAULT_HARNESS_DIRS)} (or pass --dir)."
            )
        return "\n".join(f"- {name}  ({path})" for name, path in specs.items())

    @server.tool()
    def describe_harness(harness: str) -> str:
        """Show a harness's workflow mode and agents. `harness` is a name or path."""
        from superqode.harness import apply_workflow_preset, load_harness_spec

        path = _resolve_spec_path(harness, harness_dir)
        if path is None:
            return f"Unknown harness: {harness!r}. Use list_harnesses to see options."
        try:
            spec = apply_workflow_preset(load_harness_spec(path))
        except Exception as exc:
            return f"Failed to load {path}: {exc}"
        lines = [
            f"Harness: {harness}",
            f"Path: {path}",
            f"Workflow mode: {spec.workflow.mode.value}",
            f"Runtime: {spec.runtime.backend}",
        ]
        primary = getattr(getattr(spec, "model_policy", None), "primary", None)
        if primary:
            lines.append(f"Default model: {primary}")
        agents = list(getattr(spec, "agents", ()) or ())
        if agents:
            lines.append(f"Agents ({len(agents)}):")
            lines.extend(f"  - {a.id}: {getattr(a, 'role', '') or '(no role)'}" for a in agents)
        return "\n".join(lines)

    @server.tool()
    async def run_harness(harness: str, task: str, provider: str = "", model: str = "") -> str:
        """Run a harness workflow against `task`. `harness` is a name or spec path."""
        path = _resolve_spec_path(harness, harness_dir)
        if path is None:
            return f"Unknown harness: {harness!r}. Use list_harnesses to see options."
        try:
            return await run_harness_workflow(path, task, provider, model)
        except Exception as exc:
            return f"Harness run failed: {exc}"

    return server


def run_server(
    transport: str = "stdio",
    host: str = "127.0.0.1",
    port: int = 8765,
    harness_dir: Optional[str] = None,
) -> None:
    server = build_harness_mcp_server(harness_dir)
    if transport == "http":
        server.settings.host = host
        server.settings.port = port
        server.run(transport="streamable-http")
    else:
        server.run(transport="stdio")


def main(argv=None) -> None:
    import argparse

    parser = argparse.ArgumentParser(
        prog="superqode-mcp", description="Expose SuperQode harnesses over MCP."
    )
    parser.add_argument("--http", action="store_true", help="Serve over streamable HTTP")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--dir", default=None, help="Directory of harness specs")
    args = parser.parse_args(argv)
    run_server("http" if args.http else "stdio", args.host, args.port, args.dir)


if __name__ == "__main__":
    main()
