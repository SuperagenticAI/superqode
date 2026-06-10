# Multi-Repo Search & Edit Safety

SuperQode gives local models fast, accurate code search: across **one repo or
many**: and an immediate feedback loop after every edit so they self-correct.

---

## Code search (grep / glob)

Search is powered by **ripgrep**, spawned directly (no shell) with structured
`--json` output:

- **Grep** searches file *contents* by regex, returning `file:line: match`.
- **Glob** finds files by *name* pattern (`**/*.py`), honoring `.gitignore`.
- Both pass the pattern verbatim (regex metacharacters are safe), respect
  `.gitignore`, and report when results were **truncated** or some paths were
  **skipped**, so the model knows to narrow the search.

The model is also steered to delegate open-ended, multi-round searches to a
subagent and to batch speculative searches in one turn.

---

## Searching across many repositories

Register the repos you want searchable, then search them all in **one fast
pass** (ripgrep is multi-threaded and takes many roots at once).

```text
:workspace add ~/code/api
:workspace add ~/code/web
:workspace list
:workspace remove ~/code/api
```

The registry persists in `~/.superqode/workspace.json`. To search across all
registered repos, ask the agent to "search all my repos for X": grep/glob fan
out and label matches by repo:

```text
Found 2 match(es) across 2 repos:

  api/src/auth/session.ts:42:  export function createSession(
  web/lib/api/client.ts:88:  const s = await createSession(
```

(Under the hood the tools take an `all_repos` parameter; the registered repos are
also exposed to read/search as additional roots.)

### Absolute paths

You can search an absolute path directly (`path: /abs/dir`). A path inside the
current project or a registered repo is honored silently; a path **outside** the
workspace is blocked with a hint to `:workspace add` it: unless you opt in with
`SUPERQODE_ALLOW_EXTERNAL_SEARCH=1`. This keeps autonomous runs from quietly
reading files outside your project while still honoring paths you authorize.

### Other roots via env

`SUPERQODE_SEARCH_ROOTS` (os-path-separated) adds extra read-only roots in
addition to the `:workspace` registry: useful for one-off setups.

---

## Post-edit verification

After the agent writes or edits a file, SuperQode runs a **fast, single-file
check** and feeds any findings straight back to the model so it fixes mistakes
immediately instead of shipping a broken edit:

```text
Successfully wrote 14 bytes to app.py

⚠️  1 issue(s) detected after your edit:
  app.py:1:8: F401 [*] `os` imported but unused
If your change caused these, fix them before continuing.
```

Checks by language:

| Language | Checker |
|---|---|
| Python | `ruff check` (lint + syntax) → `py_compile` fallback |
| JS / TS | `eslint` (when configured) |
| Go | `gofmt -e` (syntax) |
| JSON / YAML | parse validation |

It's fast (single file, bounded), **silent on clean files**, and best-effort: it
can never break the underlying edit. It applies to SuperQode's built-in / BYOK /
local edit tools (ACP and SDK runtimes use their own editing).

| Variable | Effect |
|---|---|
| `SUPERQODE_VERIFY_EDITS=0` | Disable post-edit diagnostics (on by default) |
| `SUPERQODE_FORMAT_ON_EDIT=1` | Auto-format files after edit (ruff/gofmt/prettier; off by default) |
