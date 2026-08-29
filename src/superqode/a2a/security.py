"""Read Agent Card security schemes into something SuperQode can act on.

A2A lists five scheme types. HTTP Bearer is already ``--token``. API keys are
a named header or query parameter. OAuth2 and OIDC need a token mint. HTTP
Basic is ``user:pass`` in the token field. This module names the requirement
so the CLI can prompt and inspect can explain.

``securityRequirements`` (or OpenAPI ``security``) is a list of OR-options.
Each option is an AND of named schemes. An empty option means anonymous is
allowed.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass


@dataclass(frozen=True)
class ApiKeyNeed:
    """An API key the card wants in a header or query string."""

    scheme: str
    header: str | None = None
    query: str | None = None
    required: bool = False


@dataclass(frozen=True)
class OAuthNeed:
    """An OAuth2 or OIDC scheme the card wants, if it gives us endpoints."""

    scheme: str
    openid_url: str | None = None
    authorization_url: str | None = None
    token_url: str | None = None
    device_authorization_url: str | None = None
    client_credentials_token_url: str | None = None
    scopes: tuple[str, ...] = ()
    required: bool = False

    @property
    def runnable(self) -> bool:
        return bool(
            self.openid_url
            or (self.authorization_url and self.token_url)
            or self.client_credentials_token_url
            or self.device_authorization_url
        )


@dataclass(frozen=True)
class AuthGroup:
    """One OR-option from ``securityRequirements``. Members are AND."""

    names: tuple[str, ...]
    api_keys: tuple[ApiKeyNeed, ...] = ()
    oauth: tuple[OAuthNeed, ...] = ()
    http_bearer: bool = False
    http_basic: bool = False
    mutual_tls: bool = False

    @property
    def anonymous(self) -> bool:
        return not self.names


def describe_auth(card: dict) -> str:
    """Human line for inspect: schemes, API-key header, required or not."""
    schemes = card.get("securitySchemes")
    names: list[str] = []
    if isinstance(schemes, dict):
        names = [str(key) for key in schemes if str(key).strip()]
    groups = requirement_groups(card)
    required = bool(groups) and not any(group.anonymous for group in groups)
    keys = api_key_needs(card)
    header_hint = ""
    for need in keys:
        if need.header:
            header_hint = f"; pass --header {need.header}:<value>"
            break
        if need.query:
            header_hint = f"; pass --token as query {need.query}"
            break
    if has_http_basic(card) and not header_hint:
        header_hint = "; pass --token as user:password for HTTP Basic"
    if has_mutual_tls(card) and "--tls-cert" not in header_hint:
        header_hint += "; pass --tls-cert and --tls-key"
    if not names:
        return "Auth: none advertised"
    listed = ", ".join(names)
    if required:
        return f"Auth: {listed} required{header_hint}"
    return f"Auth: {listed} advertised, not required{header_hint}"


def api_key_needs(card: dict) -> list[ApiKeyNeed]:
    required_names = _required_scheme_names(card)
    needs: list[ApiKeyNeed] = []
    for name, body in _iter_schemes(card):
        parsed = _parse_api_key(name, body, required=name in required_names)
        if parsed is not None:
            needs.append(parsed)
    return needs


def oauth_needs(card: dict) -> list[OAuthNeed]:
    required_names = _required_scheme_names(card)
    needs: list[OAuthNeed] = []
    for name, body in _iter_schemes(card):
        parsed = _parse_oauth(name, body, required=name in required_names)
        if parsed is not None:
            needs.append(parsed)
    return needs


def requirement_groups(card: dict) -> list[AuthGroup]:
    """OR-list of AND-groups. Empty list means the card requires nothing."""
    raw = card.get("securityRequirements") or card.get("security") or []
    if not isinstance(raw, list) or not raw:
        return []
    by_name = {name: body for name, body in _iter_schemes(card)}
    groups: list[AuthGroup] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        mapping = item.get("schemes") if isinstance(item.get("schemes"), dict) else item
        if not isinstance(mapping, dict):
            continue
        names = tuple(
            str(key) for key in mapping if str(key).strip() and str(key) not in {"schemes"}
        )
        api_keys: list[ApiKeyNeed] = []
        oauth: list[OAuthNeed] = []
        http_bearer = False
        http_basic = False
        mutual_tls = False
        for name in names:
            body = by_name.get(name, {})
            key = _parse_api_key(name, body, required=True)
            if key is not None:
                api_keys.append(key)
            parsed_oauth = _parse_oauth(name, body, required=True)
            if parsed_oauth is not None:
                scopes = mapping.get(name)
                if isinstance(scopes, list) and scopes:
                    parsed_oauth = OAuthNeed(
                        scheme=parsed_oauth.scheme,
                        openid_url=parsed_oauth.openid_url,
                        authorization_url=parsed_oauth.authorization_url,
                        token_url=parsed_oauth.token_url,
                        device_authorization_url=parsed_oauth.device_authorization_url,
                        client_credentials_token_url=parsed_oauth.client_credentials_token_url,
                        scopes=tuple(str(item) for item in scopes if str(item).strip())
                        or parsed_oauth.scopes,
                        required=True,
                    )
                oauth.append(parsed_oauth)
            if _is_http_bearer(body):
                http_bearer = True
            if _is_http_basic(body):
                http_basic = True
            if _is_mutual_tls(body):
                mutual_tls = True
        groups.append(
            AuthGroup(
                names=names,
                api_keys=tuple(api_keys),
                oauth=tuple(oauth),
                http_bearer=http_bearer,
                http_basic=http_basic,
                mutual_tls=mutual_tls,
            )
        )
    return groups


def has_http_bearer(card: dict) -> bool:
    for _name, body in _iter_schemes(card):
        if _is_http_bearer(body):
            return True
    return False


def has_http_basic(card: dict) -> bool:
    for _name, body in _iter_schemes(card):
        if _is_http_basic(body):
            return True
    return False


def has_mutual_tls(card: dict) -> bool:
    for _name, body in _iter_schemes(card):
        if _is_mutual_tls(body):
            return True
    return False


def missing_api_key_header(card: dict, headers: dict[str, str]) -> str | None:
    """Return the header name a required API-key scheme wants, if it is absent."""
    have = {key.lower() for key in headers}
    for need in api_key_needs(card):
        if not need.required or not need.header:
            continue
        if need.header.lower() not in have:
            return need.header
    return None


def missing_api_key(
    card: dict,
    headers: dict[str, str],
    query: dict[str, str] | None = None,
) -> ApiKeyNeed | None:
    """Return the first required API-key header or query that is absent."""
    have_headers = {key.lower() for key in headers}
    have_query = {key.lower() for key in (query or {})}
    for need in api_key_needs(card):
        if not need.required:
            continue
        if need.header and need.header.lower() not in have_headers:
            return need
        if need.query and need.query.lower() not in have_query:
            return need
    return None


def bind_api_key(
    card: dict,
    *,
    token: str,
    headers: dict[str, str],
) -> tuple[str, dict[str, str], dict[str, str], list[str]]:
    """Map a typed credential onto Bearer, extra headers, and query params.

    When the card only asks for an API key, the token field is that key, not
    an Authorization Bearer. When the card only asks for HTTP Basic, the token
    field is ``user:password``. When the card asks for Bearer as well, the
    token stays Bearer and the API key must already be in ``headers``.
    """
    notes: list[str] = []
    extra = dict(headers)
    extra_query: dict[str, str] = {}
    keys = api_key_needs(card)
    bearer = token
    only_basic = has_http_basic(card) and not has_http_bearer(card) and not keys
    if only_basic and token:
        extra["Authorization"] = _basic_header(token)
        bearer = ""
        notes.append("Using token as HTTP Basic")
        return bearer, extra, extra_query, notes
    only_api_key = bool(keys) and not has_http_bearer(card)
    if only_api_key and token:
        need = keys[0]
        if need.header:
            extra.setdefault(need.header, token)
            bearer = ""
            notes.append(f"Using token as API key header {need.header}")
        elif need.query:
            extra_query.setdefault(need.query, token)
            bearer = ""
            notes.append(f"Using token as API key query {need.query}")
    return bearer, extra, extra_query, notes


def group_satisfied(
    group: AuthGroup,
    headers: dict[str, str],
    query: dict[str, str] | None = None,
    *,
    has_tls: bool = False,
) -> bool:
    """True when the AND of this group is already present on the request."""
    if group.anonymous:
        return True
    have_headers = {key.lower(): value for key, value in headers.items()}
    have_query = {key.lower() for key in (query or {})}
    authorization = have_headers.get("authorization", "")
    for need in group.api_keys:
        if need.header and need.header.lower() not in have_headers:
            return False
        if need.query and need.query.lower() not in have_query:
            return False
    if group.http_bearer and not authorization.lower().startswith("bearer "):
        return False
    if group.http_basic and not authorization.lower().startswith("basic "):
        return False
    if group.oauth and not authorization.lower().startswith("bearer "):
        return False
    if group.mutual_tls and not has_tls:
        return False
    return True


def _required_scheme_names(card: dict) -> set[str]:
    """Schemes that appear in every non-anonymous group (true AND), plus
    schemes that are the only way to authenticate.

    Used as a hint for inspect. Satisfaction still goes through
    ``requirement_groups``.
    """
    groups = [group for group in requirement_groups(card) if not group.anonymous]
    names: set[str] = set()
    for group in groups:
        names.update(group.names)
    return names


def _iter_schemes(card: dict):
    schemes = card.get("securitySchemes")
    if not isinstance(schemes, dict):
        return
    for name, value in schemes.items():
        body = value if isinstance(value, dict) else {}
        for nest in (
            "apiKeySecurityScheme",
            "openIdConnectSecurityScheme",
            "oauth2SecurityScheme",
            "httpAuthSecurityScheme",
            "mutualTlsSecurityScheme",
        ):
            inner = body.get(nest)
            if isinstance(inner, dict):
                merged = dict(body)
                merged.update(inner)
                body = merged
                break
        yield str(name), body


def _parse_api_key(name: str, body: dict, *, required: bool) -> ApiKeyNeed | None:
    kind = str(body.get("type") or "").lower().replace("_", "").replace("-", "")
    if kind in {"oauth2", "oauth", "openidconnect", "http", "https", "mutualtls"}:
        return None
    header_name = str(body.get("name") or "").strip()
    if not header_name:
        return None
    if kind and kind != "apikey":
        return None
    location = str(body.get("in") or body.get("location") or "header").lower()
    if location in {"header", "headers"}:
        return ApiKeyNeed(scheme=name, header=header_name, required=required)
    if location in {"query", "querystring"}:
        return ApiKeyNeed(scheme=name, query=header_name, required=required)
    return None


def _parse_oauth(name: str, body: dict, *, required: bool) -> OAuthNeed | None:
    kind = str(body.get("type") or "").lower()
    openid = str(body.get("openIdConnectUrl") or body.get("openIdConnectURL") or "").strip() or None
    if kind in {"openidconnect", "openIdConnect".lower()} or openid:
        scopes = _scopes_from_body(body)
        return OAuthNeed(
            scheme=name,
            openid_url=openid,
            scopes=scopes,
            required=required,
        )
    if kind in {"oauth2", "oauth"} or "flows" in body or "authorizationUrl" in body:
        flows = body.get("flows") if isinstance(body.get("flows"), dict) else {}
        code = (
            flows.get("authorizationCode")
            if isinstance(flows.get("authorizationCode"), dict)
            else {}
        )
        client_flow = (
            flows.get("clientCredentials")
            if isinstance(flows.get("clientCredentials"), dict)
            else {}
        )
        device_flow = (
            flows.get("deviceCode")
            if isinstance(flows.get("deviceCode"), dict)
            else flows.get("deviceAuthorization")
            if isinstance(flows.get("deviceAuthorization"), dict)
            else {}
        )
        auth_url = (
            str(code.get("authorizationUrl") or body.get("authorizationUrl") or "").strip() or None
        )
        token_url = str(code.get("tokenUrl") or body.get("tokenUrl") or "").strip() or None
        client_token = str(client_flow.get("tokenUrl") or "").strip() or None
        device_auth = device_flow.get("deviceAuthorizationUrl") or device_flow.get(
            "authorizationUrl"
        )
        device_url = str(device_auth or "").strip() or None
        if not token_url and client_token:
            token_url = client_token
        scopes = (
            _scopes_from_body(code)
            or _scopes_from_body(client_flow)
            or _scopes_from_body(device_flow)
            or _scopes_from_body(body)
        )
        return OAuthNeed(
            scheme=name,
            authorization_url=auth_url,
            token_url=token_url,
            device_authorization_url=device_url,
            client_credentials_token_url=client_token,
            scopes=scopes,
            required=required,
        )
    return None


def _is_http_bearer(body: dict) -> bool:
    kind = str(body.get("type") or "").lower()
    scheme = str(body.get("scheme") or "").lower()
    if kind in {"http", "https"} and scheme in {"bearer", "token"}:
        return True
    if "httpAuthSecurityScheme" in body:
        inner = body.get("httpAuthSecurityScheme") or {}
        if str(inner.get("scheme") or "").lower() in {"bearer", "token"}:
            return True
    return False


def _is_http_basic(body: dict) -> bool:
    kind = str(body.get("type") or "").lower()
    scheme = str(body.get("scheme") or "").lower()
    if kind in {"http", "https"} and scheme == "basic":
        return True
    if "httpAuthSecurityScheme" in body:
        inner = body.get("httpAuthSecurityScheme") or {}
        if str(inner.get("scheme") or "").lower() == "basic":
            return True
    return False


def _is_mutual_tls(body: dict) -> bool:
    kind = str(body.get("type") or "").lower().replace("_", "").replace("-", "")
    return kind in {"mutualtls", "mtls"}


def _basic_header(token: str) -> str:
    raw = token if ":" in token else f":{token}"
    encoded = base64.b64encode(raw.encode("utf-8")).decode("ascii")
    return f"Basic {encoded}"


def _scopes_from_body(body: dict) -> tuple[str, ...]:
    raw = body.get("scopes")
    if isinstance(raw, dict):
        return tuple(str(key) for key in raw if str(key).strip())
    if isinstance(raw, list):
        return tuple(str(item) for item in raw if str(item).strip())
    return ()
