# Prime Intellect Prime Agent

[Prime Agent](https://github.com/PrimeIntellect-ai/prime-agent) is Prime
Intellect's open-source (MIT) RLM agent for coding and long-running autonomous
tasks. It speaks the Agent Client Protocol natively, so SuperQode connects to it
over ACP without an adapter.

Prime Agent is an RLM harness: a persistent IPython kernel is the model's only
primary tool. Files, shell commands, skills, and recursive sub-agents are all
reached by writing Python rather than by separate tool calls.

## Connection route

| Route | Primary command | Authentication | Harness owner |
| --- | --- | --- | --- |
| Prime Agent ACP | `:prime connect` | `prime-agent` then `/login` | Prime Agent |

SuperQode starts `prime-agent --mode acp`. Prime Agent owns the model, the
IPython kernel, sub-agent recursion, and its continual harness state. SuperQode
provides the terminal, model selection, session surface, and ACP events.

Prime Agent also appears under `:connect` in the Subscriptions group, because
what its login buys is an upstream model on a plan you already pay for.
`:connect prime-agent` reaches the same ACP route as `:prime connect`, and
reports the install and login steps when Prime Agent is not ready yet.

SuperQode cannot drive this OAuth itself. Prime Agent has no `login`
subcommand, and neither its ACP nor its RPC mode exposes an authentication
call; `/login` lives only in its interactive terminal.

`:prime login` therefore hands the terminal over. SuperQode suspends, Prime
Agent starts in its own interface, and after `/login` and quitting Prime the
SuperQode session resumes and re-reads the credential store. The browser opens
only after an explicit confirmation, and SuperQode never implements Prime
Intellect's OAuth or copies a token.

## Install

```bash
curl -fsSL https://app.primeintellect.ai/prime-agent/install.sh | sh
```

Confirm the install from the TUI:

```text
:prime status
```

## Authentication

Prime Agent manages its own credentials in `~/.prime/agent/auth.json`.
SuperQode never reads or stores them; `:prime status` reports only which
provider names are present.

```bash
prime-agent
/login
```

Subscription logins are ChatGPT Plus or Pro, Claude Pro or Max, and GitHub
Copilot. API keys for Anthropic, OpenAI, Google, Groq, OpenRouter and others are
read from the environment or the auth file.

### GitHub Copilot model entitlement

A Copilot login lists Prime Agent's full Copilot catalog, but the account only
serves models that have been enabled for it. A model that is listed but not
enabled fails with:

```text
The requested model is not supported
```

Enable the model in VS Code under Copilot Chat, model selector, Enable. Then it
becomes usable from SuperQode.

## Local models, no API key

Prime Agent reads extra providers from `~/.prime/agent/models.json`, so local
Ollama, LM Studio, or vLLM endpoints work offline and at no cost:

```json
{
  "providers": {
    "ollama": {
      "baseUrl": "http://localhost:11434/v1",
      "api": "openai-completions",
      "apiKey": "ollama",
      "compat": { "supportsDeveloperRole": false },
      "models": [{ "id": "qwen3.5:9b" }]
    }
  }
}
```

The `apiKey` value is required but ignored by Ollama. Set
`compat.supportsDeveloperRole` to `false` for servers that reject the
`developer` role used by reasoning-capable models.

Writing that file by hand is optional. `:prime local` scans for running local
servers, registers every chat model it finds, and leaves any provider it did not
discover untouched, so a hand-written entry is never dropped. Embedding and
reranking models are skipped because they cannot drive an agent loop.

Local providers appear in `:prime models` alongside subscription models.

## TUI commands

| Command | Behavior |
| --- | --- |
| `:prime` | Show the command surface |
| `:prime connect [model]` | Connect Prime Agent over ACP |
| `:prime models [search]` | Pick a model from the catalog, optionally filtered |
| `:prime model <provider/model>` | Set a model directly, without the picker |
| `:prime local` | Register local model servers with Prime Agent |
| `:prime depth [n]` | Recursion depth for the next launch |
| `:prime goal [text]` | Seed a persistent goal |
| `:prime autonomous [gate]` | Autonomous mode and completion gates |
| `:prime agents` | Live sessions and the RLM subagent tree |
| `:prime schedule` | Scheduled and recurring prompts |
| `:prime packages` | Installed capability packages |
| `:prime status` | Binary, version, logins, local providers, pinned model |
| `:prime doctor` | Background service health |
| `:prime update` | Run Prime Agent's own updater |
| `:prime login` | Authentication steps, including local models |
| `:prime help` | Command reference |

`sessions` and `subagents` are accepted for `agents`, `services` for `doctor`,
and `schedules` and `package` for their plural and singular forms.

### Reading the subagent tree

`:prime agents` reads Prime's background service, so it shows the RLM recursion
as it happens. Children are indented by `rlmDepth` and counted separately:

```text
    main                 running     active
      └─ reviewer        running     idle       depth 1
      └─ test-runner     running     idle       depth 1

  1 root, 2 RLM subagent(s)
```

Sessions started from SuperQode over ACP run in their own process and are not
held by the background service, so they do not appear here. This view covers
agents started with `prime-agent` directly, and the children they spawn.

`:prime-agent` is accepted as an alias. The generic route
`:connect acp prime-agent` also works and uses Prime Agent's default model.

### Model selection requires a reconnect

Prime Agent fixes its model when the process starts and advertises no
`availableModels` over ACP, so the ACP-canonical `session/set_model` call cannot
move it. SuperQode therefore pins the selection and relaunches the process with
`--provider` and `--model` rather than switching in place.

```text
:prime models qwen
:prime model ollama/qwen3.5:9b
```

A selector without a provider is passed through as `--model` alone and left for
Prime Agent to resolve.

## Inspect the ACP route

```bash
superqode agents show prime-agent
superqode agents doctor prime-agent --live
```

## Execution model and trust

Prime Agent's IPython kernel runs with the permissions of the user who launched
SuperQode. There is no sandbox by default, and Prime Agent does not send ACP
permission requests, so SuperQode's approval prompts never appear on this route.

Treat a Prime Agent session as equivalent to running Python and shell commands
directly. For untrusted repositories, isolate the process externally with a
container or a dedicated worktree, or use Prime Agent's own sandbox extension.

## RLM routes compared

SuperQode has three RLM paths. They solve different problems and none replaces
another.

| Route | Engine | Recursion | Streaming | Sandbox |
| --- | --- | --- | --- | --- |
| Prime Agent | TypeScript host with an IPython kernel | Live sub-agent sessions with messaging | Yes | None by default |
| [RLM Code](../advanced/rlm-code.md) | Python, in process | Configured depth and branch budgets | No | Docker by default |
| [Recursive tools](../local-recursive-dynamic-coding.md) | SuperQode agent loop | `context_handle` and `spawn_harness` | Yes | Docker friendly |

RLM Code produces a measurable trajectory with length-generalization metrics and
is suited to sandboxed, repeatable analysis. Prime Agent spawns live sub-agents
and mutates its own harness state during a session, which suits long-horizon
coding. Choose RLM Code when the run has to be measured and contained, and Prime
Agent when the run has to keep going.

## RLM settings pinned at launch

Prime reads goal, autonomous policy and recursion depth when the process
starts. None of them is an ACP field, so SuperQode pins the values and applies
them to the next launch. Changing one reconnects rather than editing a live
session.

```text
:prime depth 3
:prime goal "Get the release green"
:prime autonomous "pytest -q"
:prime autonomous "ruff check ."
:prime connect
```

Goal and autonomous become `--goal`, `--autonomous` and repeated
`--autonomous-gate` arguments. Depth has no flag at all: Prime reads
`RLM_MAX_DEPTH` from the environment, so SuperQode sets it on the agent process
only, never on its own.

`:prime depth 0` disables recursion outright. Prime computes
`allowRecursion` as `depth < maxDepth`, so at zero the sub-agent instructions
are dropped from the system prompt and the model is never told it can spawn
children.

Depth resolves in this order, so a value set inside a Prime session or in its
global settings wins over the environment:

```text
session state  →  inherited config  →  global settings  →  RLM_MAX_DEPTH  →  1
```

`:prime status` shows everything currently pinned, and `:prime connect` reports
it as the session starts. Values that are unset are left entirely alone rather
than sent as defaults.

## In-session commands are not reachable over ACP

`/goal`, `/autonomous` and `/rlm-max-depth` are covered by the launch settings
above. The rest, including `/refine`, `/compact` and `/heartbeat`, run inside a
Prime session and are unreachable over ACP: Prime advertises an empty command
list at `initialize`, and its ACP mode has no command expansion. They have typed
equivalents in RPC mode, which SuperQode does not yet speak.

Sending one as a prompt does not fail loudly. It reaches the model as ordinary
text, and a capable model answers as though it had run, which reads like success
without any of the effect. Run `prime-agent` directly for those, or drive
`prime-agent --mode rpc`, which does expose a command surface.

## Known limits

- ACP mode hosts one session per process, so parallel work needs one process
  per session.
- Token usage and cost are not reported over ACP, so Prime Agent sessions show
  no token accounting in SuperQode.
- Session resume is unavailable on this route because Prime Agent reports
  `loadSession: false`.
