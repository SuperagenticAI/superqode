# Plugin Commands

Manage SuperQode plugins: discover, validate, install, and control plugins that extend agent capabilities.

---

## Overview

The `superqode plugins` command group manages plugins:

```bash
superqode plugins COMMAND [OPTIONS] [ARGS]
```

Plugins are discovered from these directories (scanned in order):

| Directory | Description |
|-----------|-------------|
| `.superqode/plugins/` | Project-level plugins |
| `.agents/plugins/` | Legacy project-level plugins |
| `~/.superqode/plugins/` | User-level (global) plugins |

Plugin state is stored in `.superqode/plugins.json`, which tracks the disabled plugin list.

---

## Project Trust

Commands that modify plugin state (`add`, `enable`, `disable`) require the project to be trusted:

```bash
superqode trust yes
```

---

## Plugin Manifest Format

Every plugin is defined by a `plugin.json` manifest file:

```json
{
  "id": "my-plugin",
  "name": "My Plugin",
  "version": "1.0.0",
  "api_version": 1,
  "requires_superqode": ">=0.2.32,<1.0",
  "description": "Adds custom tools and hooks",
  "tools": [],
  "commands": [],
  "skills": [],
  "providers": [],
  "permission_rules": [],
  "context_injectors": [],
  "event_hooks": []
}
```

### Manifest Fields

| Field | Description |
|-------|-------------|
| `id` | Unique plugin identifier |
| `name` | Human-readable display name |
| `version` | Semantic version string |
| `description` | Short description of plugin functionality |
| `api_version` | Extension API compatibility version (currently `1`) |
| `requires_superqode` | Optional SuperQode version constraint |
| `tools` | Custom tool definitions the plugin contributes |
| `commands` | Custom TUI slash/colon commands the plugin contributes |
| `skills` | Skill definitions the plugin contributes |
| `providers` | Provider configurations the plugin registers |
| `permission_rules` | Additional permission rules for the plugin |
| `context_injectors` | Context injection hooks |
| `event_hooks` | Event hook registrations |

---

### Event Hooks

The `event_hooks` array registers callbacks at lifecycle points. Each entry has:

| Field | Description |
|-------|-------------|
| `point` | Hook point identifier (see below) |
| `handler` | Python module path in `module:func` format |
| `name` | Optional human-readable name |

Supported hook points (11 total):

| Hook Point | Trigger |
|------------|---------|
| `session_start` | Session begins |
| `user_prompt_submit` | User submits a prompt |
| `before_llm_call` | Before LLM API call |
| `after_llm_call` | After LLM API response |
| `permission_request` | Permission request raised |
| `before_tool_call` | Before a tool executes |
| `after_tool_call` | After a tool completes |
| `after_turn_complete` | After a turn finishes |
| `before_compact` | Before context is compacted |
| `after_compact` | After context is compacted |
| `stop` | Session stops |

Example:

```json
{
  "event_hooks": [
    {
      "point": "before_tool_call",
      "handler": "my_plugin.hooks:on_before_tool",
      "name": "Log tool calls"
    }
  ]
}
```

---

## plugins list

List discoverable plugins with version and enabled/disabled state.

```bash
superqode plugins list [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--all` | Show plugins from all discovery directories |
| `--json` | Emit JSON output |

### Examples

```bash
# List project plugins
superqode plugins list

# List all discoverable plugins
superqode plugins list --all

# JSON output
superqode plugins list --all --json
```

---

## plugins show

Show detailed manifest information for a specific plugin.

```bash
superqode plugins show PLUGIN_ID
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PLUGIN_ID` | Unique plugin identifier |

### Example

```bash
superqode plugins show my-plugin
```

---

## plugins validate

Validate a single `plugin.json` manifest file against the schema.

```bash
superqode plugins validate PATH
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PATH` | Path to a `plugin.json` file |

### Example

```bash
superqode plugins validate .superqode/plugins/my-plugin/plugin.json
```

---

## plugins doctor

Validate all discoverable plugin manifests (or a specific path). This default
check does not import executable plugin code. Use `--runtime` in a trusted
project to import contributions and report activation failures.

```bash
superqode plugins doctor [PATH]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PATH` | Optional path to validate instead of all discoverable manifests |

### Examples

```bash
# Validate all discoverable manifests
superqode plugins doctor

# Validate a specific directory
superqode plugins doctor .superqode/plugins/my-plugin

# Import and activate trusted extension contributions
superqode trust yes
superqode plugins doctor --runtime
```

---

## plugins add

Install a local plugin directory or `plugin.json` file. Requires a trusted project.

```bash
superqode plugins add SOURCE
```

### Arguments

| Argument | Description |
|----------|-------------|
| `SOURCE` | Path to a plugin directory or `plugin.json` file |

### Examples

```bash
superqode plugins add ./my-plugin
superqode plugins add ./my-plugin/plugin.json
```

### Prerequisites

Project must be trusted:

```bash
superqode trust yes
```

---

## plugins enable

Enable a plugin for the current project. Requires a trusted project.

```bash
superqode plugins enable PLUGIN_ID
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PLUGIN_ID` | Plugin identifier to enable |

### Example

```bash
superqode plugins enable my-plugin
```

### Prerequisites

Project must be trusted:

```bash
superqode trust yes
```

---

## plugins disable

Disable a plugin for the current project. Requires a trusted project.

```bash
superqode plugins disable PLUGIN_ID
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PLUGIN_ID` | Plugin identifier to disable |

### Example

```bash
superqode plugins disable my-plugin
```

### Prerequisites

Project must be trusted:

```bash
superqode trust yes
```
