# IDE Integration

Integrate SuperQode into your IDE for real-time quality feedback, inline diagnostics, and quick fixes directly in your editor.

Note: IDE integrations are an enterprise feature.

---

## Overview

SuperQode provides IDE integration through:

- **LSP Server**: Language Server Protocol for editor-agnostic integration
- **VSCode Extension**: Native VSCode extension with diagnostics and commands
- **Diagnostics**: QE findings shown as inline errors/warnings
- **Quick Fixes**: Apply QE-suggested fixes directly from the editor
- **Commands**: Run QE sessions from within your IDE

---

## VSCode Extension

### Installation

Install the SuperQode extension from the VSCode Marketplace:

1. Open VSCode
2. Go to Extensions (Ctrl+Shift+X / Cmd+Shift+X)
3. Search for "SuperQode"
4. Click Install

Or install from command line:

```bash
code --install-extension superqode.superqode
```

### Features

The VSCode extension provides:

- **Real-time Diagnostics**: QE findings shown as problems in Problems panel
- **Inline Warnings**: Findings highlighted directly in code
- **Quick Fixes**: Apply patches from QE sessions
- **Status Bar**: QE status indicator
- **Commands**: Run QE sessions from Command Palette

### Configuration

Add to your VSCode `settings.json`:

```json
{
  "superqode.enable": true,
  "superqode.showStatusBar": true,
  "superqode.serverPath": "superqode",
  "superqode.autoRunOnSave": false,
  "superqode.diagnosticSeverity": {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "info",
    "info": "hint"
  }
}
```

**Settings:**

| Setting | Description | Default |
|---------|-------------|---------|
| `superqode.enable` | Enable SuperQode | `true` |
| `superqode.showStatusBar` | Show status bar item | `true` |
| `superqode.serverPath` | Path to `superqode` CLI | `"superqode"` |
| `superqode.autoRunOnSave` | Run QE on file save | `false` |
| `superqode.diagnosticSeverity` | Map QE severity to diagnostic level | (see above) |

### Usage

#### Run QE Session

1. Open Command Palette (Ctrl+Shift+P / Cmd+Shift+P)
2. Type "SuperQode: Run QE"
3. Select mode (Quick Scan or Deep QE)

Or use the status bar:
- Click the SuperQode status bar item
- Select "Run Quick Scan" or "Run Deep QE"

#### View Findings

Findings appear in:

- **Problems Panel**: All findings listed
- **Editor**: Inline warnings/errors
- **Hover**: Details on hover over underlined code

#### Apply Quick Fixes

1. Hover over a finding in the editor
2. Click "Quick Fix" or press Ctrl+. (Cmd+. on Mac)
3. Select "Apply QE Fix" from suggestions

---

## LSP Server

The LSP server provides editor-agnostic integration for any LSP-compatible editor.

### Starting the Server

```bash
# Stdio mode (for editors)
superqode serve lsp

# TCP mode (for debugging)
superqode serve lsp --transport tcp --port 9000
```

### Supported Editors

- **VSCode**: Via extension (automatic)
- **Neovim**: Via `nvim-lspconfig`
- **Vim**: Via `vim-lsp` or `coc.nvim`
- **Emacs**: Via `lsp-mode`
- **Sublime Text**: Via `LSP` package
- **Atom**: Via `atom-languageclient`

---

## Neovim Setup

### Using nvim-lspconfig

```lua
-- Add to your Neovim config (init.lua or init.vim)

-- Register SuperQode LSP server
require('lspconfig.configs').superqode = {
  default_config = {
    cmd = { 'superqode', 'serve', 'lsp' },
    filetypes = { '*' },  -- All file types
    root_dir = function(fname)
      return vim.fn.getcwd()
    end,
    settings = {},
  },
}

-- Setup the server
require('lspconfig').superqode.setup({
  on_attach = function(client, bufnr)
    -- Key mappings
    vim.api.nvim_buf_set_keymap(bufnr, 'n', 'gD', '<cmd>lua vim.lsp.buf.declaration()<CR>', opts)
    vim.api.nvim_buf_set_keymap(bufnr, 'n', 'gd', '<cmd>lua vim.lsp.buf.definition()<CR>', opts)
    vim.api.nvim_buf_set_keymap(bufnr, 'n', 'K', '<cmd>lua vim.lsp.buf.hover()<CR>', opts)
  end,
})
```

### Using lazy.nvim

```lua
-- In your plugins configuration

{
  "neovim/nvim-lspconfig",
  config = function()
    local lspconfig = require("lspconfig")

    lspconfig.superqode.setup({
      cmd = { "superqode", "serve", "lsp" },
      filetypes = { "*" },
      root_dir = lspconfig.util.root_pattern("superqode.yaml", ".git"),
    })
  end,
}
```

---

## Emacs Setup

### Using lsp-mode

```elisp
;; Add to your Emacs config

(use-package lsp-mode
  :init
  (setq lsp-superqode-server-command '("superqode" "serve" "lsp"))

  :config
  (lsp-register-client
   (make-lsp-client :new-connection (lsp-stdio-connection "superqode serve lsp")
                    :major-modes '(prog-mode)
                    :server-id 'superqode)))
```

---

## LSP Features

### Diagnostics

QE findings are exposed as LSP diagnostics:

```json
{
  "range": {
    "start": {"line": 41, "character": 10},
    "end": {"line": 41, "character": 45}
  },
  "severity": 2,
  "message": "SQL Injection Vulnerability: Unsanitized user input in SQL query",
  "source": "SuperQode",
  "code": "F001"
}
```

**Severity Mapping:**

