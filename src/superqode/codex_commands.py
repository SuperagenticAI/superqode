"""The supported Codex controls shared by help and both completion surfaces."""

CODEX_COMMANDS = (
    ("help", "Show Codex commands and integration limits"),
    ("status", "Show Codex CLI/app-server status"),
    ("doctor", "Run the installed CLI's redacted diagnostic report"),
    ("model", "Pick or set the Codex model for future turns"),
    ("models", "List models available to this Codex account"),
    ("effort", "Pick or set Codex reasoning effort"),
    ("sandbox", "Set the Codex sandbox override"),
    ("permissions", "Inspect/select profiles; on-request, untrusted, never or granular policy"),
    ("plan", "Set native Codex Plan mode: on or off"),
    ("review", "Review changes, --base <branch>, or --commit <sha>"),
    ("new", "Start a fresh Codex chat, optionally with a name"),
    ("thread", "Show the current Codex thread"),
    ("history", "Inspect earlier messages and tool calls; --cursor pages back"),
    ("tools", "Inspect SuperQode tools exposed through Codex dynamic tools"),
    (
        "turn-options",
        "Set JSON output schema, summary, service tier or client message ID for the next turn",
    ),
    ("attach", "Attach a user-owned local Codex daemon, or return to stdio"),
    ("sessions", "List Codex sessions; supports --archived, --all and --cursor"),
    ("resume", "Resume a Codex thread by ID or --last"),
    ("fork", "Fork the current Codex thread or a saved thread ID"),
    ("compact", "Compact the current Codex thread"),
    ("rename", "Rename the current Codex thread"),
    ("archive", "Archive a Codex thread"),
    ("unarchive", "Restore an archived Codex thread by ID"),
    ("account", "Show the signed-in Codex account"),
    ("login", "Sign in with ChatGPT; --device-auth, status, or cancel"),
    ("logout", "Sign out of Codex"),
    ("usage", "Read account rate limits or token activity with --tokens"),
    ("mcp", "Inspect Codex MCP tools; reload or --cursor <cursor>"),
    ("skills", "List Codex skills; --reload refreshes discovery"),
    ("plugins", "List Codex plugins; --reload refreshes the catalog"),
    ("apps", "List Codex apps; --reload or --cursor <cursor>"),
    ("hooks", "Inspect Codex lifecycle hooks"),
    ("features", "Inspect Codex experimental feature state; --cursor <cursor>"),
    ("config", "Inspect redacted Codex config layers and managed requirements"),
    ("ps", "List this Codex thread's background terminals"),
    ("stop", "Stop this Codex thread's background terminals"),
    ("cancel", "Interrupt the active Codex turn"),
    ("agents", "List this Codex thread's descendant agent sessions"),
    ("rollout", "Show this Codex thread's saved transcript path"),
    ("pwd", "Show the Codex working directory"),
    ("diff", "Inspect workspace changes in SuperQode"),
    ("copy", "Copy the latest response using SuperQode"),
)

CODEX_ALIASES = {
    "?": "help",
    "--help": "help",
    "-h": "help",
    "reasoning": "effort",
    "threads": "sessions",
    "info": "thread",
    "plugin": "plugins",
    "experimental": "features",
    "debug-config": "config",
    "subagents": "agents",
    "cwd": "pwd",
    "clean": "stop",
}

CODEX_OPTIONS = {
    "plan": (("on", "Use native Codex Plan mode"), ("off", "Use native Codex default mode")),
    "permissions": (
        ("mediated", "Use human approvals, on-request policy and workspace-write sandbox"),
        ("on-request", "Let Codex request approvals"),
        ("never", "Never request approvals; retain sandbox restrictions"),
        ("untrusted", "Ask for commands outside Codex's trusted set"),
        ("profile", "Select a named permission profile: follow with its ID"),
        ("granular", "Follow with JSON approval categories"),
    ),
    "login": (
        ("--device-auth", "Sign in with a one-time device code"),
        ("status", "Check the signed-in account"),
        ("cancel", "Cancel the pending sign-in"),
    ),
    "review": (
        ("--detached", "Run review in a separate read-only Codex thread"),
        ("--uncommitted", "Review staged, unstaged and untracked changes"),
        ("--base", "Follow with a base branch"),
        ("--commit", "Follow with a commit SHA"),
    ),
    "sessions": (
        ("--archived", "List archived threads"),
        ("--all", "Include other working directories"),
        ("--cursor", "Follow with the returned page cursor"),
    ),
    "resume": (("--last", "Resume the latest saved thread in this directory"),),
    "usage": (("--tokens", "Read account token activity"),),
    "mcp": (
        ("verbose", "Show the full Codex MCP inventory"),
        ("reload", "Reload Codex MCP configuration"),
        ("login", "Authorize a Codex MCP server: follow with its name"),
        ("--cursor", "Follow with the returned page cursor"),
    ),
    "skills": (("--reload", "Rescan Codex skills"),),
    "plugins": (("--reload", "Refresh the Codex plugin catalog"),),
    "apps": (
        ("--reload", "Refresh the Codex app catalog"),
        ("--cursor", "Follow with the returned page cursor"),
    ),
    "features": (("--cursor", "Follow with the returned page cursor"),),
    "ps": (("--cursor", "Follow with the returned page cursor"),),
    "agents": (("--cursor", "Follow with the returned page cursor"),),
    "history": (("--cursor", "Follow with the returned history cursor"),),
}


def redact_codex_data(value):
    """Configuration and inventory responses may contain credential settings."""
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            normalized = str(key).lower().replace("_", "").replace("-", "")
            sensitive = any(
                marker in normalized
                for marker in (
                    "apikey",
                    "accesstoken",
                    "refreshtoken",
                    "bearertoken",
                    "password",
                    "secret",
                    "authorization",
                    "credential",
                    "headers",
                )
            ) or normalized in {"env", "environment", "token", "key"}
            result[key] = "[redacted]" if sensitive else redact_codex_data(item)
        return result
    if isinstance(value, list):
        return [redact_codex_data(item) for item in value]
    return value
