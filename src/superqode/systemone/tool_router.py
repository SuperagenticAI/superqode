"""Turn-stable tool visibility routing for coding harnesses.

The router is deliberately independent of any agent SDK.  It consumes the
small :class:`SystemOneClient` protocol, so live Jev, replay fixtures, and
local test doubles all exercise the same policy.  Failures and incomplete
answers always preserve the complete catalogue.
"""

from __future__ import annotations

import os
import re
import time
from dataclasses import dataclass, field
from typing import Mapping, Protocol, Sequence

from ..providers.gateway.base import ToolDefinition
from .client import SystemOneClient
from .live import LiveSystemOneClient
from .types import NoulQuestion


DEFAULT_ALWAYS_KEEP = frozenset(
    {
        "apply_patch",
        "bash",
        "edit",
        "edit_file",
        "glob",
        "grep",
        "list_dir",
        "list_directory",
        "read",
        "read_file",
        "run_terminal_command",
        "search_replace",
        "tool_search",
        "write",
        "write_file",
    }
)


@dataclass(frozen=True)
class ToolRoutingSettings:
    """Local routing policy resolved once per process/loop."""

    mode: str = "off"  # off | shadow | enforce
    threshold: float = 0.30
    timeout_ms: int = 1500
    always_keep: frozenset[str] = DEFAULT_ALWAYS_KEEP

    @property
    def enabled(self) -> bool:
        return self.mode in {"shadow", "enforce"}


@dataclass(frozen=True)
class TurnToolPlan:
    """One immutable tool decision, reused for every model step in a turn."""

    mode: str
    original: tuple[str, ...]
    selected: tuple[str, ...]
    probabilities: Mapping[str, float] = field(default_factory=dict)
    latency_ms: int = 0
    status: str = "disabled"
    error: str = ""

    @property
    def dropped(self) -> tuple[str, ...]:
        selected = set(self.selected)
        return tuple(name for name in self.original if name not in selected)

    @property
    def effective(self) -> tuple[str, ...]:
        return self.selected if self.mode == "enforce" else self.original


class ToolDecisionProvider(Protocol):
    """Provider-neutral closed-set decision surface."""

    async def probabilities(
        self, request: str, tools: Sequence[ToolDefinition]
    ) -> Mapping[str, float]: ...


class SystemOneToolDecisionProvider:
    """Ask one Jev Noul question per tool in a single parallel evaluation."""

    def __init__(self, client: SystemOneClient) -> None:
        self.client = client

    async def probabilities(
        self, request: str, tools: Sequence[ToolDefinition]
    ) -> Mapping[str, float]:
        question_ids: dict[str, str] = {}
        questions: dict[str, NoulQuestion] = {}
        catalogue: list[dict[str, str]] = []
        for index, tool in enumerate(tools):
            qid = f"tool_{index}"
            question_ids[qid] = tool.name
            catalogue.append({"name": tool.name, "description": tool.description})
            questions[qid] = NoulQuestion(
                instructions=(
                    "Will completing the developer request need this tool at any step, "
                    "including investigation, implementation, verification, or cleanup? "
                    f"Tool: {tool.name}. Description: {tool.description}"
                ),
                criteria={
                    "true": "The tool is likely to be needed during this turn.",
                    "false": "The turn can be completed without this tool.",
                },
            )
        answers = await self.client.evaluate(
            state={"developer_request": request, "available_tools": catalogue},
            questions=questions,
        )
        probabilities = answers.noul_map()
        if set(probabilities) != set(question_ids):
            raise ValueError("tool routing response was incomplete")
        return {question_ids[qid]: probability for qid, probability in probabilities.items()}


