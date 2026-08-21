"""Drive a vendor's own CLI on the user's subscription, without ACP.

Subscriptions must spend the plan the user already pays for. Every vendor CLI
here authenticates through its own login (``grok login``, ``copilot login``,
``cursor-agent login`` …) and exposes a non-interactive mode with structured
output, so SuperQode can render the turn in its own TUI while the vendor keeps
owning the agent loop.

Two things are deliberate:

* **Billing.** The child process starts from :func:`subscription_child_env`, so
  an API key left in the shell cannot silently move the session onto metered
  billing. The user's own environment is never modified: only the dict handed
  to this one subprocess omits those variables.
* **Permissions.** Vendor headless modes cannot prompt, so they require
  pre-authorisation. That is stated to the user on the first turn rather than
  being applied quietly.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import Any, Callable

from superqode.harness.events import HarnessEvent
from superqode.runtime.errors import RuntimeNotInstalledError

_DEFAULT_TURN_TIMEOUT = 900.0


def _turn_timeout() -> float:
    try:
        value = float(os.environ.get("SUPERQODE_VENDOR_CLI_TIMEOUT", "") or _DEFAULT_TURN_TIMEOUT)
    except ValueError:
        return _DEFAULT_TURN_TIMEOUT
    return value if value > 0 else _DEFAULT_TURN_TIMEOUT


# --- stream parsers -----------------------------------------------------------
#
# Each parser turns one decoded JSON object into zero or more HarnessEvents.
# They are pure so the wire formats can be tested from recorded fixtures
# without launching a vendor CLI.


def _text_event(text: str) -> list[HarnessEvent]:
    return [HarnessEvent(type="model_delta", data={"text": text})] if text else []


def parse_copilot_event(obj: dict) -> list[HarnessEvent]:
    """GitHub Copilot CLI ``--output-format json`` (JSONL)."""
    kind = str(obj.get("type") or "")
    data = obj.get("data") or {}
    if kind == "assistant.message_delta":
        return _text_event(str(data.get("deltaContent") or ""))
    if kind == "session.auto_mode_resolved":
        model = str(data.get("chosenModel") or "")
        # Copilot Free advertises no catalog, so this is the only place the
        # actually-used model is reported.
        return [HarnessEvent(type="model_request", data={"model": model})] if model else []
    if kind == "session.usage_checkpoint":
        return [HarnessEvent(type="turn_usage", data=dict(data))]
    if kind == "assistant.turn_end":
        return [HarnessEvent(type="turn_complete", data={"status": "completed"})]
    return []


_GROK_TERMINAL_TOOL_STATUSES = frozenset(
    {"completed", "complete", "failed", "error", "cancelled", "canceled"}
)
# Patterns that already look like Grok's rule DSL are passed through as-is.
_GROK_RULE_PREFIXES = (
    "Bash(",
    "Edit(",
    "Write(",
    "Read(",
    "Grep(",
    "WebFetch(",
    "MCPTool(",
)
# SuperQode tool ids we can name as a Grok prefix without inventing a glob.
_GROK_TOOL_RULES = {
    "bash": "Bash",
    "read_file": "Read",
    "read": "Read",
    "list_directory": "Read",
    "list_dir": "Read",
    "write_file": "Write",
    "write": "Write",
    "edit_file": "Edit",
    "edit": "Edit",
    "grep": "Grep",
    "fetch": "WebFetch",
    "web_fetch": "WebFetch",
}


def grok_rule_from_pattern(pattern: str) -> str | None:
    """Translate one SuperQode allow/deny pattern into a Grok ``--allow``/``--deny`` rule.

    Only exact Grok DSL (``Bash(rm*)``) and a small tool-name map are forwarded.
    An unrecognized glob is dropped rather than guessed — a bad translation
    would silently over-allow.
    """
    text = str(pattern or "").strip()
    if not text:
        return None
    if text.startswith(_GROK_RULE_PREFIXES) or text in {
        "Bash",
        "Edit",
        "Write",
        "Read",
        "Grep",
        "WebFetch",
        "MCPTool",
    }:
        return text
    mapped = _GROK_TOOL_RULES.get(text)
    return mapped


def _grok_plan_todos(entries: Any) -> list[dict[str, str]]:
    todos: list[dict[str, str]] = []
    if not isinstance(entries, list):
        return todos
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("content") or entry.get("step") or entry.get("text") or "").strip()
        if not content:
            continue
        todos.append(
            {
                "id": str(entry.get("id") or index),
                "content": content,
                "status": str(entry.get("status") or "pending"),
                "priority": str(entry.get("priority") or "medium"),
            }
        )
    return todos


def _grok_end_data(obj: dict, *, status: str, error: str | None = None) -> dict[str, Any]:
    """Spend-safe payload for ``end`` / ``error``. Absent cost is not treated as free."""
    data: dict[str, Any] = {
        "status": status,
        "stop_reason": obj.get("stopReason") or obj.get("stop_reason"),
        "session_id": obj.get("sessionId") or obj.get("session_id"),
        "request_id": obj.get("requestId") or obj.get("request_id"),
        "usage": obj.get("usage") or {},
        "num_turns": obj.get("num_turns"),
        "model_usage": obj.get("modelUsage") or obj.get("model_usage") or {},
    }
    if error:
        data["error"] = error
    cost_partial = bool(obj.get("cost_is_partial") or obj.get("usage_is_incomplete"))
    if cost_partial:
        data["cost_is_partial"] = True
        if obj.get("usage_is_incomplete"):
            data["usage_is_incomplete"] = True
    elif "total_cost_usd" in obj:
        data["total_cost_usd"] = obj.get("total_cost_usd")
        if "total_cost_usd_ticks" in obj:
            data["total_cost_usd_ticks"] = obj.get("total_cost_usd_ticks")
    return data


def parse_grok_event(obj: dict) -> list[HarnessEvent]:
    """Grok CLI ``--output-format streaming-json`` (ACP session updates as NDJSON)."""
    kind = str(obj.get("type") or "")
    if kind == "text":
        return _text_event(str(obj.get("data") or ""))
    if kind == "thought":
        return [HarnessEvent(type="thinking", data={"text": str(obj.get("data") or "")})]
    if kind == "tool_call":
        return [
            HarnessEvent(
                type="tool_call",
                data={
                    "tool_name": str(obj.get("toolName") or obj.get("title") or "tool"),
                    "tool_call_id": obj.get("toolCallId") or obj.get("tool_call_id"),
                    "args": obj.get("rawInput") if isinstance(obj.get("rawInput"), dict) else {},
                    "kind": obj.get("kind"),
                    "title": obj.get("title"),
                    "status": obj.get("status"),
                },
            )
        ]
    if kind == "tool_call_update":
        status = str(obj.get("status") or "").strip().lower()
        if status not in _GROK_TERMINAL_TOOL_STATUSES:
            return []
        raw_output = obj.get("rawOutput")
        if raw_output is None:
            output = ""
        elif isinstance(raw_output, str):
            output = raw_output
        else:
            output = json.dumps(raw_output, ensure_ascii=False)
        failed = status in {"failed", "error", "cancelled", "canceled"}
        return [
            HarnessEvent(
                type="tool_result",
                data={
                    "tool_name": str(obj.get("toolName") or ""),
                    "tool_call_id": obj.get("toolCallId") or obj.get("tool_call_id"),
                    "success": not failed,
                    "output": output,
                    "status": status,
                },
            )
        ]
    if kind == "plan":
        todos = _grok_plan_todos(obj.get("entries"))
        return [HarnessEvent(type="plan_update", data={"todos": todos})] if todos else []
    if kind == "usage":
        # Per-response ledger. PureMode has no turn_usage handler; spend is
        # flushed on ``end``. Keep the event for callers that inspect the
        # stream, without inventing a cost.
        usage = obj.get("usage") if isinstance(obj.get("usage"), dict) else {}
        return [HarnessEvent(type="turn_usage", data=dict(usage))] if usage else []
    if kind == "available_commands":
        # Session ads belong on runtime metadata, not a harness event.
        return []
    if kind == "error":
        message = str(obj.get("message") or obj.get("data") or "Grok reported an error")
        return [
            HarnessEvent(
                type="turn_complete",
                data=_grok_end_data(obj, status="failed", error=message),
            )
        ]
    if kind == "end":
        return [HarnessEvent(type="turn_complete", data=_grok_end_data(obj, status="completed"))]
    return []


def _warp_payload(obj: dict, *drop: str) -> dict:
    """Everything except the routing tags, which are the line's own payload."""
    skip = {"type", *drop}
    return {key: value for key, value in obj.items() if key not in skip}


