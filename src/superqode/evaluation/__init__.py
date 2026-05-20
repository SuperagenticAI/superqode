"""Evaluation and validation APIs."""

try:
    from codeoptix.evaluation import EvaluationEngine as CodeOptiXEngine
    from codeoptix.behaviors import create_behavior
    from codeoptix.evaluation.bloom_integration import BloomIdeationIntegration
    from codeoptix.evolution import EvolutionEngine as CodeOptiXEvolutionEngine

    CODEOPTIX_AVAILABLE = True
except ImportError:
    CODEOPTIX_AVAILABLE = False
    CodeOptiXEngine = None
    create_behavior = None
    BloomIdeationIntegration = None
    CodeOptiXEvolutionEngine = None

from superqode.execution.modes import QEMode
from superqode.superqe import (
    QEEvent,
    QEEventCollector,
    QEEventEmitter,
    QEOrchestrator,
    QESession,
    QESessionConfig,
    EventType,
    emit_event,
    get_event_emitter,
    set_event_emitter,
)
from superqode.superqe.session import QEStatus

__all__ = [
    "CODEOPTIX_AVAILABLE",
    "CodeOptiXEngine",
    "create_behavior",
    "BloomIdeationIntegration",
    "CodeOptiXEvolutionEngine",
    "EventType",
    "QEEvent",
    "QEEventCollector",
    "QEEventEmitter",
    "QEMode",
    "QEOrchestrator",
    "QESession",
    "QESessionConfig",
    "QEStatus",
    "emit_event",
    "get_event_emitter",
    "set_event_emitter",
]
