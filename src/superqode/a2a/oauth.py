"""Mint an access token for an A2A Agent Card that requires OAuth or OIDC.

Reuses the MCP PKCE client and a fixed localhost callback. SuperQode does
not hang this off ``:codex login``: that shells out to a vendor CLI. The
card gives us ``openIdConnectUrl`` or authorization/token URLs; we register
with the authorization server when it allows DCR, open a browser, exchange
the code, and send the access token as Bearer.

The redirect URI is always ``http://localhost:19876/a2a/oauth/callback``.
Identity providers must allowlist that exact value. The callback server
does not walk ports.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from superqode.a2a.security import AuthGroup, OAuthNeed, group_satisfied
from superqode.mcp.oauth import MCPOAuthProvider, OAuthConfig, OAuthTokens

CLIENT_ID_ENV = "SUPERQODE_A2A_OAUTH_CLIENT_ID"
CLIENT_SECRET_ENV = "SUPERQODE_A2A_OAUTH_CLIENT_SECRET"
CALLBACK_PORT = 19876
CALLBACK_PATH = "/a2a/oauth/callback"
REDIRECT_URI = f"http://localhost:{CALLBACK_PORT}{CALLBACK_PATH}"
DEVICE_GRANT = "urn:ietf:params:oauth:grant-type:device_code"
STORAGE_DIR = Path.home() / ".superqode" / "a2a-oauth"


class A2AOAuthError(Exception):
    """The card requires OAuth and SuperQode could not complete the flow."""


KEYRING_SERVICE = "superqode-a2a-oauth"


@dataclass
class StoredOAuth:
    """Tokens and the client registration bound to one agent origin."""

    tokens: OAuthTokens | None = None
    client_id: str = ""
    client_secret: str = ""
    revocation_endpoint: str = ""


class A2AOAuthStore:
    """OAuth records in the OS keyring, with owner-only files as fallback.

    Keyring is the same backend MCP uses (macOS Keychain, Windows Credential
    Manager, Secret Service). When it is missing, files under
    ``~/.superqode/a2a-oauth/`` stay at mode 0o600.
    """

    def __init__(
        self,
        storage_dir: Path | None = None,
        *,
        keyring: object | None = None,
        use_keyring: bool | None = None,
    ) -> None:
        self.storage_dir = Path(storage_dir) if storage_dir is not None else STORAGE_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        try:
            self.storage_dir.chmod(0o700)
        except OSError:
            pass
        self._keyring_service = KEYRING_SERVICE
        if keyring is not None:
            self._keyring = keyring
        elif use_keyring is False:
            self._keyring = None
        else:
            self._keyring = _open_keyring()

    def _path(self, origin: str) -> Path:
        digest = hashlib.sha256(origin.encode()).hexdigest()[:16]
        return self.storage_dir / f"{digest}.json"

    def _identity(self, origin: str) -> str:
        return hashlib.sha256(origin.encode()).hexdigest()[:24]

    def load(self, origin: str) -> StoredOAuth:
        if self._keyring is not None:
            try:
                raw = self._keyring.get_password(self._keyring_service, self._identity(origin))
            except Exception:  # noqa: BLE001 - keyring backends fail in odd ways
                raw = None
            if raw:
                parsed = _record_from_payload(raw, origin)
                if parsed.tokens or parsed.client_id:
                    return parsed
        return self._load_file(origin)

    def load_tokens(self, origin: str) -> OAuthTokens | None:
        return self.load(origin).tokens

    def save_tokens(
        self,
        origin: str,
        tokens: OAuthTokens,
        *,
        revocation_endpoint: str | None = None,
    ) -> None:
        record = self.load(origin)
        record.tokens = tokens
        if revocation_endpoint:
            record.revocation_endpoint = revocation_endpoint
        self._write(origin, record)

    def save_client(self, origin: str, client_id: str, client_secret: str = "") -> None:
        record = self.load(origin)
        record.client_id = client_id
        if client_secret:
            record.client_secret = client_secret
        self._write(origin, record)

    def clear(self, origin: str) -> bool:
        removed = False
        if self._keyring is not None:
            identity = self._identity(origin)
            try:
                existing = self._keyring.get_password(self._keyring_service, identity)
            except Exception:  # noqa: BLE001
                existing = None
            if existing:
                try:
                    self._keyring.delete_password(self._keyring_service, identity)
                    removed = True
                except Exception:  # noqa: BLE001
                    pass
        path = self._path(origin)
        if path.exists():
            path.unlink()
            removed = True
        return removed

    def _load_file(self, origin: str) -> StoredOAuth:
        path = self._path(origin)
        try:
            payload = path.read_text(encoding="utf-8")
        except OSError:
            return StoredOAuth()
        return _record_from_payload(payload, origin)

    def _write(self, origin: str, record: StoredOAuth) -> None:
        payload = _record_to_payload(origin, record)
        body = json.dumps(payload, indent=2)
        if self._keyring is not None:
            try:
                self._keyring.set_password(self._keyring_service, self._identity(origin), body)
                path = self._path(origin)
                if path.exists():
                    path.unlink()
                return
            except Exception:  # noqa: BLE001 - fall through to the file store
                pass
        path = self._path(origin)
        descriptor = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(body + "\n")
        try:
            path.chmod(0o600)
        except OSError:
            pass


def _open_keyring() -> object | None:
    from superqode.mcp.auth_storage import _has_keyring

    if not _has_keyring():
        return None
    try:
        import keyring

        return keyring
    except Exception:  # noqa: BLE001
        return None


def _record_from_payload(raw: str | dict, origin: str) -> StoredOAuth:
    del origin
    if isinstance(raw, str):
        try:
            payload = json.loads(raw)
        except ValueError:
            return StoredOAuth()
    else:
        payload = raw
    if not isinstance(payload, dict):
        return StoredOAuth()
    tokens = None
    raw_tokens = payload.get("oauth_tokens")
    if isinstance(raw_tokens, dict) and raw_tokens.get("access_token"):
        tokens = OAuthTokens.from_dict(raw_tokens)
    return StoredOAuth(
        tokens=tokens,
        client_id=str(payload.get("client_id") or ""),
        client_secret=str(payload.get("client_secret") or ""),
        revocation_endpoint=str(payload.get("revocation_endpoint") or ""),
    )


def _record_to_payload(origin: str, record: StoredOAuth) -> dict[str, object]:
    payload: dict[str, object] = {"origin": origin}
    if record.tokens is not None:
        payload["oauth_tokens"] = record.tokens.to_dict()
    if record.client_id:
        payload["client_id"] = record.client_id
    if record.client_secret:
        payload["client_secret"] = record.client_secret
    if record.revocation_endpoint:
        payload["revocation_endpoint"] = record.revocation_endpoint
    return payload


def oauth_storage() -> A2AOAuthStore:
    return A2AOAuthStore()


async def logout_origin(origin: str) -> tuple[bool, bool]:
    """Delete stored tokens and revoke them at the identity provider if it allows.

    Returns ``(cleared, revoked)``. Local deletion still happens when revoke
    fails: logout must not strand the user on a dead refresh token.
    """
    storage = oauth_storage()
    stored = storage.load(origin)
    revoked = False
    if stored.tokens and stored.revocation_endpoint:
        revoked = await _revoke_tokens(stored.revocation_endpoint, stored)
    cleared = storage.clear(origin)
    return cleared, revoked


async def _revoke_tokens(endpoint: str, stored: StoredOAuth) -> bool:
    """RFC 7009. Best-effort: one success is enough to report revoked."""
    if stored.tokens is None:
        return False
    any_ok = False
    for token, hint in (
        (stored.tokens.refresh_token, "refresh_token"),
        (stored.tokens.access_token, "access_token"),
    ):
        if not token:
            continue
        body = {"token": token, "token_type_hint": hint}
        if stored.client_id:
            body["client_id"] = stored.client_id
        if stored.client_secret:
            body["client_secret"] = stored.client_secret
        try:
            await _form_post(endpoint, body)
            any_ok = True
        except A2AOAuthError:
            continue
    return any_ok


async def ensure_access_token(
    origin: str,
    need: OAuthNeed,
    *,
    interactive: bool = True,
    client_id: str | None = None,
    on_status: Callable[[str], None] | None = None,
) -> str:
    """Return a usable access token, refreshing or opening a browser if needed."""
    if not need.required:
        return ""
    storage = oauth_storage()
    stored = storage.load(origin)
    if stored.tokens and not stored.tokens.is_expired():
        _status(on_status, "Using stored OAuth access token")
        return stored.tokens.access_token

    metadata = await discover_oauth_metadata(origin, need)
    need = merge_need(need, metadata)
    client_id, client_secret = _resolve_client(origin, stored, client_id)

    if stored.tokens and stored.tokens.refresh_token:
        try:
            provider, metadata = await _provider(
                origin,
                need,
                client_id,
                client_secret=client_secret,
                metadata=metadata,
            )
            refreshed = await provider.refresh_tokens(
                stored.tokens.refresh_token, origin, metadata=metadata
            )
            _persist_grant(storage, origin, refreshed, metadata)
            _status(on_status, "Refreshed OAuth access token")
            return refreshed.access_token
        except Exception:  # noqa: BLE001 - fall through to a fresh grant
            pass

    can_client_credentials = bool(client_id and client_secret and _token_endpoint(need, metadata))
    prefer_user_login = bool(interactive and _authorization_endpoint(need, metadata))
    if can_client_credentials and not prefer_user_login:
        try:
            tokens = await _client_credentials(
                need, metadata, client_id=client_id, client_secret=client_secret
            )
            _persist_grant(storage, origin, tokens, metadata)
            _status(on_status, "Obtained OAuth access token with client credentials")
            return tokens.access_token
        except Exception:  # noqa: BLE001 - not every AS allows this grant
            if not interactive:
                raise A2AOAuthError(
                    "Client credentials grant failed. Pass --token, or run without "
                    "--json so SuperQode can open a browser."
                ) from None

    if not interactive:
        raise A2AOAuthError(
            f"Card requires {need.scheme}. Pass --token, set "
            f"{CLIENT_ID_ENV} and {CLIENT_SECRET_ENV} for client credentials, "
            "or run without --json so SuperQode can open a browser."
        )

    if not _authorization_endpoint(need, metadata) and not _device_endpoint(need, metadata):
        raise A2AOAuthError(
            f"Card requires {need.scheme} but neither the card nor "
            f"{origin} advertised authorization, token, or device endpoints. "
            "Pass --token after minting one yourself."
        )

    prefer_device = (not _has_local_browser()) and bool(_device_endpoint(need, metadata))
    if prefer_device:
        tokens = await _device_code_flow(
            origin,
            need,
            metadata,
            client_id=client_id,
            client_secret=client_secret,
            on_status=on_status,
        )
        _persist_grant(storage, origin, tokens, metadata)
        return tokens.access_token

    if _authorization_endpoint(need, metadata):
        if not _has_local_browser() and not _device_endpoint(need, metadata):
            raise A2AOAuthError(
                "OAuth authorization-code needs a browser that can return to "
                f"{REDIRECT_URI}. That cannot complete over SSH. Pass --token, "
                "use client credentials, or an identity provider that advertises "
                "device_authorization_endpoint."
            )
        tokens = await _browser_flow(
            origin,
            need,
            metadata=metadata,
            client_id=client_id,
            client_secret=client_secret,
            on_status=on_status,
        )
        _persist_grant(storage, origin, tokens, metadata)
        return tokens.access_token

    tokens = await _device_code_flow(
        origin,
        need,
        metadata,
        client_id=client_id,
        client_secret=client_secret,
        on_status=on_status,
    )
    _persist_grant(storage, origin, tokens, metadata)
    return tokens.access_token


def _persist_grant(
    storage: A2AOAuthStore, origin: str, tokens: OAuthTokens, metadata: dict
) -> None:
    storage.save_tokens(
        origin,
        tokens,
        revocation_endpoint=str(metadata.get("revocation_endpoint") or ""),
    )


async def discover_oauth_metadata(origin: str, need: OAuthNeed) -> dict:
    """OIDC document, then RFC 9728/8414 on the agent origin."""
    provider = MCPOAuthProvider(OAuthConfig(redirect_uri=REDIRECT_URI))
    metadata: dict = {}
    if need.openid_url:
        fetched = provider._fetch_metadata(need.openid_url)
        if fetched:
            metadata.update(fetched)
    if need.authorization_url and need.token_url:
        metadata.setdefault("authorization_endpoint", need.authorization_url)
        metadata.setdefault("token_endpoint", need.token_url)
    if need.client_credentials_token_url:
        metadata.setdefault("token_endpoint", need.client_credentials_token_url)
    if need.device_authorization_url:
        metadata.setdefault("device_authorization_endpoint", need.device_authorization_url)
    if "authorization_endpoint" not in metadata or "token_endpoint" not in metadata:
        discovered = await provider.discover_oauth_metadata(origin)
        for key, value in discovered.items():
            metadata.setdefault(key, value)
    if need.openid_url and "registration_endpoint" not in metadata:
        # OIDC discovery is the authorization server; DCR lives there, not
        # on the A2A agent origin.
        pass
    return metadata


def merge_need(need: OAuthNeed, metadata: dict) -> OAuthNeed:
    """Copy discovered endpoints onto the card's OAuth need."""
    return OAuthNeed(
        scheme=need.scheme,
        openid_url=need.openid_url,
        authorization_url=need.authorization_url
        or str(metadata.get("authorization_endpoint") or "")
        or None,
        token_url=need.token_url or str(metadata.get("token_endpoint") or "") or None,
        device_authorization_url=need.device_authorization_url
        or str(metadata.get("device_authorization_endpoint") or "")
        or None,
        client_credentials_token_url=need.client_credentials_token_url,
        scopes=need.scopes,
        required=need.required,
    )


