"""Customer-operated authenticated issue and monitoring admission."""

from pathlib import Path
import json

import click
from .factory_operations import output, project_option


@click.group()
def intake():
    """Authenticate inbound events and queue bounded work without starting agents."""


@intake.command("receive")
@project_option
@click.option("--source", type=click.Choice(["github", "linear", "monitor"]), required=True)
@click.option("--body", required=True, help="Project-relative raw webhook body")
@click.option("--headers", required=True, help="Project-relative JSON headers")
@output
def receive(project, source, body, headers):
    from superqode.factory.definition import project_path
    from superqode.factory.operations import read
    from superqode.factory.intake import receive

    root = Path(project).resolve()
    return receive(
        root,
        source,
        read(project_path(root, body), 64000),
        json.loads(read(project_path(root, headers), 8000)),
    )


@intake.command("serve")
@project_option
@click.option("--port", type=click.IntRange(1024, 65535), default=8767)
def serve(project, port):
    """Listen on loopback behind the customer's HTTPS proxy; never run agents."""
    from superqode.factory.intake import serve

    serve(project, port=port)
