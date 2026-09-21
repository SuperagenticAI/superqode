# Jev Tool Routing Commands

The `superqode optimize` command group adds local, provider-neutral Jev Tool
Routing to supported coding harnesses. Start in shadow mode so Jev recommends a
smaller catalogue while the harness still receives its complete tool list.

```bash
export TYPESAFE_API_KEY="..."
superqode optimize enable opencode --provider google --model gemini-3.8-flash
opencode-jev run "review this repository"
```

No command in this group rewrites a developer's persistent harness
configuration. Launch adapters use process-local arguments, environment
overlays, and temporary files that are removed after the run.

## Commands

| Command | Purpose |
| --- | --- |
| `superqode optimize enable [HARNESS]...` | Create managed `*-jev` launchers. With no arguments, enable every detected compatible harness that has enough configuration. |
| `superqode optimize status` | Show configured launchers, routes, modes, and file health. |
| `superqode optimize disable [HARNESS]...` | Remove selected managed launchers, or all of them when omitted. |
| `superqode optimize uninstall` | Remove every managed launcher and the non-secret preferences file. |
| `superqode optimize setup [HARNESS]` | Detect installations, make one small Jev connectivity call, and print launch commands. |
| `superqode optimize verify HARNESS` | Check the adapter, controlled schema reduction, and same-turn decision-cache reuse without invoking a coding model. |
| `superqode optimize doctor` | Report installed harnesses and their integration status. |
| `superqode optimize env HARNESS` | Preview the non-persistent command, environment overlay, and generated files. |
| `superqode optimize run HARNESS` | Start the loopback gateway, run the harness, print aggregate routing metrics, and clean up. |
| `superqode optimize bench` | Run the small labeled, coding-model-free routing evaluation. |
| `superqode optimize mcp` | Expose the same router as a local stdio MCP server. |

Pass harness arguments after `--`. Pi requires a model id. Google runs require
`GEMINI_API_KEY` and use the harness's native Gemini protocol:

```bash
superqode optimize run opencode --provider google --model gemini-3.8-flash \
  -- run "review this repository"

superqode optimize run pi --provider google --model gemini-3.8-flash \
  -- --print "review this repository"
```

The generated OpenCode and Pi configurations contain a non-secret local
placeholder. The gateway owns `GEMINI_API_KEY` and replaces the placeholder only
on the upstream request. This preserves Gemini thought signatures while keeping
credentials out of temporary configuration.

Supported launch profiles are OpenCode, Pi, Claude Code, Grok Build, Codex, and
native SuperQode. Codex subscription traffic currently receives its catalogue
server-side, so it is reported as `gateway-limited`. Antigravity is
`detect-only` until its CLI exposes a model endpoint hook.

Use `--mode enforce` only after reviewing shadow reports. Routing always keeps
the core workspace tools, fails open on errors, and never executes a tool. Stock
Pi exposes only four core tools, so it commonly reports no reduction until
extensions add a larger catalogue.

The managed preferences live at `~/.superqode/jev-routing.json` (or beneath
`SUPERQODE_HOME`) with `0600` permissions. Launchers default to `~/.local/bin`;
set `SUPERQODE_BIN_DIR` or pass `--bin-dir` to choose another location. A
launcher is removed only when it still carries SuperQode's management marker,
so disable and uninstall never delete a user-owned replacement.

For the standalone HTTP gateway, Python SDK, service, and deployment details,
see [Serve Commands](serve-commands.md) and
[SystemOne and Jev](../advanced/systemone.md#jev-tool-routing).
