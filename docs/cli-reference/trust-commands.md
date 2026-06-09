# Trust Commands

Manage project trust state. Trust is required for plugins and MCP operations. Trust state is stored per-project based on a hash of the project path.

---

## trust status

Show the current project trust status.

```bash
superqode trust status [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--json` | Emit JSON output |

### Output

```
Trust Status: trusted

Project: /Users/you/code/my-project
Path Hash: a1b2c3d4
Trusted: Yes
Trust File: ~/.superqode/trust/a1b2c3d4
```

---

## trust doctor

Show trust-sensitive files in the current project.

```bash
superqode trust doctor
```

Scans the project for files that require trust: plugin manifests, MCP configurations, and other executable/hook files. Lists each file with its trust requirement and current status.

---

## trust yes

Trust the current project.

```bash
superqode trust yes
```

Writes a trust marker to `~/.superqode/trust/<path-hash>` enabling plugins and MCP operations in this project.

---

## trust no

Mark the current project as untrusted.

```bash
superqode trust no
```

Removes the trust marker file, disabling plugins and MCP operations in this project.

---

## Trust Model

Trust is a per-project setting determined by the project's absolute path hash. The trust state is stored in `~/.superqode/trust/<path-hash>`:

| State | Description |
|-------|-------------|
| `trusted` | Plugins and MCP operations are allowed |
| `untrusted` | Plugins and MCP operations are blocked |

Projects are untrusted by default. Use `trust yes` to enable plugins and MCP operations after reviewing the project. The `superqode init` command may prompt for trust when creating project scaffolding.
