"""ACP protocol diagnostics alias; agent management stays under `agents`."""

import click
from .agents import agents_doctor


@click.group()
def acp():
    """Inspect ACP protocol compatibility, including opt-in v2 Preview."""


acp.add_command(agents_doctor, "doctor")
