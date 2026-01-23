"""Enterprise feature gating for SuperQode OSS."""

from __future__ import annotations

from rich.console import Console


_console = Console()


def require_enterprise(feature_name: str) -> bool:
    """Check if enterprise features are available."""
    try:
        import superqode_enterprise  # noqa: F401
    except Exception:
        _console.print(
            f"[yellow]{feature_name} is available in SuperQode Enterprise.[/yellow]\n"
            "[dim]Install the enterprise package to enable this feature.[/dim]"
        )
        return False
    return True