def _warp_todos(entries: Any, *, completed: bool) -> list[dict[str, str]]:
    """Warp todos carry ``title``/``description`` and no id or status of their own."""
    todos: list[dict[str, str]] = []
    if not isinstance(entries, list):
        return todos
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            continue
        content = str(entry.get("title") or "").strip()
        if not content:
            continue
        todos.append(
            {
                "id": str(index),
                "content": content,
                "status": "completed" if completed else "pending",
            }
        )
    return todos


def _warp_system_event(obj: dict) -> list[HarnessEvent]:
    """Warp ``system`` lines, sub-tagged by ``event_type``."""
    event_type = str(obj.get("event_type") or "")
    data: dict[str, Any] = {"event": event_type, **_warp_payload(obj, "event_type")}
    if event_type == "conversation_started":
        # ``--conversation <ID>`` resumes from this id, so hand it up under the
        # name the runtime stores sessions by.
        conversation_id = str(obj.get("conversation_id") or "")
        if conversation_id:
            data["session_id"] = conversation_id
    return [HarnessEvent(type="runtime_event", data=data)]


def parse_warp_event(obj: dict) -> list[HarnessEvent]:
    """Warp Oz CLI ``--output-format ndjson``.

    Every line is one object tagged by ``type``; tool lines carry a second
    ``tool`` tag naming the tool, which is passed through rather than
    translated into a SuperQode tool id.

    Warp reports no per-call tool ids, so ``tool_error`` and ``tool_canceled``
    cannot be correlated back to the call they belong to. Their tool name is
    left empty rather than guessed at from ordering.

    The format has no terminal event: the stream simply ends. ``turn_complete``
    is synthesized by the runtime from the exit status.
    """
    kind = str(obj.get("type") or "")

    if kind == "agent":
        return _text_event(str(obj.get("text") or ""))
    if kind == "agent_reasoning":
        text = str(obj.get("text") or "")
        return [HarnessEvent(type="thinking", data={"text": text})] if text else []
    if kind == "tool_call":
        return [
            HarnessEvent(
                type="tool_call",
                data={
                    "tool_name": str(obj.get("tool") or "tool"),
                    "args": _warp_payload(obj, "tool"),
                },
            )
        ]
    if kind == "tool_result":
        payload = _warp_payload(obj, "tool")
        return [
            HarnessEvent(
                type="tool_result",
                data={
                    "tool_name": str(obj.get("tool") or ""),
                    "success": True,
                    "output": json.dumps(payload, ensure_ascii=False) if payload else "",
                },
            )
        ]
    if kind == "tool_error":
        return [
            HarnessEvent(
                type="tool_result",
                data={
                    "tool_name": "",
                    "success": False,
                    "output": str(obj.get("error") or ""),
                    "status": "failed",
                },
            )
        ]
    if kind == "tool_canceled":
        return [
            HarnessEvent(
                type="tool_result",
                data={"tool_name": "", "success": False, "output": "", "status": "cancelled"},
            )
        ]
    if kind in {"update_todos", "complete_todos"}:
        completed = kind == "complete_todos"
        entries = obj.get("completed_todos") if completed else obj.get("todo_list")
        todos = _warp_todos(entries, completed=completed)
        return [HarnessEvent(type="plan_update", data={"todos": todos})] if todos else []
    if kind == "system":
        return _warp_system_event(obj)
    if kind == "artifact_created":
        return [
            HarnessEvent(
                type="runtime_event",
                data={"event": "artifact_created", **_warp_payload(obj)},
            )
        ]
    # These two variants are not renamed on the wire, so they arrive in the
    # Rust variant's own casing rather than snake_case.
    if kind == "SkillInvoked":
        return [
            HarnessEvent(
                type="runtime_event",
                data={"event": "skill_invoked", "name": str(obj.get("name") or "")},
            )
        ]
    if kind == "Subagent":
        return [
            HarnessEvent(
                type="runtime_event",
                data={"event": "subagent", "task_id": str(obj.get("task_id") or "")},
            )
        ]
    return []


