"""
SuperQode Servers.

- Web Server: Run SuperQode TUI in a web browser using textual-serve
"""

from .web import (
    WebServer,
    WebServerConfig,
    start_server,
)

__all__ = [
    # Web server
    "WebServer",
    "WebServerConfig",
    "start_server",
]
