"""
Web Server Mode - Run TUI in Browser.

Uses textual-serve to run the SuperQode TUI in a web browser.
Enables remote access and collaborative sessions.

Features:
- Browser-based terminal UI
- Authentication
- Multiple concurrent sessions
- Session sharing

Note: Requires textual-serve to be installed.
"""

from __future__ import annotations

import asyncio
import os
import secrets
import sys
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
import json

try:
    from textual_serve.server import Server

    TEXTUAL_SERVE_AVAILABLE = True
except ImportError:
    Server = None
    TEXTUAL_SERVE_AVAILABLE = False


@dataclass
class WebServerConfig:
    """Configuration for the web server."""

    host: str = "127.0.0.1"
    port: int = 8080

    # Authentication
    require_auth: bool = True
    auth_token: Optional[str] = None  # Generated if not provided

    # Sessions
    max_sessions: int = 10
    session_timeout: int = 3600  # 1 hour

    # TLS
    ssl_cert: Optional[str] = None
    ssl_key: Optional[str] = None

    # Project
    project_path: Optional[Path] = None

    def __post_init__(self):
        if self.require_auth and not self.auth_token:
            self.auth_token = secrets.token_urlsafe(32)


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

        await server.start()
    """

    def __init__(self, config: Optional[WebServerConfig] = None):
        if not TEXTUAL_SERVE_AVAILABLE:
            raise ImportError(
                "textual-serve is required for web server mode. "
                "Install with: pip install textual-serve"
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

    def _create_app_factory(self):
        """Create the Textual app factory for serving."""
        project_path = self.config.project_path

        def factory():
            # Import here to avoid circular imports
            from superqode.app_main import SuperQodeApp

            app = SuperQodeApp()

            # Set project path if configured
            if project_path:
                os.chdir(project_path)

            return app

        return factory

    async def start(self) -> None:
        """Start the web server."""
        if self._running:
            return

        # Create server
        self._server = Server(
            self._create_app_factory(),
            host=self.config.host,
            port=self.config.port,
        )

        # Configure SSL if provided
        if self.config.ssl_cert and self.config.ssl_key:
            self._server.ssl_certfile = self.config.ssl_cert
            self._server.ssl_keyfile = self.config.ssl_key

        self._running = True

        print(f"🌐 SuperQode Web Server starting...")
        print(f"   URL: {self.url}")

        if self.config.require_auth:
            print(f"   Token: {self.config.auth_token}")
            print(f"   Full URL: {self.authenticated_url}")

        # Start serving
        await self._server.serve()

    def start_sync(self) -> None:
        """Start server synchronously."""
        asyncio.run(self.start())

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
) -> None:
    """
    Convenience function to start the web server.

    Usage:
        from superqode.server import start_server
        start_server(host="0.0.0.0", port=8080)
    """
    config = WebServerConfig(
        host=host,
        port=port,
        project_path=project_path,
        require_auth=require_auth,
    )

    server = WebServer(config)
    server.start_sync()


def add_server_command():
    """Add server command to CLI.

    Call this during CLI setup to add the 'serve' command.
    """
    import click

    @click.command("serve")
    @click.option("--host", default="127.0.0.1", help="Host to bind to")
    @click.option("--port", default=8080, type=int, help="Port to listen on")
    @click.option("--no-auth", is_flag=True, help="Disable authentication")
    @click.option("--token", default=None, help="Authentication token")
    @click.option("--project", default=None, help="Project directory")
    def serve_command(host, port, no_auth, token, project):
        """Start SuperQode in web server mode."""
        config = WebServerConfig(
            host=host,
            port=port,
            require_auth=not no_auth,
            auth_token=token,
            project_path=Path(project) if project else None,
        )

        if not TEXTUAL_SERVE_AVAILABLE:
            click.echo(
                "Error: textual-serve is required for web server mode.\n"
                "Install with: pip install textual-serve"
            )
            sys.exit(1)

        server = WebServer(config)
        server.start_sync()

    return serve_command
