# Plugin Authoring

SuperQode plugins let you extend the agent with custom tools, CLI commands, skills, event hook handlers, permission policies, providers, and context injectors. This guide covers every part of the plugin system.

The native `core` harness always starts with only `read`, `write`, `edit`, and
`bash`. Enabled extensions are applied after that stable base contract, so users
pay the prompt and tool-schema cost only for capabilities they deliberately
install. Extension failures are isolated and reported without taking down the
agent loop.

There are two distribution formats:

- **Python packages** using the `superqode.extensions` entry-point group. This
  is the preferred format for reusable extensions.
- **Project plugin manifests** under `.superqode/plugins/`. These are convenient
  for repository-specific extensions and execute only after project trust is
  granted.

## Python Package Extensions

Create an extension with the public decorator API:

```python
from superqode import Extension, ExtensionContext

extension = Extension("company-tools", version="0.1.0")


@extension.tool(description="Search approved internal documentation", read_only=True)
def search_internal_docs(query: str) -> str:
    return search_company_index(query)


@extension.before_tool
def check_policy(ctx, name: str = "", arguments=None):
    return None


@extension.command("extension-info")
def extension_info(args: str, context: ExtensionContext) -> str:
    return f"company-tools is active for {context.root}"


@extension.context
def company_context(context: ExtensionContext) -> str:
    return "Follow the company's repository validation policy."
```

Expose the object through `pyproject.toml`:

```toml
[project.entry-points."superqode.extensions"]
company-tools = "company_superqode:extension"
```

An entry point may expose an `Extension` directly or a zero-argument function
that returns one. Installed entry points are explicit user installations;
project-local manifest code remains trust-gated. See
`examples/extensions/python-package/` for a complete package.

### Package conformance checkpoint

The repository ships three independent distributions under
`examples/extensions/packages/`: a typed tool, a permission policy, and a
Markdown skill. A fourth wheel represents an in-place upgrade of the tool
package. The lifecycle checker builds the current SuperQode wheel, creates a temporary virtual environment and
verifies real package metadata and entry-point discovery, execution, policy
decisions, skill loading, disable/re-enable, and upgrade behaviour:

```bash
uv run python scripts/check_extension_packages.py
```

Core is asserted to contain exactly four tools before the installed packages
activate. The temporary environment is deleted after the check and the
development environment is not modified.

### Current stable boundary

Extension API version 1 covers tools, TUI commands, Markdown skills, lifecycle
hooks, bounded context sources, declarative permission rules, and `ProviderDef`
registrations for the native harness. Compaction strategies, custom output
renderers, subagent implementations, validators, MCP-server contributions, and
portable custom harness loops are not part of API version 1 yet.

---

## Plugin Manifest

Every plugin is defined by a `plugin.json` manifest file. The only required field is `id` (or `name`, which falls back to `id`). All other fields are optional and default to sensible empty values.

