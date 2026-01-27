<img src="https://raw.githubusercontent.com/SuperagenticAI/superqode/main/assets/super-qode-header.png" alt="SuperQode Banner" />

# Serve Commands

Start various SuperQode servers for IDE and web integration.

---

## Overview

The `superqode serve` command group provides commands for running SuperQode servers:

- **LSP Server**: Language Server Protocol server for IDE integration
- **Web Server**: Browser-based TUI interface
- **Status**: Check running server status

Note: `superqode serve` is an enterprise feature.

---

## serve lsp

Start the Language Server Protocol (LSP) server for IDE integration.

```bash
superqode serve lsp [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--transport`, `-t` | Transport mode: `stdio` or `tcp` | `stdio` |
| `--port`, `-p` | Port for TCP transport | `9000` |
| `--project` | Project root directory | `.` (current directory) |
| `--verbose`, `-v` | Enable verbose logging | `false` |

### Transport Modes

#### stdio Mode (Default)

For editor integration. The server communicates via stdin/stdout.

```bash
# Start LSP in stdio mode (for editors)
superqode serve lsp
```

**Use case**: When launched by your editor/IDE (VSCode, Neovim, etc.)

#### TCP Mode

For debugging and manual connection. The server listens on a TCP port.

```bash
# Start LSP on TCP port 9000
superqode serve lsp --transport tcp --port 9000
```

**Use case**: Debugging, testing, or manual editor configuration

### Examples

```bash
# Start in stdio mode (default, for editors)
superqode serve lsp

# Start in TCP mode for debugging
superqode serve lsp -t tcp -p 9000

# Start with verbose logging
superqode serve lsp --verbose

# Start for specific project
superqode serve lsp --project ./myproject
```

---

## IDE Integration

### VSCode Setup

1. Install the SuperQode VSCode extension
2. The extension automatically connects to the LSP server
3. QE findings appear as diagnostics in the Problems panel

**Configuration**: The extension launches `superqode serve lsp` automatically.

### Neovim Setup

Using `nvim-lspconfig`:

```lua
require('lspconfig.configs').superqode = {
    default_config = {
        cmd = { 'superqode', 'serve', 'lsp' },
        filetypes = { '*' },
        root_dir = function(fname)
            return vim.fn.getcwd()
        end,
    },
}
require('lspconfig').superqode.setup{}
```

### Other LSP Clients

Any LSP-compatible editor can connect:

```bash
# stdio mode (launched by editor)
superqode serve lsp

# TCP mode (manual connection)
superqode serve lsp -t tcp -p 9000
```

Then configure your LSP client to connect to `localhost:9000`.

---

## serve web

Start the web server for browser-based TUI.

```bash
superqode serve web [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--port`, `-p` | Port for web server | `8080` |
| `--host`, `-h` | Host to bind to | `127.0.0.1` |
| `--project` | Project root directory | `.` |
| `--no-open` | Don't open browser automatically | `false` |

### Examples

```bash
# Start on default port (8080)
superqode serve web

# Use custom port
superqode serve web -p 3000

# Allow external connections
superqode serve web -h 0.0.0.0

# Start without opening browser
superqode serve web --no-open

# Start for specific project
superqode serve web --project ./myproject
```

### Access

Once started, open your browser to:

```
http://localhost:8080
```

(or the port you specified)

The web interface provides the same TUI experience as the terminal version.

---

## serve status

Show status of running servers.

```bash
superqode serve status [OPTIONS]
```

### Options

| Option | Description | Default |
|--------|-------------|---------|
| `--project` | Project directory | `.` |

### Examples

```bash
# Check server status
superqode serve status
```

### Output

Shows status for:
- **LSP Server**: Running status (TCP mode only; stdio mode doesn't show)
- **Web Server**: Running status on port 8080

### Example Output

```
SuperQode Server Status

LSP Server: Not running (stdio mode doesn't show here)
Web Server: Running on port 8080
```

**Note**: LSP servers in stdio mode don't appear in status because they're process-to-process connections, not network services.

---

## Common Workflows

### IDE Integration (LSP)

```bash
# Start LSP server for editor
superqode serve lsp

# Or let your editor start it automatically
# (VSCode extension does this)
```

### Web Interface

```bash
# Start web server
superqode serve web

# Browser opens automatically at http://localhost:8080
```

### Debugging LSP

```bash
# Start in TCP mode for debugging
superqode serve lsp -t tcp -p 9000 --verbose

# Connect with LSP client or test manually
```

### Check Running Servers

```bash
# See what's running
superqode serve status
```

---

## Server Features

### LSP Server Features

- **Diagnostics**: QE findings appear as editor diagnostics
- **Code Actions**: Quick fixes and suggestions
- **Documentation**: Hover information for findings
- **Workspace**: Full project context awareness

### Web Server Features

- **Full TUI**: Complete SuperQode TUI in browser
- **Interactive**: All TUI commands and features
- **Accessible**: Use from any device on network
- **No Installation**: Just a browser needed

---

## Troubleshooting

### Port Already in Use

```
Error: Address already in use
```

**Solution**:
```bash
# Use a different port
superqode serve web -p 3000
superqode serve lsp -t tcp -p 9001
```

### LSP Not Connecting

**For stdio mode**: Ensure your editor is launching the command correctly.

**For TCP mode**:
```bash
# Verify server is running
superqode serve status

# Check port accessibility
curl http://localhost:9000/health
```

### Web Server Not Accessible

**Local only (default)**:
```bash
# Default (localhost only)
superqode serve web

# Allow external access
superqode serve web -h 0.0.0.0
```

**Firewall**: Ensure port 8080 (or your port) is open.

### LSP Diagnostics Not Showing

**Check**:
1. LSP server is running (`superqode serve status`)
2. Editor LSP client is configured correctly
3. Project has QE findings (run `superqe run .` first)

---

## Security Considerations

### LSP Server

- **stdio mode**: Process-to-process, no network exposure
- **TCP mode**: Only bind to `127.0.0.1` by default (localhost only)

### Web Server

- **Default**: Binds to `127.0.0.1` (localhost only)
- **External access**: Use `--host 0.0.0.0` only in trusted networks
- **Authentication**: Not included (add reverse proxy for production)

### Best Practices

1. **Development**: Use default localhost binding
2. **Team Access**: Use reverse proxy with authentication
3. **CI/CD**: Don't expose servers externally

---

## Related Commands

- `superqe run` - Generate QE findings for LSP diagnostics
- `superqe dashboard` - Alternative web interface for QRs

---

## Next Steps

- [IDE Integration](../integration/ide.md) - Detailed IDE setup guides
- [QE Commands](qe-commands.md) - Quality engineering workflows
