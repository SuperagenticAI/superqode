# MCP OAuth Authentication

## Overview

MCP servers using HTTP or SSE transports can require OAuth 2.0 authentication. SuperQode implements the Authorization Code flow with PKCE, with automatic metadata discovery and secure token storage.

## OAuth Flow

1. Metadata discovery from /.well-known/oauth-protected-resource (RFC 9728) or /.well-known/oauth-authorization-server (RFC 8414)
2. Auth URL generation with PKCE challenge + state parameter (CSRF protection)
3. Local callback server on localhost:19876/mcp/oauth/callback
4. Token exchange (authorization code for access + refresh tokens)
5. Automatic token refresh with 5-minute expiry buffer
6. Secure storage in OS keychain (via keyring package) or ~/.superqode/mcp-auth/ with 0600 permissions

## Token Storage

- KeyringTokenStorage: OS-native keychain (macOS Keychain, Windows Credential Manager, GNOME Secret Service / KWallet)
- MCPAuthStorage: file-based fallback at ~/.superqode/mcp-auth/, files named <sha256(url)[:16]>.json, 0600 permissions
- Auto-selection: trying keyring first, falling back to filesystem

## Hugging Face Auto-Auth

For HuggingFace MCP servers (huggingface.co, hf.co, *.hf.space), tokens are auto-injected from HF_TOKEN, HUGGING_FACE_HUB_TOKEN env vars, or ~/.cache/huggingface/token. No manual setup needed.

## MCP Server Config

Server auth is configured via headers in MCPHttpConfig or MCPSSEConfig. Environment variables in env dicts support ${VAR} substitution.

## Configuration

Servers can be configured in .superqode/mcp.json, ~/.superqode/mcp.json, or ~/.config/superqode/mcp.json. Both {"mcpServers": {...}} and {"servers": {...}} top-level keys are accepted.
