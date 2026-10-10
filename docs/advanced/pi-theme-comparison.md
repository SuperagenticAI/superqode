# Pi theme comparison: 9 October 2026

The initial review compared the SuperQode 2.10.1 checkout with released Pi source
and current community packages. It found incomplete repainting, fixed syntax
and export colors, and missing light/system/custom themes. The implementation
follow-up below closes those core gaps. The later comparison and gap sections
retain the initial baseline so the reasoning is reviewable.

## Implemented follow-up

- Complete semantic palettes now drive owned CSS, retained transcript strips,
  live legacy palette aliases, code views, and new HTML exports. Switching
  preserves drafts, prompt selection, queued tasks, tool evidence, streaming
  buffers, transcript content, and the reading viewport.
- Native light, terminal-derived system, automatic light/dark selection, and
  named appearance pairs are available. POSIX OSC queries run asynchronously,
  accept fragmented late replies, and follow terminal appearance changes.
- Versioned native JSON and Pi imports support variable references, hex, ANSI,
  OKLCH, and OKHSL. All 71 Awesome Pi Themes 1.2.19 palettes validated. Extra
  extension colors are preserved as data without executing TypeScript.
- Active user files hot-reload with last-good recovery. Imports reject name
  collisions; saved selections use atomic replacement and report write errors.
- The searchable picker previews a coding session without mutating the active
  palette. Its complete preview fits at 80×24. Startup --theme/--use-theme is
  temporary; theme list/check/import/init support CLI and TUI discovery.
- The gallery includes all 71 Awesome Pi Themes 1.2.19 palettes offline, with
  installed/available status, search, swatches, and install-and-apply on Enter.
  Bare `:theme import` opens a validation/preview dialog; F2 or the Import JSON
  button opens it from the gallery. `theme browse` exposes source metadata,
  and `theme install --all` installs the entire collection. A fresh install
  has 87 distinct choices, including the original and six light palettes.
- Effective small-text roles target 4.5:1 on their supported surfaces. The
  original decorative-preset contrast exceptions are removed. Four licensed
  initial community palettes, all 71 offline catalog palettes, their licenses,
  and the JSON schema ship in the installed wheel.

Validation: **6,184 regression tests passed**, 30 skipped, 24 live integration
tests excluded, 139 warnings recorded; **531 final focused checks passed**.
Every one of the 71 catalog themes also applied in the mounted app at both
80×24 and 120×40, preserving the draft, selection, and transcript. There were
58 successful real-PTY checks across two sizes, repeated against the installed
wheel. All responsiveness budgets and the strict docs build passed. A fresh
core-wheel installation exercised the gallery, bare import dialog, install,
apply/save, and repeat installation of the whole collection.
Evidence is in validation/pi-theme-implementation. See [Themes](themes.md) for
the shipped interface and format.

The subsequent [theme reliability audit](theme-reliability-review.md) found and
fixed additional import, preference, picker, system-contrast, startup, symlink
and terminal-framing edge cases. It includes separate verification of the
updated source and installed wheel; the figures above describe the earlier
gallery implementation run.

This establishes feature coverage and local regression evidence. Pi still has
its own package/extension APIs and automatic project theme discovery. Windows
uses native-driver appearance fallbacks; Windows/Linux OSC behavior and live
provider workflows are not certified by these macOS/offline checks. A claim of
better developer usability needs comparative developer feedback.

## Current releases

