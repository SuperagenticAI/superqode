---
title: Harness Hub
description: Discover, build, inspect, run, evaluate, and optimize coding-agent harnesses from one terminal experience.
---

# Harness Hub

The Harness Hub is the catalog. `:connect` is how you start a harness. Browse
what SuperQode can run, inspect setup, and Use an entry that is ready on this
machine.

The Hub brings SuperQode native harnesses, established coding agents, ACP
agents, optional runtimes, model and task presets, and repository-owned custom
HarnessSpecs into one browsable terminal surface. It does not replace those
agents or require a separate desktop application. It gives them a consistent
discovery, setup, switching, continuity, policy, and evidence layer.

## Open the Hub

Launch SuperQode in a repository and enter:

```text
:hub
```

The Hub is a full terminal screen rather than a block appended to the
conversation. Use the mouse or keyboard to:

- search names, runtimes, sources, licenses, and descriptions
- filter to **Ready**, **Needs setup**, **Open source**, **Your harnesses**, or
  **Coming soon** (`a` `r` `s` `o` `c` `n`)
- inspect setup, runtime, provenance, and session-continuity details without
  leaving the Hub
- use an available harness or follow its setup route
- start the custom harness builder

Press `/` to focus search, arrow keys to move, `Enter` to use (or learn more
for coming-soon rows), `I` to inspect in place, `B` to build, and `Esc` to
return. Click a row to preview; Use is explicit. `:hub` opens on **Ready**
when anything is ready on this machine.

## What appears in the Hub

| Hub category | What it contains |
| --- | --- |
| SuperQode harnesses | Native harnesses such as the core, workbench, workflow, and recursive routes available in the installed release |
| Coding agents | Managed connections to established vendor coding agents |
| ACP agents | Installed, featured, recent, and registry-discoverable Agent Client Protocol agents |
| Optional integrations | Harness runtimes that require an explicit optional dependency or external setup, such as LangChain DeepAgents and Hugging Face Tau |
| Model and task presets | Ready-made configurations for a model family or task shape |
| Ecosystem watch | Relevant external harness projects that are discoverable but not yet supported by SuperQode |
| Project harnesses | Repository-owned HarnessSpecs discovered from the current project |

An entry marked **Ready** can be started now (a signed-in coding agent, or a
SuperQode harness that already has a model). **Needs a model** is a SuperQode
harness such as Core or RLM: the harness is installed, but Use opens Local / an
API key / a plan because there is nothing to talk to yet. **Needs setup** means
a dependency, executable, or login is missing. **Coming soon** is an ecosystem
entry SuperQode cannot run. These states describe startability, not a security
certification.

The Hub catalogs harnesses, and only harnesses. Model providers, local
inference servers, memory providers, sandboxes, protocol surfaces,
observability sinks, and chat channels are all real integrations, but someone
opening the Hub is choosing a harness, not assembling a dependency list. Those
live in the [integration catalog](integrations/index.md), and models are
selected with `:connect` once a harness is active.

### Open source harnesses

Whether a harness is open source is a property of the harness itself, not of
the route SuperQode takes to it. OpenCode arrives over ACP, Codex arrives as a
vendor connection, DeepAgents arrives as an optional runtime, and Aider is not
runnable from SuperQode at all, yet all four are open source. Openness is
therefore a filter rather than a category, so nothing has to move out of the
category that explains how to connect it.

```text
:hub
```

Press `o`, or select **Open source**. From the CLI:

```bash
superqode hub list --openness open
superqode hub list --openness closed
superqode hub show deepagents
```

Each record carries `openness`, `license`, and `repository`. Four sources
answer the question, in order of precedence:

| Source | Applies to |
| --- | --- |
| A license SuperQode has verified against the project's published metadata | Any entry |
| The `open-source` tag in the bundled ACP agent catalog | ACP agents |
| The `harness_openness` field on the vendor connection profile | Vendor coding agents |
| SuperQode's own Apache-2.0 source | SuperQode harnesses and presets |

Anything none of these can answer stays blank and is reported as **Not
published** rather than assumed either way. Two cases this protects:
a source-available license such as the Functional Source License is not
reported as open source, and a repository's own HarnessSpec is never given a
license SuperQode has no way to know.

Openness says nothing about readiness, support, or security. It answers one
question: can you read and fork the code that runs the loop.

