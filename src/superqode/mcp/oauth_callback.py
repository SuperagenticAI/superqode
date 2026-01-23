"""
MCP OAuth Callback Server - Local HTTP Server for OAuth Redirects.

Implements a lightweight HTTP server to handle OAuth callbacks
during the authorization flow.

Features:
- Single-use callback handling
- Timeout support
- Success/error page display
- Thread-safe operation
"""

from __future__ import annotations

import asyncio
import logging
import urllib.parse
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from typing import Dict, Optional
import threading

logger = logging.getLogger(__name__)


# HTML templates for callback responses
SUCCESS_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Authorization Successful</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        }
        .container {
            text-align: center;
            padding: 40px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            max-width: 400px;
        }
        .icon {
            font-size: 64px;
            margin-bottom: 20px;
        }
        h1 {
            color: #22c55e;
            margin: 0 0 10px 0;
            font-size: 24px;
        }
        p {
            color: #666;
            margin: 0;
            font-size: 14px;
        }
        .close-msg {
            margin-top: 20px;
            color: #999;
            font-size: 12px;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✓</div>
        <h1>Authorization Successful</h1>
        <p>You have been authenticated with the MCP server.</p>
        <p class="close-msg">You can close this window and return to SuperQode.</p>
    </div>
    <script>
        // Try to close the window after a delay
        setTimeout(function() {
            window.close();
        }, 3000);
    </script>
</body>
</html>"""

ERROR_HTML = """<!DOCTYPE html>
<html>
<head>
    <title>Authorization Failed</title>
    <style>
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            display: flex;
            justify-content: center;
            align-items: center;
            height: 100vh;
            margin: 0;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
        }
        .container {
            text-align: center;
            padding: 40px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.15);
            max-width: 400px;
        }
        .icon {
            font-size: 64px;
            margin-bottom: 20px;
        }
        h1 {
            color: #ef4444;
            margin: 0 0 10px 0;
            font-size: 24px;
        }
        p {
            color: #666;
            margin: 0;
            font-size: 14px;
        }
        .error-detail {
            margin-top: 15px;
            padding: 10px;
            background: #fef2f2;
            border-radius: 6px;
            color: #b91c1c;
            font-size: 12px;
            font-family: monospace;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="icon">✕</div>
        <h1>Authorization Failed</h1>
        <p>There was a problem authenticating with the MCP server.</p>
        <div class="error-detail">{error}</div>
    </div>
</body>
</html>"""


@dataclass
class CallbackResult:
    """Result from an OAuth callback."""

    code: Optional[str] = None
    state: Optional[str] = None
    error: Optional[str] = None
    error_description: Optional[str] = None


class OAuthCallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler for OAuth callbacks."""

    # Class-level storage for callback results
    callback_results: Dict[str, asyncio.Future] = {}
    server_lock = threading.Lock()

    def log_message(self, format: str, *args) -> None:
        """Suppress default logging."""
        logger.debug(format % args)

    def do_GET(self) -> None:
        """Handle GET request (OAuth callback)."""
        # Parse the URL
        parsed = urllib.parse.urlparse(self.path)

        # Only handle the callback path
        if parsed.path != "/mcp/oauth/callback":
            self.send_error(404, "Not Found")
            return

        # Parse query parameters
        params = urllib.parse.parse_qs(parsed.query)

        # Extract OAuth parameters
        code = params.get("code", [None])[0]
        state = params.get("state", [None])[0]
        error = params.get("error", [None])[0]
        error_description = params.get("error_description", [None])[0]

        # Create result
        result = CallbackResult(
            code=code,
            state=state,
            error=error,
            error_description=error_description,
        )

        # Store result and notify waiting future
        with self.server_lock:
            if state and state in self.callback_results:
                future = self.callback_results[state]
                if not future.done():
                    # Use call_soon_threadsafe to set result from HTTP thread
                    try:
                        loop = future.get_loop()
                        loop.call_soon_threadsafe(future.set_result, result)
                    except Exception as e:
                        logger.error(f"Error setting callback result: {e}")

        # Send response
        if error:
            self._send_error_page(error, error_description)
        else:
            self._send_success_page()

    def _send_success_page(self) -> None:
        """Send success HTML page."""
        content = SUCCESS_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_error_page(self, error: str, description: Optional[str]) -> None:
        """Send error HTML page."""
        error_msg = error
        if description:
            error_msg = f"{error}: {description}"

        content = ERROR_HTML.format(error=error_msg).encode("utf-8")
        self.send_response(400)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)


