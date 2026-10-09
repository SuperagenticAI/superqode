# Theme Commands

`superqode theme` manages palette data without starting a coding agent. See [Themes](../advanced/themes.md) for the format, preview, terminal appearance, and live reload.

| Command | Behavior |
| --- | --- |
| `superqode theme list [--json]` | List names, appearances, sources, and discovery errors. |
| `superqode theme browse [QUERY] [--json]` | Search installed themes and all 71 offline Awesome Pi palettes; JSON includes provenance and license. |
| `superqode theme install NAME...` | Install catalog palettes by name; retain existing files and saved selection. |
| `superqode theme install --all` | Install the entire offline collection without npm or network access. |
| `superqode theme check FILE [--json]` | Validate native/Pi JSON; report effective contrast and preserved extension colors. |
| `superqode theme import FILE` | Convert and copy a palette into the user theme directory; reject collisions. |
| `superqode theme init FILE --name NAME --base BASE` | Create an editable native palette; refuse an existing destination. |

## Launch and select

```bash
superqode --theme light
superqode --use-theme system
superqode --theme light/tokyonight
superqode --theme ./my-theme.json
```

Startup selection applies for that launch. Use `:theme` or `:theme browse` in the TUI to search, preview, install, and save a selection. Bare `:theme import` opens the file-path preview dialog; `:theme import FILE` applies and saves the imported name directly. `:theme install NAME` installs and applies a catalog theme; bare `:theme install` opens the gallery. `:theme install --all` installs the collection without selecting a theme. `:theme help` lists these actions.

`:theme list`, `:theme browse QUERY`, `:theme check FILE`, and `:theme init FILE --name NAME` expose the corresponding CLI commands. `:theme reload` rescans the user directory.

```bash
superqode theme init ./my-theme.json --name my-theme --base light
superqode theme check ./my-theme.json --json
superqode theme import ./my-theme.json
```

Native and Pi JSON files are limited to 256 KiB. Imported colors are normalized for readability; arbitrary code is never executed. User themes live at `~/.superqode/themes/`. A failed save retains existing preferences and reports an error.
