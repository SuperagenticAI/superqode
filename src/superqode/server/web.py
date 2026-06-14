"""
Web Server Mode - Run TUI in Browser.

Uses textual-serve to run the SuperQode TUI in a web browser.
Enables authenticated browser access to the local TUI.

Features:
- Browser-based terminal UI
- Authentication
- Multiple concurrent sessions
- Session sharing

Note: Requires textual-serve to be installed.
"""

from __future__ import annotations

import ipaddress
import os
import secrets
import shlex
import sys
import webbrowser
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional
import json

try:
    from textual_serve.server import Server

    TEXTUAL_SERVE_AVAILABLE = True
except ImportError:
    Server = None
    TEXTUAL_SERVE_AVAILABLE = False


AUTH_COOKIE_NAME = "superqode_web_auth"


@dataclass
class WebServerConfig:
    """Configuration for the web server."""

    host: str = "127.0.0.1"
    port: int = 8080

    # Authentication
    require_auth: bool = True
    auth_token: Optional[str] = None  # Generated if not provided
    allow_remote: bool = False

    # Sessions
    max_sessions: int = 10
    session_timeout: int = 3600  # 1 hour

    # TLS
    ssl_cert: Optional[str] = None
    ssl_key: Optional[str] = None

    # Project
    project_path: Optional[Path] = None

    def __post_init__(self):
        if not is_loopback_host(self.host) and not self.allow_remote:
            raise ValueError(
                "Remote web serving is disabled by default. Use --allow-remote only on "
                "trusted networks."
            )
        if not self.require_auth and not is_loopback_host(self.host):
            raise ValueError("Authentication cannot be disabled for remote web serving.")
        if self.require_auth and not self.auth_token:
            self.auth_token = secrets.token_urlsafe(32)

    @property
    def cookie_secure(self) -> bool:
        return bool(self.ssl_cert)


def is_loopback_host(host: str) -> bool:
    """Return True when a bind host is local-machine only."""
    normalized = host.strip().lower()
    if normalized in {"localhost", "127.0.0.1", "::1"}:
        return True
    if normalized in {"0.0.0.0", "::", ""}:
        return False
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


def extract_web_auth_token(
    query: Mapping[str, str],
    headers: Mapping[str, str],
    cookies: Mapping[str, str],
) -> Optional[str]:
    """Extract a web auth token from query, bearer header, or cookie."""
    query_token = query.get("token")
    if query_token:
        return query_token

    header = headers.get("Authorization") or headers.get("authorization") or ""
    if header.lower().startswith("bearer "):
        bearer = header[7:].strip()
        if bearer:
            return bearer

    cookie_token = cookies.get(AUTH_COOKIE_NAME)
    if cookie_token:
        return cookie_token
    return None


def is_web_request_authorized(
    query: Mapping[str, str],
    headers: Mapping[str, str],
    cookies: Mapping[str, str],
    expected_token: Optional[str],
) -> bool:
    """Check web request auth without leaking timing on token comparison."""
    supplied = extract_web_auth_token(query, headers, cookies)
    return bool(
        expected_token and supplied and secrets.compare_digest(supplied, expected_token)
    )


@dataclass
class WebSession:
    """A web session."""

    id: str
    created_at: datetime = field(default_factory=datetime.now)
    last_active: datetime = field(default_factory=datetime.now)
    user_agent: str = ""
    remote_addr: str = ""
    project_path: str = ""