async def _browser_flow(
    origin: str,
    need: OAuthNeed,
    *,
    metadata: dict,
    client_id: str | None,
    client_secret: str,
    on_status: Callable[[str], None] | None,
) -> OAuthTokens:
    from superqode.mcp.oauth_callback import OAuthCallbackServer

    client_id, client_secret = await _ensure_client(
        origin, metadata, client_id, client_secret, on_status=on_status
    )
    callback = OAuthCallbackServer(port=CALLBACK_PORT, callback_path=CALLBACK_PATH)
    try:
        await callback.start(strict_port=True)
    except OSError as exc:
        raise A2AOAuthError(
            f"Cannot bind {REDIRECT_URI}. Port {CALLBACK_PORT} is already in use. "
            "Identity providers allowlist that exact URI; SuperQode will not "
            "pick another port. Free the port and retry."
        ) from exc
    redirect_uri = callback.get_redirect_uri()
    if redirect_uri != REDIRECT_URI:
        await callback.stop()
        raise A2AOAuthError(f"OAuth callback bound {redirect_uri}, expected {REDIRECT_URI}.")

    provider, metadata = await _provider(
        origin, need, client_id, client_secret=client_secret, metadata=metadata
    )
    auth_url = await provider.start_auth_flow(origin, metadata=metadata)
    _status(on_status, f"Open this URL to authorize:\n{auth_url}")
    try:
        webbrowser.open(auth_url)
    except Exception:  # noqa: BLE001 - the printed URL is the fallback
        _status(on_status, "Could not open a browser; paste the URL above.")
    parsed = urllib.parse.urlparse(auth_url)
    state = urllib.parse.parse_qs(parsed.query).get("state", [None])[0]
    if not state:
        await callback.stop()
        raise A2AOAuthError("OAuth authorization URL was missing state")
    result = await callback.wait_for_callback(state, timeout=300)
    await callback.stop()
    if result.error:
        raise A2AOAuthError(result.error_description or result.error or "OAuth callback failed")
    if not result.code:
        raise A2AOAuthError("OAuth callback returned no code")
    return await provider.handle_callback(result.code, state, metadata=metadata)


