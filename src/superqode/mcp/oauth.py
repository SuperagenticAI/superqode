"""
MCP OAuth Provider - OAuth 2.0 Authentication for MCP Servers.

Implements OAuth 2.0 with PKCE (Proof Key for Code Exchange) for
secure authentication with MCP servers that require it.

Features:
- PKCE flow for public clients
- Dynamic client registration
- Token refresh
- Secure state management
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class OAuthConfig:
    """OAuth configuration for an MCP server."""

    client_id: Optional[str] = None
    client_secret: Optional[str] = None
    scope: str = "mcp"
    redirect_uri: str = "http://localhost:19876/mcp/oauth/callback"
    # PKCE settings
    use_pkce: bool = True
    code_challenge_method: str = "S256"


@dataclass
class OAuthTokens:
    """OAuth tokens from authentication."""

    access_token: str
    refresh_token: Optional[str] = None
    expires_at: Optional[datetime] = None
    token_type: str = "Bearer"
    scope: str = ""

    def is_expired(self) -> bool:
        """Check if the access token is expired."""
        if self.expires_at is None:
            return False
        # Consider expired 5 minutes before actual expiry
        buffer = timedelta(minutes=5)
        return datetime.now() >= (self.expires_at - buffer)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for storage."""
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "token_type": self.token_type,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "OAuthTokens":
        """Create from dictionary."""
        expires_at = None
        if data.get("expires_at"):
            expires_at = datetime.fromisoformat(data["expires_at"])

        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=expires_at,
            token_type=data.get("token_type", "Bearer"),
            scope=data.get("scope", ""),
        )


@dataclass
class OAuthState:
    """State for an OAuth flow in progress."""

    state: str
    code_verifier: str  # For PKCE
    server_url: str
    created_at: datetime = field(default_factory=datetime.now)

    def is_expired(self) -> bool:
        """Check if the state has expired (10 minute timeout)."""
        return datetime.now() > (self.created_at + timedelta(minutes=10))


