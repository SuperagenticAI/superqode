# Jev Tool Routing Commands

The `superqode optimize` command group adds local, provider-neutral Jev Tool
Routing to supported coding harnesses. Start in shadow mode so Jev recommends a
smaller catalogue while the harness still receives its complete tool list.

For the feature overview, architecture, supported-harness matrix, environment
variables, Python SDK, HTTP and MCP service, safety model, benchmark summary,
and troubleshooting, start with the
[Jev Tool Routing guide](../advanced/jev-tool-routing.md).

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

## Benchmark snapshot: 21 September 2026

This snapshot was collected with SuperQode 2.4.10 and a routing threshold of
0.30. Each harness received the same calculator task: read two Python files,
run a two-test `unittest` suite, report its status, and evaluate `add(19, 23)`.
Shadow mode was the full-catalogue baseline; enforce mode sent Jev's selected
catalogue. Grok Build, Claude Code, and OpenCode were run twice per mode in
alternating order. Every included run returned the expected answer and passing
test result.

"Input" below is the sum of provider-reported uncached input, cache creation,
and cache-read input across every model call in a run. Cost is the amount
reported by the harness. Wall time includes gateway startup, the Jev decision,
model calls, and tool execution.

| Harness and model | Coding catalogue | Schema bytes | Avg shadow input | Avg enforce input | Input change | Avg shadow cost | Avg enforce cost | Avg wall time, shadow / enforce |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Grok Build 1.0.40, `grok-4.6` | 25 -> 7 | 75.8% lower | 33,188 | 16,287 | 50.9% lower | $0.04261 | $0.02766 | 11.64s / 13.92s |
| Claude Code 2.1.275, Haiku 4.5 | 28 -> 2 | 86.0% lower | 112,584 | 30,744 | 72.7% lower | $0.03582 | $0.01302 | 10.38s / 10.61s |
| OpenCode 1.17.11, `gemini-3.8-flash` | 10 -> 6 | 41.1% lower | 33,172 | 32,403 | 2.3% lower | $0.02728 | $0.02709 | 9.08s / 10.11s |

The Grok aggregate report also contained a one-tool utility request. Across the
two coding calls plus that utility request, each run reported 51 -> 15 tool
entries and 89,640 -> 21,730 schema bytes. The 25 -> 7 figure above isolates the
coding catalogue seen on each model step.

Claude's first shadow repetition reached the 1.5-second Jev timeout by 2ms and
failed open, so Claude received all 28 tools as designed. Its matching enforce
run completed routing in 1,458ms. The second pair completed routing in both
modes. Shadow still forwarded the full catalogue in every baseline run.

OpenCode demonstrates why schema reduction and end-to-end cost must be reported
separately. Its catalogue was consistently smaller, while one enforce
repetition added an extra model step. Across the two-run averages, model input
and cost were effectively flat and enforce was about one second slower.

Pi's stock four-tool surface produced 4 -> 4 tools and 0% schema reduction in
one run per mode; both tasks passed. Codex 0.155.1 completed the task through
ChatGPT-authenticated traffic and reported 22,769 input tokens, but its request
contained zero client-visible tool definitions. That route remains
`gateway-limited`. Antigravity remains `detect-only`.

The coding-model-free benchmark produced the following result from one local
run:

| Scenario | Tools | Reduction | Required-tool recall | Jev latency |
| --- | ---: | ---: | ---: | ---: |
| Workspace test | 20 -> 6 | 70% | 100% | 810ms |
| Web research | 20 -> 9 | 55% | 100% | 620ms |
| Image task | 20 -> 7 | 65% | 100% | 682ms |
| Database analysis | 20 -> 7 | 65% | 100% | 567ms |
| Browser form | 20 -> 7 | 65% | 100% | 655ms |
| **Average** | | **64%** | **100%** | **667ms** |

The authenticated Cloud Run service selected the same tool sets for all five
scenarios. Its average server-reported Jev latency was 556ms. These small
samples establish integration behavior and expose variance; they are not a
statistical performance distribution. Re-run the commands against your own
catalogues and tasks before using the figures for capacity or budget planning.

