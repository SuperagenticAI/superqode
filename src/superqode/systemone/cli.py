"""Shared Click options for decision routing, separate from coding options."""

import os
import click

from .providers import get_provider


def decision_options(function):
    function = click.option(
        "--reviewed-policy",
        is_flag=True,
        help="Acknowledge that the selected provider/model policy has been evaluated before enforcement.",
    )(function)
    function = click.option(
        "--decision-model", default=None, help="Decision model ID, independent of the coding model"
    )(function)
    return click.option(
        "--decision-provider",
        type=click.Choice(["typesafe", "google", "openai"]),
        default=None,
        help="Decision engine; API usage is billed separately",
    )(function)


def apply_selection(provider, model, reviewed_policy):
    if model and not provider:
        raise click.UsageError("Use --decision-provider with --decision-model")
    if not provider and not reviewed_policy:
        return
    definition = get_provider(
        provider or os.environ.get("SUPERQODE_SYSTEMONE_PROVIDER", "typesafe")
    )
    if model and model not in definition.models:
        raise click.UsageError("Choose a supported decision model: " + ", ".join(definition.models))
    values = {
        "SUPERQODE_SYSTEMONE_PROVIDER": definition.id,
        "SUPERQODE_SYSTEMONE_MODEL": model or definition.model,
        "SUPERQODE_SYSTEMONE_ENDPOINT": definition.endpoint,
        "SUPERQODE_SYSTEMONE_API_KEY_ENV": definition.api_key_env,
        "SUPERQODE_SYSTEMONE_POLICY_REVIEWED": "true" if reviewed_policy else "false",
    }
    previous = {key: os.environ.get(key) for key in values}
    os.environ.update(values)

    def restore():
        for key, value in previous.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    click.get_current_context().call_on_close(restore)


def credential_status():
    from .config import routing_settings

    settings = routing_settings()
    present = bool(
        (
            os.environ.get("SUPERQODE_SYSTEMONE_API_KEY")
            or os.environ.get(settings.api_key_env)
            or ""
        ).strip()
    )
    return settings, present
