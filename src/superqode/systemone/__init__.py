"""System One decision plane for SuperQode.

State in, typed questions out. Code owns control flow. Pydantic shapes,
a schema-strict stub, frozen question packs, compose, and an optional
live HTTP client. Not a generation provider.
"""

from .client import (
    ReplaySystemOneClient,
    StubSystemOneClient,
    SystemOneClient,
    SystemOneError,
    SystemOneTimeout,
)
from .decision import DecisionResult, evaluate_decision
from .compose import GateAction, GateDecision, compose_tool_gate, evaluate_tool_gate
from .config import DEFAULT_MODEL, SYSTEMONE_ENV, SystemOneSettings, resolve_systemone
from .live import LiveSystemOneClient
from .pack import QuestionPack, ToolGateThresholds, builtin_pack_ids, load_pack
from .runtime import apply_systemone_gate
from .state import ToolGateState
from .tool_router import (
    SystemOneToolDecisionProvider,
    ToolRouter,
    ToolRoutingSettings,
    TurnToolPlan,
    build_tool_router,
    resolve_tool_routing,
)
from .types import (
    Answers,
    ChoiceAnswer,
    ChoiceQuestion,
    NoulAnswer,
    NoulQuestion,
    Question,
    SchemaViolation,
    ScoreAnswer,
    ScoreQuestion,
    bind_answers,
)

__all__ = [
    "Answers",
    "DecisionResult",
    "evaluate_decision",
    "ChoiceAnswer",
    "ChoiceQuestion",
    "DEFAULT_MODEL",
    "GateAction",
    "GateDecision",
    "LiveSystemOneClient",
    "NoulAnswer",
    "NoulQuestion",
    "Question",
    "QuestionPack",
    "ReplaySystemOneClient",
    "SYSTEMONE_ENV",
    "SystemOneSettings",
    "SchemaViolation",
    "ScoreAnswer",
    "ScoreQuestion",
    "StubSystemOneClient",
    "SystemOneClient",
    "SystemOneError",
    "SystemOneTimeout",
    "ToolGateState",
    "ToolGateThresholds",
    "SystemOneToolDecisionProvider",
    "ToolRouter",
    "ToolRoutingSettings",
    "TurnToolPlan",
    "apply_systemone_gate",
    "bind_answers",
    "builtin_pack_ids",
    "compose_tool_gate",
    "evaluate_tool_gate",
    "load_pack",
    "resolve_systemone",
    "build_tool_router",
    "resolve_tool_routing",
]