In the terminal these states are measured on the machine you are using. In the
published snapshot they cannot be, so `--public` reports the structural answer
instead: harnesses SuperQode ships are **Ready** for everyone, and any route
that wraps an external CLI, account, or optional package is **Needs setup** for
everyone. A public catalog must never report the exporting machine's installed
binaries as product truth.

### Logo ownership

The logo identifies who owns the runnable implementation rather than the model
family or upstream project associated with it. Official vendor connections, ACP
agents, inference engines, and upstream runtimes use their official logos.
SuperQode-built native harnesses and built-in presets use the SuperQode logo,
even when they target a model family such as GLM, Qwen, Kimi, Gemma, DeepSeek,
or MiniMax.

For example, the official Prime Agent connection uses the Prime Intellect logo.
The `prime-agent-python` built-in preset uses the SuperQode logo because its
host integration and HarnessSpec are maintained by Superagentic AI. The
entry's provenance and **Based on** fields still identify the upstream runtime
without implying that the SuperQode implementation is an official vendor
product.

## Evaluation and optimization

The Hub is where harnesses are evaluated and optimized, not only discovered, so
every HarnessSpec entry carries the commands that measure it and improve it,
next to the commands that run it.

Inspecting a native or repository-owned harness shows an **Evaluate** block and
an **Optimize** block:

```text
superqode harness test --spec harness.yaml
superqode harness eval --spec harness.yaml --tasks eval-tasks.yaml
superqode harness bench --manifest harnessbench.yaml

superqode harness optimize-omni --spec harness.yaml --tasks eval-tasks.yaml
superqode harness optimize --spec harness.yaml --tasks eval-tasks.yaml
superqode harness promote stage
```

Vendor and ACP entries show neither: the connected agent owns its own loop, and
the Hub says so rather than implying SuperQode can tune it.

The optimizers and evaluators themselves are not Hub entries. Every one follows
the same contract: start from a versioned artifact, measure it, stage a
candidate, gate the candidate, and let a human adopt it. See
[Optimization Story](advanced/optimization.md) for the full workflow and
[Running, Measuring, and Optimizing a Harness](advanced/harness-optimization.md)
for the run/measure/optimize split.

### ZCode