class ToolRouter:
    """Select schemas once per turn while preserving safe failure semantics."""

    def __init__(
        self,
        provider: ToolDecisionProvider,
        settings: ToolRoutingSettings,
    ) -> None:
        self.provider = provider
        self.settings = settings

    async def plan(self, request: str, tools: Sequence[ToolDefinition]) -> TurnToolPlan:
        original = tuple(tool.name for tool in tools)
        if not self.settings.enabled or not tools:
            return TurnToolPlan(
                mode=self.settings.mode,
                original=original,
                selected=original,
                status="disabled" if not self.settings.enabled else "empty",
            )
        started = time.monotonic()
        try:
            probabilities = dict(await self.provider.probabilities(request, tools))
            if set(probabilities) != set(original):
                raise ValueError("tool routing response did not cover the full catalogue")
            selected = tuple(
                name
                for name in original
                if name in self.settings.always_keep
                or probabilities[name] >= self.settings.threshold
            )
            # A router is an optimization, never permission to remove all means
            # of recovery. An empty decision therefore fails open.
            if not selected:
                raise ValueError("tool routing removed every tool")
            return TurnToolPlan(
                mode=self.settings.mode,
                original=original,
                selected=selected,
                probabilities=probabilities,
                latency_ms=round((time.monotonic() - started) * 1000),
                status="ok",
            )
        except Exception as exc:
            return TurnToolPlan(
                mode=self.settings.mode,
                original=original,
                selected=original,
                latency_ms=round((time.monotonic() - started) * 1000),
                status="fail_open",
                error=type(exc).__name__,
            )

    @staticmethod
    def apply(tools: Sequence[ToolDefinition], plan: TurnToolPlan) -> list[ToolDefinition]:
        allowed = set(plan.effective)
        return [tool for tool in tools if tool.name in allowed]


def resolve_tool_routing(
    environ: Mapping[str, str] | None = None,
) -> ToolRoutingSettings:
    """Resolve the intentionally small local-first environment contract."""
    env = os.environ if environ is None else environ
    raw_mode = str(env.get("SUPERQODE_TOOL_ROUTING", "off")).strip().lower()
    aliases = {"1": "shadow", "true": "shadow", "on": "shadow", "jev": "shadow"}
    mode = aliases.get(raw_mode, raw_mode)
    if mode not in {"off", "shadow", "enforce"}:
        raise ValueError("SUPERQODE_TOOL_ROUTING must be off, shadow, or enforce")
    threshold = float(env.get("SUPERQODE_TOOL_ROUTING_THRESHOLD", "0.30"))
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("SUPERQODE_TOOL_ROUTING_THRESHOLD must be between 0 and 1")
    timeout_ms = max(int(env.get("SUPERQODE_TOOL_ROUTING_TIMEOUT_MS", "1500")), 1)
    configured = {
        item
        for item in re.split(r"[\s,]+", env.get("SUPERQODE_TOOL_ROUTING_ALWAYS_KEEP", ""))
        if item
    }
    return ToolRoutingSettings(
        mode=mode,
        threshold=threshold,
        timeout_ms=timeout_ms,
        always_keep=DEFAULT_ALWAYS_KEEP | configured,
    )


def build_tool_router(
    settings: ToolRoutingSettings | None = None,
    *,
    client: SystemOneClient | None = None,
) -> ToolRouter | None:
    """Build the Jev-backed router only when explicitly enabled and usable."""
    resolved = settings or resolve_tool_routing()
    if not resolved.enabled:
        return None
    if client is None:
        api_key = os.environ.get("TYPESAFE_API_KEY", "").strip()
        if not api_key:
            return None
        client = LiveSystemOneClient(api_key=api_key, timeout_ms=resolved.timeout_ms)
    return ToolRouter(SystemOneToolDecisionProvider(client), resolved)


__all__ = [
    "DEFAULT_ALWAYS_KEEP",
    "SystemOneToolDecisionProvider",
    "ToolDecisionProvider",
    "ToolRouter",
    "ToolRoutingSettings",
    "TurnToolPlan",
    "build_tool_router",
    "resolve_tool_routing",
]