class WebServer:
    """
    Web server for running SuperQode TUI in browser.

    Wraps textual-serve to provide browser-based access
    to the SuperQode TUI.

    Usage:
        config = WebServerConfig(host="0.0.0.0", port=8080)
        server = WebServer(config)

        print(f"Access token: {server.config.auth_token}")
        print(f"Open: http://{config.host}:{config.port}")

        server.start_sync()
    """

    def __init__(self, config: Optional[WebServerConfig] = None):
        if not TEXTUAL_SERVE_AVAILABLE:
            raise ImportError(
                "textual-serve is required for web server mode. "
                'Install with: pip install "superqode[web]"'
            )

        self.config = config or WebServerConfig()
        self._server: Optional[Server] = None
        self._sessions: Dict[str, WebSession] = {}
        self._running = False

    @property
    def is_running(self) -> bool:
        """Check if server is running."""
        return self._running

    @property
    def url(self) -> str:
        """Get the server URL."""
        protocol = "https" if self.config.ssl_cert else "http"
        return f"{protocol}://{self.config.host}:{self.config.port}"

    @property
    def authenticated_url(self) -> str:
        """Get URL with authentication token."""
        if self.config.require_auth and self.config.auth_token:
            return f"{self.url}?token={self.config.auth_token}"
        return self.url

    def _textual_command(self) -> str:
        """Command textual-serve runs for each browser websocket session."""
        package_root = Path(__file__).resolve().parents[1]
        return f"{shlex.quote(sys.executable)} {shlex.quote(str(package_root / 'app_main.py'))}"

    def _create_textual_server(self) -> Server:
        if not TEXTUAL_SERVE_AVAILABLE or Server is None:
            raise ImportError(
                "textual-serve is required for web server mode. "
                'Install with: pip install "superqode[web]"'
            )

        config = self.config

        class AuthenticatedServer(Server):
            async def _make_app(self):  # type: ignore[override]
                app = await super()._make_app()
                if not config.require_auth:
                    return app

                from aiohttp import web

                @web.middleware
                async def auth_middleware(request, handler):
                    token = config.auth_token or ""
                    if not is_web_request_authorized(
                        request.query, request.headers, request.cookies, token
                    ):
                        raise web.HTTPUnauthorized(
                            text="SuperQode web auth required. Open the tokened URL printed by the server."
                        )

                    response = await handler(request)
                    if request.query.get("token") == token:
                        response.set_cookie(
                            AUTH_COOKIE_NAME,
                            token,
                            httponly=True,
                            secure=config.cookie_secure,
                            samesite="Strict",
                            max_age=config.session_timeout,
                        )
                    return response

                app.middlewares.append(auth_middleware)
                return app

        return AuthenticatedServer(
            self._textual_command(),
            host=config.host,
            port=config.port,
            title="SuperQode",
            public_url=self.url,
        )

    def start_sync(self) -> None:
        """Start server synchronously."""
        if self._running:
            return

        if self.config.project_path:
            os.chdir(self.config.project_path)

        self._server = self._create_textual_server()

        # Configure SSL if provided
        if self.config.ssl_cert and self.config.ssl_key:
            self._server.ssl_certfile = self.config.ssl_cert
            self._server.ssl_keyfile = self.config.ssl_key

        self._running = True

        print("SuperQode Web Server starting...")
        print(f"   URL: {self.url}")

        if self.config.require_auth:
            print(f"   Token: {self.config.auth_token}")
            print(f"   Full URL: {self.authenticated_url}")

        self._server.serve()

    async def stop(self) -> None:
        """Stop the web server."""
        if not self._running:
            return

        self._running = False

        if self._server:
            # textual-serve doesn't have a clean shutdown method
            # so we just mark it as stopped
            self._server = None

        self._sessions.clear()

    def get_sessions(self) -> List[WebSession]:
        """Get all active sessions."""
        return list(self._sessions.values())


def start_server(
    host: str = "127.0.0.1",
    port: int = 8080,
    project_path: Optional[Path] = None,
    require_auth: bool = True,
    auth_token: Optional[str] = None,
    allow_remote: bool = False,
    open_browser: bool = False,
) -> None:
    """
    Convenience function to start the web server.

    Usage:
        from superqode.server import start_server
        start_server(host="0.0.0.0", port=8080, allow_remote=True)
    """
    config = WebServerConfig(
        host=host,
        port=port,
        project_path=project_path,
        require_auth=require_auth,
        auth_token=auth_token,
        allow_remote=allow_remote,
    )

    server = WebServer(config)
    if open_browser and is_loopback_host(host):
        webbrowser.open(server.authenticated_url)
    server.start_sync()


def add_server_command():
    """Add server command to CLI.

    Call this during CLI setup to add the 'serve' command.
    """
    import click

    @click.command("serve")
    @click.option("--host", default="127.0.0.1", help="Host to bind to")
    @click.option("--port", default=8080, type=int, help="Port to listen on")
    @click.option("--no-auth", is_flag=True, help="Disable local URL token display")
    @click.option("--token", default=None, help="Authentication token")
    @click.option(
        "--allow-remote",
        is_flag=True,
        help="Allow binding to non-loopback hosts such as 0.0.0.0",
    )
    @click.option("--project", default=None, help="Project directory")
    def serve_command(host, port, no_auth, token, allow_remote, project):
        """Start SuperQode in web server mode."""
        config = WebServerConfig(
            host=host,
            port=port,
            require_auth=not no_auth,
            auth_token=token,
            allow_remote=allow_remote,
            project_path=Path(project) if project else None,
        )

        if not TEXTUAL_SERVE_AVAILABLE:
            click.echo(
                "Error: textual-serve is required for web server mode.\n"
                'Install with: pip install "superqode[web]"'
            )
            sys.exit(1)

        server = WebServer(config)
        server.start_sync()

    return serve_command