async def _device_code_flow(
    origin: str,
    need: OAuthNeed,
    metadata: dict,
    *,
    client_id: str | None,
    client_secret: str,
    on_status: Callable[[str], None] | None,
) -> OAuthTokens:
    client_id, client_secret = await _ensure_client(
        origin, metadata, client_id, client_secret, on_status=on_status
    )
    if not client_id:
        raise A2AOAuthError(_missing_client_message(need.scheme))
    device_url = _device_endpoint(need, metadata)
    token_url = _token_endpoint(need, metadata)
    if not device_url or not token_url:
        raise A2AOAuthError(
            f"Card requires {need.scheme} device code but the authorization "
            "server did not advertise device_authorization_endpoint and token_endpoint."
        )
    body = {"client_id": client_id, "scope": " ".join(need.scopes) if need.scopes else "openid"}
    if client_secret:
        body["client_secret"] = client_secret
    started = await _form_post(device_url, body)
    device_code = str(started.get("device_code") or "")
    user_code = str(started.get("user_code") or "")
    verify = str(started.get("verification_uri_complete") or started.get("verification_uri") or "")
    interval = int(started.get("interval") or 5)
    expires_in = int(started.get("expires_in") or 600)
    if not device_code or not verify:
        raise A2AOAuthError("Device authorization did not return a device_code and URI")
    _status(
        on_status,
        f"Visit {verify} and enter code {user_code}" if user_code else f"Visit {verify}",
    )
    deadline = asyncio.get_event_loop().time() + expires_in
    token_body = {
        "grant_type": DEVICE_GRANT,
        "device_code": device_code,
        "client_id": client_id,
    }
    if client_secret:
        token_body["client_secret"] = client_secret
    while asyncio.get_event_loop().time() < deadline:
        await asyncio.sleep(max(interval, 1))
        try:
            response = await _form_post(token_url, token_body)
        except A2AOAuthError as exc:
            text = str(exc)
            if "authorization_pending" in text:
                continue
            if "slow_down" in text:
                interval += 5
                continue
            raise
        if response.get("error") == "authorization_pending":
            continue
        if response.get("error") == "slow_down":
            interval += 5
            continue
        if response.get("error"):
            raise A2AOAuthError(str(response.get("error_description") or response["error"]))
        return _tokens_from_response(response)
    raise A2AOAuthError("Device code expired before authorization completed")