def parse_generic_event(obj: dict) -> list[HarnessEvent]:
    """Best-effort reader for Claude-Code-style ``stream-json`` and friends.

    Vendors that were not individually verified land here. It reads the shapes
    those formats share and stays silent on anything it does not recognise, so
    an unknown field can never be rendered as if it were assistant output.
    """
    kind = str(obj.get("type") or "")

    # {"type": "assistant", "message": {"content": [{"type": "text", "text": …}]}}
    message = obj.get("message")
    if isinstance(message, dict):
        chunks = []
        content = message.get("content")
        if isinstance(content, list):
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    chunks.append(str(block.get("text") or ""))
        elif isinstance(content, str):
            chunks.append(content)
        return _text_event("".join(chunks))

    if kind in {"result", "end", "turn_end", "done"}:
        return [HarnessEvent(type="turn_complete", data={"status": "completed"})]

    for key in ("delta", "text", "content"):
        value = obj.get(key)
        if isinstance(value, str) and value:
            return _text_event(value)
    return []


PARSERS: dict[str, Callable[[dict], list[HarnessEvent]]] = {
    "copilot": parse_copilot_event,
    "grok": parse_grok_event,
    "warp": parse_warp_event,
    "generic": parse_generic_event,
}


# --- vendor descriptors -------------------------------------------------------


