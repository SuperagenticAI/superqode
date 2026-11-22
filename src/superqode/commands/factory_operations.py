"""Factory operations commands shared with native Studio."""

from functools import wraps
import json

import click


def output(function):
    @wraps(function)
    def invoke(*args, **kwargs):
        try:
            value = function(*args, **kwargs)
            click.echo(json.dumps(value, indent=2))
            if isinstance(value, dict) and (
                value.get("structural_passed") is False
                or (value.get("worker_ready") is False and kwargs.get("probe"))
            ):
                raise click.exceptions.Exit(2)
        except (ValueError, OSError, KeyError) as exc:
            raise click.ClickException(str(exc)) from exc

    return invoke


def project_option(function):
    return click.option("--project", default=".", type=click.Path(file_okay=False))(function)


@click.group()
def operations():
    """Check readiness, prepare services and recover Factory sources/evidence."""


@operations.command("check")
@project_option
@click.option(
    "--probe", is_flag=True, help="Execute protected synthetic isolation probes; no models"
)
@click.option("--require-platform", type=click.Choice(["Darwin", "Linux"]), default=None)
@output
def check(project, probe, require_platform):
    from superqode.factory.operations import readiness

    return readiness(project, probe=probe, require_platform=require_platform or "")


@operations.command("handover")
@project_option
@click.option("--run", "runs", multiple=True)
@click.option("--improvement", "improvements", multiple=True)
@output
def handover(project, runs, improvements):
    """Back up pinned Factory sources and explicitly selected historical evidence."""
    from superqode.factory.handover import create

    return create(project, runs=runs, improvements=improvements)


@operations.command("verify")
@project_option
@click.argument("identity")
@click.option("--digest", required=True)
@output
def verify(project, identity, digest):
    from superqode.factory.handover import inspect

    return inspect(project, identity, expected=digest)


@operations.command("restore")
@project_option
@click.argument("identity")
@click.option("--digest", required=True)
@click.option(
    "--destination", required=True, help=".superqode/factory-operations/restores/<new-name>"
)
@output
def restore(project, identity, digest, destination):
    """Recover sources into a fresh project-local folder; historical evidence stays inert."""
    from superqode.factory.handover import restore

    return restore(project, identity, expected=digest, destination=destination)


@operations.command("deploy")
@project_option
@click.option(
    "--platform", "target_platform", type=click.Choice(["Darwin", "Linux"]), required=True
)
@click.option("--target-project", required=True)
@click.option("--python", required=True)
@click.option("--reference", required=True, help="One pinned WorkOrder id")
@click.option("--user", default="superqode")
@output
def deploy(project, target_platform, target_project, python, reference, user):
    """Write a disabled one-shot service package; never install or start it."""
    from superqode.factory.operations import deployment

    return deployment(
        project,
        target_platform=target_platform,
        target_project=target_project,
        python=python,
        reference=reference,
        user=user,
    )


@operations.command("retention")
@project_option
@click.option("--keep", default=2, type=int)
@click.option("--days", default=30, type=int)
@click.option("--cutoff", type=float)
@click.option("--apply-digest", default="", help="Apply exactly the reviewed inventory and cutoff")
@output
def retention(project, keep, days, cutoff, apply_digest):
    """Preview generated-archive cleanup; apply only with the exact reviewed digest."""
    from superqode.factory.handover import retention, prune

    review = retention(project, keep=keep, days=days, cutoff=cutoff)
    if apply_digest:
        if cutoff is None or review["digest"] != apply_digest:
            raise ValueError("Supply the exact reviewed cutoff and inventory digest")
        return prune(project, review)
    return review


@operations.command("checkpoint")
@project_option
@output
def checkpoint(project):
    """Encrypt a stopped runtime and Git history; keep its key separately."""
    from superqode.factory.recovery import create

    return create(project)


@operations.command("verify-runtime")
@click.option("--archive", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--key-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--digest", required=True)
@output
def verify_runtime(archive, key_file, digest):
    from superqode.factory.recovery import decode

    manifest, entries = decode(archive, key_file, digest)
    return {"manifest": manifest, "verified_files": len(entries), "execution_enabled": False}


@operations.command("recover-runtime")
@click.option("--archive", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--key-file", required=True, type=click.Path(exists=True, dir_okay=False))
@click.option("--digest", required=True)
@click.option("--destination", required=True, type=click.Path(file_okay=False))
@output
def recover_runtime(archive, key_file, digest, destination):
    from superqode.factory.recovery import restore

    return restore(archive, key_file, expected=digest, destination=destination)


@operations.command("acknowledge-recovery")
@project_option
@click.option("--digest", required=True)
@click.option("--probe", is_flag=True)
@output
def acknowledge_recovery(project, digest, probe):
    from superqode.factory.recovery import acknowledge

    return acknowledge(project, digest, probe=probe)


@operations.command("retire-preview")
@project_option
@output
def retire_preview(project):
    from superqode.factory.lifecycle import review

    return review(project)


@operations.command("retire")
@project_option
@click.option("--digest", required=True)
@output
def retire(project, digest):
    from superqode.factory.lifecycle import retire

    return retire(project, digest)


@operations.command("reactivate")
@project_option
@click.option("--digest", required=True)
@click.option("--probe", is_flag=True)
@output
def reactivate(project, digest, probe):
    from superqode.factory.lifecycle import reactivate

    return reactivate(project, digest, probe=probe)
