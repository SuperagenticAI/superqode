"""
Constitution System - Quality rules and guardrails.

Provides a declarative system for defining:
- Quality principles and policies
- Enforcement rules with actions
- Metrics and thresholds
- Quality gates

Based on customizable YAML/JSON configuration files.
"""

from .schema import (
    Constitution,
    Principle,
    Rule,
    Condition,
    Action,
    Metric,
    Threshold,
    PriorityLevel,
    ActionType,
    SeverityLevel,
    ConditionOperator,
    ThresholdMode,
)
from .loader import (
    ConstitutionLoader,
    load_constitution,
    get_default_constitution,
)
from .evaluator import (
    ConstitutionEvaluator,
    EvaluationResult,
    RuleViolation,
    evaluate_against_constitution,
)

__all__ = [
    # Schema
    "Constitution",
    "Principle",
    "Rule",
    "Condition",
    "Action",
    "Metric",
    "Threshold",
    "PriorityLevel",
    "ActionType",
    "SeverityLevel",
    "ConditionOperator",
    "ThresholdMode",
    # Loader
    "ConstitutionLoader",
    "load_constitution",
    "get_default_constitution",
    # Evaluator
    "ConstitutionEvaluator",
    "EvaluationResult",
    "RuleViolation",
    "evaluate_against_constitution",
]