| Release | Theme relevance |
| --- | --- |
| [Pi v1.1.0, 7 October 2026](https://github.com/earendil-works/pi/releases/tag/v1.1.0) | Latest stable release at review time. The comparison uses this tag rather than unreleased `main`. |
| [Pi v0.99.0, 29 September](https://github.com/earendil-works/pi/releases/tag/v0.99.0) | Introduced the default terminal-derived `system` theme, perceptual colour formats, appearance metadata, and extension theme APIs. |
| [Pi v1.0.0, 1 October](https://github.com/earendil-works/pi/releases/tag/v1.0.0) | Fixed excessive saturation when deriving colours from pastel terminal palettes such as Catppuccin Frappe. |
| [Awesome Pi Themes v1.2.19, 3 October](https://github.com/isashi/awesome-pi-themes/blob/main/CHANGELOG.md) | Community collection reached 71 dark themes; the latest additions are Saffron Cavern and Amethyst Drift. The [npm metadata](https://registry.npmjs.org/awesome-pi-themes/latest) also reports 1.2.19. |

Pi's core includes `system`, `dark`, and `light`. Its system mode queries the
terminal palette, follows appearance changes, and targets 4.5:1 body-text contrast
on panel backgrounds. Startup waits at most 100 ms for colour responses, with
fallbacks and support for late responses. These are documented behaviours; this
review did not independently exercise Pi in a live terminal. See the
[released theme guide](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/themes.md).

## Capability comparison

| Capability | Released Pi | SuperQode before these changes |
| --- | --- | --- |
| Appearance | System, dark, light; automatic light/dark pairs. | Seven dark presets: SuperQode, High Contrast, Tokyo Night, Dracula, Nord, Monokai, Gruvbox. |
| Customisation | JSON files, user/project/package discovery, collision diagnostics. | Python registry; no supported custom JSON loader or theme directory. |
| Reloading | Active user file hot-reloads; other sources use `/reload`. | Palette changes live; existing conversation lines retain resolved colours. |
| Semantic coverage | Message, tool-state, markdown, syntax, diff, selection, search, scrollbar and editor-mode roles. | 34 palette fields become 25 runtime keys; several roles share accent aliases. |
| Syntax and export | Theme-specific roles and export backgrounds. | Fixed Pygments style and fixed dark HTML template. |
| Trial selection | `--use-theme` overrides the initial selection for one run. | Picker/command saves the selection; no equivalent CLI override found. |
| Preview | Community gallery previews a coding session and optional footer. | Picker shows accent swatches, without a complete code/diff/message preview. |
| Accessibility | System palette derives contrast-aware colours. | Explicit high-contrast preset and default-palette contrast tests; decorative presets have exceptions. |

Pi format and loading claims above are supported by its
[v1.1.0 schema](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/src/modes/interactive/theme/theme-schema.json),
[loader and watcher](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/src/modes/interactive/theme/theme.ts),
and [theme guide](https://github.com/earendil-works/pi/blob/v1.1.0/packages/coding-agent/docs/themes.md).
The [community gallery](https://isashi.github.io/awesome-pi-themes/) is a separate
project, not a built-in Pi theme picker. Token counts describe the implementations;
they do not measure usability.

## Verified gaps in SuperQode

### Applying a theme leaves parts of the interface unchanged

A mounted 80x24 probe wrote an error message and then selected Tokyo Night.
The runtime palette changed to background `#1a1b26` and error `#f7768e`, but
the screen remained `#000000` and the earlier error remained `#f43f5e`.
The transcript survived the switch. Local evidence is recorded in
`validation/pi-theme-2026-10-09/superqode-theme-probe.json`.

The source explains the result:

- `src/superqode/app/css.py` fixes the screen and many widget backgrounds to black.
- `src/superqode/app/mixins/helpers.py::_apply_and_persist_theme` rebuilds the home screen and refreshes selected widgets, while preserving existing styled transcript objects.
- `src/superqode/code_theme.py` and `src/superqode/rendering/markdown.py` use a fixed syntax palette.
- `src/superqode/rendering/html_export.py` uses fixed role colours and a dark template.
- `src/superqode/widgets/theme_picker.py` fixes its own modal colours.

Calling `ConversationLog.redraw_conversation()` directly is insufficient: it
clears the visual log, replays a limited message record, resumes following, and
scrolls to the end. A cosmetic change must preserve tool details, streaming
state, selection, scroll position, drafts, and queued prompts.

### Contrast coverage allows unreadable secondary colours

Measured with the existing contrast calculation on each palette's declared
background, rather than every actual widget background:

| Theme | Background | Text | Muted | Dim |
| --- | --- | --- | --- | --- |
| SuperQode | `#000000` | 16.55:1 | 8.19:1 | 4.35:1 |
| High Contrast | `#000000` | 21.00:1 | 15.91:1 | 11.54:1 |
| Tokyo Night | `#1a1b26` | 8.10:1 | **4.10:1** | **2.76:1** |
| Dracula | `#282a36` | 11.29:1 | 6.12:1 | 3.03:1 |
| Nord | `#2e3440` | 10.26:1 | 9.25:1 | 5.49:1 |
| Monokai | `#2d2a2e` | 12.64:1 | 4.57:1 | **2.88:1** |
| Gruvbox | `#282828` | 8.59:1 | **4.02:1** | 3.03:1 |

Bold values fail the project's current 4.5:1 body/secondary or 3:1 decorative
threshold. Small text conveying instructions or status should meet the body
threshold even when its token is named `dim`. Once backgrounds apply correctly,
test the foreground/background pairs actually used by every component.

### Persistence can hide failures

`src/superqode/app/theme_bridge.py::save_theme` writes configuration directly,
silently catches write failures, and replaces malformed JSON with an empty
configuration before saving. A user can receive a successful theme-change
message even when the choice will not survive a restart. Use atomic replacement,
retain unrelated settings, and distinguish an applied palette from a saved choice.

## Adoption order

| Priority | Change | Acceptance condition |
| --- | --- | --- |
| P0: before a theme-focused trial | Route Textual CSS, Rich output, overlays, code and diffs through one semantic palette. | Each existing preset visibly updates the complete interface; preserve the default brand identity. |
| P0 | Repaint retained content from structured render records. | Switching while streaming or scrolled up preserves messages, tool cards, selection, viewport, draft and queue. |
| P0 | Repair secondary contrast and expand mounted coverage. | Every supported preset passes contrast checks on its actual surfaces; instructions remain readable without colour. |
| P1 | Add a complete light preset and an opt-in terminal-derived system mode. | Light terminals, unavailable colour responses, late SSH responses and appearance changes work without losing keystrokes or delaying connection. |
| P1 | Introduce a versioned JSON schema, user theme directory and explicit project theme loading. | Invalid files, duplicate names and failed saves produce useful diagnostics; the last working theme stays active. |
| P1 | Add safe hot reload, atomic persistence and a per-run theme option. | Partial writes and deletion retain the working palette; a trial override leaves the saved preference intact. |
| P2 | Add Pi JSON import and a curated sample library. | Unsupported fields/formats are reported; importing a palette requires no Pi extension runtime. |
| P2 | Preview the actual SuperQode message, tool, code and diff renderers in the picker. | Users can assess readability before applying; cancel restores the prior appearance. Add search when the library grows. |

Keep the current SuperQode preset as the default during this work. A complete
light theme and trustworthy switching offer more immediate developer value than
dozens of partially applied palettes.

## Reusing Pi palettes and code

The released schema has 51 required colour roles and five optional roles.
It supports variables, terminal defaults, ANSI indices, hexadecimal, OKLCH and
OKHSL colours. Our importer must resolve these explicitly rather than treating
every string as a hexadecimal colour. The sample
[Halcyon Rivet JSON](https://github.com/isashi/awesome-pi-themes/blob/main/themes/halcyon-rivet.json)
passed validation against Pi v1.1.0's schema. It uses variable references and
`text: ""`, so even this sample requires terminal-default handling. One valid
sample does not establish compatibility for the whole collection.

Suggested adapter boundaries:

| Pi role | SuperQode destination |
| --- | --- |
| `text`, `muted`, `dim`, status and border roles | Semantic foreground/status/border tokens, with surface-specific contrast checks. |
| `md*`, `syntax*`, `toolDiff*` | Dedicated markdown, Pygments and diff mappings; avoid collapsing them into brand accents. |
| Message/tool backgrounds | Corresponding message and tool surfaces, including pending/error states. |
| `export.*` | HTML export tokens. Pi has no single required general screen-background token; define our screen background explicitly rather than assuming a message or export panel is equivalent. |
| Optional search, scrollbar and reasoning colours | Documented fallbacks; preserve source metadata and report roles not yet used. |

Port small colour-resolution and contrast algorithms if useful. Pi's TypeScript
UI lifecycle is coupled to its own terminal framework; SuperQode uses Python,
Textual and Rich. Importing that runtime would add substantial integration work.
Both [Pi](https://github.com/earendil-works/pi/blob/v1.1.0/LICENSE) and
[Awesome Pi Themes](https://github.com/isashi/awesome-pi-themes/blob/main/LICENSE)
use MIT licensing; copied code or palettes must retain the applicable copyright
and permission notice.

Start palette evaluation with [Ayu Light and Mirage](https://github.com/iodic/pi-ayu-themes)
for light/dark coverage, then Halcyon Rivet for a subdued dark option and Saffron
Cavern for the latest community addition. These are candidates for adaptation,
not palettes already validated in SuperQode. Awesome Pi Themes also ships an
opt-in header/footer extension. Reuse its semantic status presentation ideas;
palette adoption does not require installing or executing that extension.

## Verification scope

The four existing theme-related test files passed: **42 tests**. The mounted
probe and contrast measurements above expose gaps those tests do not currently
reject. Reproduce the unit baseline with:

```bash
uv run pytest -q tests/test_theme_picker.py tests/test_theme_contrast.py \
  tests/test_theme_repaint.py tests/test_design_system_contrast.py
uv run python scripts/show_theme_contrast.py tokyonight
```

This review inspected released upstream source and package data, validated one
community JSON theme, and exercised the local app headlessly. It did not install
Pi or community extensions, validate all 71 palettes, or establish live terminal
appearance support across operating systems. No theme runtime changes were made
in this follow-up. See the [developer trial readiness review](developer-trial-readiness-review.md)
for the wider developer journey and remaining live acceptance checks.