class MCPOAuthProvider:
    """
    OAuth 2.0 provider for MCP server authentication.

    Implements the OAuth 2.0 Authorization Code flow with PKCE
    for secure authentication with MCP servers.

    Usage:
        provider = MCPOAuthProvider(config)

        # Get authorization URL
        auth_url = await provider.start_auth_flow(server_url, metadata)

        # Open browser for user authentication
        # ... wait for callback ...

        # Exchange code for tokens
        tokens = await provider.handle_callback(code, state)

        # Use tokens
        headers = {"Authorization": f"Bearer {tokens.access_token}"}
    """

    def __init__(self, config: Optional[OAuthConfig] = None):
        self.config = config or OAuthConfig()
        self._pending_flows: Dict[str, OAuthState] = {}
        self._metadata_cache: Dict[str, Dict[str, Any]] = {}

    async def discover_oauth_metadata(self, server_url: str) -> Dict[str, Any]:
        """
        Discover OAuth metadata from server.

        Looks for .well-known/oauth-authorization-server endpoint.
        """
        if server_url in self._metadata_cache:
            return self._metadata_cache[server_url]

        # Try standard OAuth discovery endpoint
        parsed = urllib.parse.urlparse(server_url)
        base_url = f"{parsed.scheme}://{parsed.netloc}"

        metadata_url = f"{base_url}/.well-known/oauth-authorization-server"

        try:
            loop = asyncio.get_event_loop()
            metadata = await loop.run_in_executor(None, lambda: self._fetch_metadata(metadata_url))

            if metadata:
                self._metadata_cache[server_url] = metadata
                return metadata

        except Exception as e:
            logger.debug(f"OAuth discovery failed for {server_url}: {e}")

        # Return empty if discovery fails
        return {}

    def _fetch_metadata(self, url: str) -> Optional[Dict[str, Any]]:
        """Fetch OAuth metadata synchronously."""
        try:
            req = urllib.request.Request(url)
            req.add_header("Accept", "application/json")

            ctx = ssl.create_default_context()

            with urllib.request.urlopen(req, timeout=10, context=ctx) as response:
                return json.loads(response.read().decode("utf-8"))

        except (urllib.error.HTTPError, urllib.error.URLError):
            return None
        except json.JSONDecodeError:
            return None

    def _generate_pkce_pair(self) -> tuple[str, str]:
        """
        Generate PKCE code verifier and challenge.

        Returns (code_verifier, code_challenge).
        """
        # Generate random code verifier (43-128 characters)
        code_verifier = secrets.token_urlsafe(64)

        # Generate code challenge using S256 method
        if self.config.code_challenge_method == "S256":
            digest = hashlib.sha256(code_verifier.encode()).digest()
            code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
        else:
            # Plain method (not recommended)
            code_challenge = code_verifier

        return code_verifier, code_challenge

    async def start_auth_flow(
        self,
        server_url: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> str:
        """
        Start the OAuth authorization flow.

        Returns the authorization URL to open in the browser.
        """
        # Get OAuth metadata if not provided
        if metadata is None:
            metadata = await self.discover_oauth_metadata(server_url)

        # Get authorization endpoint
        auth_endpoint = metadata.get("authorization_endpoint", f"{server_url}/oauth/authorize")

        # Generate state for CSRF protection
        state = secrets.token_urlsafe(32)

        # Generate PKCE pair
        code_verifier, code_challenge = self._generate_pkce_pair()

        # Store state for verification
        self._pending_flows[state] = OAuthState(
            state=state,
            code_verifier=code_verifier,
            server_url=server_url,
        )

        # Build authorization URL
        params = {
            "response_type": "code",
            "client_id": self.config.client_id or "superqode",
            "redirect_uri": self.config.redirect_uri,
            "scope": self.config.scope,
            "state": state,
        }

        # Add PKCE parameters
        if self.config.use_pkce:
            params["code_challenge"] = code_challenge
            params["code_challenge_method"] = self.config.code_challenge_method

        auth_url = f"{auth_endpoint}?{urllib.parse.urlencode(params)}"
        return auth_url

    async def handle_callback(
        self,
        code: str,
        state: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OAuthTokens:
        """
        Handle the OAuth callback and exchange code for tokens.

        Args:
            code: Authorization code from callback
            state: State parameter from callback

        Returns:
            OAuthTokens with access and refresh tokens
        """
        # Verify state
        if state not in self._pending_flows:
            raise ValueError("Invalid or expired state parameter")

        flow_state = self._pending_flows.pop(state)

        if flow_state.is_expired():
            raise ValueError("OAuth flow has expired")

        # Get OAuth metadata if not provided
        if metadata is None:
            metadata = await self.discover_oauth_metadata(flow_state.server_url)

        # Get token endpoint
        token_endpoint = metadata.get("token_endpoint", f"{flow_state.server_url}/oauth/token")

        # Build token request
        token_data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self.config.redirect_uri,
            "client_id": self.config.client_id or "superqode",
        }

        # Add PKCE verifier
        if self.config.use_pkce:
            token_data["code_verifier"] = flow_state.code_verifier

        # Add client secret if available
        if self.config.client_secret:
            token_data["client_secret"] = self.config.client_secret

        # Exchange code for tokens
        loop = asyncio.get_event_loop()
        token_response = await loop.run_in_executor(
            None, lambda: self._request_tokens(token_endpoint, token_data)
        )

        return self._parse_token_response(token_response)

    async def refresh_tokens(
        self,
        refresh_token: str,
        server_url: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> OAuthTokens:
        """
        Refresh expired access token using refresh token.

        Args:
            refresh_token: The refresh token
            server_url: Server URL for token endpoint

        Returns:
            New OAuthTokens with refreshed access token
        """
        if metadata is None:
            metadata = await self.discover_oauth_metadata(server_url)

        token_endpoint = metadata.get("token_endpoint", f"{server_url}/oauth/token")

        token_data = {
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
            "client_id": self.config.client_id or "superqode",
        }

        if self.config.client_secret:
            token_data["client_secret"] = self.config.client_secret

        loop = asyncio.get_event_loop()
        token_response = await loop.run_in_executor(
            None, lambda: self._request_tokens(token_endpoint, token_data)
        )

        return self._parse_token_response(token_response)

    def _request_tokens(self, token_endpoint: str, data: Dict[str, str]) -> Dict[str, Any]:
        """Make token request synchronously."""
        encoded_data = urllib.parse.urlencode(data).encode("utf-8")

        req = urllib.request.Request(
            token_endpoint,
            data=encoded_data,
            method="POST",
        )
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "application/json")

        ctx = ssl.create_default_context()

        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8") if e.fp else ""
            raise ValueError(f"Token request failed: {e.code} - {error_body}")

    def _parse_token_response(self, response: Dict[str, Any]) -> OAuthTokens:
        """Parse token response into OAuthTokens."""
        if "error" in response:
            raise ValueError(f"OAuth error: {response['error']}")

        access_token = response.get("access_token")
        if not access_token:
            raise ValueError("No access token in response")

        # Calculate expiry time
        expires_at = None
        if "expires_in" in response:
            expires_at = datetime.now() + timedelta(seconds=response["expires_in"])

        return OAuthTokens(
            access_token=access_token,
            refresh_token=response.get("refresh_token"),
            expires_at=expires_at,
            token_type=response.get("token_type", "Bearer"),
            scope=response.get("scope", ""),
        )

    def cleanup_expired_flows(self) -> None:
        """Clean up expired OAuth flows."""
        expired = [state for state, flow in self._pending_flows.items() if flow.is_expired()]
        for state in expired:
            del self._pending_flows[state]


async def dynamic_client_registration(
    server_url: str,
    client_name: str = "SuperQode",
    redirect_uris: Optional[list[str]] = None,
) -> Dict[str, Any]:
    """
    Perform dynamic client registration with an OAuth server.

    Some OAuth servers support RFC 7591 dynamic client registration,
    which allows clients to register themselves.

    Returns the registration response including client_id and optionally
    client_secret.
    """
    if redirect_uris is None:
        redirect_uris = ["http://localhost:19876/mcp/oauth/callback"]

    # Try to discover registration endpoint
    provider = MCPOAuthProvider()
    metadata = await provider.discover_oauth_metadata(server_url)

    registration_endpoint = metadata.get("registration_endpoint")
    if not registration_endpoint:
        raise ValueError("Server does not support dynamic client registration")

    registration_data = {
        "client_name": client_name,
        "redirect_uris": redirect_uris,
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",  # Public client
    }

    loop = asyncio.get_event_loop()

    def _register() -> Dict[str, Any]:
        req = urllib.request.Request(
            registration_endpoint,
            data=json.dumps(registration_data).encode("utf-8"),
            method="POST",
        )
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")

        ctx = ssl.create_default_context()

        with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
            return json.loads(response.read().decode("utf-8"))

    return await loop.run_in_executor(None, _register)
