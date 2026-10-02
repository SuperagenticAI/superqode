"""Real transport ownership and credential identity regressions."""

import asyncio
import sys
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest

from superqode.mcp.auth_storage import MCPAuthStorage
from superqode.mcp.client import MCPClientManager
from superqode.mcp.config import MCPServerConfig, MCPStdioConfig, MCPHttpConfig
from superqode.mcp.oauth import MCPOAuthProvider, OAuthTokens
from superqode.harness.pipy_mcp import PiPyMCPTools


def test_named_credentials_are_isolated_and_legacy_migration_is_explicit(tmp_path):
    root = MCPAuthStorage(tmp_path)
    url = "https://same.example/mcp"
    root.save_tokens(url, OAuthTokens("legacy"))
    a, b = root.for_server("a"), root.for_server("b")
    assert a.load_tokens(url) is None
    assert a.adopt_legacy_credentials(url)
    assert not b.adopt_legacy_credentials(url)
    assert a.load_tokens(url).access_token == "legacy"
    b.save_tokens(url, OAuthTokens("different"))
    assert a.load_tokens(url).access_token == "legacy"
    assert b.load_tokens(url).access_token == "different"
    assert a.load_tokens(url + "/different") is None


@pytest.mark.asyncio
async def test_callback_issuer_is_pinned_and_state_consumed(monkeypatch):
    provider = MCPOAuthProvider()
    metadata = {
        "issuer": "https://auth.example",
        "token_endpoint": "https://auth.example/token",
        "authorization_endpoint": "https://auth.example/authorize",
        "authorization_response_iss_parameter_supported": True,
    }
    url = await provider.start_auth_flow("https://resource.example", metadata)
    state = parse_qs(urlparse(url).query)["state"][0]
    requests = []
    monkeypatch.setattr(
        provider,
        "_request_tokens",
        lambda endpoint, args: requests.append(endpoint) or {"access_token": "ok"},
    )
    with pytest.raises(ValueError, match="issuer"):
        await provider.handle_callback("code", state, issuer="https://other.example")
    assert not requests
    with pytest.raises(ValueError, match="state"):
        await provider.handle_callback("code", state, issuer="https://auth.example")
    url = await provider.start_auth_flow("https://resource.example", metadata)
    state = parse_qs(urlparse(url).query)["state"][0]
    await provider.handle_callback(
        "code", state, {"token_endpoint": "https://other.example"}, issuer="https://auth.example"
    )
    assert requests == ["https://auth.example/token"]


@pytest.mark.asyncio
async def test_refresh_reloads_after_lock_and_preserves_refresh_and_scope(monkeypatch, tmp_path):
    root = MCPAuthStorage(tmp_path)
    monkeypatch.setattr("superqode.mcp.auth_storage.get_auth_storage", lambda: root)
    manager = MCPClientManager()
    manager.add_server(
        MCPServerConfig(
            id="account", name="account", config=MCPHttpConfig(url="https://same.example")
        )
    )
    storage = root.for_server("account")
    storage.save_tokens(
        "https://same.example",
        OAuthTokens(
            "old",
            refresh_token="rotating",
            scope="mcp read",
            expires_at=datetime.now() - timedelta(seconds=1),
        ),
    )
    count = 0

    async def refresh(self, refresh_token, server_url):
        nonlocal count
        count += 1
        await asyncio.sleep(0.05)
        return OAuthTokens("fresh")

    monkeypatch.setattr(MCPOAuthProvider, "refresh_tokens", refresh)
    assert all(
        await asyncio.gather(
            *(manager.authenticate_server("account", required_scopes="read") for _ in range(5))
        )
    )
    assert count == 1
    tokens = storage.load_tokens("https://same.example")
    assert tokens.refresh_token == "rotating" and tokens.scope == "mcp read"


