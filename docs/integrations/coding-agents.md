---
title: Coding Agents
description: Connect subscription and SDK coding agents to SuperQode.
---

# Coding agents

The connected product retains ownership of its inner coding-agent loop on these
routes. SuperQode provides the terminal, session switching, surrounding policy,
and normalized events supported by each adapter.

| Integration | Install and authenticate | Start | Verify | Detailed guide |
| --- | --- | --- | --- | --- |
| OpenAI Codex SDK | `uv tool install "superqode[codex-sdk]"`, then `codex login` | `:connect codex` | `superqode runtime doctor codex-sdk` | [OpenAI Codex](../providers/codex.md) |
| Codex over ACP | Install and sign in to the Codex CLI | `:connect acp codex` | `superqode agents doctor codex` | [OpenAI Codex](../providers/codex.md#codex-over-acp) |
| Anthropic Claude Agent SDK | `uv tool install "superqode[claude-agent-sdk]"`, then set `ANTHROPIC_API_KEY` | `:runtime claude-agent-sdk` | `superqode runtime doctor claude-agent-sdk` | [Anthropic Claude](../providers/anthropic-claude.md) |
| Cursor subscription | Install Cursor CLI, then run `cursor-agent login` | `:connect cursor` | `superqode agents doctor cursor` | [ACP Coding Agents](../providers/acp.md) |
| Amp subscription | Install Amp and `acp-amp`, then run `amp login` | `:connect amp` | `superqode agents doctor amp` | [ACP Coding Agents](../providers/acp.md) |
| GitHub Copilot plan | Install `superqode[copilot-sdk]` and/or `@github/copilot`, then `copilot login` | `:connect copilot` | `:copilot status` | [GitHub Copilot](../providers/github-copilot.md) |
| Google Antigravity CLI | Install `agy` and complete Google sign-in | `:connect antigravity` | `:antigravity status` | [Google Antigravity](../providers/antigravity.md) |
| Google Antigravity SDK | `uv tool install "superqode[antigravity-sdk]"`, then set `GEMINI_API_KEY` or `GOOGLE_API_KEY` | `:antigravity sdk` | `superqode runtime doctor antigravity-sdk` | [Google Antigravity](../providers/antigravity.md) |
| xAI Grok Build | Install the Grok CLI, then run `grok login` | `:connect grok` | `superqode agents doctor grok --live` | [xAI Grok](../providers/grok.md) |
| Factory Droid | Install and authenticate the Droid CLI | `:connect droid` | `superqode agents doctor droid` | [ACP Coding Agents](../providers/acp.md) |
| Kiro / Amazon Q Developer | Install Kiro CLI and complete vendor sign-in | `:connect kiro` | `superqode agents doctor kiro` | [ACP Coding Agents](../providers/acp.md) |
| Kimi Code | `uv tool install kimi-cli --no-cache`, then complete Kimi CLI setup | `:connect kimi-code` | `superqode agents doctor kimi` | [Kimi Code](../providers/kimi.md#kimi-code-subscription-and-acp) |
| Qwen Code | `npm install -g @qwen-code/qwen-code`, then `qwen auth` | `:connect qwen-code` | `superqode agents doctor qwen` | [Qwen Code](../providers/qwen-code.md) |
| Deep Agents Code | `curl -LsSf https://langch.in/dcode \| bash`, then `dcode` and `/auth` | `:connect deepagents-code` | `superqode agents doctor deepagents-code` | [LangChain DeepAgents](../providers/deepagents.md) |
| Any installed ACP agent | Install the agent described by the ACP catalog | `:connect acp <agent>` | `superqode agents doctor <agent>` | [ACP Coding Agents](../providers/acp.md) |

The `vendor-sdks` bundle is intended for environments that require all four
supported vendor SDK runtimes:

```bash
uv tool install "superqode[vendor-sdks]"
superqode runtime setup
```

The bundle contains the Codex, Copilot, Claude Agent, and Antigravity SDK
packages. Vendor CLIs and their authentication remain separate.
