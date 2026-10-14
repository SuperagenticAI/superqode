"""User-facing route capabilities without probing accounts or starting agents."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConnectionCapability:
    label: str
    state: str
    detail: str


def connection_capabilities(
    *, connector="", runtime="", acp_capabilities=None, codex=None, native_loop=None
):
    """Separate host features, negotiated agent features and unknown vendor state."""
    if runtime in {"pipy", "codegem"}:
        return (
            ConnectionCapability(
                "Permissions", "Host process", "No interactive tool approval or tool sandbox"
            ),
            ConnectionCapability(
                "Continue", "Native session", "Conversation state; switching may replay context"
            ),
            ConnectionCapability(
                "Live steering", "Supported", "Steering is delivered at the next supported boundary"
            ),
            ConnectionCapability(
                "Compaction", "Harness-owned", "Selected runtime context management"
            ),
            ConnectionCapability(
                "File recovery", "Not guaranteed", "Conversation checkpoints do not restore files"
            ),
            ConnectionCapability("Usage", "When reported", "Missing usage is unknown"),
        )
    if connector == "external-cli":
        return (
            ConnectionCapability(
                "Interface", "Vendor-owned", "Opens the vendor terminal interface"
            ),
            ConnectionCapability(
                "Controls and recovery",
                "Vendor-owned",
                "SuperQode does not supervise this external session",
            ),
        )
    if (connector in {"byok", "local"} and not runtime) or (
        runtime == "builtin" and connector != "acp" and native_loop is not False
    ):
        return (
            ConnectionCapability("Permissions", "SuperQode", "ASK/AUTO/DENY and project policy"),
            ConnectionCapability("Continue / fork", "SuperQode", "Saved native conversation"),
            ConnectionCapability("Live steering", "Supported", "Use :steer during a native turn"),
            ConnectionCapability("Compaction", "SuperQode", ":compact [instructions]"),
            ConnectionCapability("File recovery", "SuperQode", "Bounded Git task checkpoints"),
            ConnectionCapability(
                "Usage", "When reported", "Provider usage; cost may be unavailable"
            ),
        )
    if connector == "acp":
        resume = (
            "Not negotiated"
            if acp_capabilities is None
            else "Advertised"
            if acp_capabilities.get("loadSession")
            else "Context replay"
        )
        return (
            ConnectionCapability("Permissions", "Agent + host", "Agent requests host approval"),
            ConnectionCapability("Continue", resume, "Exact resume depends on the agent"),
            ConnectionCapability("Live steering", "Unavailable", "Use :queue add for a follow-up"),
            ConnectionCapability("Compaction", "Agent-owned", "Use the agent's context controls"),
            ConnectionCapability("File recovery", "SuperQode", "Bounded Git task checkpoints"),
            ConnectionCapability("Usage", "When reported", "Only negotiated/reported agent data"),
        )
    if runtime == "codex-cli":

        def supported(method):
            if not codex or not codex.verified:
                return "Not verified"
            return "Supported" if codex.supports(method) else "Unavailable"

        return (
            ConnectionCapability(
                "Permissions", "Codex + host", "Codex sandbox; supported host policy"
            ),
            ConnectionCapability("Continue", supported("thread/resume"), "Codex thread state"),
            ConnectionCapability("Fork", supported("thread/fork"), "Independent Codex thread"),
            ConnectionCapability(
                "Live steering", supported("turn/steer"), ":steer during a Codex turn"
            ),
            ConnectionCapability("Compaction", supported("thread/compact/start"), ":codex compact"),
            ConnectionCapability("File recovery", "SuperQode", "Bounded Git task checkpoints"),
            ConnectionCapability("Usage", "When reported", "Codex account and token reports"),
        )
    return (
        ConnectionCapability(
            "Permissions", "Harness-owned", "Supported host controls vary by route"
        ),
        ConnectionCapability(
            "Continue / fork", "Route-dependent", "Check the harness's session controls"
        ),
        ConnectionCapability(
            "Live steering",
            "Unavailable" if native_loop is False else "Not verified",
            "Use :queue add if steering is unavailable",
        ),
        ConnectionCapability("Compaction", "Harness-owned", "Native :compact is not universal"),
        ConnectionCapability(
            "File recovery", "SuperQode", "Bounded Git task checkpoints for hosted tasks"
        ),
        ConnectionCapability("Usage", "When reported", "Unavailable values are not zero usage"),
    )


def profile_capabilities(profile):
    """Menus are navigation, not connected routes."""
    connector = getattr(profile, "connector", "")
    if connector.endswith("picker") or connector.endswith("menu"):
        return ()
    if connector in {"byok", "local"}:
        return (
            ConnectionCapability(
                "Model source", "Selected harness", "Retains the harness you chose"
            ),
            ConnectionCapability(
                "Controls and recovery", "Harness-dependent", "Verify after selecting the model"
            ),
            ConnectionCapability(
                "Usage", "When reported", "Provider usage; cost may be unavailable"
            ),
        )
    return connection_capabilities(
        connector=connector, runtime=getattr(profile, "runtime", "") or ""
    )


def capability_text(rows):
    return "\n".join(f"{row.label}: {row.state} · {row.detail}" for row in rows)
