# PiPy: a pi twin in Python

PiPy is a native SuperQode harness that replicates the architecture of
[pi](https://github.com/earendil-works/pi) in Python: an event-first agent loop,
parallel tool execution, mid-run steering, an append-only session tree, and pi's
own tool surface and prompt shape.

It is opt in. `core` remains the default harness, and installing or upgrading
SuperQode changes nothing until you select PiPy.

## Select it

```bash
superqode --harness pipy
```

In the TUI, open `:connect`, then select **PiPy (pi twin)**. The aliases `pi`
and `pi-python` resolve to the same harness.

## Pure host permissions

PiPy executes tools with the permissions of the process that launched
SuperQode. There are no approval prompts, no sandbox, no execution policy and no
network policy on this harness. That matches pi, where isolation is the user's
job through a container or a VM.

This is the opposite posture to every other native SuperQode harness. Selecting
PiPy is opting into it, and the harness picker says so before you do.

If you want the policy stack, use `core` or `workbench`:

```bash
superqode --harness core
```

The PiPy code path does not import SuperQode's approval manager, permission
manager or sandbox. A test walks the import graph of the whole package to keep
it that way, and a second test asserts that a PiPy run which writes a file emits
no approval event.

## What PiPy replicates

| Area | Behaviour |
| --- | --- |
| Loop | Parallel tool execution by default, with per-tool sequential opt out. `tool_execution_end` in completion order, tool results in assistant order |
| Streaming | Tool output reaches the model while a tool is still running |
| Tools | `read`, `bash`, `edit`, `write` by default; `grep`, `find` and `ls` selectable |
| Editing | `edit` takes an array of replacements, all matched against the original file, with fuzzy matching through smart quotes and Unicode dashes |
| Prompt | Tool list built from each tool's own snippet, deduplicated guidelines, project context, skills, working directory last |
| Sessions | Append-only JSONL tree with branch, resume, fork and compaction |
| Steering | Messages injected mid-run, and follow-ups that wait for the agent to settle |

Behaviour is tracked against pi source by the suite in `tests/pipy/`, with a
test named for each replicated behaviour.

## Sessions

PiPy keeps its own session store, separate from every other harness:

```text
~/.superqode/pipy/sessions/--Users-you-your-repo--/<timestamp>_<id>.jsonl
```

One directory per working directory, one file per session. The file format is
byte-compatible with pi's own version 3 session files, so a PiPy session opens
in pi and a pi session opens in PiPy.

Sessions are append-only. Compaction, branching and renaming all add entries
rather than rewriting history, so navigating back to an earlier point is
lossless.

Set `SUPERQODE_PIPY_SESSION_DIR` to move the store, or `SUPERQODE_PIPY_DIR` to
move the whole PiPy root.

## Reading an existing pi repository

PiPy reads pi's project-level resources so an existing pi repository works
without changes:

- `.pi/skills/**/SKILL.md`
- `.pi/prompts/*.md`
- `AGENTS.md` or `CLAUDE.md`

PiPy writes only under `~/.superqode/pipy/`. It never writes into `~/.pi/`, so a
real pi installation cannot be affected.

## Switching harnesses

Each harness keeps its own session store. Switching to PiPy starts or resumes a
PiPy session; switching away starts or resumes that harness's own session. The
conversation does not transfer, and neither store is modified by the other.

That is a session boundary, not a fault. Fork a PiPy session if you want to
explore an alternative without disturbing the original:

| Command | Effect |
| --- | --- |
| `compact` | Summarise older context and keep working |
| `tree` | Move to another point in the session tree, summarising the branch left behind |
| `fork` | Copy the current branch into a new session, leaving the source untouched |
| `resume` | Reopen a previous session for this directory |
| `new` | Start a fresh session |
| `name` | Name the current session |
| `model` | Switch the model for the next turn |
| `session` | Show the session id, path, tree leaf and stats |
| `export` | Render the current branch as Markdown |
| `skill` | Invoke a skill by name |
| `prompt` | Run a prompt template by name |

## Providers

PiPy runs through SuperQode's provider gateway, so every provider SuperQode
supports is available. Stop reasons, token usage and cost are carried through to
the session record.

Image content is not yet passed to the model on the gateway path. Reading an
image reports its type but does not attach it.

## Extensions

SuperQode extensions apply to PiPy through the normal hook points: session
start, prompt submit, before and after a tool call, turn complete and stop. An
extension may block a tool call, which pi's own extensions can also do.

`PERMISSION_REQUEST` is deliberately not wired, because that hook point is the
approval stack PiPy omits.

## Relationship to Tau

[Hugging Face Tau](tau.md) is a separate optional integration and is unaffected
by PiPy. Tau remains selectable, keeps its own sessions and its own read-only
tool policy. PiPy takes no dependency on Tau.

## Attribution

PiPy is a Python port of pi, which is distributed under the MIT License,
Copyright (c) 2025 Mario Zechner. Ported modules name the upstream file they
derive from, and the full notice is in `NOTICE` at the repository root.
