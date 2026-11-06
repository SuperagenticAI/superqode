"""Inspect private Tailscale access without installing or reconfiguring a VPN."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit


def private_origin(value):
    """Accept a concrete HTTPS tailnet hostname, never a public tunnel URL."""
    if not isinstance(value, str) or len(value) > 253:
        raise ValueError("Enter the Mac's private https://name.tailnet.ts.net address")
    parsed = urlsplit(value.strip())
    try:
        valid = (
            parsed.scheme == "https"
            and parsed.hostname
            and parsed.hostname.endswith(".ts.net")
            and len(parsed.hostname.split(".")) >= 4
            and parsed.port in (None, 443)
            and not parsed.username
            and not parsed.password
            and parsed.path in ("", "/")
            and not parsed.query
            and not parsed.fragment
            and all(c.isascii() and (c.isalnum() or c in ".-") for c in parsed.hostname)
        )
    except ValueError:
        valid = False
    if not valid:
        raise ValueError("Use a private HTTPS Tailscale hostname without a path or credentials")
    return "https://" + parsed.hostname.lower()


def tailscale_binary():
    return shutil.which("tailscale") or next(
        (
            str(p)
            for p in (
                Path("/Applications/Tailscale.app/Contents/MacOS/Tailscale"),
                Path("/Applications/Tailscale.app/Contents/MacOS/tailscale"),
            )
            if p.is_file()
        ),
        None,
    )


def command(binary, *arguments):
    result = subprocess.run(
        [binary, *arguments], capture_output=True, text=True, timeout=8, check=False
    )
    if result.returncode or len(result.stdout) > 1_000_000:
        raise ValueError("Open Tailscale, sign in and enable it, then check the connection again")
    return json.loads(result.stdout)


def inspect(port=47831):
    """Do not return peer inventory, account information or raw command output."""
    binary = tailscale_binary()
    result = {
        "installed": bool(binary),
        "ready": False,
        "private_url": "",
        "issue": "Install Tailscale on this Mac and your iPhone, then sign in to your private network.",
        "docs": "https://tailscale.com/docs/features/tailscale-serve",
        "download": "https://tailscale.com/download",
        "command": f"tailscale serve --bg http://127.0.0.1:{port}",
    }
    if not binary:
        return result
    try:
        status = command(binary, "status", "--json")
        if status.get("BackendState") != "Running":
            raise ValueError("Open Tailscale and connect this Mac before enabling remote access")
        host = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
        result["private_url"] = private_origin("https://" + host)
        serving = command(binary, "serve", "status", "--json")
        # Refuse any public Funnel configuration, even when a different port is public.
        if any((serving.get("AllowFunnel") or {}).values()):
            raise ValueError(
                "Public Tailscale Funnel is enabled. Disable Funnel before using private remote access."
            )
        web = (serving.get("Web") or {}).get(host + ":443", {})
        handler = (web.get("Handlers") or {}).get("/", {})
        if handler.get("Proxy") not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            raise ValueError(
                "Configure private Tailscale Serve using the command below, then verify again. Existing services are not changed automatically."
            )
        result.update(ready=True, issue="")
    except (ValueError, OSError, subprocess.TimeoutExpired, TypeError):
        # Only controlled repair text is shown; CLI output may contain identities or tokens.
        import sys

        error = sys.exception()
        result["issue"] = (
            str(error)
            if type(error) is ValueError and not isinstance(error, json.JSONDecodeError)
            else "Tailscale could not be checked. Open Tailscale and retry."
        )
    return result
