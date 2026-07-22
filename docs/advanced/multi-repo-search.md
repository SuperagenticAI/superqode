# Multi-Repo Search & Edit Safety

SuperQode provides code search across one or more repositories and can run
bounded verification after each edit.

---

## Code search (grep / glob)

For broad local exploration, start with `local_code_search`. It runs a compact
offline broker over local file paths, literal content, and code symbols, and it
can fan out across every registered repo with `all_repos`. When
`.superqode/code-search.sqlite3` covers the requested roots, `local_code_search`
uses that SQLite FTS5 index first; otherwise it falls back to live filesystem
search.

For exact search, SuperQode uses **ripgrep**, spawned directly (no shell) with
structured `--json` output:

- **Grep** searches file *contents* by regex, returning `file:line: match`.
- **Glob** finds files by *name* pattern (`**/*.py`), honoring `.gitignore`.
- Both pass the pattern verbatim (regex metacharacters are safe), respect
  `.gitignore`, and report when results were **truncated** or some paths were
  **skipped**, so the model knows to narrow the search.

The model is also steered to delegate open-ended, multi-round searches to a
subagent and to batch speculative searches in one turn.

---

## Searching across many repositories

Register each searchable repository, then query all registered roots in one
multi-threaded ripgrep invocation.

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

The tools use the `all_repos` parameter to include registered repositories as
additional read and search roots.

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

After the agent writes or edits a file, SuperQode runs a bounded single-file
check and returns any findings to the model:

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

Verification is bounded to one file and produces no output for a clean result.
It does not alter the result of the underlying edit. It applies to SuperQode's
builtin, BYOK, and local edit tools; ACP and SDK runtimes use their own editing
implementations.

| Variable | Effect |
|---|---|
| `SUPERQODE_VERIFY_EDITS=0` | Disable post-edit diagnostics (on by default) |
| `SUPERQODE_FORMAT_ON_EDIT=1` | Auto-format files after edit (ruff/gofmt/prettier; off by default) |