## Reproduce the benchmarks

Run the following from a clean SuperQode checkout. The published snapshot used
SuperQode 2.4.10, Grok Build 1.0.40, Claude Code 2.1.275, OpenCode 1.17.11,
Codex 0.155.1, and a routing threshold of 0.30. Record your installed versions
with the results because harness catalogues and model behavior change.

### 1. Install and check the routing path

```bash
git clone https://github.com/SuperagenticAI/superqode.git
cd superqode
uv sync

export TYPESAFE_API_KEY="..."
uv run superqode optimize doctor
uv run superqode optimize setup --json
```

Capture the executable versions alongside the raw results:

```bash
uv run superqode --version
grok --version
claude --version
opencode --version
pi --version
codex --version
```

Missing harnesses can be omitted; `optimize doctor` distinguishes an absent
executable from a route that is installed but limited by its protocol.

`optimize setup` makes one live Jev call and writes no harness configuration.
Keep provider credentials in environment variables. The benchmark routes used:

| Route | Required credential |
| --- | --- |
| Grok Build with xAI | `XAI_API_KEY` |
| Claude Code with Anthropic | `ANTHROPIC_API_KEY` |
| OpenCode or Pi with Google | `GEMINI_API_KEY` |
| Codex with the public OpenAI API | `OPENAI_API_KEY` |
| Codex subscription route | Existing `codex login` session |

Only export credentials for routes you intend to run. The provider and harness
processes inherit the shell environment; SuperQode does not serialize those
keys into its temporary harness configuration or benchmark logs.

### 2. Reproduce the labeled routing evaluation

This command uses the five 20-tool scenarios embedded in SuperQode. It calls
Jev, but it does not invoke a coding model:

```bash
mkdir -p benchmark-results
uv run superqode optimize bench --threshold 0.30 --json \
  | tee benchmark-results/labeled-routing.json
```

The JSON contains every selected-tool count, missing required tool, recall,
reduction, and Jev latency. A successful reproduction has
`missing_required: []` for each scenario. Selection and latency can vary as
the routing model changes, so retain the raw JSON with the date and SuperQode
version.

### 3. Prepare the end-to-end calculator task

Use the committed fixture rather than recreating files by hand:

```bash
REPO_ROOT="$PWD"
FIXTURE="$(mktemp -d)/jev-tool-routing"
cp -R examples/bench/jev-tool-routing "$FIXTURE"
cd "$FIXTURE"
python -m unittest -q

SUPERQODE="$REPO_ROOT/.venv/bin/superqode"
PROMPT='Read calc.py and test_calc.py, run python -m unittest -q from this directory, then report the test count, status, and add(19, 23). Do not modify files.'
mkdir -p benchmark-results
set -o pipefail
```

The control must report two passing tests. The prompt and fixture are identical
for shadow and enforce runs. Shadow asks Jev for a selection while forwarding
the full catalogue; enforce forwards the selected catalogue.

### 4. Run matching shadow and enforce pairs

Run each pair from the fixture directory. Use a fresh session each time and
alternate modes: shadow 1, enforce 1, shadow 2, enforce 2. The commands below
write the complete harness output and the final SuperQode routing report to
files.

Grok Build with xAI:

```bash
export XAI_API_KEY="..."

/usr/bin/time -p "$SUPERQODE" optimize run grok \
  --provider xai --mode shadow --threshold 0.30 -- \
  --model grok-4.6 --disable-web-search --no-subagents \
  --permission-mode dontAsk --output-format json --single "$PROMPT" \
  2>&1 | tee benchmark-results/grok-shadow-1.log

/usr/bin/time -p "$SUPERQODE" optimize run grok \
  --provider xai --mode enforce --threshold 0.30 -- \
  --model grok-4.6 --disable-web-search --no-subagents \
  --permission-mode dontAsk --output-format json --single "$PROMPT" \
  2>&1 | tee benchmark-results/grok-enforce-1.log
```

Claude Code with Anthropic:

