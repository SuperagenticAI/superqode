"""Inspect and start private Tailscale access without installing a VPN."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import time
from urllib.parse import urlsplit

HTTPS_PORT = 47832


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
            and parsed.port in (None, 443, HTTPS_PORT)
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
    suffix = f":{parsed.port}" if parsed.port not in (None, 443) else ""
    return "https://" + parsed.hostname.lower() + suffix


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


def tailscale_app():
    path = Path("/Applications/Tailscale.app")
    return path if path.is_dir() else None


def command(binary, *arguments):
    result = subprocess.run(
        [binary, *arguments], capture_output=True, text=True, timeout=3, check=False
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
        "issue": "Install Tailscale on this Mac and on the iPhone, then sign in to the same account on both.",
        "docs": "https://tailscale.com/docs/features/tailscale-serve",
        "download": "https://tailscale.com/download",
        "command": "",
    }
    if not binary:
        return result
    try:
        status = command(binary, "status", "--json")
        if status.get("BackendState") != "Running":
            raise ValueError("Tailscale is not connected yet.")
        host = str((status.get("Self") or {}).get("DNSName") or "").rstrip(".")
        result["private_url"] = private_origin(f"https://{host}:{HTTPS_PORT}")
        serving = command(binary, "serve", "status", "--json")
        # Refuse any public Funnel configuration, even when a different port is public.
        if any((serving.get("AllowFunnel") or {}).values()):
            raise ValueError(
                "Public Tailscale Funnel is enabled. Disable Funnel before using private remote access."
            )
        web = (serving.get("Web") or {}).get(f"{host}:{HTTPS_PORT}", {})
        handler = (web.get("Handlers") or {}).get("/", {})
        if handler.get("Proxy") not in {f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
            raise ValueError("Click Connect this Mac to finish the private link.")
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


def setup(port=47831):
    """Explicit user action: create a private proxy only when no service is replaced."""
    current = inspect(port)
    if current["ready"]:
        return current
    binary = tailscale_binary()
    if not binary or not current["private_url"]:
        raise ValueError(current["issue"])
    config = command(binary, "serve", "status", "--json")
    if any(config.get("AllowFunnel", {}).values()):
        raise ValueError("Disable public Funnel in Tailscale before configuring private access")
    hostname = urlsplit(current["private_url"]).hostname
    # A dedicated private HTTPS port coexists with another app's Serve root.
    if (config.get("Web") or {}).get(f"{hostname}:{HTTPS_PORT}") or (config.get("TCP") or {}).get(
        str(HTTPS_PORT)
    ):
        raise ValueError(
            "Another Tailscale service is already using this private port. Existing services were left unchanged. Turn that service off in Tailscale, then click Connect again."
        )
    try:
        result = subprocess.run(
            [binary, "serve", "--bg", f"--https={HTTPS_PORT}", f"http://127.0.0.1:{port}"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=25,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        raise ValueError(
            "Tailscale is still starting. Stay signed in and click Connect again."
        ) from None
    if result.returncode:
        raise ValueError(
            "Tailscale did not finish the private link. Stay signed in and click Connect again."
        )
    return inspect(port)


def _backend(binary):
    try:
        return command(binary, "status", "--json")
    except (ValueError, OSError, subprocess.TimeoutExpired, TypeError):
        return {}


def _ensure_running(binary):
    """Start the installed Tailscale app. Never enables public Funnel or changes routes."""
    status = _backend(binary)
    if status.get("BackendState") == "Running":
        return
    app = tailscale_app()
    if app is not None:
        subprocess.run(
            ["open", "-a", str(app)],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            timeout=5,
            check=False,
        )
    try:
        subprocess.run(
            [binary, "up", "--timeout=8s"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        pass
    for _ in range(6):
        status = _backend(binary)
        if status.get("BackendState") == "Running":
            return
        time.sleep(0.4)
    if status.get("BackendState") == "NeedsLogin":
        raise ValueError("Sign in to Tailscale on this Mac, then click Connect again.")
    raise ValueError("Open Tailscale, sign in, then click Connect again.")


def connect(port=47831):
    """One click: start Tailscale when it is installed, then publish the private link."""
    binary = tailscale_binary()
    if not binary:
        raise ValueError(
            "Install Tailscale on this Mac and on the iPhone, sign in to the same account on both, then click Connect again."
        )
    _ensure_running(binary)
    result = setup(port)
    if not result.get("ready"):
        raise ValueError(
            result.get("issue") or "The private connection is not ready yet. Click Connect again."
        )
    return result