async def _client_credentials(
    need: OAuthNeed,
    metadata: dict,
    *,
    client_id: str,
    client_secret: str,
) -> OAuthTokens:
    token_url = _token_endpoint(need, metadata)
    if not token_url:
        raise A2AOAuthError("No token endpoint for client credentials")
    body = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": " ".join(need.scopes) if need.scopes else "openid",
    }
    response = await _form_post(token_url, body)
    if response.get("error"):
        raise A2AOAuthError(str(response.get("error_description") or response["error"]))
    return _tokens_from_response(response)


async def _ensure_client(
    origin: str,
    metadata: dict,
    client_id: str | None,
    client_secret: str,
    *,
    on_status: Callable[[str], None] | None,
) -> tuple[str, str]:
    resolved_id, resolved_secret = _resolve_client(origin, oauth_storage().load(origin), client_id)
    if resolved_secret:
        client_secret = resolved_secret
    if resolved_id:
        return resolved_id, client_secret
    registration_endpoint = str(metadata.get("registration_endpoint") or "")
    if not registration_endpoint:
        raise A2AOAuthError(_missing_client_message("OAuth"))
    _status(on_status, f"Registering OAuth client at {registration_endpoint}")
    try:
        registration = await register_oauth_client(registration_endpoint)
    except Exception as exc:  # noqa: BLE001 - surface as a client-id problem
        raise A2AOAuthError(
            f"Dynamic client registration failed at {registration_endpoint}: {exc}. "
            + _missing_client_message("OAuth")
        ) from exc
    resolved_id = str(registration.get("client_id") or "")
    resolved_secret = str(registration.get("client_secret") or client_secret)
    if not resolved_id:
        raise A2AOAuthError(
            "Dynamic client registration returned no client_id. " + _missing_client_message("OAuth")
        )
    oauth_storage().save_client(origin, resolved_id, resolved_secret)
    return resolved_id, resolved_secret


