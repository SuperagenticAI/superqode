"""SuperQode 'connect' CLI: acp/byok/local/setup connection helpers."""

import os
import json
import click
import click

import click


@click.group()
def connect():
    """Connect to ACP agents, BYOK or LOCAL providers, a UHP server, or an A2A agent."""
    pass


@connect.command("acp")
@click.argument("agent", metavar="AGENT")
@click.option("--project-dir", "-d", metavar="DIR", help="Project directory to work in")
def connect_acp(agent, project_dir):
    """Connect to an ACP coding agent."""
    from superqode.commands.acp import connect_agent

    exit(connect_agent(agent, project_dir))


@connect.command("byok")
@click.argument("provider", metavar="PROVIDER", required=False)
@click.argument("model", metavar="MODEL", required=False)
def connect_byok(provider, model):
    """Connect to a BYOK provider/model."""
    from superqode.commands.providers import connect_provider

    exit(connect_provider(provider, model))


@connect.command("local")
@click.argument("provider", metavar="PROVIDER", required=False)
@click.argument("model", metavar="MODEL", required=False)
def connect_local(provider, model):
    """Connect to a local/self-hosted provider/model."""
    from superqode.commands.providers import connect_local_provider

    exit(connect_local_provider(provider, model))


@connect.command("zai")
@click.argument("model", metavar="MODEL", required=False)
def connect_zai(model):
    """Connect to Z.AI GLM models through the general API.

    This does not use the restricted GLM Coding Plan endpoint.
    """
    from superqode.commands.providers import connect_provider

    exit(connect_provider("zai", model))


@connect.command("uhp")
@click.option("--base-url", metavar="URL", help="UHP server root, e.g. https://your-server")
@click.option("--api-key", metavar="KEY", help="Bearer credential for the server")
@click.option("--harness", metavar="ID", help="Harness id to select on that server")
@click.option(
    "--max-output-tokens",
    type=int,
    metavar="N",
    help="Cap the token budget for a task. Providers that bill up front refuse "
    "a request whose budget exceeds the balance.",
)
@click.option("--save/--no-save", default=True, help="Remember this connection")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def connect_uhp(base_url, api_key, harness, max_output_tokens, save, json_output):
    """Connect to a Unified Harness Protocol server and list its harnesses.

    A UHP server is a remote catalog, so connecting resolves the address,
    discovers what the server runs, and selects one harness. Without
    `--harness` the discovered harnesses are listed for you to pick from.
    """
    from superqode.commands.uhp import connect_uhp_server

    exit(
        connect_uhp_server(
            base_url,
            api_key,
            harness,
            max_output_tokens=max_output_tokens,
            save=save,
            json_output=json_output,
        )
    )


@connect.command("a2a")
@click.option("--url", metavar="URL", help="Agent origin or Agent Card URL")
@click.option("--token", metavar="TOKEN", help="Bearer credential for operations")
@click.option(
    "--header",
    "header_values",
    multiple=True,
    metavar="NAME:VALUE",
    help="Extra request header. Repeatable.",
)
@click.option("--send", "message", metavar="TEXT", help="Send one message after discovery")
@click.option("--save/--no-save", default=True, help="Remember this connection")
@click.option(
    "--inspect",
    "inspect",
    is_flag=True,
    help="Show the binding choice, skipped interfaces, and last HTTP request/response",
)
@click.option(
    "--conformance",
    is_flag=True,
    help="Run SuperQode's client checks against this card (fetch, binding, one task)",
)
@click.option(
    "--no-send",
    is_flag=True,
    help="Skip the send check. Only applies with --conformance",
)
@click.option(
    "--oauth/--no-oauth",
    default=True,
    help="When a card requires OAuth, open a browser (default: open)",
)
@click.option(
    "--logout",
    is_flag=True,
    help="Delete stored OAuth tokens for this agent origin and revoke them at the identity provider if it advertises revocation_endpoint",
)
@click.option(
    "--tls-cert",
    "tls_cert",
    metavar="PATH",
    help="Client certificate PEM for mutual TLS",
)
@click.option(
    "--tls-key",
    "tls_key",
    metavar="PATH",
    help="Client certificate private key PEM for mutual TLS",
)
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def connect_a2a(
    url,
    token,
    header_values,
    message,
    save,
    inspect,
    conformance,
    no_send,
    oauth,
    logout,
    tls_cert,
    tls_key,
    json_output,
):
    """Connect to an A2A agent from its Agent Card.

    Fetches the card, selects the first binding SuperQode can speak
    (JSON-RPC 1.0, JSON-RPC 0.3, or HTTP+JSON 1.0), and optionally sends
    one message. Open cards need no token.
    """
    from superqode.a2a.connection import parse_header_options
    from superqode.commands.a2a_connect import connect_a2a_agent

    try:
        headers = parse_header_options(header_values)
    except ValueError as exc:
        raise click.BadParameter(str(exc), param_hint="--header") from exc

    exit(
        connect_a2a_agent(
            url,
            token,
            headers=headers,
            message=message,
            save=save,
            inspect=inspect,
            conformance=conformance,
            send=not no_send,
            oauth=oauth,
            logout=logout,
            cert=tls_cert,
            key=tls_key,
            json_output=json_output,
        )
    )