[ZCode](https://zcode.z.ai/en) is indexed under **Ecosystem watch** as Z.AI's
official desktop coding harness for GLM-5.3. Inspecting it in the TUI shows its
agent-loop ownership, tools, supported platforms, official installation and
documentation, and the current SuperQode integration boundary.

ZCode is not directly runnable from SuperQode today. Its public documentation
does not currently expose an ACP server, headless CLI, or external agent SDK,
so the Hub marks it **Integration pending** rather than presenting a false
setup command. This is separate from SuperQode's supported `:connect zai`
general-API route and the community `:connect glm-cli` ACP agent.

### Letta Code

[Letta Code](https://www.letta.com/) is indexed under **Ecosystem watch** as
Letta's Apache-2.0 memory-first coding harness. Install with
`npm install -g @letta-ai/letta-code` and run `letta`. From Connect it is an
Open row (`:connect letta`): configure a provider with `/connect` or Letta
Cloud with `/login`. SuperQode does not launch the Letta loop from that row
yet.

### Warp Agent

[Warp Agent CLI](https://www.warp.dev/agent-cli) is indexed under **Ecosystem
watch** as Warp's AGPL-3.0 standalone agent (`warp`). From Connect it is an
Open row (`:connect warp`). Install with
`curl -fsSL https://app.warp.dev/download/agent-cli | bash`, then sign in or
export `WARP_API_KEY`. SuperQode does not attach Warp from that row yet.

SuperQode does not drive Warp from any row. Warp Agent's loop runs on Warp's
servers and the open client is AGPL-3.0, so there is no component to embed and
no protocol to speak. Warp has said it plans to support ACP
([warpdotdev/warp#9233](https://github.com/warpdotdev/warp/issues/9233)).
SuperQode will look at an attach again when an ACP surface or a licence change
makes one clean. Until then the row is a pointer to running Warp yourself.

### jcode

[jcode](https://jcode.sh) is indexed under **Ecosystem watch** as an
MIT-licensed terminal coding harness written in Rust, focused on low memory
use, fast start, and parallel agent swarms.

It is not runnable from SuperQode today, but its entry states a different
reason from ZCode's. jcode documents a headless `jcode run`, a TypeScript SDK,
and a versioned harness API, so a SuperQode route is buildable once someone
implements and tests one. The Hub distinguishes "no published integration
surface" from "a surface exists but no connector has been built yet".

### Headlong

[Headlong](https://headlong.ai) is indexed under **Ecosystem watch** as the
Laude Institute's Apache-2.0 agent microharness, under 10K lines of Bash and
built around `shellm`, a recursive-language-model (RLM) core that lets an
agent write bash, run it, read the output, and keep thinking between messages
instead of going idle after a task.

It is not runnable from SuperQode today, and it is a weaker Hub case than
jcode's rather than the same one. jcode publishes a headless `jcode run`, a
TypeScript SDK, and a versioned harness API: a task contract. Headlong
publishes `<agent> hello`, `ada chat`, `ada dash`, and a set of composable
`bin/` executables (`shellm`, `traj`, `context`), but no ACP server, MCP
server, SDK, or task-runner API. `<agent> hello` is a one-shot observation
sent into a standing mind that may choose not to reply, not a task call with
a result contract. It has a Unix surface to attach to instead: starting or
stopping the identity, tailing its trajectory. That surface is why the entry
reads stronger than ZCode's "nothing to connect to" case, even though there
is still no run contract to speak of. Install with
`curl -fsSL https://headlong.ai/install.sh | bash`; the installer interviews
you for an agent name and personality, and that name becomes the CLI command.

SuperQode already has three RLM routes it can run: Native RLM (first-party),
RLM Code (an optional package), and Prime Agent (a connected product over
RPC/ACP), compared in
[RLM Routes Compared](advanced/rlm-routes.md#an-external-rlm-headlong-related-not-runnable).
All three build on the same published Recursive Language Models research that
Headlong cites as prior art. Headlong sits closest to Prime Agent in kind:
both are live, self-modifying agents from the same research family (Alex
Zhang is the RLM paper's author and a Prime Agent co-author), though the word
"persistent" applies differently to each. Prime's daemon persists between
prompts; Headlong's mind never idles between them. The property none of
SuperQode's routes share with it is structural: it has no turn. Native RLM's
resident root worker keeps a session alive after the TUI detaches, but that
is still one completable turn. Headlong keeps generating thoughts whether or
not anyone is attached to it.

## Results and Activity

Important actions no longer depend on the bottom of the transcript. Harness
details, setup failures, and other consequential results open in a focused
screen. Completed state changes also produce a short notification and a compact
transcript receipt.

Use `:activity` to revisit session results and run their primary recovery or
next-step action. This gives both mouse users and keyboard users a clear way to
recover something they dismissed or did not notice.

## CLI and catalog data

The noninteractive CLI exposes the same inventory used by the TUI:

```bash
sq hub
sq hub list --search codex
sq hub list --readiness ready
sq hub show codex
sq hub list --json
sq hub list --public --json
```

The JSON form is a versioned interface for documentation, release automation,
and the SuperQode landing page. Use `--public` for a publication-safe snapshot
that excludes repository and user-registry harnesses. Each record includes identity, category,
runtime, source, readiness, integration level, continuity behavior, setup
guidance, and warnings. Executable internal objects are deliberately excluded.

Inspect data also includes installation guidance, TUI and shell commands,
documentation and upstream links, capabilities, tools, policies, HarnessSpec
inheritance, and a curated popularity rank. Native and repository-owned
HarnessSpecs derive their tool and policy details from the spec itself. Vendor
and ACP entries state when the external agent owns the tool loop instead of
guessing at a tool inventory.

For example, inspecting Antigravity shows its SuperQode command family:

```text
:connect antigravity
:agy status
:agy agents
:agy models
:agy plugin list
```

Inspecting a native harness such as Workbench shows its declared tools,
sandbox, approval profile, shell and network policy, checks, workflow, and the
equivalent `superqode harness run` command.

The index reflects the current installation and repository. A website build
can snapshot it for public discovery; the TUI overlays the current machine's
actual readiness and project harnesses when opened.

## Build your own harness

Choose **Build your own** in the Hub or use:

```text
:connect build
```

The builder can create a native HarnessSpec, import a compatible agent or
harness, or begin from a preset. Store the result in the repository when the
team needs behavior that is portable, reviewable, evaluable, and versioned with
the code.

Continue with [Bring Your Own Harness](getting-started/bring-your-own-harness.md)
for the authoring workflow and [Harness Engineering](harness-engineering.md)
for the lifecycle from design through evaluation and promotion.

## Model search migration

Earlier versions used `:hub` as an opt-in local model-search mode. Model search
now has the explicit command:

```text
:local search <model>
```

During migration, `:hub model <model>` remains an alias. Plain `:hub` always
opens the Harness Hub.
