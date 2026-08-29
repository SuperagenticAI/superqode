"""Agent Card security schemes: API keys first, then OAuth."""

from __future__ import annotations

from superqode.a2a.inspect import InspectLog, redact_text, redact_url
from superqode.a2a.security import (
    bind_api_key,
    describe_auth,
    missing_api_key_header,
    oauth_needs,
)


def test_describe_auth_names_the_api_key_header():
    card = {
        "securitySchemes": {"apiKey": {"type": "apiKey", "name": "X-API-Key", "in": "header"}},
        "securityRequirements": [{"apiKey": []}],
    }
    line = describe_auth(card)
    assert "required" in line
    assert "X-API-Key" in line


def test_bind_api_key_uses_token_as_the_named_header():
    card = {"securitySchemes": {"apiKey": {"type": "apiKey", "name": "X-API-Key", "in": "header"}}}
    bearer, headers, query, notes = bind_api_key(card, token="secret-key", headers={})
    assert bearer == ""
    assert headers["X-API-Key"] == "secret-key"
    assert query == {}
    assert any("X-API-Key" in note for note in notes)


def test_bind_api_key_uses_token_as_the_named_query():
    card = {"securitySchemes": {"apiKey": {"type": "apiKey", "name": "api_key", "in": "query"}}}
    bearer, headers, query, notes = bind_api_key(card, token="secret-key", headers={})
    assert bearer == ""
    assert headers == {}
    assert query == {"api_key": "secret-key"}
    assert any("query api_key" in note for note in notes)


def test_bind_api_key_keeps_bearer_when_the_card_also_has_http_auth():
    card = {
        "securitySchemes": {
            "bearer": {"type": "http", "scheme": "bearer"},
            "apiKey": {"type": "apiKey", "name": "X-API-Key", "in": "header"},
        }
    }
    bearer, headers, query, _notes = bind_api_key(card, token="tok", headers={})
    assert bearer == "tok"
    assert "X-API-Key" not in headers
    assert query == {}


def test_missing_required_api_key_header():
    card = {
        "securitySchemes": {"apiKey": {"type": "apiKey", "name": "X-API-Key", "in": "header"}},
        "securityRequirements": [{"apiKey": []}],
    }
    assert missing_api_key_header(card, {}) == "X-API-Key"
    assert missing_api_key_header(card, {"X-API-Key": "x"}) is None


def test_oauth_need_from_openid_connect_url():
    card = {
        "securitySchemes": {
            "google": {
                "type": "openIdConnect",
                "openIdConnectUrl": "https://accounts.example/.well-known/openid-configuration",
            }
        },
        "securityRequirements": [{"google": ["openid"]}],
    }
    needs = oauth_needs(card)
    assert len(needs) == 1
    assert needs[0].required is True
    assert needs[0].runnable is True
    assert needs[0].openid_url.endswith("openid-configuration")


def test_bind_http_basic_uses_token_as_user_password():
    card = {"securitySchemes": {"basic": {"type": "http", "scheme": "basic"}}}
    bearer, headers, query, notes = bind_api_key(card, token="user:pass", headers={})
    assert bearer == ""
    assert headers["Authorization"].startswith("Basic ")
    assert query == {}
    assert any("HTTP Basic" in note for note in notes)


def test_requirement_groups_are_or_options():
    from superqode.a2a.security import group_satisfied, requirement_groups

    card = {
        "securitySchemes": {
            "google": {
                "type": "openIdConnect",
                "openIdConnectUrl": "https://accounts.example/.well-known/openid-configuration",
            },
            "apiKey": {"type": "apiKey", "name": "X-API-Key", "in": "header"},
        },
        "securityRequirements": [{"google": []}, {"apiKey": []}],
    }
    groups = requirement_groups(card)
    assert len(groups) == 2
    assert groups[0].oauth[0].scheme == "google"
    assert groups[1].api_keys[0].header == "X-API-Key"
    assert group_satisfied(groups[1], {"X-API-Key": "x"})
    assert not group_satisfied(groups[0], {"X-API-Key": "x"})
    assert group_satisfied(groups[0], {"Authorization": "Bearer tok"})


def test_mutual_tls_group_needs_a_client_certificate():
    from superqode.a2a.security import describe_auth, group_satisfied, requirement_groups

    card = {
        "securitySchemes": {"mtls": {"type": "mutualTLS"}},
        "securityRequirements": [{"mtls": []}],
    }
    groups = requirement_groups(card)
    assert groups[0].mutual_tls is True
    assert group_satisfied(groups[0], {}) is False
    assert group_satisfied(groups[0], {}, has_tls=True) is True
    assert "--tls-cert" in describe_auth(card)


def test_anonymous_requirement_is_an_empty_group():
    from superqode.a2a.security import requirement_groups

    card = {
        "securitySchemes": {"oauth2": {"type": "oauth2"}},
        "securityRequirements": [{}, {"oauth2": []}],
    }
    groups = requirement_groups(card)
    assert groups[0].anonymous is True
    assert groups[1].anonymous is False


def test_inspect_redacts_bodies_and_query_secrets():
    log = InspectLog()
    log.request(
        "GET",
        "https://agent.example/path?api_key=secret&q=ok",
        body="invalid token: sqk_live_abc123 Bearer xyz",
    )
    event = log.events[0]
    assert "api_key=***" in event.summary
    assert "sqk_live_abc123" not in event.detail["body"]
    assert "Bearer ***" in event.detail["body"]
    assert redact_text("password: hunter2") == "password: ***"
    assert "token=***" in redact_url("https://x.test/a?token=abc")