@dataclass(frozen=True)
class VendorCLISpec:
    """How to drive one vendor CLI non-interactively."""

    name: str  # runtime name, e.g. "grok-cli"
    vendor: str  # subscription_env vendor key
    label: str
    binary: str
    install_hint: str
    #: Executables to try when ``binary`` is not found, in order. Most vendors
    #: ship one stable command and leave this empty. It exists for vendors that
    #: are mid-rename, or that install outside PATH: entries may be absolute
    #: paths, which ``shutil.which`` checks directly.
    fallback_binaries: tuple[str, ...] = ()
    subcommand: tuple[str, ...] = ()
    #: Flag carrying the prompt; None means the prompt is positional.
    prompt_flag: str | None = "-p"
    output_format: tuple[str, ...] = ()
    model_flag: str | None = "--model"
    session_flag: str | None = None
    #: SuperQode approval mode -> the vendor's own permission flags. Headless
    #: modes cannot prompt per tool, so the closest equivalent in the vendor's
    #: own vocabulary is used rather than inventing one. A vendor that offers
    #: no gradation maps every mode to the same flags, and says so.
    permission_flags: dict[str, tuple[str, ...]] = field(default_factory=dict)
    parser: str = "generic"
    #: True when the vendor refuses to run headlessly without pre-authorisation.
    requires_pre_authorisation: bool = False

    @property
    def binary_candidates(self) -> tuple[str, ...]:
        """Executables to try, in order, most preferred first."""
        return (self.binary, *self.fallback_binaries)

    def resolve_binary(self) -> str | None:
        """Absolute path to the first candidate present, or None if none are.

        ``shutil.which`` checks a candidate containing a directory component
        directly instead of searching PATH, so absolute fallbacks work here.
        """
        for candidate in self.binary_candidates:
            found = shutil.which(candidate)
            if found:
                return found
        return None

    def flags_for_approval(self, approval_mode: str | None) -> tuple[str, ...]:
        """Vendor permission flags for a SuperQode approval mode."""
        if not self.permission_flags:
            return ()
        mode = (approval_mode or "auto").strip().lower()
        if mode in self.permission_flags:
            return self.permission_flags[mode]
        return self.permission_flags.get("auto", ())

    @property
    def has_gradated_permissions(self) -> bool:
        """True when approval mode actually changes what the vendor allows."""
        return len({tuple(v) for v in self.permission_flags.values()}) > 1