```bash
export ANTHROPIC_API_KEY="..."

/usr/bin/time -p "$SUPERQODE" optimize run claude \
  --provider anthropic --mode shadow --threshold 0.30 -- \
  --model haiku --print --output-format json --permission-mode dontAsk \
  --no-session-persistence "$PROMPT" \
  2>&1 | tee benchmark-results/claude-shadow-1.log

/usr/bin/time -p "$SUPERQODE" optimize run claude \
  --provider anthropic --mode enforce --threshold 0.30 -- \
  --model haiku --print --output-format json --permission-mode dontAsk \
  --no-session-persistence "$PROMPT" \
  2>&1 | tee benchmark-results/claude-enforce-1.log
```

OpenCode with Google:

```bash
export GEMINI_API_KEY="..."

/usr/bin/time -p "$SUPERQODE" optimize run opencode \
  --provider google --model gemini-3.8-flash --mode shadow --threshold 0.30 -- \
  run --format json "$PROMPT" \
  2>&1 | tee benchmark-results/opencode-shadow-1.log

/usr/bin/time -p "$SUPERQODE" optimize run opencode \
  --provider google --model gemini-3.8-flash --mode enforce --threshold 0.30 -- \
  run --format json "$PROMPT" \
  2>&1 | tee benchmark-results/opencode-enforce-1.log
```

Pi with Google:

```bash
/usr/bin/time -p "$SUPERQODE" optimize run pi \
  --provider google --model gemini-3.8-flash --mode shadow --threshold 0.30 -- \
  --print --no-session "$PROMPT" \
  2>&1 | tee benchmark-results/pi-shadow-1.log

/usr/bin/time -p "$SUPERQODE" optimize run pi \
  --provider google --model gemini-3.8-flash --mode enforce --threshold 0.30 -- \
  --print --no-session "$PROMPT" \
  2>&1 | tee benchmark-results/pi-enforce-1.log
```

Repeat the two commands for Grok Build, Claude Code, and OpenCode with filenames
ending in `-2.log`. The published Pi check used one run per mode because its
stock catalogue contained only four core tools and remained 4 -> 4.

Codex can be checked separately:

```bash
/usr/bin/time -p "$SUPERQODE" optimize run codex \
  --provider openai --mode shadow --threshold 0.30 -- \
  exec --sandbox read-only --ephemeral --skip-git-repo-check "$PROMPT" \
  2>&1 | tee benchmark-results/codex-shadow.log
```

Codex subscription traffic currently exposes zero client-side tool definitions
to the gateway. This command verifies the route and task result; it cannot
reproduce a catalogue reduction until Codex exposes a suitable hook.

### 5. Validate and calculate the comparison

For every included run, confirm all of the following before averaging:

- the harness reports two passing tests;
- the final answer reports `add(19, 23) = 42`;
- the SuperQode report has at least one routed request;
- enforce reports fewer selected schema bytes when the catalogue is routable;
- any timeout is retained as a fail-open event, not silently discarded.

Use the terminal's `real` value for wall time. Use the harness's own JSON for
input tokens and reported cost. In the snapshot, input is uncached input plus
cache-creation input plus cache-read input across every model request. Use the
final `Jev Tool Routing report` for aggregate tool entries, schema bytes, cache
hits, unroutable catalogues, and fail-open errors. Average the two repetitions
within each mode, then calculate reduction as:

```text
reduction_percent = (shadow_average - enforce_average) / shadow_average * 100
```

Publish raw logs or their non-sensitive extracted metrics with any result.
Review them first: some harness JSON can include the task prompt, workspace
paths, model responses, or other local context. Never publish credentials or
authorization headers.

The managed preferences live at `~/.superqode/jev-routing.json` (or beneath
`SUPERQODE_HOME`) with `0600` permissions. Launchers default to `~/.local/bin`;
set `SUPERQODE_BIN_DIR` or pass `--bin-dir` to choose another location. A
launcher is removed only when it still carries SuperQode's management marker,
so disable and uninstall never delete a user-owned replacement.

For the standalone HTTP gateway, Python SDK, service, and deployment details,
see [Serve Commands](serve-commands.md) and
[SystemOne and Jev](../advanced/systemone.md#jev-tool-routing).
