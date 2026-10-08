# Codex command coverage

Checked on **2026-10-08** against installed **codex-cli 0.160.0** on macOS arm64.
The audit read all **72 named CLI command paths** (plus root help), **26 top-level commands**, and **62 slash-command variants** in the matching release source. Hidden/debug/platform-gated slash variants are included in the source count; they are not all shown in every Codex menu. The generated app-server JSON schemas were also inspected.

SuperQode 2.8.0 exposed 15 primary `:codex` subcommands. The current command catalog exposes **42**, including help. This is command coverage, not full Codex CLI or TUI parity. See [Codex integration](codex.md) for approval boundaries and native controls.

## Sources

- [Official CLI command reference](https://developers.openai.com/codex/cli/reference).
- [Official slash-command reference](https://developers.openai.com/codex/cli/slash-commands).
- [Codex 0.160.0 CLI command parser](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/cli/src/main.rs).
- [Codex 0.160.0 slash-command definitions](https://github.com/openai/codex/blob/rust-v0.160.0/codex-rs/tui/src/slash_command.rs).
- Runtime method/field verification: `codex app-server generate-json-schema --experimental --out <temporary-directory>`.

The local source checkout was dated June 2026, so the matching 0.160.0 release source and installed binary were used for this audit. Official documentation may describe a different release or platform. The installed binary is authoritative for available commands.

## Using the added controls

Connect with `:connect codex`, then enter `:codex help`. SDK connections retain the existing model/session controls; new native controls show a CLI requirement without silently switching runtimes.

```text
:codex login --device-auth
:codex new Release investigation
:codex plan on
:codex permissions on-request
:codex review --base main
:codex sessions --all
:codex resume --last
:codex fork
:codex usage
:codex usage --tokens
:codex mcp verbose
:codex mcp reload
:codex skills --reload
:codex plugins
:codex apps
:codex hooks
:codex features
:codex config
:codex doctor
:codex ps
:codex stop
:codex cancel
:codex tools
:codex history
:codex permissions profile <id>
:codex permissions untrusted
:codex permissions mediated
:codex turn-options {"summary":"concise","serviceTier":null}
:codex mcp login <server>
:codex review --detached --base main
:codex attach ws://127.0.0.1:4500
```

Inspection commands expose Codex-owned resources. SuperQode's `:mcp`, `:skills`, and plugin tooling manage separate host resources. Enabled catalog entries can be invoked with `$skill-name` and `$app-slug` or `@app-slug` in the composer. Listing alone does not enable or install an entry.

Plan mode selects a Codex collaboration preset for future turns. Approval policy and sandbox are separate controls; selecting `never` does not grant extra filesystem access. Managed Codex requirements still apply. These overrides are per connection and are not written to Codex configuration files.

The mediated preset requests human review with `on-request` and `workspace-write`;
SuperQode still only sees native actions that request approval. Turn options apply
to the next ordinary turn and are schema-checked. History falls back to
`thread/read` when the server advertises paging but has not implemented it.
Detached reviews fork saved conversations or create a separate read-only thread
for a fresh conversation; unsaved originals are not marked resumable.

Persistent rule amendments require a separate confirmation and Codex may then
write its rules. Codex also stores OAuth state after explicit MCP login. These
native writes are separate from SuperQode's per-connection overrides.

SuperQode's `:plan` host guard is a separate setting and still applies when enabled. `:codex plan off` changes the native collaboration preset.

Subscription authentication is checked before fresh-thread creation and each prompt. Sign-in starts only ChatGPT browser/device flows; API-key and access-token login are not exposed. Native CLI metadata commands do not create a thread or call a model. SDK metadata may initialize an empty thread but never starts a model turn. Configuration and inventories redact credential-related fields before display. Login URLs and one-time device codes are intentionally displayed.

Inventory/session pages show a `--cursor` continuation command when available. Session IDs are displayed in full. Changing the active session is blocked while a task runs. Archiving the current thread detaches it; unarchive restores a saved thread without activating it.

## Top-level CLI mapping

| Codex command | Coverage | SuperQode behavior |
| --- | --- | --- |
| `codex agents` | Partial | `:codex agents` lists descendants of the active thread. The CLI command center uses the shared daemon and includes other sessions. |
| `codex exec` | Mapped | Use `superqode --connect codex --print "task"`; resume/fork/review use the native thread controls. Exec-specific flags and JSONL formats stay in Codex CLI. |
| `codex review` | Native | `:codex review [instructions]`, `--uncommitted`, `--base <branch>` or `--commit <sha>`. |
| `codex login` | Native | `:codex login`, `:codex login --device-auth`, `status` and `cancel`. ChatGPT sign-in only. |
| `codex logout` | Native | `:codex logout`. |
| `codex mcp` | Partial | `:codex mcp [verbose]` inventories servers/tools; `reload` reloads configuration; `login <server>` starts OAuth. Add/remove/logout remain in Codex CLI. |
| `codex plugin` | Partial | `:codex plugins [--reload]` lists plugins. Install/remove and marketplace management remain in Codex CLI. |
| `codex app-server` | Internal | The persistent stdio app-server powers the integration. Daemon/proxy management and schema generators stay in Codex CLI. |
| `codex remote-control` | CLI | Daemon pairing/start/stop remain in Codex CLI; SuperQode currently owns a local stdio process. |
| `codex app` | CLI | Desktop launch and continuing a thread in the desktop app remain in Codex CLI. |
| `codex completion` | Mapped | SuperQode provides completion for supported `:codex` commands. Shell completion script generation stays in Codex CLI. |
| `codex update` | CLI | Update the vendor executable using `codex update`; SuperQode package updates use `superqode update`. |
| `codex doctor` | Native | `:codex doctor` runs the installed CLI's redacted JSON diagnostics asynchronously. Nonzero diagnostic exits still display the report. |
| `codex sandbox` | Different scope | `:codex sandbox` changes future agent-turn sandbox policy. The CLI command executes an arbitrary command in a vendor sandbox; that command remains in Codex CLI. |
| `codex debug` | Partial | `:codex models`, `:codex config` and `:codex status --probe` provide user diagnostics. Debug transports and prompt rendering stay in Codex CLI. |
| `codex apply` | CLI | Applying cloud task diffs remains in Codex CLI; local harness edits already affect the workspace. |
| `codex resume` | Native | `:codex resume <id>` or `:codex resume --last`. With no argument, show available sessions and their full IDs. |
| `codex queue` | Deferred | Daemon cross-session queueing is separate from SuperQode's composer queue/steering. No native `:codex queue` parity is claimed. |
| `codex archive` | Native | `:codex archive [id]`. Archiving the current thread detaches it; a subsequent prompt starts a new thread. SuperQode stays open. |
| `codex delete` | CLI | Permanent transcript/descendant deletion remains in Codex CLI. |
| `codex migrate-rollouts` | CLI | Local history maintenance remains in Codex CLI. |
| `codex unarchive` | Native | `:codex unarchive <id>` restores a saved thread; use resume separately to activate it. |
| `codex fork` | Native | `:codex fork [id]`; omitting the ID forks the active thread. |
| `codex cloud` | Deferred | Cloud task creation, listing, status, diff and apply remain in Codex CLI. |
| `codex exec-server` | CLI | Remote execution provisioning and forwarding remain in Codex CLI. |
| `codex features` | Partial | `:codex features` lists effective feature flags. Persistent enable/disable remains in Codex CLI. |

`codex help` / `--help` are covered by `:codex help` for supported controls. Run `!codex --help` for the installed CLI's full help. API credentials, arbitrary `-c` overrides, remote flags and privileged bypass flags are not forwarded by `:codex`.

## Nested CLI command inventory

Every displayed nested command was inspected with `--help`. Parent-command coverage above applies unless a dedicated mapping is listed.

| Parent | Nested commands |
| --- | --- |
| `codex exec` | `resume`, `fork`, `review` |
| `codex login` | `status` |
| `codex mcp` | `list`, `get`, `add`, `remove`, `login`, `logout` |
| `codex plugin` | `add`, `list`, `marketplace`, `remove` |
| `codex app-server` | `daemon`, `proxy`, `generate-ts`, `generate-json-schema` |
| `codex remote-control` | `start`, `stop`, `pair` |
| `codex debug` | `models`, `app-server`, `prompt-input` |
| `codex cloud` | `exec`, `status`, `list`, `apply`, `diff` |
| `codex exec-server` | `forward` |
| `codex features` | `list`, `enable`, `disable` |
| `codex plugin marketplace` | `add`, `list`, `upgrade`, `remove` |
| `codex app-server daemon` | `bootstrap`, `start`, `restart`, `update`, `enable-remote-control`, `disable-remote-control`, `stop`, `version` |
| `codex debug app-server` | `send-message-v2` |

Aliases `e` (`exec`) and `a` (`apply`) do not add independent behavior. The installed macOS `sandbox` command runs a trailing command directly; Linux and Windows sandbox details differ.

## Slash-command mapping

| Codex slash command | Coverage | SuperQode behavior |
| --- | --- | --- |
| `/model` | Native | `:codex model`, `:codex models`, `:codex effort` (`reasoning` alias). |
| `/ide` | Client | Use SuperQode's file context; automatic Codex IDE selection/open-file integration is deferred. |
| `/permissions` | Native | `:codex permissions` lists profiles; `profile <id>` selects one. `on-request`, `untrusted`, `never` and `granular <json>` select approval policy. `:codex sandbox` selects a sandbox instead of a named profile. |
| `/keymap` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/vim` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/setup-default-sandbox` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/experimental` | Inspect | `:codex features`; `experimental` is an alias. Toggles remain in Codex CLI. |
| `/approve` | Deferred | Guardian one-time retry is distinct from SuperQode's pending approval prompt and is not mapped to it. |
| `/memories` | Deferred | Memory generation/use/reset lifecycle and state controls remain in Codex CLI. |
| `/skills` | Inspect | `:codex skills [--reload]` lists Codex skills and paths. Skill insertion/picking is deferred; no SuperQode skill registry is substituted. |
| `/import` | CLI | External-agent setup/chat import remains in Codex CLI. |
| `/hooks` | Inspect | `:codex hooks` lists Codex hooks. Trust and enablement management remains in Codex CLI. |
| `/review` | Native | `:codex review` with instructions, branch or commit targets. |
| `/rename` | Native | `:codex rename <name>`. |
| `/new` | Native | `:codex new [name]`; visible SuperQode history remains on screen, and future prompts use a fresh Codex thread. |
| `/archive` | Native | `:codex archive [id]`; SuperQode stays open. |
| `/delete` | CLI | Permanent session deletion remains in Codex CLI. |
| `/resume` | Native | `:codex resume` lists sessions; provide an ID or `--last` to activate one. |
| `/fork` | Native | `:codex fork [id]`. |
| `/worktree` | Deferred | Native Codex worktree ownership/handoff requires separate integration. |
| `/app` | CLI | Continue-in-desktop remains in Codex CLI. |
| `/init` | Deferred | AGENTS.md generation can be requested in chat. A dedicated Codex init action is not implemented. |
| `/compact` | Native | `:codex compact`. |
| `/recap` | Deferred | A distinct recap action is not implemented; compaction remains available. |
| `/plan` | Native | `:codex plan on` / `off`; uses the server's advertised collaboration preset and built-in mode instructions on subsequent turns. |
| `/voice` | Deferred | Realtime audio transport and device controls are not implemented. |
| `/goal` | Deferred | Goal mutation and unattended turn continuation need a dedicated event/lifecycle implementation; no `:codex goal` facade is exposed. |
| `/agents` | Partial | `:codex agents` lists current-thread descendants with full IDs; `:codex resume <id>` switches thread. No global daemon command center. |
| `/side` | Deferred | Temporary side-chat lifecycle is not implemented. Durable forks remain available. |
| `/btw` | Deferred | Temporary side-chat alias; no parity is claimed. |
| `/copy` | Client | `:codex copy` delegates to SuperQode's response-copy UI. |
| `/export` | Deferred | Codex Markdown transcript export requires paginated history collection and a destination workflow. |
| `/raw` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/tui` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/diff` | Client | `:codex diff` delegates to SuperQode's workspace diff review, including its existing staged/unstaged/untracked behavior. |
| `/mention` | Client | Use SuperQode file mentions and attachments in its composer; there is no `:codex mention` picker. |
| `/status` | Native | `:codex status [--probe]`, `:codex thread`, `:codex account`; local connection and live RPC diagnostics. |
| `/daemon` | Partial | `:codex attach ws://127.0.0.1:<port>` attaches an explicitly selected user-owned listener. Startup, shutdown and remote pairing remain in Codex CLI. |
| `/warnings` | Partial | Turn warnings render in the event stream; a retained-warning browser is not implemented. |
| `/cd` | Deferred | Codex cwd changes must coordinate SuperQode workspace and permissions. `pwd` is available; change the SuperQode workspace before reconnecting. |
| `/pwd`, `/cwd` | Native | `:codex pwd` (`cwd` alias) shows the executing Codex directory. |
| `/usage` | Partial | `:codex usage` reads account rate limits; `--tokens` reads account token activity. Reset-credit redemption and daily/weekly display pickers remain in Codex CLI. |
| `/debug-config` | Inspect | Alias for `:codex config`; reads effective project layers and managed requirements, redacting credential fields before display. |
| `/title` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/statusline` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/theme` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/pets`, `/pet` | Client/CLI | Codex terminal presentation, keyboard/device or platform setup belongs to its client. Use SuperQode's corresponding UI settings where available; exact behavior is not mirrored. |
| `/mcp` | Inspect | `:codex mcp [verbose]` and `:codex mcp reload`. |
| `/apps` | Partial | `:codex apps [--reload]`; accessible enabled app mentions resolve in the composer. Install and app OAuth management remain in Codex CLI. |
| `/plugins` | Inspect | `:codex plugins [--reload]`; install/remove/toggles remain in Codex CLI. |
| `/logout` | Native | `:codex logout`. |
| `/quit` | Client | Exit SuperQode with its own quit control; no vendor exit command is sent. |
| `/exit` | Client | Exit SuperQode with its own quit control. |
| `/feedback` | CLI | Vendor feedback/log submission remains in Codex CLI. |
| `/rollout` | Native | `:codex rollout` shows the current thread's saved path, when the server reports it. |
| `/ps` | Native | `:codex ps [--cursor <cursor>]` inventories Codex background terminals. |
| `/stop`, `/clean` | Native | `:codex stop` (`clean` alias) stops background terminals. `:codex cancel` separately interrupts the active turn. |
| `/clear` | Partial | Use `:codex new` for a fresh thread. Clearing the visible transcript is a separate SuperQode UI operation; exact `/clear` parity is deferred. |
| `/test-approval` | Internal | Debug/test-only command; intentionally not exposed. |
| `/subagents` | Partial | Alias for `:codex agents`. |
| `/debug-m-drop` | Internal | Debug/test-only command; intentionally not exposed. |
| `/debug-m-update` | Internal | Debug/test-only command; intentionally not exposed. |

## Validation and remaining work

Automated checks cover async UI responsiveness, rejected invalid options before connection, SDK routing isolation, exact review targets, full session IDs/pagination, subscription checks for new chats, login cancellation, idle-only mutations, native Plan settings and credential redaction.

A live signed-out smoke test with an isolated `CODEX_HOME` on 0.160.0 verified skills, hooks, feature flags, permissions, MCP status, effective configuration/requirements, Plan preset discovery and doctor JSON. Metadata created no thread; guarded fresh-chat creation refused the signed-out account before `thread/start`. Doctor reported the expected unhealthy state for an empty installation home. No real login, model inference, cloud task, plugin installation or user-session mutation was performed.

Installed-schema checks gate experimental controls. Daily CI checks both pinned
0.160.0 and `@openai/codex@latest`, including real thread/reviewer/daemon protocol
checks with isolated storage and no inference. Publish includes the approval and
dynamic-tool regression contracts.

Remaining separate lifecycle work: unattended native goals, queued turns,
side chats, transcript export, plugin mutation and cloud/worktree handoffs.
SuperQode does not expose sandbox-bypassing shell/process RPCs or copy ChatGPT
tokens. Connection overrides do not write persistent Codex configuration;
explicitly confirmed rule amendments and MCP OAuth can cause Codex-managed
persistent writes. Built-in Codex actions that do not ask for approval remain
governed by Codex rather than the host executor.
