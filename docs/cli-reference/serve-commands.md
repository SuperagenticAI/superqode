# Serve Commands

Start a browser-based TUI server for SuperQode.

---

## serve web

Start the Textual TUI server over HTTP.

```bash
superqode serve web [OPTIONS]
```

### Options

| Option | Description |
|--------|-------------|
| `--host` | Bind address (default: `127.0.0.1`) |
| `--port` | Port number (default: `8000`) |

### Examples

```bash
superqode serve web
superqode serve web --host 0.0.0.0 --port 8080
```

Uses `textual-serve` to expose the full SuperQode TUI over HTTP. Open the provided URL in a browser for a terminal-like experience without a local terminal emulator.
