"""Root Click group and shared harness CLI constants."""

import click

from superqode.harness.templates import BUILTIN_TEMPLATES

# Derived from the template registry so new templates are accepted by the CLI.
# Underscore aliases stay out of the choices, matching list-templates.
HARNESS_TEMPLATE_CHOICES = tuple(name for name in BUILTIN_TEMPLATES if "_" not in name)

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
