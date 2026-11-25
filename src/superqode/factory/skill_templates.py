"""Built-in Markdown Factory Skill templates and one-click scaffolding.

Skills created here follow ``superqode.factory.skills`` frontmatter rules so
they can be snapshotted, bound to Factory harnesses, and refined by optimizers.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import yaml

from .definition import project_path, validate_definition
from .skills import parse_skill

SKILL_CATALOG: tuple[dict[str, Any], ...] = (
    {
        "id": "merge-risk",
        "name": "Merge Risk Assessment",
        "path": "skills/merge-risk/SKILL.md",
        "description": (
            "Evaluate Alignment, Impact, Verification, Rollback cost, and Error detection "
            "before opening a PR or handoff, and mitigate gaps early."
        ),
        "presets": [],
    },
    {
        "id": "ui-verification",
        "name": "UI Verification & Visual Proof",
        "path": "skills/ui-verification/SKILL.md",
        "description": (
            "Launch the app, walk the changed user flow, save screenshots/recordings to "
            ".superqode/factory-proof/, and record reusable Gotchas."
        ),
        "presets": [
            {"id": "web", "title": "Web / Playwright"},
            {"id": "macos", "title": "macOS SwiftUI App"},
            {"id": "cli", "title": "CLI / Terminal"},
        ],
    },
)


def list_skill_templates() -> list[dict[str, Any]]:
    return [dict(item) for item in SKILL_CATALOG]


def render_skill_template(skill_id: str, *, preset: str = "") -> tuple[str, str]:
    """Return ``(relative_path, markdown_content)`` for a built-in Factory skill."""
    if skill_id == "merge-risk":
        text = """---
name: merge-risk
description: Evaluate Alignment, Impact, Verification, Rollback cost, and Error detection ahead of handoff and mitigate risk early.
---
# Merge Risk Assessment

Run this checklist before completing implementation or opening a pull request.

## Categories to evaluate

1. **Alignment** — Confirm every changed file matches the requested goal or approved spec with no undocumented drive-by edits.
2. **Impact** — State the blast radius (isolated view vs. shared core module) and flag sensitive paths (auth, permissions, schemas, CI/workflows).
3. **Verification** — Confirm unit tests, protected checks, and (for UI work) visual proof were executed and passed.
4. **Rollback cost** — Identify whether the change is a reversible two-way door (standard git revert) or a one-way door (migrations, persisted state, public contracts).
5. **Error detection** — Confirm new failure paths surface clear errors or logs instead of silently swallowing exceptions.

## Mitigate before handoff

If any category is Medium or High risk and can be reduced safely (for example adding a missing test, error log, or visual proof), mitigate it before finishing.

## Required handoff sections

Include these headings in your final handoff summary:

### Impact
- **Verdict:** Low | Medium | High
- Brief summary of blast radius and affected surfaces.

### Rollback cost
- **Verdict:** Low | Medium | High
- Brief summary of how to revert safely.
"""
        return "skills/merge-risk/SKILL.md", text.strip() + "\n"

    if skill_id == "ui-verification":
        chosen = (preset or "web").strip().lower()
        if chosen == "macos":
            start_block = """## Start the app

Build and launch the macOS app locally (or run the SwiftUI preview / UI test suite):
- `swift build --package-path apps/macos`
- Capture key window states with `screencapture` or XCUITest attachments into `.superqode/factory-proof/`."""
            gotchas = """## Gotchas

- Capture Retina screenshots cleanly and name files descriptively (for example `01-before.png`, `02-after.png`).
- Verify both dark and light appearance when changing theme or surface colors."""
        elif chosen == "cli":
            start_block = """## Start the app

Run the CLI or TUI command end-to-end against a disposable project directory:
- Capture terminal transcript or rendered SVG/PNG snapshots into `.superqode/factory-proof/`.
- Confirm exit codes, stdout, and stderr match the requested behavior."""
            gotchas = """## Gotchas

- Reset temporary state directories between runs so previous configuration never masks a fresh-install bug.
- Verify non-interactive flags and error messages as well as the happy path."""
        else:
            start_block = """## Start the app

Start the local web dev server and open the running app in a headless browser (Playwright or Chrome DevTools Protocol):
- Wait for the dev server URL to become ready before walking the flow.
- Save screenshots or short recordings into `.superqode/factory-proof/`."""
            gotchas = """## Gotchas

- Wait for network/layout stability before capturing screenshots so loading spinners do not mask regressions.
- Check both desktop and narrow viewport widths when modifying navigation or sidebars."""

        text = f"""---
name: ui-verification
description: Prove a user-facing change works by exercising the running app and attaching a Visual proof summary.
---
# UI Verification

Use this skill whenever a change affects something a user can see, click, or run interactively.

{start_block}

## Walk the path

Walk the exact user flow described in the request or approved spec:
- For a bug fix, verify the original symptom no longer reproduces.
- For a new feature, walk through every primary interaction and edge case.

## Record the proof

1. Save final-state screenshots (`.png`/`.jpg`/`.webp`) or short recordings (`.mp4`/`.mov`) under `.superqode/factory-proof/`.
2. Add a `## Visual proof` section in your final response describing:
   - The exact path you walked
   - What each saved screenshot or recording demonstrates
   - Any environment constraint if the app could not be launched

{gotchas}
"""
        return "skills/ui-verification/SKILL.md", text.strip() + "\n"

    raise ValueError(f"Unknown built-in Factory skill: {skill_id}")


def scaffold_skill(
    root: str | Path,
    skill_id: str,
    *,
    preset: str = "",
    yaml_text: str = "",
    bind: bool = True,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Write a built-in Markdown Factory skill and optionally bind it into ``yaml_text``."""
    rel_path, content = render_skill_template(skill_id, preset=preset)
    parse_skill(content)
    target = project_path(root, rel_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    created = False
    if overwrite or not target.exists():
        target.write_text(content, encoding="utf-8")
        created = True

    updated_yaml = yaml_text
    asset_id = f"skill-{skill_id}"
    bound_to: list[str] = []
    if bind and yaml_text.strip():
        data = yaml.safe_load(yaml_text)
        if isinstance(data, dict):
            files = data.setdefault("data_context", {}).setdefault("files", {})
            if isinstance(files, dict):
                files[asset_id] = {"path": rel_path, "purpose": "skill"}
            harnesses = data.get("inference", {}).get("harnesses", {})
            if isinstance(harnesses, dict):
                for binding_name, binding_cfg in harnesses.items():
                    if isinstance(binding_cfg, dict):
                        skills = list(binding_cfg.get("skills") or [])
                        if asset_id not in skills:
                            skills.append(asset_id)
                        binding_cfg["skills"] = skills
                        bound_to.append(binding_name)
            validate_definition(data)
            updated_yaml = yaml.safe_dump(data, sort_keys=False)

    return {
        "id": skill_id,
        "asset_id": asset_id,
        "path": rel_path,
        "created": created,
        "bound_to": bound_to,
        "yaml": updated_yaml,
    }
