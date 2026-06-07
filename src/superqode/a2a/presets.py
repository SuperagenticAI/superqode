"""
A2A Workflow Presets - Pre-built multi-agent workflows.

These presets provide ready-to-use orchestration patterns for common scenarios.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .workflows import A2AWorkflowEngine, WorkflowStep, WorkflowResult, WorkflowPattern


@dataclass
class WorkflowPreset:
    """A pre-configured workflow preset."""

    name: str
    description: str
    agents: List[Dict[str, str]]  # [{"url": "...", "prompt": "..."}]
    pattern: str  # "sequential", "parallel", "fan_out_fan_in"


# Pre-defined presets
QUALITY_PRESETS = {
    "full_quality": WorkflowPreset(
        name="Full Quality",
        description="Run complete quality checks: unit, integration, security, lint",
        agents=[
            {"url": "", "prompt": "Run unit tests and report results", "name": "unit_tests"},
            {
                "url": "",
                "prompt": "Run integration tests and report results",
                "name": "integration_tests",
            },
            {
                "url": "",
                "prompt": "Run security analysis and find vulnerabilities",
                "name": "security_scan",
            },
            {"url": "", "prompt": "Run linting and code quality checks", "name": "lint_check"},
        ],
        pattern="parallel",
    ),
    "pre_commit": WorkflowPreset(
        name="Pre-commit",
        description="Quick checks before commit: lint, format, unit tests",
        agents=[
            {"url": "", "prompt": "Check code formatting", "name": "format_check"},
            {"url": "", "prompt": "Run linter", "name": "lint"},
            {"url": "", "prompt": "Run quick unit tests", "name": "quick_tests"},
        ],
        pattern="parallel",
    ),
    "ci_pipeline": WorkflowPreset(
        name="CI Pipeline",
        description="Full CI pipeline: build, test, security, deploy check",
        agents=[
            {"url": "", "prompt": "Build the project", "name": "build"},
            {"url": "", "prompt": "Run all tests", "name": "test"},
            {"url": "", "prompt": "Run security scan", "name": "security"},
            {"url": "", "prompt": "Check dependencies for vulnerabilities", "name": "deps_check"},
        ],
        pattern="sequential",
    ),
    "review_cycle": WorkflowPreset(
        name="Code Review",
        description="Automated code review: lint, security, style, best practices",
        agents=[
            {"url": "", "prompt": "Review code style and formatting", "name": "style_review"},
            {"url": "", "prompt": "Review code for security issues", "name": "security_review"},
            {"url": "", "prompt": "Review code for best practices", "name": "quality_review"},
            {"url": "", "prompt": "Check for code smells", "name": "smell_check"},
        ],
        pattern="parallel",
    ),
}


DEVOPS_PRESETS = {
    "deploy": WorkflowPreset(
        name="Deploy",
        description="Deploy application: build, test, push, deploy",
        agents=[
            {"url": "", "prompt": "Build container image", "name": "build_image"},
            {"url": "", "prompt": "Run smoke tests", "name": "smoke_tests"},
            {"url": "", "prompt": "Push to registry", "name": "push_image"},
            {"url": "", "prompt": "Deploy to environment", "name": "deploy"},
        ],
        pattern="sequential",
    ),
    "infra_check": WorkflowPreset(
        name="Infrastructure Check",
        description="Check infrastructure: security, compliance, cost",
        agents=[
            {"url": "", "prompt": "Check cloud security", "name": "sec_check"},
            {"url": "", "prompt": "Check compliance", "name": "compliance_check"},
            {"url": "", "prompt": "Check cost optimization", "name": "cost_check"},
        ],
        pattern="parallel",
    ),
}


class A2APresets:
    """Manage and run workflow presets.

    Usage:
        presets = A2APresets()

        # List available presets
        for name in presets.list_presets("quality"):
            print(name)

        # Run a preset
        result = await presets.run("full_quality", agent_urls)
    """

    def __init__(self):
        self._presets = {**QUALITY_PRESETS, **DEVOPS_PRESETS}

    def list_presets(self, category: Optional[str] = None) -> List[str]:
        """List available presets.

        Args:
            category: Filter by category ("quality" or "devops")

        Returns:
            List of preset names
        """
        if category == "quality":
            return list(QUALITY_PRESETS.keys())
        elif category == "devops":
            return list(DEVOPS_PRESETS.keys())
        else:
            return list(self._presets.keys())

    def get_preset(self, name: str) -> Optional[WorkflowPreset]:
        """Get a specific preset."""
        return self._presets.get(name)

    def list_categories(self) -> List[str]:
        """List preset categories."""
        return ["quality", "devops"]

    async def run(
        self,
        preset_name: str,
        agent_configs: List[Dict[str, str]],
    ) -> WorkflowResult:
        """Run a preset with provided agent configurations.

        Args:
            preset_name: Name of preset to run
            agent_configs: List of {"url": "...", "prompt": "..."} for each step

        Returns:
            WorkflowResult from execution
        """
        preset = self._presets.get(preset_name)
        if not preset:
            raise ValueError(f"Unknown preset: {preset_name}")

        engine = A2AWorkflowEngine()

        # Build steps from preset + provided configs
        steps = []
        for i, agent_config in enumerate(agent_configs):
            if i < len(preset.agents):
                step = WorkflowStep(
                    name=preset.agents[i].get("name", f"step_{i}"),
                    agent_url=agent_config.get("url", ""),
                    prompt_template=agent_config.get("prompt", preset.agents[i].get("prompt", "")),
                )
            else:
                step = WorkflowStep(
                    name=f"step_{i}",
                    agent_url=agent_config.get("url", ""),
                    prompt_template=agent_config.get("prompt", ""),
                )
            steps.append(step)

        # Run based on pattern
        if preset.pattern == "parallel":
            result = await engine.parallel(steps, "Run preset tasks")
        elif preset.pattern == "sequential":
            result = await engine.sequential(steps, "Run preset tasks")
        else:
            result = await engine.parallel(steps, "Run preset tasks")

        await engine.close()
        return result

    def describe_preset(self, name: str) -> str:
        """Get description of a preset."""
        preset = self._presets.get(name)
        if not preset:
            return f"Unknown preset: {name}"

        lines = [
            f"[bold]{preset.name}[/bold]",
            f"{preset.description}",
            "",
            f"Pattern: {preset.pattern}",
            f"Steps: {len(preset.agents)}",
            "",
            "Agents:",
        ]

        for i, agent in enumerate(preset.agents):
            lines.append(f"  {i + 1}. {agent.get('name', 'unnamed')}")

        return "\n".join(lines)


# Convenience function
def get_presets() -> A2APresets:
    """Get workflow presets manager."""
    return A2APresets()
