# Interactive Factory Studio Demo Prompts

Open `examples/factory/demo` in SuperQode macOS app, switch to **Factory Studio**,
and walk through all new Software Factory capabilities in 2 minutes:

## Demo 1: Zero-Wait Standalone Tour (No Model Required)

1. Click **Software Factory tour** on the Welcome screen (or **Tour** in the Factory Studio header).
2. Click **Auto-play** (or step with `Left` / `Right` arrow keys) across all 5 slides:
   - Slide 1: Software Factory anatomy (`Build -> Test -> Verify -> Improve`)
   - Slide 2: Interactive Triage routing toggle (Ambiguous feature pauses at Spec gate vs. Clear bug skips Spec)
   - Slide 3: Reusable `merge-risk` and `ui-verification` skills + OS sandboxed probes
   - Slide 4: SuperGauge verdict + 5-dimension Merge Risk + Visual Proof
   - Slide 5: Trial Suites + 4 built-in optimizers (`Native`, `GEPA`, `MetaHarness`, `Omni`)

## Demo 2: Clear Bug Fix (Fast Path Skipping Spec Gate)

Load **Triage, spec & build** (or **Fix and verify**), bind your connected model via
**Use current model** in **Configuration**, attach `merge-risk` and `ui-verification`
skills, and run this trial goal:

```text
Fix app.py totals so amounts for repeated categories accumulate instead of overwriting earlier rows. Preserve empty input, zero, and negative amounts. Change only app.py.
```

Expected highlights:
- `triage` classifies `complexity: small`, `needs-spec: false` -> skips `spec` automatically.
- `implement` fixes `app.py` and mitigates risk.
- `verify` runs checks, surfaces **SuperGauge** + **5-Dimension Merge Risk** (`LOW`) + **Copy PR handoff summary**.

## Demo 3: Ambiguous Feature (Triggers Spec Human Gate)

Run this open-ended feature prompt through **Triage, spec & build**:

```text
Add a summary report mode to app.py that formats totals and active counts with optional filtering and sorting.
```

Expected highlights:
- `triage` sets `needs-spec: true` because output format, CLI flags, and filter semantics are open product decisions.
- `spec` pauses at **Human Gate 1** with clarifying questions and a written spec before a single line of implementation code is written.
- After you approve the spec, `implement` builds to spec and `verify` pauses at **Human Gate 2** with SuperGauge, 5-dimension Merge Risk, and Visual Proof.