VENDOR_CLI_SPECS: dict[str, VendorCLISpec] = {
    "grok": VendorCLISpec(
        name="grok-cli",
        vendor="grok",
        label="Grok",
        binary="grok",
        install_hint="install the Grok CLI, then run `grok login`",
        prompt_flag="-p",
        output_format=("--output-format", "streaming-json"),
        model_flag="--model",
        session_flag="--resume",
        permission_flags={
            "auto": ("--permission-mode", "bypassPermissions"),
            # Headless cannot prompt. ``auto`` is Grok's classifier (blocks or
            # escalates) rather than ``acceptEdits``, which silently accepts
            # every write. SuperQode still will not pop a permission card.
            "ask": ("--permission-mode", "auto"),
            # ``plan`` is a documented no-op (same effects as default).
            # ``dontAsk`` restricts execution to pre-approved and read-only tools.
            "deny": ("--permission-mode", "dontAsk"),
        },
        parser="grok",
    ),
    "copilot": VendorCLISpec(
        name="copilot-cli",
        vendor="copilot",
        label="GitHub Copilot",
        binary="copilot",
        install_hint="run `npm install -g @github/copilot`, then `copilot login`",
        prompt_flag="-p",
        output_format=("--output-format", "json"),
        model_flag="--model",
        session_flag="--session-id",
        # Copilot's own help states --allow-all-tools is required for
        # non-interactive mode; there is no per-tool prompt to honour.
        permission_flags={
            "auto": ("--allow-all-tools",),
            "ask": ("--allow-all-tools",),
            "deny": ("--allow-all-tools",),
        },
        parser="copilot",
        requires_pre_authorisation=True,
    ),
    "cursor": VendorCLISpec(
        name="cursor-cli",
        vendor="cursor",
        label="Cursor",
        binary="cursor-agent",
        install_hint="install Cursor Agent, then sign in with `cursor-agent login`",
        prompt_flag="-p",
        output_format=("--output-format", "stream-json"),
        model_flag="--model",
        session_flag="--resume",
        permission_flags={
            "auto": ("--force",),
            "ask": ("--force",),
            "deny": ("--force",),
        },
        parser="generic",
        requires_pre_authorisation=True,
    ),
    "droid": VendorCLISpec(
        name="droid-cli",
        vendor="droid",
        label="Factory Droid",
        binary="droid",
        install_hint="install Factory Droid, then sign in with `droid`",
        subcommand=("exec",),
        prompt_flag=None,  # positional
        output_format=("--output-format", "json"),
        model_flag="--model",
        session_flag="--session-id",
        permission_flags={
            "auto": ("--auto", "high"),
            "ask": ("--auto", "low"),
            # Omitting --auto leaves Droid in its default read-only mode.
            "deny": (),
        },
        parser="generic",
    ),
    "devin": VendorCLISpec(
        name="devin-cli-print",
        vendor="devin",
        label="Devin",
        binary="devin",
        install_hint="install the Devin CLI, then run `devin auth login`",
        prompt_flag="-p",
        model_flag="--model",
        session_flag="--resume",
        permission_flags={
            "auto": ("--permission-mode", "dangerous"),
            "ask": ("--permission-mode", "accept-edits"),
            # Devin's most conservative mode still auto-approves read-only
            # tools; there is no full-deny in non-interactive mode.
            "deny": ("--permission-mode", "auto"),
        },
        parser="generic",
    ),
    "warp": VendorCLISpec(
        name="warp-cli",
        vendor="warp",
        label="Warp",
        # Warp is renaming the CLI from `oz` to `warp`, but the `warp` binary
        # shipping today is the interactive TUI with no prompt flag, so `oz`
        # stays primary. The absolute path covers a macOS install where the
        # user never ran the Command Palette's "Install Oz CLI Command".
        binary="oz",
        fallback_binaries=("oz-preview", "/Applications/Warp.app/Contents/Resources/bin/oz"),
        install_hint=(
            "install Warp from https://www.warp.dev, then run `oz login` (or export WARP_API_KEY)"
        ),
        subcommand=("agent", "run"),
        prompt_flag="-p",
        output_format=("--output-format", "ndjson"),
        # Warp routes models server-side under ids of its own (`auto`,
        # `gpt-5-4-high`, `claude-5-opus-medium`), listed by `oz model list`.
        # A SuperQode provider/model name is never one of them, so forwarding
        # it can only fail the run: Warp picks its own default instead until a
        # model surface that speaks Warp's ids exists.
        model_flag=None,
        session_flag="--conversation",
        # Warp's permissions live in server-side agent profiles selected by
        # `--profile <ID>`, so there is no auto/ask/deny vocabulary to map
        # onto. Headless runs are pre-authorised and the user is told so.
        permission_flags={},
        parser="warp",
        requires_pre_authorisation=True,
    ),
    "amp": VendorCLISpec(
        name="amp-cli",
        vendor="amp",
        label="Amp",
        binary="amp",
        install_hint="install the Amp CLI, then run `amp login`",
        prompt_flag="-x",
        output_format=("--stream-json",),
        model_flag=None,
        parser="generic",
    ),
}


