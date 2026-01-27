# Fix Suggestions

SuperQode's **Allow Suggestions** mode enables agents to demonstrate fixes in a sandbox, verify they work, and then revert-giving you proven solutions without modifying your code.

Note: Allow Suggestions mode is available in SuperQode Enterprise only.

---

## The Core Principle

!!! warning "Default Behavior: Read-Only"
    **SuperQode NEVER modifies user-submitted production code by default.** The `allow_suggestions` mode is opt-in only.

When `allow_suggestions` is enabled, SuperQode follows a strict workflow where all changes are **demonstrated** and then **reverted**.

---

## The Allow Suggestions Workflow

```
┌─────────────────────────────────────────────────────────────┐
│                  ALLOW SUGGESTIONS WORKFLOW                  │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. DETECT BUG         Agent finds issue in submitted code   │
│        ↓                                                     │
│  2. FIX IN SANDBOX     Agent modifies code to fix bug       │
│        ↓                                                     │
│  3. VERIFY FIX         Run tests, validate fix works        │
│        ↓                                                     │
│  4. PROVE BETTER       Demonstrate improvement with evidence │
│        ↓                                                     │
│  5. REPORT OUTCOME     Document findings and observations   │
│        ↓                                                     │
│  6. ADD TO QR         Record in Quality Report│
│        ↓                                                     │
│  7. REVERT CHANGES     Restore original submitted code      │
│        ↓                                                     │
│  8. USER DECIDES       Accept/reject suggested patches      │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

---

## Enabling Allow Suggestions

### Command Line

```bash
# Enable for a single session
superqe run . --mode deep --allow-suggestions
```

### Configuration File

```yaml
# superqode.yaml
qe:
  allow_suggestions: true  # Enable globally (still OFF by default)

  suggestions:
    enabled: true
    verify_fixes: true        # Run tests to verify fixes
    require_proof: true       # Require before/after metrics
    auto_generate_tests: false  # Generate regression tests for fixes
    max_fix_attempts: 3       # Max attempts per issue
    revert_on_failure: true   # Revert if fix verification fails
```

---

## How It Works in Detail

### Step 1: Detect Bug

The agent analyzes code and finds an issue:

```
[DETECTED] SQL Injection in src/api/users.py:42
  Severity: Critical
  Confidence: 0.95
  Category: Security/Injection
```

### Step 2: Fix in Sandbox

The agent creates a fix in the isolated sandbox:

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

### Step 3: Verify Fix

The agent runs tests to verify the fix works:

```
[VERIFICATION] Running tests after fix...
  ✓ test_user_search_basic
  ✓ test_user_search_special_chars
  ✓ test_user_search_sql_injection_prevented

  All tests pass (3/3)
  No regressions detected
```

### Step 4: Prove Better

The agent demonstrates improvement with evidence:

```
[PROOF] Fix Verification Results:

Before Fix:
  - Input "'; DROP TABLE users; --" causes SQL error
  - SQL injection vulnerability confirmed

After Fix:
  - Input properly escaped
  - No SQL error, returns empty result
  - Injection attempt neutralized

Improvement: SQL injection vulnerability eliminated
```

### Step 5: Report Outcome

The fix is documented with full details:

```json
{
  "finding_id": "finding-001",
  "fix_attempted": true,
  "fix_verified": true,
  "verification_result": {
    "tests_run": 3,
    "tests_passed": 3,
    "regressions": 0,
    "before_after_proof": "..."
  },
  "patch_file": "patches/fix-sql-injection.patch"
}
```

### Step 6: Add to QR

The finding and fix are recorded in the Quality Report.

### Step 7: Revert Changes

**All changes are automatically reverted:**

```
[REVERT] Restoring original code...
  ✓ src/api/users.py restored
  ✓ Workspace verified against original snapshot
  ✓ All changes reverted successfully
```

### Step 8: User Decides

You review and decide whether to apply the fix:

```bash
# List available suggestions
superqode suggestions list

# View the patch
cat .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Apply if approved
superqode suggestions apply finding-001
```

---

## Key Guarantee

!!! success "Your Code is Always Preserved"
    Even when `allow_suggestions` is enabled, SuperQode only **demonstrates** fixes-it never permanently applies them. Your original code is **always restored** after each session.

---

## Working with Suggestions

### List Suggestions

```bash
superqode suggestions list

╭─────────────────────────────────────────────────────────────╮
│                    Verified Fix Suggestions                  │
├─────────────────────────────────────────────────────────────┤
│ ID          │ Title                    │ Verified │ Status   │
├─────────────┼──────────────────────────┼──────────┼──────────┤
│ finding-001 │ SQL Injection Fix        │ ✓        │ Pending  │
│ finding-002 │ Auth Bypass Fix          │ ✓        │ Pending  │
│ finding-003 │ Rate Limiting Added      │ ✓        │ Pending  │
╰─────────────────────────────────────────────────────────────╯
```

### View a Suggestion

```bash
superqode suggestions show finding-001
```

Shows:
- Original issue description
- Fix details
- Verification results
- Patch preview
- Before/after proof

### Apply a Suggestion

```bash
# Preview the patch first
git apply --check .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Apply the suggestion
superqode suggestions apply finding-001

