# Policy Commands

`sq policy` is the terminal control surface for layered contextual governance and credential-safe execution.

| Command | Purpose |
| --- | --- |
| `policy init` | Create `.superqode/policy.yaml` with secure builder defaults. |
| `policy show` | Show merged layers, redacted credential bindings, and effective guardrails. |
| `policy explain PHASE` | Simulate and explain a request without executing or mutating anything. |

```bash
sq policy init
sq policy show --json
sq policy explain tool_call --tool bash --risk high
sq policy explain tool_call --tool fetch --host api.github.com --arg url=https://api.github.com/user
sq policy explain promotion --arg candidate_id=cand_123 --json
```

Valid phases are `request`, `response`, `tool_call`, `tool_result`, and `promotion`. Match inputs include `--tool`, `--tool-group`, `--host`, `--risk`, `--provider`, `--runtime`, and repeatable `--arg key=value`.

See [Contextual Policy and Credential-Safe Execution](../advanced/contextual-policy.md) for the YAML schema, layer precedence, secret-handling guarantees, and broker configuration.