async def register_oauth_client(registration_endpoint: str) -> dict:
    """RFC 7591 POST against the authorization server, not the A2A origin."""
    payload = {
        "client_name": "SuperQode A2A",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": [
            "authorization_code",
            "refresh_token",
            "client_credentials",
            DEVICE_GRANT,
        ],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "application_type": "native",
    }
    return await _json_post(registration_endpoint, payload)


def _resolve_client(
    origin: str,
    stored: StoredOAuth,
    client_id: str | None,
) -> tuple[str, str]:
    del origin
    resolved_id = (
        (client_id or "").strip()
        or stored.client_id.strip()
        or (os.environ.get(CLIENT_ID_ENV) or "").strip()
    )
    resolved_secret = (
        stored.client_secret.strip() or (os.environ.get(CLIENT_SECRET_ENV) or "").strip()
    )
    return resolved_id, resolved_secret


def _missing_client_message(scheme: str) -> str:
    return (
        f"Card requires {scheme}. Set {CLIENT_ID_ENV} to a public client registered "
        f"with redirect URI {REDIRECT_URI}, or use an authorization server that "
        f"advertises registration_endpoint. Optional {CLIENT_SECRET_ENV} for a "
        "confidential client."
    )


async def _provider(
    origin: str,
    need: OAuthNeed,
    client_id: str | None,
    *,
    client_secret: str = "",
    metadata: dict | None = None,
) -> tuple[MCPOAuthProvider, dict]:
    config = OAuthConfig(
        client_id=client_id,
        client_secret=client_secret or None,
        scope=" ".join(need.scopes) if need.scopes else "openid",
        redirect_uri=REDIRECT_URI,
    )
    provider = MCPOAuthProvider(config)
    resolved = dict(metadata or {})
    if not resolved:
        resolved = await discover_oauth_metadata(origin, need)
    return provider, resolved


