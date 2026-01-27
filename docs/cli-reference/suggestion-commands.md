<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Suggestion Commands

Commands for reviewing and applying verified fix suggestions from QE sessions.

Note: Suggestion commands are available in SuperQode Enterprise only.

---

## Overview

The `superqode suggestions` command group manages fix suggestions:

```bash
superqode suggestions COMMAND [OPTIONS] [ARGS]
```

Suggestions are generated when running QE with `--allow-suggestions` enabled.

---

## suggestions list

List all verified fix suggestions from QE sessions.

```bash
superqode suggestions list [PROJECT_ROOT] [OPTIONS]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `PROJECT_ROOT` | Project directory (default: `.`) |

### Options

| Option | Description |
|--------|-------------|
| `--all`, `-a` | Show all suggestions, not just improvements |

### Example

```bash
# List verified improvements
superqode suggestions list

# List all suggestions
superqode suggestions list --all
```

### Output

```
Verified Fix Suggestions
┏━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━┓
┃ #  ┃ Finding                             ┃ Status       ┃ Confidence   ┃
┡━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━┩
│ 1  │ SQL Injection Fix                   │ [CORRECT] Verified ⬆️│ 95%          │
│ 2  │ Auth Bypass Fix                     │ [CORRECT] Verified ⬆️│ 92%          │
│ 3  │ Rate Limiting Added                 │ [CORRECT] Verified ⬆️│ 88%          │
└────┴─────────────────────────────────────┴──────────────┴──────────────┘

Total: 3 verified fix suggestions
Use 'superqe logs' to see detailed agent work logs
```

---

## suggestions show

Show details of a specific suggestion.

```bash
superqode suggestions show FINDING_ID [PROJECT_ROOT]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `FINDING_ID` | The finding ID to display |
| `PROJECT_ROOT` | Project directory (default: `.`) |

### Example

```bash
superqode suggestions show finding-001
```

### Output

Shows:
- Original issue description
- Fix details
- Verification results
- Patch preview
- Before/after proof

---

## suggestions apply

Apply a verified fix suggestion.

```bash
superqode suggestions apply FINDING_ID [PROJECT_ROOT]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `FINDING_ID` | The finding ID to apply |
| `PROJECT_ROOT` | Project directory (default: `.`) |

### Example

```bash
# Apply a suggestion
superqode suggestions apply finding-001
```

### What Happens

1. The patch file is located in `.superqode/qe-artifacts/patches/`
2. The patch is applied to your codebase
3. You should run tests to verify the fix works in your environment

### Manual Application

You can also apply patches manually:

```bash
# Preview the patch
cat .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Dry-run apply
git apply --check .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Apply the patch
git apply .superqode/qe-artifacts/patches/fix-sql-injection.patch
```

---

## suggestions reject

Reject a suggestion with a reason.

```bash
superqode suggestions reject FINDING_ID [OPTIONS] [PROJECT_ROOT]
```

### Arguments

| Argument | Description |
|----------|-------------|
| `FINDING_ID` | The finding ID to reject |
| `PROJECT_ROOT` | Project directory (default: `.`) |

### Options

| Option | Description |
|--------|-------------|
| `--reason`, `-r` | Reason for rejection |

### Example

```bash
superqode suggestions reject finding-003 -r "Intentional design choice"
```

---

## Working with Suggestions

### Complete Workflow

```bash
# 1. Run QE with suggestions enabled
superqe run . --mode deep --allow-suggestions

# 2. List available suggestions
superqode suggestions list

# 3. Review a suggestion
superqode suggestions show finding-001

# 4. Preview the patch
cat .superqode/qe-artifacts/patches/fix-sql-injection.patch

# 5. Apply the suggestion
superqode suggestions apply finding-001

# 6. Run tests to verify
pytest

# 7. Commit if satisfied
git add -A
git commit -m "Fix SQL injection vulnerability"
```

### Best Practices

1. **Always review patches** before applying
2. **Run tests** after applying suggestions
3. **Use version control** to track changes
4. **Provide feedback** to improve future suggestions

---

## Patch Files

### Location

Patches are saved to:

```
.superqode/qe-artifacts/
├── patches/
│   ├── fix-sql-injection.patch
│   ├── fix-auth-bypass.patch
│   └── fix-rate-limiting.patch
└── reports/
    └── qr-*.json
```

### Format

Patches use unified diff format:

```diff
--- a/src/api/users.py
+++ b/src/api/users.py
@@ -40,7 +40,9 @@ def search_users(query: str):
     """Search for users by name."""
     conn = get_db_connection()
     cursor = conn.cursor()
-    sql = f"SELECT * FROM users WHERE name LIKE '%{query}%'"
+    sql = "SELECT * FROM users WHERE name LIKE ?"
+    params = (f"%{query}%",)
-    cursor.execute(sql)
+    cursor.execute(sql, params)
     return cursor.fetchall()
```

---

## Verification Status

| Status | Meaning |
|--------|---------|
| `[CORRECT] Verified` | Fix passed all verification checks |
| `[INCORRECT] Failed` | Fix failed verification |
| `⬆️ Improvement` | Fix is proven to improve the code |
| `➖ Neutral` | Fix works but improvement not measured |

---

## Providing Feedback

After reviewing suggestions, provide feedback to improve future QE runs:

```bash
# If the suggestion was helpful
superqe feedback finding-001 --valid

# If the suggestion was wrong
superqe feedback finding-001 --false-positive -r "This is expected behavior"

# If you applied the fix
superqe feedback finding-001 --fixed -r "Applied suggested patch"
```

---

## Troubleshooting

### No Suggestions Found

```
No verified fixes found.
Run 'superqe run . --mode deep --allow-suggestions' to generate fix suggestions.
```

**Solution**: Run QE with `--allow-suggestions` flag.

### Patch Doesn't Apply

```
error: patch failed: src/api/users.py:42
```

**Solution**: The code may have changed since the QE session. Try:

1. Check if the file was modified
2. Apply the patch manually with context
3. Run a new QE session

### Applied Wrong Suggestion

**Solution**: Use git to revert:

```bash
git checkout -- src/api/users.py
```

---

## Next Steps

- [Allow Suggestions](../concepts/suggestions.md) - Understand the suggestion workflow
- [QR Documentation](../concepts/qr.md) - Quality Reports
- [QE Commands](qe-commands.md) - Full QE command reference
