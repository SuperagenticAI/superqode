"""Publication checks distinguish missing images from host request filtering."""

import importlib.util
import io
import json
from pathlib import Path
from unittest.mock import Mock
import urllib.error

import pytest


@pytest.fixture
def checker():
    path = Path(__file__).parents[1] / "scripts" / "check_published_agent_card.py"
    spec = importlib.util.spec_from_file_location("card_checker", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def response(body, content_type="application/octet-stream"):
    result = io.BytesIO(body)
    result.headers = {"Content-Type": content_type}
    return result


def http_error(code):
    return urllib.error.HTTPError("https://example.com/icon.png", code, "error", {}, None)


@pytest.mark.parametrize("head_status", [403, 404, 405, 429, 503])
def test_head_error_is_confirmed_with_get(checker, monkeypatch, head_status):
    open_url = Mock(side_effect=[http_error(head_status), response(b"\x89PNG\r\n\x1a\nimage")])
    monkeypatch.setattr(checker.urllib.request, "urlopen", open_url)
    assert checker.icon_problem({"iconUrl": "https://example.com/icon.png"}) is None
    assert [call.args[0].get_method() for call in open_url.call_args_list] == ["HEAD", "GET"]


@pytest.mark.parametrize(
    "status,conclusive",
    [(404, True), (410, True), (401, True), (403, False), (429, False), (503, False)],
)
def test_get_errors_preserve_missing_image_failure(checker, monkeypatch, status, conclusive):
    monkeypatch.setattr(
        checker.urllib.request,
        "urlopen",
        Mock(side_effect=[http_error(status), http_error(status)]),
    )
    message, actual = checker.icon_problem({"iconUrl": "https://example.com/icon.png"})
    assert actual is conclusive
    assert f"HTTP {status} on GET" in message


def test_card_fetch_uses_checker_user_agent(checker, monkeypatch):
    open_url = Mock(return_value=response(json.dumps({"name": "SuperQode"}).encode()))
    monkeypatch.setattr(checker.urllib.request, "urlopen", open_url)
    assert checker.fetch("https://example.com/card.json") == {"name": "SuperQode"}
    assert open_url.call_args.args[0].get_header("User-agent") == checker.USER_AGENT


def test_real_card_mismatch_still_fails(checker, monkeypatch, tmp_path):
    artifact = tmp_path / "card.json"
    artifact.write_text('{"name": "SuperQode"}')
    monkeypatch.setattr(checker, "fetch", lambda url: {"name": "Different"})
    monkeypatch.setattr("sys.argv", ["checker", "--artifact", str(artifact)])
    assert checker.main() == 1
