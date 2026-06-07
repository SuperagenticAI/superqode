# Doctor Command

One-shot diagnostic for your SuperQode developer setup.

---

## doctor

Check basic developer setup status.

```bash
superqode doctor
```

Runs a comprehensive diagnostic across five areas:

| Check | Description |
|-------|-------------|
| Python version | Verify minimum Python version requirement |
| Dependencies | Check installed packages and optional extras |
| Config file | Validate `superqode.yaml` if present |
| Provider connectivity | Probe configured provider endpoints |
| ACP agent availability | Detect installed ACP coding agents |

### Output

```
SuperQode Doctor
Python: 3.12.3 [CORRECT]
Dependencies: All core dependencies satisfied [CORRECT]
Config: superqode.yaml found and valid [CORRECT]
Provider anthropic: [CORRECT] Configured
Provider ollama: [CORRECT] Running at http://localhost:11434
ACP Agent opencode: [CORRECT] Available
ACP Agent claude: [MISSING] Not installed

Summary: 6 passed, 1 missing
```

The doctor command is read-only and does not modify any configuration.
