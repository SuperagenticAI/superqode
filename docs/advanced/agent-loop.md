# Inside the Agent Loop

This page describes the SuperQode builtin runtime lifecycle and its execution safeguards, with emphasis on local-model behavior. It identifies the configuration associated with each stage.

The builtin loop lives in `superqode/agent/loop.py` (`AgentLoop`). Other runtimes (ADK, OpenAI Agents, Codex SDK, DeepAgents, PydanticAI) replace this engine but keep the same harness contract.

## The lifecycle of one run

```text
your prompt
  │
  ├─ 1. context window resolved (live probe for local servers)
  ├─ 2. doom-loop guard armed
  │
  ╭─ iteration ──────────────────────────────────────────────╮
  │ 3. steering drained (messages you typed mid-run)         │
  │ 4. tool schemas computed (deferred activations included) │
  │ 5. reminders attached (changed files, stale todos)       │
  │ 6. model called (rate-limit retry + backoff inside)      │
  │ 7. tool calls parsed (JSON repair) and guarded           │
  │ 8. batch executed (parallel only if all read-only)       │
  │ 9. turn diff emitted; compaction if near the window      │
  ╰──── repeat until the model stops calling tools ──────────╯
  │
  ├─ 10. cut at token limit? auto-continue
  ├─ 11. steering pending? keep going
  ├─ 12. rubric set? self-grade, maybe revise
  └─ final answer
```

The following sections describe each lifecycle stage in order.

## 1. Context windows that match reality

Static model metadata does not necessarily reflect the active context window. For example, a model advertised with a 128K context window operates with an 8K window when loaded with `num_ctx 8192`. Before the first call, the loop queries the active server (Ollama `/api/ps`, llama.cpp `/props`, and LM Studio or vLLM/DS4 `/v1/models`) for the loaded context window. It uses that value to calculate compaction thresholds, recent-message retention budgets, and tool-output limits.

Try it in the TUI:

```text
:context           # show the detected window and how it was found
:context 16384     # pin it manually
:context detect    # re-probe
```

## 2-3. Input during an active run

You can send input while the agent is running. For built-in local and BYOK connections, SuperQode injects the message **between the agent's tool calls**, allowing it to affect the current run. The log records this event as `steering the current run`. If the message arrives while the model is completing a response, the run continues with the new input.

On connections that cannot be steered, including ACP agents and `codex-sdk`, messages enter the type-ahead queue and are sent when the agent becomes available. Use `:queue clear` to empty the queue.

From Python, the same mechanism:

```python
loop.steer("also check the README")   # thread-safe; returns True if a run is live
```

## 4. Deferred tools and `tool_search`

Every advertised tool schema consumes prompt tokens on every call. On an 8K local model, 20 schemas can consume a significant portion of the context window. Deferred loading keeps large tool schemas registered but unadvertised until the model requests them:

```bash
export SUPERQODE_DEFERRED_TOOLS=auto    # defer the heavy set, local providers only
# or =all (every provider), or =web_fetch,view_image (exactly these)
```

When deferred loading is enabled, the model receives the smaller `tool_search` schema. A call such as `tool_search(query="fetch a web page")` activates matching tools, whose full schemas are available on the next step. The core coding tools for reading, editing, patching, shell execution, search, and task tracking are not deferred.

## 5. System reminders

Two situations get a `<system-reminder>` note attached to the outgoing request. Reminders ride on the request only and are never stored in history, so they cost context exactly once:

- **A file changed on disk after the agent read it** (your editor, a formatter, another agent). The note lists the files and tells the model to re-read before editing, pre-empting the edit-conflict rejection it would otherwise hit. Each change is announced once.
- **Open todos have gone quiet.** If pending/in-progress todo items exist, a rate-limited nudge (at most every 8 iterations) reminds the model to update or complete them.

A third reminder is opt-in: **memory recall** (`SUPERQODE_AUTO_RECALL=1`) searches your local memory store with the run's prompt and surfaces the top hits once per prompt, clearly labeled as background to verify. See [Memory & Learning](memory.md) for the full capture-and-recall loop.

Disable with `SUPERQODE_REMINDERS=0`.

## 6. Model-call retry and fallback behavior

- **Rate limits and overload** (429, 503, 529, "overloaded"): retried with exponential backoff, honoring `Retry-After`/`retry-after-ms` headers. `SUPERQODE_RATE_LIMIT_RETRIES` (default 3) controls attempts; a provider demanding a pause over 60s surfaces as an error instead of hanging your session.
- **Streaming failures**: one automatic fallback to a non-streaming completion before reporting the error.
- **Empty responses**: retried once non-streaming.