### Complete Schema

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "0.1.0",
  "api_version": 1,
  "requires_superqode": ">=0.2.35,<1.0",
  "description": "Extends SuperQode with custom code review capabilities.",
  "tools": [
    {
      "name": "analyze_complexity",
      "description": "Analyze code complexity for a given file",
      "path": "tools/complexity.py"
    }
  ],
  "commands": [
    {
      "name": "review",
      "description": "Run a code review session",
      "path": "commands/review.py",
      "aliases": ["r"],
      "category": "code-quality"
    }
  ],
  "skills": [
    "skills/review.md"
  ],
  "providers": [
    {
      "name": "my-custom-provider",
      "path": "providers/custom.py"
    }
  ],
  "permission_rules": [
    {
      "tool": "bash",
      "pattern": "npm publish",
      "action": "deny"
    }
  ],
  "context_injectors": [
    {
      "path": "injectors/prompt_suffix.md"
    }
  ],
  "event_hooks": [
    {
      "point": "before_tool_call",
      "handler": "my_plugin.hooks:audit_tool_call",
      "name": "Audit tool calls"
    },
    {
      "point": "after_turn_complete",
      "handler": "my_plugin.hooks.log_turn",
      "name": "Log turn completion"
    }
  ]
}
```

### Field Reference

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `id` | string | *required* | Unique plugin identifier |
| `name` | string | same as `id` | Human-readable display name |
| `version` | string | `"0.1.0"` | Semantic version |
| `description` | string | `""` | Short summary of plugin functionality |
| `api_version` | integer | `1` | SuperQode extension API compatibility version |
| `requires_superqode` | string | `""` | Optional comma-separated version constraints |
| `tools` | array | `[]` | Custom tool definitions (see Defining Tools) |
| `commands` | array | `[]` | Custom CLI command definitions (see Defining Slash Commands) |
| `skills` | array | `[]` | Skill file paths relative to the plugin directory (see Defining Skills) |
| `providers` | array | `[]` | Provider registration entries |
| `permission_rules` | array | `[]` | Permission rule entries (see Permission Rules) |
| `context_injectors` | array | `[]` | Context injection entries (see Context Injectors) |
| `event_hooks` | array | `[]` | Lifecycle hook registrations (see Event Hook Handlers) |

The manifest also accepts camelCase aliases for compatibility: `permissionRules`, `contextInjectors`, `eventHooks`.

---

## Hook Points

The agent loop fires hooks at 11 lifecycle points. Each hook receives a `LifecycleContext` with `session_id`, `provider`, `model`, `working_directory`, `iteration`, and a `metadata` dict for custom data.

### All Hook Points

| Hook Point | Fired When | Decision Support |
|------------|-----------|-----------------|
| `session_start` | Once per session, before the first turn | No |
| `user_prompt_submit` | After the user prompt is added to the conversation | Yes |
| `before_llm_call` | Immediately before the LLM API request is sent | No |
| `after_llm_call` | Immediately after the LLM API response is received | No |
| `permission_request` | When a tool requires human approval (permission manager returns ASK) | Yes |
| `before_tool_call` | Right before a tool's `execute` method runs | Yes |
| `after_tool_call` | Right after a tool returns a result or raises | No |
| `after_turn_complete` | Once per iteration, after all tools have run | No |
| `before_compact` | Before context compaction runs | Yes |
| `after_compact` | After context compaction has completed | No |
| `stop` | When the loop completes and returns a response | No |

### Decision Hooks

Four hook points support decision semantics: `user_prompt_submit`, `permission_request`, `before_tool_call`, and `before_compact`. These are the gating points where hooks can influence the loop's control flow.

A decision hook returns one of the following:

| Return Value | Meaning |
|-------------|---------|
| `None` | Abstain. No opinion; the next hook or default flow applies. |
| `True` or `HookDecision(action=ALLOW)` | Explicitly allow/approve the operation. |
| `False` or `HookDecision(action=DENY)` | Block the operation. |
| `dict` or `HookDecision(action=MODIFY, arguments={...})` | Proceed with modified arguments (only meaningful for `before_tool_call` and `user_prompt_submit`). |

**Deny precedence.** The first hook to return `DENY` short-circuits the decision loop and wins immediately. A later `ALLOW` can never override an earlier `DENY`. This ensures a security-monitoring plugin's deny always takes effect even if another plugin would have allowed the call.

A hook that raises an exception is logged and treated as abstaining (fail-open). Hooks must never crash the loop.

### Observer Hooks

The remaining seven hook points are observer-only. Their return values are ignored. They are useful for logging, metrics, audit trails, and side effects.

---

## Defining Tools

Plugin tools are Python classes that subclass `Tool` from `superqode.tools.base`. The `Tool` abstract base class requires four members: `name`, `description`, `parameters` (a JSON Schema dict), and an async `execute` method.

### Tool Class Example

```python
# tools/complexity.py
from superqode.tools.base import Tool, ToolContext, ToolResult


