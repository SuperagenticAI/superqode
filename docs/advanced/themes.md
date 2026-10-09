# Themes

Choose a palette without restarting your coding session. Theme changes repaint retained conversation lines, syntax highlighting, dialogs, status bars, search/selection highlights, and future HTML exports. Drafts, queued prompts, tool history, and the transcript viewport remain in place.

See the [theme reliability review](theme-reliability-review.md) for bugs found during the follow-up audit and the validation coverage.

## Choose and preview

```bash
superqode --theme light
superqode --theme system
superqode --theme auto
superqode --theme light/tokyonight
superqode theme list
```

In the TUI, use `:theme` or `:theme browse` to open the searchable gallery. **All themes** includes installed palettes and the offline community catalog; **Installed** filters to themes ready to use. Search by name, appearance (`light`/`dark`), source (`custom`), or collection (`Awesome Pi`). Arrow keys preview palette swatches, a coding exchange, tool output, syntax, a diff, and a warning. Tab moves between controls; Enter applies and saves, installing a catalog theme first when needed. Escape cancels without changing the palette or installing anything. Use `:theme nord` to apply a name directly.

The initial collection has seven original dark palettes, a native light palette, terminal-derived `system`, `auto`, and four MIT-licensed community palettes: Ayu Light, Ayu Mirage, Halcyon Rivet, and Saffron Cavern. Run the list command for the complete installed collection.

The offline catalog includes **all 71 palettes from Awesome Pi Themes 1.2.19**. Two are already bundled, giving a fresh installation 83 distinct choices. No network connection or npm setup is needed. Preview before selecting; the gallery shows whether Enter will apply or install and apply. To install one, several, or the entire collection from a shell:

```bash
superqode theme browse
superqode theme browse ocean
superqode theme install alien-candy cosmic-lagoon
superqode theme install --all
```

CLI installation copies palettes into `~/.superqode/themes/` without changing your saved choice. Repeated installation retains existing files and accepts description-only edits; modified colors produce a conflict message. Select an edited installed theme in the gallery to apply your version. In the TUI, `:theme install NAME` installs, applies, and saves; bare `:theme install` opens the gallery. `:theme install --all` installs the collection, after which `:theme` lets you choose. `:theme help` shows the available actions. Unknown names suggest close matches and point back to the gallery.

The startup `--theme` (alias `--use-theme`) option lasts for that launch; it does not change the saved preference. Installed names take priority over same-named project files; use an explicit path such as `./light` to load a file. TUI selection saves atomically to `~/.superqode/config.json`, preserving unrelated settings. If saving fails, the palette still applies and the error is shown. Invalid, excessively nested, non-regular, or larger-than-1-MiB preference files are retained and reported instead of crashing or being overwritten.

## Follow the terminal

`system` derives its canvas and surface colors from the terminal's foreground/background and ANSI palette. On POSIX terminals, SuperQode sends OSC 10, 11, and 4 queries asynchronously; it does not delay startup. Late replies and appearance changes repaint the active session, including an open theme preview. Delayed RGB fragments retain their framing independently of the Escape-key timeout. Navigation and paste can interrupt an unfinished report; escape sequences inside bracketed paste remain paste content. Middle-gray terminal backgrounds retain readable body text across raised, hover, and active surfaces.

`auto` chooses the native light or SuperQode dark palette. A `light-name/dark-name` pair selects the first name for light appearance and the second for dark. Keep using an explicit named palette if your terminal does not report colors.

Windows and non-terminal hosts retain their native Textual input driver and use environment/default appearance fallbacks. The POSIX OSC implementation has been tested in a real macOS PTY; Windows/Linux terminal appearance reporting still needs hands-on validation. Where querying is unavailable, set `SUPERQODE_TERMINAL_BACKGROUND` and `SUPERQODE_TERMINAL_FOREGROUND` to six-digit hex colors before launching. `COLORFGBG` supplies an additional appearance hint.

## Create a custom palette

```bash
superqode theme init ./my-theme.json --name my-theme --base light
superqode theme check ./my-theme.json
superqode --theme ./my-theme.json
```

Native themes use a versioned JSON schema shipped at `superqode/data/themes/schema.json`. Start from an existing palette with the init command so all available keys are discoverable. A small valid document is:

```json
{
  "version": 1,
  "name": "my-theme",
  "description": "My project palette",
  "appearance": "dark",
  "colors": {"bg_void": "#161821"},
  "tokens": {"error": "#e95678"}
}
```

`colors` overrides native palette fields. `tokens` overrides semantic roles, including syntax, Markdown, diff, selection, tool surfaces, and export backgrounds. `vars` can hold reusable color values. Supported color forms are three/six-digit hex, ANSI indices 0-255, variable references, `oklch(...)`, `okhsl(...)`, and an empty string for the appearance fallback. Imported values resolve to concrete RGB; ANSI indices use Rich's standard palette. Perceptual colors are converted to sRGB.

Theme names must be unique lowercase slugs of at most 64 characters. Built-in names are reserved. Files are limited to 256 KiB. Validation rejects unknown native keys, missing required Pi roles, circular variables, invalid colors, and surfaces that cannot share readable text. Effective body/status/syntax text is adjusted to at least 4.5:1 on the supported text surfaces. This may brighten or darken source colors; validation reports the resulting palette's contrast, not the unmodified source's.

## Import Pi palettes

```bash
superqode theme check ./pi-theme.json --json
superqode theme import ./pi-theme.json
superqode --theme imported-name
```

Pi JSON palettes are converted to the native schema in `~/.superqode/themes/`. All 51 required and five optional Pi v1.1.0 roles are recognized. Additional extension color roles are preserved under `extensions` and reported by the checker; they do not alter SuperQode's UI. Imports never execute upstream extensions and refuse name/file collisions. Importing from the CLI does not change your saved selection.

In the TUI, **Import JSON…** (F2 in the gallery) or bare **`:theme import`** opens a file-path dialog. Paste a path (spaces need no quotes in the dialog), inspect its preview, and choose **Import & apply**. Invalid files and duplicate names show an inline error, leaving the dialog open for correction. Escape cancels. The command `:theme import "path with spaces.json"` remains available for direct import, apply, and save.

The catalog pins Awesome Pi Themes revision `a268b1aca442d348705e7733dc3db9af927079e0`; each source file was checked against its Git blob hash. All 71 palettes pass the importer. This is palette compatibility, not compatibility with Pi's TypeScript extensions. Community palette files carry their upstream MIT licenses; see the repository NOTICE and the source URLs from `superqode theme browse --json`.

## Edit and reload

User JSON files are discovered at startup and when the picker opens. The active user file is checked every half second and hot-reloads after a valid edit. Themes linked from a dotfiles repository also reload, including when the link is repointed or the entire themes directory is a symlink. A partial write, invalid edit, or deleted file keeps the last working palette and reports an actionable error. Use `:theme reload` to rescan user themes manually. It does not change the saved preference.

Project files load only when you explicitly provide their path with `--theme`; they do not load automatically or hot-reload. Import a project palette into the user directory if you want live editing. Existing HTML files retain their colors; newly exported files use the active palette.

If you explicitly select and save a project palette in the TUI, SuperQode installs a native copy into your user themes directory so the selection survives the next launch. This also applies to project palettes in saved appearance pairs. The project file is retained, and an existing destination file is never overwritten.