# Or apply the patch directly
git apply .superqode/qe-artifacts/patches/fix-sql-injection.patch
```

### Reject a Suggestion

```bash
# Mark as rejected with reason
superqode suggestions reject finding-003 -r "Intentional design choice"
```

---

## Configuration Options

### Full Suggestions Configuration

```yaml
qe:
  allow_suggestions: true

  suggestions:
    # Core settings
    enabled: true
    verify_fixes: true          # Run tests to verify
    require_proof: true         # Require evidence

    # Test generation
    auto_generate_tests: true   # Generate regression tests
    test_output_dir: ".superqode/qe-artifacts/generated-tests"

    # Fix attempts
    max_fix_attempts: 3         # Max attempts per issue
    revert_on_failure: true     # Revert if fix fails

    # Patch handling
    patch_format: unified       # unified, context, git
    preserve_patches: true      # Keep patches after session
```

### Per-Session Override

```bash
# Enable suggestions for this session only
superqe run . --allow-suggestions

# Override other settings
superqe run . --allow-suggestions --generate
```

---

## Verification Process

### What Gets Verified

| Check | Description |
|-------|-------------|
| **Compilation** | Code compiles/parses without errors |
| **Tests Pass** | Existing tests still pass |
| **No Regressions** | No new failures introduced |
| **Issue Resolved** | The original issue is fixed |
| **Harness Validation** | Code passes linting/type checks |

### Verification Results

```json
{
  "verification": {
    "status": "passed",
    "checks": {
      "compilation": true,
      "tests_pass": true,
      "no_regressions": true,
      "issue_resolved": true,
      "harness_validation": true
    },
    "tests_run": 42,
    "tests_passed": 42,
    "duration_seconds": 15.3
  }
}
```

### Failed Verification

If verification fails:

1. The fix is discarded
2. Original code is preserved
3. Failure is logged in QR
4. Agent may attempt alternative fix (up to `max_fix_attempts`)

```
[VERIFICATION FAILED] Fix for finding-001
  Reason: Test test_user_permissions failed
  Action: Reverted, attempting alternative fix (2/3)
```

---

## Generated Tests

When `auto_generate_tests` is enabled:

```bash
# Generated tests are saved to:
.superqode/qe-artifacts/generated-tests/
├── test_sql_injection.py
├── test_auth_bypass.py
└── test_rate_limiting.py
```

### Example Generated Test

```python
# test_sql_injection.py
"""
Regression test for SQL Injection fix (finding-001)
Generated by SuperQode QE
"""

import pytest
from src.api.users import search_users

class TestSqlInjectionPrevention:
    """Tests that SQL injection is properly prevented."""

    def test_normal_search_works(self):
        """Normal search queries work correctly."""
        results = search_users("john")
        assert isinstance(results, list)

    def test_injection_attempt_neutralized(self):
        """SQL injection attempts are safely handled."""
        # This should not cause SQL errors
        results = search_users("'; DROP TABLE users; --")
        assert isinstance(results, list)
        # Should return empty or safe results
        assert len(results) >= 0

    def test_special_chars_escaped(self):
        """Special characters are properly escaped."""
        results = search_users("O'Brien")
        assert isinstance(results, list)
```

---

## Best Practices

### 1. Review Before Applying

Always review patches before applying:

```bash
# View the patch
cat .superqode/qe-artifacts/patches/fix-sql-injection.patch

# Dry-run apply
git apply --check fix-sql-injection.patch
```

### 2. Run Tests After Applying

After applying a suggestion, run your test suite:

```bash
superqode suggestions apply finding-001
pytest  # Run your tests
```

### 3. Use Version Control

Apply patches in a clean git state:

```bash
git status  # Ensure clean state
superqode suggestions apply finding-001
git diff    # Review changes
git add -p  # Stage selectively
git commit -m "Fix SQL injection vulnerability"
```

### 4. Provide Feedback

Help improve suggestions by providing feedback:

```bash
# If the fix works well
superqe feedback finding-001 --valid

# If it doesn't work
superqe feedback finding-001 --false-positive -r "Breaks feature X"
```

---

## Safety Guarantees

| Guarantee | Description |
|-----------|-------------|
| **Sandbox Isolation** | All fixes applied in isolated workspace |
| **Automatic Revert** | Changes always reverted after session |
| **No Auto-Apply** | Fixes are never applied without user action |
| **Verification Required** | Fixes must pass tests before suggestion |
| **Patch Preservation** | Patches saved as artifacts for review |

---

## Next Steps

- [Harness Validation](../advanced/harness-system.md) - Patch validation system
- [Test Generation](../qe-features/test-generation.md) - Generated test details
- [CI/CD Integration](../integration/cicd.md) - Automated suggestion handling