class AnalyzeComplexityTool(Tool):

    @property
    def name(self) -> str:
        return "analyze_complexity"

    @property
    def description(self) -> str:
        return "Analyze cyclomatic complexity of a Python source file."

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to analyze"
                }
            },
            "required": ["path"]
        }

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        filepath = ctx.working_directory / args["path"]
        if not filepath.exists():
            return ToolResult(success=False, output=f"File not found: {args['path']}")
        source = filepath.read_text(encoding="utf-8")
        complexity = self._compute_complexity(source)
        return ToolResult(success=True, output=str(complexity))

    def _compute_complexity(self, source: str) -> int:
        count = 0
        for line in source.splitlines():
            stripped = line.strip()
            if stripped.startswith(("if ", "elif ", "for ", "while ", "except ", "with ")):
                count += 1
        return count
```

### ToolContext

The `ToolContext` provides the execution environment:

- `session_id` -- current session identifier
- `working_directory` -- project root path
- `search_roots` -- optional extra read-only search paths
- `on_output` -- streaming output callback
- `on_progress` -- progress callback `(fraction, status_message)`
- `tool_registry` -- reference to the global tool registry (for meta-tools like BatchTool)
- `max_output_bytes` -- per-model byte cap for tool output

### ToolResult

Always return a `ToolResult`:

- `success: bool`
- `output: str` -- result text sent back to the model
- `error: Optional[str]` -- error message if failed
- `metadata: Dict[str, Any]` -- debugging/logging metadata (not sent to the model)

### Registration in Plugin Manifest

Reference the tool class in the `tools` array with a `path` pointing to the module. The plugin system imports the module and instantiates the class whose name matches the `name` field.

```json
{
  "tools": [
    {
      "name": "analyze_complexity",
      "description": "Analyze code complexity for a given file",
      "path": "tools/complexity.py"
    }
  ]
}
```

The `path` is relative to the plugin directory. The module must define a class with the same name as the tool (PascalCase of the tool name, e.g. `analyze_complexity` maps to `AnalyzeComplexityTool` or `AnalyzeComplexity`). The tool class must be importable at that path.

---

## Defining Slash Commands

Plugin commands are dispatched as slash/colon commands in the SuperQode TUI. Each command entry in the `commands` array specifies:

```json
{
  "commands": [
    {
      "name": "review",
      "description": "Run a code review session on the current branch",
      "path": "commands/review.py",
      "aliases": ["r", "code-review"],
      "category": "code-quality"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | Command name (used as `/name`) |
| `description` | string | Help text displayed in the command palette |
| `path` | string | Relative path to the command module |
| `aliases` | array of string | Alternative names for the command |
| `category` | string | Grouping category for the command palette |

The module at `path` should export a callable (function or class with `__call__`) that receives the command arguments and the current session context.

---

## Defining Skills

Skills are reusable, Markdown-based agent workflows defined in `.agents/skills/<slug>/SKILL.md` files. Plugins can contribute skills by listing them in the `skills` array.

### Plugin Manifest Entry

```json
{
  "skills": [
    "skills/review.md"
  ]
}
```

Paths are relative to the plugin directory. The referenced file should be a Markdown file with YAML frontmatter. It can be a flat file or placed under `skills/<slug>/SKILL.md`.

### Skill File Format

```markdown
---
name: code_review
description: Review code for bugs, security issues, and best practices
enabled: true
input_schema:
  type: object
  properties:
    file_path:
      type: string
      description: Path to the file to review
  required:
    - file_path
output_schema:
  type: object
  properties:
    issues:
      type: array
      items:
        type: object
        properties:
          severity:
            type: string
          description:
            type: string
---

# Code Review Skill

You are an expert code reviewer. When this skill is invoked:

1. Read the specified file.
2. Analyze for bugs, security vulnerabilities, and style issues.
3. Provide a structured report with severity ratings.
```

### Frontmatter Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | file stem or parent directory name | Skill identifier |
| `description` | string | `""` | Short description shown in tool listings |
| `enabled` | boolean | `true` | Whether the skill is active on load |
| `input_schema` | object | `null` | JSON Schema for skill invocation arguments |
| `output_schema` | object | `null` | JSON Schema describing the skill's response structure |

The canonical convention is `.agents/skills/<slug>/SKILL.md`, but a flat `.md` file in the plugin's `skills/` directory also works. The slug becomes the skill name when no explicit `name` is set in the frontmatter.

---

## Event Hook Handlers

Event hook handlers are callables registered in the `event_hooks` array. Each entry specifies a `point` (one of the 11 hook points), a `handler` string in `module:function` format, and an optional `name`.

### Handler Registration Format

```json
{
  "event_hooks": [
    {
      "point": "before_tool_call",
      "handler": "my_plugin.hooks:audit_tool_call",
      "name": "Audit all tool calls"
    },
    {
      "point": "after_turn_complete",
      "handler": "my_plugin.hooks.log_turn"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `point` | string | One of the 11 hook point names |
| `handler` | string | Python import path in `module:function` format (or `module.function`) |
| `name` | string | Optional display name for the hook (defaults to `plugin_id:handler`) |

### Handler Signature

Every handler receives a `LifecycleContext` as the first argument, plus point-specific extra arguments.

```python
# hooks.py
from superqode.agent.hooks import LifecycleContext, HookDecision


def audit_tool_call(
    ctx: LifecycleContext,
    name: str = "",
    arguments: dict | None = None,
    **kwargs,
) -> None | HookDecision:
    """Observer hook: logs every tool call."""
    print(f"[audit] iteration {ctx.iteration}: tool={name}")
    return None  # observer hooks always abstain


async def log_turn(
    ctx: LifecycleContext,
    **kwargs,
) -> None:
    """Observer hook: fires after each turn completes."""
    print(f"[log] turn {ctx.iteration} complete (session={ctx.session_id})")
```

### Decision Handler Example

```python
# policy.py
from superqode.agent.hooks import LifecycleContext, HookDecision


def block_dangerous_commands(
    ctx: LifecycleContext,
    name: str = "",
    arguments: dict | None = None,
    **kwargs,
) -> HookDecision | None:
    """Block shell commands that match dangerous patterns."""
    if name != "bash":
        return None  # abstain
    cmd = (arguments or {}).get("command", "")
    if "rm -rf /" in cmd or "sudo" in cmd:
        return HookDecision(
            action="deny",
            message="This command is blocked by security policy.",
            reason="matches dangerous command pattern",
        )
    return None
```

### Key Behavior

- Handlers can be sync or async. Async functions are awaited automatically.
- Observer hooks (all points except the four decision points) have their return values ignored.
- Decision hooks return `None` to abstain, `True`/`HookDecision(action="allow")` to allow, `False`/`HookDecision(action="deny")` to deny, or a `dict`/`HookDecision(action="modify", arguments={...})` to modify arguments.
- Exceptions from any handler are caught and logged. They never abort the loop or prevent other hooks from running.
- The first hook to return `DENY` wins. Later hooks are not called for that decision.
- The handler string accepts both `module:function` (canonical, preferred) and `module.function` (Pythonic) formats. The colon form disambiguates packages whose final dotted segment shares a name with an attribute.

---

## Permission Rules

Permission rules let plugins encode declarative auto-approval or auto-denial policies for tool calls. They are evaluated at the `permission_request` hook point.

### Rule Format

```json
{
  "permission_rules": [
    {
      "tool": "bash",
      "pattern": "npm publish",
      "action": "deny"
    },
    {
      "tool": "bash",
      "pattern": "pytest *",
      "action": "allow"
    },
    {
      "tool": "web_fetch",
      "action": "ask"
    }
  ]
}
```

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `tool` | string (glob) | `"*"` | Glob pattern matching the tool name |
| `pattern` | string (glob) | `"*"` | Glob pattern matched against argument values |
| `action` | string | `"ask"` | One of `allow`, `deny`, or `ask` |
| `argument` | string | `""` | If set, the pattern is matched only against this specific argument key; if empty, the pattern is matched against all argument values |

### Evaluation Semantics

- Rules are evaluated in order. The first matching rule wins.
- `allow` auto-approves the tool call (the human prompt is skipped).
- `deny` blocks the call with a policy message.
- `ask` abstains, so the normal permission prompt flow takes over.
- If no rule matches, the outcome is abstain and the prompt flow proceeds.

Because permission rules are registered as a standard `permission_request` handler, they compose with any other decision hooks under deny-precedence. A deny from either a rule or a custom hook wins.

### Glob Matching

The `tool` and `pattern` fields support standard Unix glob patterns (`*`, `?`, `[abc]`). For example:

```yaml
tool: "bash"          -- matches only the bash tool
tool: "web_*"         -- matches web_search, web_fetch, etc.
tool: "*"             -- matches any tool
pattern: "git push *" -- matches commands starting with "git push"
```

---

## Context Injectors

Context injectors let plugins inject additional content into the agent's system prompt or conversation context. Each entry specifies a path to a file whose contents are injected.

```json
{
  "context_injectors": [
    {
      "path": "injectors/prompt_suffix.md"
    }
  ]
}
```

The `path` is relative to the plugin directory. The file content is appended to the system prompt. You can also reference a JSON Schema via an optional `schema` field to define the expected structure of the injected data.

```json
{
  "context_injectors": [
    {
      "path": "injectors/custom_context.json",
      "schema": "schemas/context_schema.json"
    }
  ]
}
```

| Field | Type | Description |
|-------|------|-------------|
| `path` | string | Relative path to the context file (Markdown or JSON) |
| `schema` | string | Optional relative path to a JSON Schema file for validation |

---

## Directory Layout

A complete plugin project follows a conventional directory structure. Here is the recommended layout:

```text
my-plugin/
  plugin.json            # Manifest (required)
  tools/
    my_tool.py           # Custom tool classes
  commands/
    my_command.py        # Slash command implementations
  skills/
    review.md            # Skill definition files
  hooks.py               # Event hook handlers
  policy.py              # Permission rules and policy logic
```

All paths in the manifest are relative to the plugin directory. The `tools/`, `commands/`, `skills/`, `injectors/`, and `providers/` subdirectories follow standard naming conventions but are not mandatory. You may organize code as you see fit, as long as the manifest paths resolve correctly.

Skills conventionally follow the `.agents/skills/<slug>/SKILL.md` convention within the plugin directory:

```text
my-plugin/
  skills/
    code-review/
      SKILL.md
```

But a flat file like `skills/review.md` is equally valid.

---

## Distribution

### Installing a Plugin

Install a plugin from a local directory or a `plugin.json` file:

```bash
superqode plugins add ./my-plugin
superqode plugins add ./my-plugin/plugin.json
```

The project must be trusted before installing:

```bash
superqode trust yes
```

The plugin is copied into `.superqode/plugins/<plugin-id>/`. The directory name is derived from the plugin `id` with special characters replaced by hyphens.

### Storage Location

Installed plugins are stored at:

```text
.superqode/plugins/<plugin-id>/
  plugin.json
  tools/
  commands/
  ...
```

Plugins are discovered from three locations (scanned in order):

| Directory | Scope |
|-----------|-------|
| `.superqode/plugins/` | Project-level plugins |
| `.agents/plugins/` | Legacy project-level plugins |
| `~/.superqode/plugins/` | User-level (global) plugins |

### Enabling and Disabling

Plugin state (enabled/disabled) is tracked in `.superqode/plugins.json`:

```json
{
  "disabled": ["my-plugin"]
}
```

```bash
superqode plugins enable my-plugin
superqode plugins disable my-plugin
```

Disabled plugins are still discoverable but are not loaded into the agent loop. You can see their state with:

```bash
superqode plugins list
superqode plugins list --all    # include disabled plugins
superqode plugins list --json   # machine-readable output
```

To import executable contributions and verify capability activation, run the
trust-gated runtime doctor:

```bash
superqode trust yes
superqode plugins doctor --runtime
```

The normal doctor validates manifests without importing plugin code.

### Validation

Validate a plugin manifest at any time:

```bash
superqode plugins validate .superqode/plugins/my-plugin/plugin.json
superqode plugins doctor                        # validate all discoverable plugins
superqode plugins doctor .superqode/plugins/     # validate a specific directory
```

Validation checks for required fields, correct hook point names, resolvable file paths, and proper entry shapes. All issues are reported in one pass so you can fix them without repeated runs.
