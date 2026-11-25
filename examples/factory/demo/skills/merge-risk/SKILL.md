---
name: merge-risk
description: Evaluate Alignment, Impact, Verification, Rollback cost, and Error detection ahead of handoff and mitigate risk early.
---
# Merge Risk Assessment

Run this checklist before completing implementation or opening a pull request.

## Categories to evaluate

1. **Alignment** - Confirm every changed file matches the requested goal or approved spec with no undocumented drive-by edits.
2. **Impact** - State the blast radius (isolated view vs. shared core module) and flag sensitive paths (auth, permissions, schemas, CI/workflows).
3. **Verification** - Confirm unit tests, protected checks, and (for UI work) visual proof were executed and passed.
4. **Rollback cost** - Identify whether the change is a reversible two-way door (standard git revert) or a one-way door (migrations, persisted state, public contracts).
5. **Error detection** - Confirm new failure paths surface clear errors or logs instead of silently swallowing exceptions.

## Mitigate before handoff

If any category is Medium or High risk and can be reduced safely (for example adding a missing test, error log, or visual proof), mitigate it before finishing.

## Required handoff sections

### Impact
- **Verdict:** Low | Medium | High
- Brief summary of blast radius and affected surfaces.

### Rollback cost
- **Verdict:** Low | Medium | High
- Brief summary of how to revert safely.