def spec_for(vendor: str) -> VendorCLISpec | None:
    """Descriptor for a vendor id, profile id, or runtime name."""
    from superqode.providers.subscription_env import resolve_vendor

    key = resolve_vendor(vendor) or (vendor or "").strip().lower()
    if key in VENDOR_CLI_SPECS:
        return VENDOR_CLI_SPECS[key]
    for candidate in VENDOR_CLI_SPECS.values():
        if candidate.name == key:
            return candidate
    return None


# --- runtime ------------------------------------------------------------------


class VendorCLIRuntime:
    """Run a vendor CLI headlessly on the user's subscription."""

    def __init__(
        self,
        *,
        spec: VendorCLISpec,
        config: Any = None,
        approval_mode: str = "auto",
        permission_manager: Any = None,
        **_unused: Any,
    ) -> None:
        """Build the runtime.

        Extra keyword arguments are accepted and ignored except
        ``permission_manager``. Callers that have one (PureMode, headless,
        the harness backend) should pass it so Grok ``--allow``/``--deny``
        can project SuperQode patterns. The factory does not invent one.
        """
        if spec.resolve_binary() is None:
            raise RuntimeNotInstalledError(
                f"{spec.label} CLI was not found on PATH. To use it: {spec.install_hint}."
            )
        self.spec = spec
        self.config = config
        #: SuperQode approval mode ("auto" / "ask" / "deny"), translated into
        #: the vendor's own permission vocabulary for each turn.
        self.approval_mode = approval_mode
        self.permission_manager = permission_manager or _unused.get("permission_manager")
        self.stripped_api_keys: list[str] = []
        self._session_id: str | None = None
        self._process: Any = None
        self._cancelled = False
        self._announced_permissions = False
        self._tool_names: dict[str, str] = {}
        self._session_commands: dict[str, Any] = {}

    @property
    def name(self) -> str:
        return self.spec.name

    @property
    def harness_owner(self) -> str:
        return self.spec.vendor

    @property
    def metadata(self) -> dict[str, Any]:
        return {
            "runtime": self.spec.name,
            "harness_owner": self.spec.vendor,
            "authentication": "vendor-subscription",
            "billing": "subscription",
            "structured_events": True,
            "model": getattr(self.config, "model", "") or "cli-default",
            "session_id": self._session_id,
            "available_commands": dict(self._session_commands) if self._session_commands else {},
        }

    def build_command(self, prompt: str) -> list[str]:
        """Argv for one non-interactive turn."""
        binary = self.spec.resolve_binary() or self.spec.binary
        argv: list[str] = [binary, *self.spec.subcommand]
        argv.extend(self.spec.output_format)

        model = str(getattr(self.config, "model", "") or "").strip()
        if model and model.lower() not in {"auto", "default"} and self.spec.model_flag:
            argv.extend([self.spec.model_flag, model])

        if self._session_id and self.spec.session_flag:
            argv.extend([self.spec.session_flag, self._session_id])

        argv.extend(self.spec.flags_for_approval(self.approval_mode))
        argv.extend(self._policy_flags())

        if self.spec.prompt_flag:
            argv.extend([self.spec.prompt_flag, prompt])
        else:
            argv.append(prompt)
        return argv

    def _permission_notice(self) -> HarnessEvent | None:
        """Explain how this turn is authorised, in the vendor's own terms.

        A headless CLI cannot prompt per tool, so the honest thing is to name
        the vendor mode actually in force rather than let the user assume their
        approval setting is being enforced call by call.
        """
        if self._announced_permissions or not self.spec.permission_flags:
            return None
        self._announced_permissions = True
        mode = (self.approval_mode or "auto").strip().lower()
        flags = " ".join(self.spec.flags_for_approval(mode)) or "the vendor default"

        if self.spec.has_gradated_permissions:
            if self.spec.vendor == "grok":
                detail = (
                    f"Grok runs non-interactively here. SuperQode's '{mode}' "
                    f"approval mode is Grok's {flags} for the whole turn. "
                    "Deny/allow rules, not per-tool prompts, are what bind. "
                    "Use :connect grok (ACP) for permission cards."
                )
            else:
                detail = (
                    f"{self.spec.label} runs non-interactively here, so SuperQode's "
                    f"'{mode}' approval mode is applied as {self.spec.label}'s own "
                    f"setting ({flags}) for the whole turn rather than prompting per "
                    "tool call."
                )
        else:
            detail = (
                f"{self.spec.label} runs non-interactively here, which its CLI "
                f"only supports with tools pre-authorised ({flags}). Tool calls "
                "in this session are not individually approved, whatever the "
                "approval mode. Use the ACP route if you want per-tool prompts."
            )
        return HarnessEvent(type="thinking", data={"text": detail})

    def _policy_flags(self) -> tuple[str, ...]:
        """Grok ``--allow``/``--deny`` rules projected from SuperQode patterns."""
        if self.spec.vendor != "grok":
            return ()
        config = getattr(self.permission_manager, "config", None)
        if config is None:
            return ()
        flags: list[str] = []
        for pattern in getattr(config, "deny_patterns", None) or []:
            rule = grok_rule_from_pattern(str(pattern))
            if rule:
                flags.extend(["--deny", rule])
        for pattern in getattr(config, "allow_patterns", None) or []:
            rule = grok_rule_from_pattern(str(pattern))
            if rule:
                flags.extend(["--allow", rule])
        return tuple(flags)

    def _annotate_event(self, event: HarnessEvent) -> HarnessEvent:
        """Fill tool names from earlier ``tool_call`` lines; keep session ads."""
        if event.type == "tool_call":
            tool_id = event.data.get("tool_call_id")
            name = str(event.data.get("tool_name") or "")
            if tool_id and name:
                self._tool_names[str(tool_id)] = name
        elif event.type == "tool_result":
            tool_id = event.data.get("tool_call_id")
            if tool_id and not event.data.get("tool_name"):
                event.data["tool_name"] = self._tool_names.get(str(tool_id), "tool")
        return event

    async def run_harness_events(self, prompt: str) -> AsyncIterator[HarnessEvent]:
        """Stream one turn as normalized harness events."""
        from superqode.providers.subscription_env import subscription_child_env

        self._cancelled = False
        notice = self._permission_notice()
        if notice is not None:
            yield notice

        # Only the child's environment omits diverting API keys. os.environ is
        # left exactly as the user set it.
        child_env, self.stripped_api_keys = subscription_child_env(self.spec.vendor)
        argv = self.build_command(prompt)
        parser = PARSERS.get(self.spec.parser, parse_generic_event)

        try:
            self._process = await asyncio.create_subprocess_exec(
                *argv,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(getattr(self.config, "working_directory", os.getcwd())),
                env=child_env,
                limit=10 * 1024 * 1024,
            )
        except (OSError, ValueError) as exc:
            yield HarnessEvent(
                type="turn_complete",
                data={"status": "failed", "error": f"Could not start {self.spec.label}: {exc}"},
            )
            return

        saw_terminal_event = False
        try:
            async for event in self._stream(parser):
                if event.type == "turn_complete":
                    saw_terminal_event = True
                # Vendors that announce their session id up front (Warp's
                # `conversation_started`) rather than at the end still need it
                # captured for the resume flag.
                self._remember_session(event)
                yield event
        except asyncio.TimeoutError:
            self._kill()
            yield HarnessEvent(
                type="turn_complete",
                data={
                    "status": "failed",
                    "error": (
                        f"{self.spec.label} exceeded {_turn_timeout():g}s "
                        "(set SUPERQODE_VENDOR_CLI_TIMEOUT to change the limit)"
                    ),
                },
            )
            return

        returncode = await self._process.wait()
        if self._cancelled:
            yield HarnessEvent(type="turn_complete", data={"status": "cancelled"})
            return
        if returncode in (130, 143):
            yield HarnessEvent(type="turn_complete", data={"status": "cancelled"})
            return
        if returncode != 0:
            stderr = b""
            if self._process.stderr is not None:
                try:
                    stderr = await self._process.stderr.read(4000)
                except Exception:  # noqa: BLE001 - diagnostics only
                    stderr = b""
            detail = stderr.decode(errors="replace").strip()
            yield HarnessEvent(
                type="turn_complete",
                data={
                    "status": "failed",
                    "error": detail or f"{self.spec.label} exited with {returncode}.",
                },
            )
            return
        if not saw_terminal_event:
            yield HarnessEvent(type="turn_complete", data={"status": "completed"})

    async def _stream(self, parser) -> AsyncIterator[HarnessEvent]:
        assert self._process is not None and self._process.stdout is not None
        deadline = _turn_timeout()
        while True:
            line = await asyncio.wait_for(self._process.stdout.readline(), timeout=deadline)
            if not line:
                return
            if self._cancelled:
                self._kill()
                return
            text = line.decode(errors="replace").strip()
            if not text:
                continue
            if not text.startswith("{"):
                # Plain progress output. Surfacing it as thinking keeps a
                # non-JSON vendor readable instead of silently blank.
                yield HarnessEvent(type="thinking", data={"text": text})
                continue
            try:
                obj = json.loads(text)
            except json.JSONDecodeError:
                continue
            if not isinstance(obj, dict):
                continue
            if str(obj.get("type") or "") == "available_commands":
                self._session_commands = {
                    "tools": list(obj.get("tools") or []),
                    "commands": list(obj.get("commands") or []),
                }
            for event in parser(obj):
                yield self._annotate_event(event)

    async def run_streaming(self, prompt: str) -> AsyncIterator[str]:
        """Assistant text only, for callers that do not consume harness events.

        ``AgentRuntime`` requires this alongside ``run``; PureMode prefers
        ``run_harness_events`` when present, but the non-streaming paths do not.
        """
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta":
                text = str(event.data.get("text") or "")
                if text:
                    yield text

    async def run(self, prompt: str):
        """One turn as an ``AgentResponse``, for non-streaming callers."""
        from superqode.agent.loop import AgentResponse

        chunks: list[str] = []
        stopped_reason = "complete"
        error: str | None = None
        async for event in self.run_harness_events(prompt):
            if event.type == "model_delta":
                chunks.append(str(event.data.get("text") or ""))
            elif event.type == "turn_complete":
                status = str(event.data.get("status") or "")
                if status and status != "completed":
                    stopped_reason = status
                    error = event.data.get("error")
        return AgentResponse(
            content="".join(chunks),
            messages=[],
            tool_calls_made=0,
            iterations=1,
            stopped_reason=stopped_reason,
            error=error,
        )

    def _remember_session(self, event: HarnessEvent) -> None:
        session_id = event.data.get("session_id")
        if session_id:
            self._session_id = str(session_id)

    def _kill(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass

    def cancel(self) -> None:
        self._cancelled = True
        self._kill()

    def reset_cancellation(self) -> None:
        self._cancelled = False

    def set_model(self, model: str | None) -> None:
        if self.config is not None:
            self.config.model = model or ""

    async def aclose(self) -> None:
        self._kill()