## 7. Tool-call argument normalization

Tool-call arguments can vary across models. The parser normalizes Markdown code fences, double-encoded JSON strings, Python dictionary syntax (`'single quotes'`, `True/None`), trailing commas, and prose surrounding an otherwise valid object. If normalization fails, the tool is not executed with empty arguments. The model receives an error and a valid format example.

**Repeated-call guard:** the third consecutive identical tool call, with the same tool and arguments, is intercepted and replaced with corrective feedback. If the model immediately repeats the call, the run stops with `stopped_reason="loop_detected"`. Calls separated by a different operation do not trigger the guard. Configure the threshold with `doom_loop_threshold` in `AgentConfig` or `SUPERQODE_DOOM_LOOP_THRESHOLD`; a value of `0` disables it.

## 8. Mutation-safe parallelism

Tools declare `read_only`. A turn's tool calls run **concurrently only when every call is read-only** ("read these 5 files" stays fast). Any batch containing an edit, write, shell command, or unknown/MCP tool runs sequentially in call order, so two edits can never race the same file.

## 9. Context management

1. **Bounded tool output.** `read_file` caps output at 2,000 lines or 50 KB with `N:` line numbers and continuation hints. Shell output beyond the model-sized cap is stored in full under `~/.superqode/tool-output`, with seven-day retention and `SUPERQODE_TOOL_OUTPUT_DIR` available as an override. The model receives a head-and-tail preview and the stored path. A loop-level guard applies the same bound to tools that do not enforce their own limits, including MCP and web tools.
2. **Deterministic pruning.** When the conversation approaches the context limit, stale tool outputs older than the protected recent tail are replaced with bounded placeholders. This operation does not require a model call, and current-turn results remain available.
3. **Model-based compaction.** If pruning does not recover sufficient context, earlier turns are summarized into a structured nine-section report. Thresholds scale to the detected context window. Set `SUPERQODE_AUTO_COMPACT=0` to disable compaction.

**Turn diff:** after a turn changes files, the thinking trace includes `Turn changed 2 file(s) (+45/-12): ...`. The combined unified diff is available through `loop.last_turn_diff` for interfaces and hooks.

## 10. Auto-continue on token-limit cuts

When a response stops with `finish_reason="length"` (output token limit) and no tool calls, the loop asks the model to continue from exactly where it stopped and joins the parts, up to `max_auto_continues` times (default 2, `0` disables). The continuation streams from the exact break point.

## 12. Rubric self-grading

Define completion criteria with a rubric:

```bash
superqode -p --rubric "All tests pass. The fix includes a regression test. No TODO left behind." \
  "fix the flaky date test"
# or --rubric @rubric.txt
```

Before the run completes, a separate grader call evaluates the transcript against the rubric. `needs_revision` feedback re-enters the loop up to `max_rubric_rounds`, which defaults to 2. A `satisfied` or `failed` result ends grading. Grader failures do not prevent the run from terminating.

From Python: `AgentConfig(rubric="...", max_rubric_rounds=2)`.

## Prompt-based tool calling (`tool_call_format`)

Some local models have no native tool-calling head at all. Set `tool_call_format: prompt` in a harness spec's `model_policy` (or `AgentConfig(tool_call_format="prompt")`) and the loop:

1. renders the tool catalog and call format into the system prompt,
2. sends **no** native tool schemas,
3. extracts `<tool_call>{"name": ..., "arguments": {...}}</tool_call>` blocks from the response text and executes them exactly like native calls (with the same JSON repair).

`compact-json` / `strict-json` remain argument-style hints for native calling; `native`/unset is the default.

## Quick reference: loop environment variables

| Variable | Effect | Default |
|---|---|---|
| `SUPERQODE_AUTO_COMPACT` | adaptive compaction | on |
| `SUPERQODE_DOOM_LOOP_THRESHOLD` | identical-call intercept threshold | 3 |
| `SUPERQODE_RATE_LIMIT_RETRIES` | overload retry attempts | 3 |
| `SUPERQODE_REMINDERS` | system reminders | on |
| `SUPERQODE_DEFERRED_TOOLS` | deferred tool loading (`auto`/`all`/names) | off |
| `SUPERQODE_TOOL_OUTPUT_DIR` | spill directory | `~/.superqode/tool-output` |
| `SUPERQODE_AUTO_MEMORY` | session-end memory extraction | off |
| `SUPERQODE_AUTO_RECALL` | saved-memory recall at run start | off |

See also: [Tools Catalog](tools-catalog.md) · [Policies & Safety](policies.md) · [Multi-Agent](multi-agent.md) · [Local Context & Compaction](local-context.md)