| QE Severity | LSP Severity | Description |
|-------------|--------------|-------------|
| `critical` | `1` (Error) | Red underline |
| `high` | `1` (Error) | Red underline |
| `medium` | `2` (Warning) | Yellow underline |
| `low` | `3` (Information) | Blue underline |
| `info` | `4` (Hint) | Gray underline |

### Code Actions

Apply QE fixes via code actions:

```json
{
  "title": "Apply QE Fix: Sanitize SQL query",
  "kind": "quickfix",
  "edit": {
    "changes": {
      "file:///path/to/file.py": [{
        "range": {"start": {"line": 41}, "end": {"line": 42}},
        "newText": "sql = \"SELECT * FROM users WHERE name LIKE ?\"\nparams = (f\"%{query}%\",)"
      }]
    }
  }
}
```

### Hover Information

Hover over findings for details:

```json
{
  "contents": {
    "kind": "markdown",
    "value": "## SQL Injection Vulnerability\n\n**Severity:** High\n\n**Location:** src/api/users.py:42\n\n**Description:** User input is directly interpolated into SQL query without sanitization.\n\n**Suggested Fix:** Use parameterized queries with placeholders."
  }
}
```

---

## Configuration

### LSP Server Options

```bash
superqode serve lsp --help

Options:
  --transport, -t  Transport mode: stdio or tcp
  --port, -p       Port for TCP transport (default: 9000)
  --project        Project root directory (default: current directory)
  --verbose, -v    Enable verbose logging
```

### Project Configuration

The LSP server reads your `superqode.yaml` configuration:

```yaml
# superqode.yaml
superqode:
  version: "2.0"

# LSP-specific settings
lsp:
  auto_refresh: true        # Refresh diagnostics on file changes
  refresh_delay: 500        # Delay in ms before refreshing
  max_diagnostics: 100      # Maximum diagnostics per file
```

---

## Troubleshooting

### LSP Server Not Starting

**Problem**: Extension can't connect to LSP server

**Solution**:
1. Verify `superqode` is in PATH:
   ```bash
   which superqode
   ```

2. Test LSP server manually:
   ```bash
   superqode serve lsp --transport tcp --port 9000
   ```

3. Check VSCode output:
   - Open Output panel (View → Output)
   - Select "SuperQode" from dropdown
   - Look for error messages

### Diagnostics Not Showing

**Problem**: QE findings not appearing as diagnostics

**Solution**:
1. Run a QE session first:
   ```bash
   superqe run . --mode quick
   ```

2. Check if QR was generated:
   ```bash
   ls -la .superqode/qe-artifacts/
   ```

3. Restart LSP server:
   - VSCode: Reload window (Ctrl+Shift+P → "Reload Window")
   - Neovim: Restart LSP client

### Slow Performance

**Problem**: LSP server is slow or unresponsive

**Solution**:
1. Reduce `max_diagnostics` in config
2. Use `--mode quick` for faster QE
3. Exclude large directories:
   ```yaml
   qe:
     workspace:
       exclude:
         - node_modules
         - .venv
         - build
   ```

---

## Commands

### VSCode Commands

Available in Command Palette:

- **SuperQode: Run Quick Scan**: Run quick QE analysis
- **SuperQode: Run Deep QE**: Run comprehensive QE analysis
- **SuperQode: Show Findings**: Open findings panel
- **SuperQode: Clear Findings**: Clear current diagnostics
- **SuperQode: Refresh Diagnostics**: Reload findings from latest QR

### Key Bindings

Default key bindings (can be customized):

| Action | Windows/Linux | macOS |
|--------|---------------|-------|
| Show Quick Fix | `Ctrl+.` | `Cmd+.` |
| Show Hover | `Ctrl+K Ctrl+I` | `Cmd+K Cmd+I` |
| Go to Problem | `F8` | `F8` |

---

## Example Workflow

### 1. Install Extension

```bash
code --install-extension superqode.superqode
```

### 2. Open Project

```bash
cd /path/to/project
code .
```

### 3. Run QE

- Press `Ctrl+Shift+P` (Cmd+Shift+P on Mac)
- Type "SuperQode: Run Quick Scan"
- Wait for analysis to complete

### 4. Review Findings

- Open Problems panel (View → Problems)
- Click on findings to jump to code
- Hover over underlined code for details

### 5. Apply Fixes

- Place cursor on finding
- Press `Ctrl+.` (Cmd+. on Mac)
- Select "Apply QE Fix"

---

## Advanced Usage

### Custom LSP Configuration

For advanced editors, configure LSP directly:

```json
{
  "lsp": {
    "superqode": {
      "command": ["superqode", "serve", "lsp"],
      "args": ["--transport", "stdio"],
      "rootPatterns": ["superqode.yaml", ".git"],
      "filetypes": ["*"],
      "initializationOptions": {},
      "settings": {}
    }
  }
}
```

### WebSocket Transport

Some editors support WebSocket (if added to LSP server):

```bash
# Future feature
superqode serve lsp --transport websocket --port 9000
```

---

## Best Practices

### 1. Run QE Before Reviewing

Always run QE session before expecting diagnostics:

```bash
superqe run . --mode quick
```

### 2. Use Quick Mode for Development

Quick mode is faster and suitable for development:

```bash
# In VSCode command
SuperQode: Run Quick Scan
```

### 3. Review Before Applying Fixes

Don't auto-apply fixes. Review them first:

- Hover to see suggested fix
- Check the patch in Problems panel
- Apply manually if needed

### 4. Exclude Build Artifacts

Configure excludes for better performance:

```yaml
qe:
  workspace:
    exclude:
      - node_modules
      - dist
      - build
```

---

## Next Steps

- [CI/CD Integration](cicd.md) - Pipeline integration
- [QE Features](../qe-features/index.md) - Understanding QE capabilities