@pytest.mark.asyncio
async def test_real_stdio_multiple_servers_owned_cleanup_and_pipy_images(tmp_path):
    server = tmp_path / "server.py"
    server.write_text("""from mcp.server.fastmcp import FastMCP
from mcp.types import ImageContent, TextContent
m = FastMCP("fixture")
@m.tool()
def capture(value: int) -> list:
    return [TextContent(type="text", text=f"Error rate is {value}"), ImageContent(type="image", data="aGVsbG8=", mimeType="image/png")]
if __name__ == "__main__": m.run(transport="stdio")
""")
    config = {
        "mcp_servers": {
            sid: {"command": sys.executable, "args": [str(server)]}
            for sid in ("account_a", "account_b")
        }
    }
    bridge = await PiPyMCPTools.create(config)
    try:
        assert len(bridge.tools) == 2
        found = await bridge.tools[0].execute("search", {"query": "capture"})
        assert len(found.details["tools"]) == 2
        result = await bridge.tools[1].execute(
            "call", {"server": "account_a", "tool": "capture", "arguments": {"value": 2}}
        )
        assert "Error rate" in result.text
        assert any(block.type == "image" for block in result.content)
        with pytest.raises(Exception, match="integer"):
            await bridge.tools[1].execute(
                "invalid", {"server": "account_a", "tool": "capture", "arguments": {"value": "bad"}}
            )
        assert len(bridge.manager._owners) == 2
    finally:
        manager = bridge.manager
        await bridge.close()
    assert not manager._owners


@pytest.mark.asyncio
async def test_cancel_handshake_closes_in_owner_task(monkeypatch):
    manager = MCPClientManager()
    manager.add_server(
        MCPServerConfig(id="slow", name="slow", config=MCPStdioConfig(command="unused"))
    )
    started = asyncio.Event()
    cleanup = []

    async def establish(connection):
        import contextlib

        @contextlib.asynccontextmanager
        async def transport():
            owner = asyncio.current_task()
            try:
                yield
            finally:
                cleanup.append(asyncio.current_task() is owner)

        connection._exit_stack = contextlib.AsyncExitStack()
        await connection._exit_stack.enter_async_context(transport())
        started.set()
        await asyncio.Event().wait()

    monkeypatch.setattr(manager, "_establish_connection", establish)
    waiting = asyncio.create_task(manager.connect("slow"))
    await started.wait()
    await manager.disconnect("slow")
    assert await waiting is False
    assert cleanup == [True]


@pytest.mark.asyncio
async def test_real_oauth_callback_rejects_ambiguous_and_replayed_state():
    import urllib.request
    import urllib.error
    from superqode.mcp.oauth_callback import OAuthCallbackServer

    server = OAuthCallbackServer(port=0)
    await server.start()
    try:
        waiting = asyncio.create_task(server.wait_for_callback("fixture-state", timeout=5))
        await asyncio.sleep(0)

        def request(query):
            try:
                with urllib.request.urlopen(
                    server.get_redirect_uri() + query, timeout=3
                ) as response:
                    return response.status
            except urllib.error.HTTPError as exc:
                return exc.code

        assert await asyncio.to_thread(request, "?state=fixture-state&state=other&code=code") == 400
        assert not waiting.done()
        assert (
            await asyncio.to_thread(
                request, "?state=fixture-state&code=code&iss=https%3A%2F%2Fissuer.example"
            )
            == 200
        )
        result = await waiting
        assert result.issuer == "https://issuer.example"
        assert await asyncio.to_thread(request, "?state=fixture-state&code=code") == 400
    finally:
        await server.stop()


@pytest.mark.asyncio
async def test_failed_startup_keeps_error_until_explicit_disconnect(monkeypatch):
    from superqode.mcp.client import MCPConnectionState

    manager = MCPClientManager()
    manager.add_server(
        MCPServerConfig(id="failed", name="failed", config=MCPStdioConfig(command="unused"))
    )

    async def fail(connection):
        raise RuntimeError("fixture handshake failed")

    monkeypatch.setattr(manager, "_establish_connection", fail)
    assert not await manager.connect("failed")
    await manager._owners["failed"]
    assert manager._connections["failed"].state == MCPConnectionState.ERROR
    assert manager._connections["failed"].error_message == "fixture handshake failed"
    await manager.disconnect("failed")
    assert manager._connections["failed"].state == MCPConnectionState.DISCONNECTED


@pytest.mark.asyncio
async def test_disconnect_cancels_owned_catalog_refresh(monkeypatch):
    from superqode.mcp.client import MCPConnection

    manager = MCPClientManager()
    config = MCPServerConfig(id="refresh", name="refresh", config=MCPStdioConfig(command="unused"))
    manager._connections["refresh"] = MCPConnection(server_config=config)
    refresh = asyncio.create_task(asyncio.Event().wait())
    manager._refresh_tasks["refresh"] = {refresh}
    await manager._disconnect_owned("refresh")
    assert refresh.cancelled()
    assert "refresh" not in manager._refresh_tasks