class OAuthCallbackServer:
    """
    Local HTTP server for OAuth callbacks.

    Runs a lightweight HTTP server on localhost to receive OAuth
    authorization callbacks.

    Usage:
        server = OAuthCallbackServer()
        await server.start()

        # Start OAuth flow with state parameter
        state = "random_state_value"

        # Wait for callback
        result = await server.wait_for_callback(state, timeout=300)

        # result.code contains the authorization code

        await server.stop()
    """

    DEFAULT_PORT = 19876

    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self._server: Optional[HTTPServer] = None
        self._server_thread: Optional[threading.Thread] = None
        self._running = False

    async def start(self) -> None:
        """Start the callback server."""
        if self._running:
            return

        # Create HTTP server
        try:
            self._server = HTTPServer(
                ("localhost", self.port),
                OAuthCallbackHandler,
            )
            self._server.timeout = 1  # Allow periodic checks

            # Start server in background thread
            self._running = True
            self._server_thread = threading.Thread(
                target=self._serve_forever,
                daemon=True,
            )
            self._server_thread.start()

            logger.info(f"OAuth callback server started on port {self.port}")

        except OSError as e:
            if "Address already in use" in str(e):
                # Port in use, try next port
                self.port += 1
                await self.start()
            else:
                raise

    def _serve_forever(self) -> None:
        """Server loop running in background thread."""
        while self._running:
            self._server.handle_request()

    async def stop(self) -> None:
        """Stop the callback server."""
        self._running = False

        if self._server:
            self._server.shutdown()
            self._server = None

        if self._server_thread:
            self._server_thread.join(timeout=5)
            self._server_thread = None

        logger.info("OAuth callback server stopped")

    async def wait_for_callback(
        self,
        state: str,
        timeout: float = 300,
    ) -> CallbackResult:
        """
        Wait for an OAuth callback with the given state.

        Args:
            state: The state parameter to wait for
            timeout: Maximum time to wait in seconds

        Returns:
            CallbackResult with the authorization code or error
        """
        if not self._running:
            await self.start()

        # Create future for this state
        loop = asyncio.get_event_loop()
        future: asyncio.Future[CallbackResult] = loop.create_future()

        with OAuthCallbackHandler.server_lock:
            OAuthCallbackHandler.callback_results[state] = future

        try:
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            return CallbackResult(
                error="timeout",
                error_description="OAuth callback timed out",
            )
        finally:
            # Clean up
            with OAuthCallbackHandler.server_lock:
                OAuthCallbackHandler.callback_results.pop(state, None)

    def get_redirect_uri(self) -> str:
        """Get the redirect URI for this server."""
        return f"http://localhost:{self.port}/mcp/oauth/callback"

    @property
    def is_running(self) -> bool:
        """Check if the server is running."""
        return self._running


# Global server instance for shared use
_global_server: Optional[OAuthCallbackServer] = None


async def get_callback_server() -> OAuthCallbackServer:
    """Get or create the global callback server."""
    global _global_server

    if _global_server is None:
        _global_server = OAuthCallbackServer()

    if not _global_server.is_running:
        await _global_server.start()

    return _global_server


async def shutdown_callback_server() -> None:
    """Shutdown the global callback server."""
    global _global_server

    if _global_server is not None:
        await _global_server.stop()
        _global_server = None
