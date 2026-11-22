"""Explicit headless operation of saved, bounded experiment policies."""

import click

from .factory_operations import output, project_option


@click.group()
def campaign():
    """Operate finite opt-in improvement campaigns; never activate proposals."""


@campaign.command("create")
@project_option
@output
def create(project):
    from superqode.factory.campaigns import create

    return create(project)


@campaign.command("inspect")
@project_option
@click.argument("identity")
@output
def inspect(project, identity):
    from superqode.factory.campaigns import inspect

    return inspect(project, identity)


@campaign.command("enqueue")
@project_option
@click.argument("identity")
@click.option("--digest", "expected", required=True)
@click.option("--kind", required=True)
@click.option("--key", required=True)
@click.option("--source", required=True)
@click.option("--source-digest", required=True)
@click.option("--parent", default="")
@output
def enqueue(project, identity, **options):
    from superqode.factory.campaigns import enqueue

    return enqueue(project, identity, **options)


@campaign.command("run")
@project_option
@click.argument("identity")
@click.option("--digest", required=True)
@click.option("--live", is_flag=True)
@output
def run(project, identity, digest, live):
    from superqode.factory.campaigns import advance

    return advance(project, identity, digest, live=live)


@campaign.command("worker")
@project_option
@click.argument("identity")
@click.option("--digest", required=True)
@click.option("--live", is_flag=True)
@output
def worker(project, identity, digest, live):
    """Process admitted triggers automatically until a finite campaign stop."""
    from superqode.factory.campaigns import run_worker

    return run_worker(project, identity, digest, live=live)


@campaign.command("stop")
@project_option
@click.argument("identity")
@click.option("--digest", required=True)
@output
def stop(project, identity, digest):
    from superqode.factory.campaigns import stop

    return stop(project, identity, digest)
