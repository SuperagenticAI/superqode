"""Tests for web server access policy."""

import pytest

from superqode.server.web import (
    AUTH_COOKIE_NAME,
    WebServerConfig,
    extract_web_auth_token,
    is_loopback_host,
    is_web_request_authorized,
)


def test_loopback_hosts_are_local():
    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert is_loopback_host("::1")


def test_remote_hosts_are_not_loopback():
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("::")
    assert not is_loopback_host("192.168.1.10")


def test_remote_binding_requires_explicit_opt_in():
    with pytest.raises(ValueError, match="Remote web serving is disabled"):
        WebServerConfig(host="0.0.0.0")


def test_remote_binding_generates_token_when_allowed():
    config = WebServerConfig(host="0.0.0.0", allow_remote=True)

    assert config.require_auth
    assert config.auth_token


def test_remote_binding_cannot_disable_auth():
    with pytest.raises(ValueError, match="Authentication cannot be disabled"):
        WebServerConfig(host="0.0.0.0", allow_remote=True, require_auth=False)


def test_web_auth_accepts_query_token():
    assert is_web_request_authorized({"token": "secret"}, {}, {}, "secret")


def test_web_auth_accepts_bearer_token():
    assert is_web_request_authorized({}, {"Authorization": "Bearer secret"}, {}, "secret")


def test_web_auth_accepts_cookie_token():
    assert is_web_request_authorized({}, {}, {AUTH_COOKIE_NAME: "secret"}, "secret")


def test_web_auth_rejects_missing_or_wrong_token():
    assert not is_web_request_authorized({}, {}, {}, "secret")
    assert not is_web_request_authorized({"token": "wrong"}, {}, {}, "secret")
    assert not is_web_request_authorized({"token": "secret"}, {}, {}, None)


def test_web_auth_extracts_query_before_cookie():
    token = extract_web_auth_token({"token": "query-token"}, {}, {AUTH_COOKIE_NAME: "cookie-token"})

    assert token == "query-token"
