# Environment Variables

Every `SUPERQODE_*` variable in one place. Most behavior is configurable per-harness or in `superqode.yaml` too; env vars win for quick experiments, CI, and per-shell overrides.

## Agent loop

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_AUTO_COMPACT` | `0`/`1` | on | Adaptive context compaction (prune stale tool output first, summarize only if still needed). |
| `SUPERQODE_DOOM_LOOP_THRESHOLD` | int | `3` | Consecutive identical tool calls before the guard intercepts; `0` disables. |
| `SUPERQODE_RATE_LIMIT_RETRIES` | int | `3` | Retries with backoff on 429/503/529/overloaded (honors `Retry-After`). |
| `SUPERQODE_REMINDERS` | `0`/`1` | on | `<system-reminder>` notes: externally-changed files, stale todos. |
| `SUPERQODE_AUTO_MEMORY` | `0`/`1` | off | Extract durable preferences/facts/decisions after completed runs into local memory (background task, deduplicated, tagged `auto`). |
| `SUPERQODE_AUTO_RECALL` | `0`/`1` | off | Surface relevant saved memories to the agent at run start, as a clearly labeled system reminder (local provider only, once per prompt). |

## Tools

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_TOOL_PROFILE` | `coding`/`full`/`standard`/`ds4`/`none` | `coding` | Which tool registry interactive sessions use. |
| `SUPERQODE_DEFERRED_TOOLS` | `auto`/`all`/names | off | Hide heavy tool schemas until the model activates them via `tool_search`. `auto` = local providers only. |
| `SUPERQODE_TOOL_OUTPUT_DIR` | path | `~/.superqode/tool-output` | Where oversized tool output spills (7-day retention). |
| `SUPERQODE_VERIFY_EDITS` | `0`/`1` | on | Post-edit diagnostics (ruff/py_compile, eslint, gofmt, JSON/YAML) fed back to the model. |
| `SUPERQODE_FORMAT_ON_EDIT` | `0`/`1` | off | Auto-format files after agent edits. |
| `SUPERQODE_SEARCH_ROOTS` | paths (`:`-sep) | unset | Extra read-only roots for read/search tools (cloned repos outside the project). |
| `SUPERQODE_ALLOW_EXTERNAL_SEARCH` | `0`/`1` | off | Permission-gate for absolute search paths outside the workspace. |
| `SUPERQODE_MCP_SEARCH` | `0`/`1` | off | Inject MCP search/execute tools into the registry. |

## Safety & policy

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_EXEC_POLICY` | path | unset | Explicit exec-policy YAML, prepended to project (`.superqode/execpolicy.yaml`) and user (`~/.superqode/execpolicy.yaml`) rules. |
| `SUPERQODE_SHELL_ENV_POLICY` | `inherit`/`filter-secrets` | `inherit` | Strip secret-looking env vars (`*KEY*`, `*TOKEN*`, `*SECRET*`, `*PASSWORD*`, ...) from spawned shell commands. |
| `SUPERQODE_SHELL_ENV_ALLOW` | names (`,`-sep) | unset | Exceptions kept when filtering secrets. |
| `SUPERQODE_SANDBOX` | mode | off | OS sandbox for shell commands (macOS Seatbelt / Linux bwrap). |

## Providers & models

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_PROVIDER` | provider id | `openai` | Default provider for headless runs. |
| `SUPERQODE_MODEL` | model id | `<openai-fast-model>` | Default model for headless runs. |
| `SUPERQODE_HARNESS` | path | unset | HarnessSpec YAML/JSON to load on start. |
| `SUPERQODE_CONNECT` | profile name | unset | Auto-connect a connection profile when the TUI starts (set by `--connect`). |
| `OLLAMA_HOST` etc. | URL | per-provider | Local server endpoints (see [Local Models](../providers/local.md)). |

Provider API keys (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, ...) follow each provider's standard names. See [BYOK Providers](../providers/byok.md).

