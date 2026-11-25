---
name: ui-verification
description: Prove a CLI or user-facing change works end-to-end and attach a Visual proof summary.
---
# UI Verification

Use this skill whenever a change affects user-facing CLI output, formatting, or interactive behavior.

## Start the app

Run `python app.py` and `python self_check.py <case>` against the demo inputs:
- Verify exit codes, stdout JSON structure, and edge-case behavior.
- Save any captured terminal snapshots or output diagrams into `.superqode/factory-proof/`.

## Walk the path

Walk the exact flow described in the request or approved spec:
- For a bug fix (`totals`, `active`, or `ordered`), confirm the failing input now produces the exact expected output.
- For a new feature, walk through both standard and empty/edge-case inputs.

## Record the proof

1. Save snapshots (`.png`/`.jpg`/`.webp`) under `.superqode/factory-proof/` when recording visual states.
2. Add a `## Visual proof` section in your final response describing:
   - The exact commands and inputs you exercised
   - The observed outputs before and after the change
   - Any environment constraint if a check could not run

## Gotchas

- `totals` must preserve negative and zero amounts when accumulating duplicate categories.
- `active` must check `item.get("active") is True` because Python `bool` is a subclass of `int` (`1 == True`).
- `ordered` must use `str.casefold` and return a new sorted list without mutating the input list.
