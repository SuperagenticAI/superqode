"""Root Click group and shared harness CLI constants."""

import click

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


@click.group()
def harness():
    """Create, validate, and run SuperQode harness specs."""
    pass
