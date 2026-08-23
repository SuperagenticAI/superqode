"""Issue and inspect API keys for a hosted SuperQode A2A agent."""

from __future__ import annotations

import secrets

import click
from rich.console import Console

from superqode.a2a.keys import (
    REVOKED_ENV,
    SECRET_ENV,
    KeyMintError,
    mint_key,
    resolve_secret,
    revoked_key_ids,
    verify_key,
)

console = Console()


@click.group("a2a-keys")
def a2a_keys() -> None:
    """Issue, inspect, and revoke A2A agent API keys."""


@a2a_keys.command("secret")
def generate_secret() -> None:
    """Print a new signing secret to set as SUPERQODE_A2A_KEY_SECRET."""
    click.echo(f"{SECRET_ENV}={secrets.token_urlsafe(48)}")
    console.print(
        "\n[yellow]Set this on the server that verifies keys, and keep it there.[/yellow]\n"
        "Changing it invalidates every key already issued."
    )


@a2a_keys.command("issue")
@click.argument("customer")
@click.option("--tier", default="trial", show_default=True, help="Tier recorded in the key")
@click.option("--days", default=30, show_default=True, type=int, help="How long the key is valid")
@click.option("--test-key", is_flag=True, help="Mint a sqk_test_ key instead of sqk_live_")
@click.option("--secret", envvar=SECRET_ENV, help=f"Signing secret (or set {SECRET_ENV})")
def issue(customer: str, tier: str, days: int, test_key: bool, secret: str | None) -> None:
    """Mint a key for CUSTOMER."""
    try:
        key, claims = mint_key(
            customer, tier=tier, valid_days=days, secret=secret, live=not test_key
        )
    except KeyMintError as error:
        raise click.ClickException(str(error)) from error

    # Print the key through click rather than the Rich console: Rich wraps at
    # terminal width, and a wrapped secret is a broken secret once copied.
    click.echo("")
    click.echo(key)
    click.echo("")
    console.print(f"customer  {claims.customer}")
    console.print(f"tier      {claims.tier}")
    console.print(f"key id    {claims.key_id}")
    console.print(f"expires   in {claims.expires_in_days:.0f} days")
    console.print(
        "\n[yellow]Copy it now. Keys are signed rather than stored, so this value "
        "cannot be shown again.[/yellow]"
    )
    console.print(f"To revoke before expiry, add [bold]{claims.key_id}[/bold] to {REVOKED_ENV}.")


@a2a_keys.command("verify")
@click.argument("key")
@click.option("--secret", envvar=SECRET_ENV, help=f"Signing secret (or set {SECRET_ENV})")
def verify(key: str, secret: str | None) -> None:
    """Check whether KEY would be accepted right now."""
    verdict = verify_key(key, secret=secret)
    if verdict.valid and verdict.claims is not None:
        console.print("[green]valid[/green]")
        console.print(f"customer  {verdict.claims.customer}")
        console.print(f"tier      {verdict.claims.tier}")
        console.print(f"key id    {verdict.claims.key_id}")
        console.print(f"expires   in {verdict.claims.expires_in_days:.1f} days")
        return

    console.print(f"[red]rejected[/red]  {verdict.reason}")
    if verdict.claims is not None:
        console.print(f"customer  {verdict.claims.customer} (key id {verdict.claims.key_id})")
    raise SystemExit(1)


@a2a_keys.command("status")
@click.option("--secret", envvar=SECRET_ENV, help=f"Signing secret (or set {SECRET_ENV})")
def status(secret: str | None) -> None:
    """Show whether this environment can issue and verify keys."""
    configured = resolve_secret(secret) is not None
    revoked = revoked_key_ids()
    console.print(f"{SECRET_ENV}  {'[green]set[/green]' if configured else '[red]missing[/red]'}")
    console.print(f"{REVOKED_ENV}  {len(revoked)} revoked key id(s)")
    if not configured:
        console.print(
            "\n[yellow]Without a secret this server refuses every key rather than "
            "accepting them.[/yellow]\nGenerate one with: superqode a2a-keys secret"
        )