## Local model tuning

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_OLLAMA_NUM_CTX` | int | unset | Request this context length from Ollama per call. Ollama's MLX backend honors only Modelfile-baked values. |
| `SUPERQODE_OLLAMA_KEEP_ALIVE` | duration | `30m` | How long Ollama keeps the model loaded between calls. |
| `SUPERQODE_DISABLE_LOCAL_SHAPING` | `0`/`1` | off | Skip local-request shaping (num_ctx, keep-alive, tool-temperature clamps). |
| `SUPERQODE_DISABLE_PROMPT_CACHE` | `0`/`1` | off | Disable prompt-cache annotations on outgoing requests. |
| `SUPERQODE_DS4_THINKING` | mode | unset | Force the DS4 thinking mode instead of the per-model default. |
| `SUPERQODE_MLX_INPROCESS` | `0`/`1` | on | Serve MLX models in-process; set `0` to require an external server. |
| `SUPERQODE_UTILITY_PROVIDER` | `apple-fm` or `provider/model` | unset | Route utility calls (rubric grading, memory extraction) to a cheaper model; `apple-fm` uses the on-device Apple Foundation Model. Falls back to the session model. See [Local Stack Doctor](../advanced/local-stack.md). |

## Channel daemon

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_TELEGRAM_BOT_TOKEN` | token | unset | Telegram bot token for `superqode daemon` (from @BotFather). |
| `SUPERQODE_SLACK_APP_TOKEN` | `xapp-...` | unset | Slack app-level token for Socket Mode. |
| `SUPERQODE_SLACK_BOT_TOKEN` | `xoxb-...` | unset | Slack bot token for posting messages. |
| `SUPERQODE_DISCORD_BOT_TOKEN` | token | unset | Discord bot token for the Gateway connection. |

Chat allowlists and defaults live in `~/.superqode/channels.yaml`. See [Chat Channels](../advanced/channels.md).

## ACP connections

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_ACP_CLIENT` | client id | unset | Pin which ACP client implementation the TUI uses. |
| `SUPERQODE_ACP_STARTUP_TIMEOUT` | seconds | `15` | How long to wait for an ACP agent process to start. |
| `SUPERQODE_ACP_REQUEST_TIMEOUT` | seconds | `12` | Timeout for individual ACP requests. |
| `SUPERQODE_ACP_PROMPT_TIMEOUT` | seconds | `180` | Timeout for a full ACP prompt turn. |
| `SUPERQODE_ACP_TERMINAL_PTY` | `0`/`1` | on | Allocate a PTY for ACP terminal sessions (POSIX only). |
| `SUPERQODE_ACP_TRAFFIC_LOG` | `0`/`1` | off | Record raw ACP JSON-RPC traffic for debugging. |
| `SUPERQODE_ACP_TRAFFIC_LOG_PATH` | path | under `SUPERQODE_HOME` | Where the ACP traffic log is written. |
| `SUPERQODE_ACP_PRINT_LOGS` | `0`/`1` | off | Print agent process logs through the TUI (opencode agents). |
| `SUPERQODE_FAST_AGENT_ACP_COMMAND` | command | built-in | Override the command used to launch the fast-agent ACP server. |

## Core, sessions, and state

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_HOME` | path | `~/.superqode` | Root for user-level SuperQode state (trust store, logs, tool output). |
| `SUPERQODE_STATE_DIR` | path | `.superqode` | Project-level state directory used by workspace coordination. |
| `SUPERQODE_TRUST_STORE` | path | `~/.superqode/trust.json` | Location of the project trust store. |
| `SUPERQODE_CWD` | path | set automatically | Project root propagated to spawned helper processes. |
| `SUPERQODE_MAX_ITERATIONS` | int | `0` (unlimited) | Safety cap on agent loop iterations per run. |
| `SUPERQODE_SESSION_HISTORY_LIMIT` | int | `20` | How many stored messages a resumed session loads. |
| `SUPERQODE_STARTUP_HEALTH` | `0`/`1` | off | Run provider health checks at TUI startup. |

## Output & UX

| Variable | Values | Default | Effect |
|---|---|---|---|
| `SUPERQODE_LOG_VERBOSITY` | `quiet`/`normal`/`verbose` | `normal` | Tool-output verbosity. Set by `--quiet`/`--verbose`; the TUI `:log` command changes it live. |
| `SUPERQODE_QUIET` | `0`/`1` | off | Same as passing `--quiet`. |
| `SUPERQODE_VERBOSE` | `0`/`1` | off | Same as passing `--verbose`. |
| `SUPERQODE_VIM_MODE` | `0`/`1` | saved preference or off | Override the optional Vim-like modal navigation layer for the TUI. |

## Notes

- Boolean variables accept `1/true/yes/on` and `0/false/no/off`.
- Env vars set in the shell that launches SuperQode are inherited by spawned subprocesses (ACP clients, shell sessions) unless the env policy filters them.
- The [Agent Loop guide](../advanced/agent-loop.md) explains the behavior behind each loop variable.