async def satisfy_card_auth(
    client,
    origin: str,
    *,
    token: str,
    headers: dict[str, str],
    interactive: bool,
    skip_oauth: bool = False,
    prompt_secret: Callable[[str], str] | None = None,
    on_status: Callable[[str], None] | None = None,
) -> None:
    """Attach API-key headers/query and, if needed, an OAuth access token."""
    from superqode.a2a.client import A2AClientError
    from superqode.a2a.security import (
        bind_api_key,
        has_http_bearer,
        requirement_groups,
    )

    card = getattr(client, "_card_data", None) or {}
    bearer, extra, extra_query, notes = bind_api_key(card, token=token, headers=headers)
    for note in notes:
        client.inspect.auth(note)
    if extra:
        client._http.headers.update(extra)
    if extra_query:
        client.add_query_params(extra_query)
    if bearer:
        client._http.headers["Authorization"] = f"Bearer {bearer}"
    elif token and not has_http_bearer(card):
        client._http.headers.pop("Authorization", None)

    groups = requirement_groups(card)
    if not groups or any(group.anonymous for group in groups):
        return
    current_headers = {str(k): str(v) for k, v in client._http.headers.items()}
    current_query = dict(getattr(client, "_query_params", {}) or {})
    has_tls = bool(getattr(client, "_tls_cert", "") or "")
    if any(
        group_satisfied(group, current_headers, current_query, has_tls=has_tls) for group in groups
    ):
        return

    last_error: Exception | None = None
    for group in groups:
        try:
            await _complete_group(
                client,
                origin,
                group,
                interactive=interactive,
                skip_oauth=skip_oauth,
                prompt_secret=prompt_secret,
                on_status=on_status,
            )
        except A2AClientError as exc:
            last_error = exc
            continue
        current_headers = {str(k): str(v) for k, v in client._http.headers.items()}
        current_query = dict(getattr(client, "_query_params", {}) or {})
        has_tls = bool(getattr(client, "_tls_cert", "") or "")
        if group_satisfied(group, current_headers, current_query, has_tls=has_tls):
            return
    if last_error is not None:
        raise last_error
    names = ", ".join(name for group in groups for name in group.names) or "auth"
    raise A2AClientError(
        f"Card requires {names}. Pass --token, --header, or complete OAuth.",
        inspect=client.inspect,
    )