@connect.command("setup")
@click.argument("provider", metavar="PROVIDER")
@click.option("--json", "json_output", is_flag=True, help="Emit JSON")
def connect_setup(provider, json_output):
    """Show how to connect a provider: env vars, base URL, docs, and a test command.

    Works for any of the 130+ models.dev providers (curated or synthesized).
    Example: `superqode connect setup deepinfra`
    """
    from superqode.providers.dynamic import resolve_provider_def, is_curated_provider
    from superqode.providers.registry import ProviderCategory
    from superqode.providers.catalog import load_models_catalog_cached, filter_models

    pdef = resolve_provider_def(provider)
    if pdef is None:
        raise click.ClickException(
            f"Unknown provider '{provider}'. Run `superqode models providers` to list them."
        )

    # Example models: curated examples first, else top catalog models for this id.
    examples = list(pdef.example_models or [])
    if not examples:
        catalog_models = filter_models(
            load_models_catalog_cached(), provider=pdef.id, limit=5, sort="context"
        )
        examples = [m.id for m in catalog_models]

    is_local = pdef.category == ProviderCategory.LOCAL
    connect_kind = "local" if is_local else "byok"
    missing_env = [e for e in (pdef.env_vars or []) if not os.environ.get(e)]
    configured = bool(pdef.env_vars) and not missing_env

    if json_output:
        click.echo(
            json.dumps(
                {
                    "id": pdef.id,
                    "name": pdef.name,
                    "curated": is_curated_provider(pdef.id),
                    "dynamic": pdef.dynamic,
                    "category": pdef.category.value,
                    "routing": "openai-compatible"
                    if pdef.litellm_prefix == "openai/"
                    else "native",
                    "env_vars": list(pdef.env_vars or []),
                    "env_configured": configured,
                    "base_url_env": pdef.base_url_env,
                    "default_base_url": pdef.default_base_url,
                    "docs_url": pdef.docs_url,
                    "example_models": examples,
                    "connect_command": f"superqode connect {connect_kind} {pdef.id} <model>",
                },
                indent=2,
            )
        )
        return

    tag = "curated / recommended" if is_curated_provider(pdef.id) else "from models.dev"
    click.echo(f"Provider:  {pdef.name} ({pdef.id})  —  {tag}")
    click.echo(f"Category:  {pdef.category.value}")
    if pdef.env_vars:
        status = "✓ set" if configured else "not set"
        click.echo(f"\nAPI key:   {status}")
        for env in pdef.env_vars:
            present = "✓" if os.environ.get(env) else " "
            click.echo(f"  [{present}] export {env}=...")
    elif is_local:
        click.echo("\nAPI key:   none required (local server)")
    if pdef.base_url_env:
        click.echo(f"\nBase URL:  export {pdef.base_url_env}={pdef.default_base_url or '<url>'}")
        if pdef.default_base_url:
            click.echo(f"           (defaults to {pdef.default_base_url})")
    if pdef.docs_url:
        click.echo(f"\nDocs:      {pdef.docs_url}")
    if examples:
        click.echo("\nExample models:")
        for m in examples[:5]:
            click.echo(f"  - {m}")
    click.echo("\nNext:")
    click.echo(f"  superqode models --provider {pdef.id}        # browse this provider's models")
    model_hint = examples[0] if examples else "<model>"
    click.echo(f"  superqode connect {connect_kind} {pdef.id} {model_hint}")
    if missing_env:
        click.echo(
            f"\n⚠  Set {' or '.join(missing_env)} before connecting "
            "(SuperQode reads keys from the environment; it never stores them)."
        )