async def _complete_group(
    client,
    origin: str,
    group: AuthGroup,
    *,
    interactive: bool,
    skip_oauth: bool,
    prompt_secret: Callable[[str], str] | None,
    on_status: Callable[[str], None] | None,
) -> None:
    from superqode.a2a.client import A2AClientError

    for need in group.api_keys:
        headers = {str(k): str(v) for k, v in client._http.headers.items()}
        query = dict(getattr(client, "_query_params", {}) or {})
        if need.header and need.header.lower() not in {key.lower() for key in headers}:
            value = ""
            if prompt_secret and interactive:
                value = prompt_secret(need.header)
            if value:
                client._http.headers[need.header] = value.strip()
                client.inspect.auth(f"API key supplied for header {need.header}")
            else:
                raise A2AClientError(
                    f"Card requires API key in header {need.header}. "
                    f"Pass --header {need.header}:<value> or paste it in the token field.",
                    inspect=client.inspect,
                )
        if need.query and need.query.lower() not in {key.lower() for key in query}:
            value = ""
            if prompt_secret and interactive:
                value = prompt_secret(need.query)
            if value:
                client.add_query_params({need.query: value.strip()})
                client.inspect.auth(f"API key supplied for query {need.query}")
            else:
                raise A2AClientError(
                    f"Card requires API key in query {need.query}. "
                    "Pass --token <value>; SuperQode appends it to request URLs.",
                    inspect=client.inspect,
                )

    if group.http_basic:
        authorization = str(client._http.headers.get("Authorization") or "")
        if not authorization.lower().startswith("basic "):
            raise A2AClientError(
                "Card requires HTTP Basic. Pass --token as user:password.",
                inspect=client.inspect,
            )

    if group.http_bearer and not str(client._http.headers.get("Authorization") or ""):
        raise A2AClientError(
            "Card requires HTTP Bearer. Pass --token.",
            inspect=client.inspect,
        )

    if group.mutual_tls and not getattr(client, "_tls_cert", ""):
        raise A2AClientError(
            "Card requires mutual TLS. Pass --tls-cert and --tls-key.",
            inspect=client.inspect,
        )

    if not group.oauth:
        return
    if str(client._http.headers.get("Authorization") or "").lower().startswith("bearer "):
        return
    oauth_need = _preferred_oauth(group.oauth)
    try:
        access = await ensure_access_token(
            origin,
            oauth_need,
            interactive=interactive and not skip_oauth,
            on_status=on_status,
        )
    except A2AOAuthError as exc:
        raise A2AClientError(str(exc), inspect=client.inspect) from exc
    if access:
        client._http.headers["Authorization"] = f"Bearer {access}"
        client.inspect.auth(f"OAuth access token obtained ({oauth_need.scheme})")


def _preferred_oauth(needs: tuple[OAuthNeed, ...]) -> OAuthNeed:
    for need in needs:
        if need.openid_url:
            return need
    for need in needs:
        if need.runnable:
            return need
    return needs[0]


def _authorization_endpoint(need: OAuthNeed, metadata: dict) -> str:
    return need.authorization_url or str(metadata.get("authorization_endpoint") or "")


def _token_endpoint(need: OAuthNeed, metadata: dict) -> str:
    return (
        need.token_url
        or need.client_credentials_token_url
        or str(metadata.get("token_endpoint") or "")
    )


def _device_endpoint(need: OAuthNeed, metadata: dict) -> str:
    return need.device_authorization_url or str(metadata.get("device_authorization_endpoint") or "")


def _has_local_browser() -> bool:
    if sys.platform in {"darwin", "win32"}:
        return True
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def _tokens_from_response(response: dict) -> OAuthTokens:
    from datetime import datetime, timedelta

    access = str(response.get("access_token") or "")
    if not access:
        raise A2AOAuthError("Token response had no access_token")
    expires_at = None
    if response.get("expires_in") is not None:
        expires_at = datetime.now() + timedelta(seconds=int(response["expires_in"]))
    return OAuthTokens(
        access_token=access,
        refresh_token=response.get("refresh_token"),
        expires_at=expires_at,
        token_type=str(response.get("token_type") or "Bearer"),
        scope=str(response.get("scope") or ""),
    )


async def _form_post(url: str, data: dict[str, str]) -> dict:
    encoded = urllib.parse.urlencode(data).encode("utf-8")

    def _send() -> dict:
        req = urllib.request.Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
        req.add_header("Accept", "application/json")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else ""
            raise A2AOAuthError(f"Token request failed: {exc.code} - {body}") from exc

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send)


async def _json_post(url: str, data: dict) -> dict:
    encoded = json.dumps(data).encode("utf-8")

    def _send() -> dict:
        req = urllib.request.Request(url, data=encoded, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json")
        ctx = ssl.create_default_context()
        try:
            with urllib.request.urlopen(req, timeout=30, context=ctx) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8") if exc.fp else ""
            raise A2AOAuthError(f"Registration failed: {exc.code} - {body}") from exc

    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _send)


def _status(on_status: Callable[[str], None] | None, message: str) -> None:
    if on_status:
        on_status(message)
