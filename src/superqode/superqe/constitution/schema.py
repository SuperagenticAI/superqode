"""
Constitution Schema - Data models for quality rules and policies.

Defines the structure for:
- Principles: High-level quality guidance
- Rules: Enforcement mechanisms
- Metrics: Measurement definitions
- Thresholds: Quality gates
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class PriorityLevel(str, Enum):
    """Priority levels for principles and rules."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ActionType(str, Enum):
    """Actions to take when a rule is violated."""

    FAIL = "fail"
    WARN = "warn"
    NOTIFY = "notify"
    BLOCK = "block"
    REQUIRE_REVIEW = "require_review"
    AUTO_FIX = "auto_fix"
    ESCALATE = "escalate"


class SeverityLevel(str, Enum):
    """Severity levels for violations."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


class ConditionOperator(str, Enum):
    """Operators for rule conditions."""

    EQUALS = "equals"
    NOT_EQUALS = "not_equals"
    GREATER_THAN = "greater_than"
    GREATER_THAN_OR_EQUAL = "greater_than_or_equal"
    LESS_THAN = "less_than"
    LESS_THAN_OR_EQUAL = "less_than_or_equal"
    CONTAINS = "contains"
    NOT_CONTAINS = "not_contains"
    MATCHES = "matches"
    IN = "in"
    NOT_IN = "not_in"
    EXISTS = "exists"
    NOT_EXISTS = "not_exists"


class ThresholdMode(str, Enum):
    """Mode for threshold evaluation."""

    ABSOLUTE = "absolute"
    PERCENTAGE = "percentage"
    RELATIVE = "relative"


@dataclass
class Condition:
    """A condition for rule evaluation."""

    field: str
    operator: ConditionOperator
    value: Any
    description: Optional[str] = None

    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate the condition against a context."""
        actual = self._get_field_value(context, self.field)

        if self.operator == ConditionOperator.EQUALS:
            return actual == self.value
        elif self.operator == ConditionOperator.NOT_EQUALS:
            return actual != self.value
        elif self.operator == ConditionOperator.GREATER_THAN:
            return actual > self.value
        elif self.operator == ConditionOperator.GREATER_THAN_OR_EQUAL:
            return actual >= self.value
        elif self.operator == ConditionOperator.LESS_THAN:
            return actual < self.value
        elif self.operator == ConditionOperator.LESS_THAN_OR_EQUAL:
            return actual <= self.value
        elif self.operator == ConditionOperator.CONTAINS:
            return self.value in actual if actual else False
        elif self.operator == ConditionOperator.NOT_CONTAINS:
            return self.value not in actual if actual else True
        elif self.operator == ConditionOperator.MATCHES:
            import re

            return bool(re.match(self.value, str(actual)))
        elif self.operator == ConditionOperator.IN:
            return actual in self.value
        elif self.operator == ConditionOperator.NOT_IN:
            return actual not in self.value
        elif self.operator == ConditionOperator.EXISTS:
            return actual is not None
        elif self.operator == ConditionOperator.NOT_EXISTS:
            return actual is None

        return False

    def _get_field_value(self, context: Dict[str, Any], field: str) -> Any:
        """Get a field value from context using dot notation."""
        parts = field.split(".")
        value = context
        for part in parts:
            if isinstance(value, dict):
                value = value.get(part)
            else:
                return None
        return value


@dataclass
class Action:
    """An action to take when a rule is violated."""

    type: ActionType
    message: Optional[str] = None
    severity: SeverityLevel = SeverityLevel.ERROR
    remediation: Optional[str] = None
    auto_fix_command: Optional[str] = None
    notify_channels: List[str] = field(default_factory=list)


@dataclass
class Principle:
    """A quality principle - high-level guidance."""

    id: str
    name: str
    description: str
    priority: PriorityLevel = PriorityLevel.MEDIUM
    category: str = "general"
    mandatory: bool = False
    related_principles: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)


@dataclass
class Rule:
    """A rule for enforcing a principle."""

    id: str
    name: str
    description: str
    principle_id: str
    conditions: List[Condition]
    action: Action
    enabled: bool = True
    severity: SeverityLevel = SeverityLevel.ERROR
    tags: List[str] = field(default_factory=list)
    environments: List[str] = field(default_factory=list)  # Which environments to apply

    def evaluate(self, context: Dict[str, Any]) -> bool:
        """Evaluate all conditions. Returns True if rule passes (no violation)."""
        return all(cond.evaluate(context) for cond in self.conditions)


@dataclass
class Metric:
    """A metric definition for measurement."""

    id: str
    name: str
    description: str
    data_type: str  # number, percentage, duration, count, ratio
    aggregation: str = "avg"  # sum, avg, min, max, count, percentile
    warning_threshold: Optional[float] = None
    critical_threshold: Optional[float] = None
    target_threshold: Optional[float] = None
    unit: Optional[str] = None
    dependencies: List[str] = field(default_factory=list)


@dataclass
class Threshold:
    """A threshold/quality gate definition."""

    id: str
    name: str
    description: str
    metric_id: str
    mode: ThresholdMode = ThresholdMode.ABSOLUTE
    value: float = 0.0
    operator: ConditionOperator = ConditionOperator.GREATER_THAN_OR_EQUAL
    blocking: bool = True  # If True, failing blocks deployment
    environments: List[str] = field(default_factory=list)
    period: Optional[str] = None  # e.g., "7d" for last 7 days


@dataclass
class Constitution:
    """
    A complete constitution defining quality rules and policies.

    Contains principles, rules, metrics, and thresholds that
    define acceptable quality standards for a project.
    """

    name: str
    version: str
    description: str = ""
    principles: List[Principle] = field(default_factory=list)
    rules: List[Rule] = field(default_factory=list)
    metrics: List[Metric] = field(default_factory=list)
    thresholds: List[Threshold] = field(default_factory=list)
    extends: Optional[str] = None  # Parent constitution to inherit from
    metadata: Dict[str, Any] = field(default_factory=dict)

    def get_principle(self, id: str) -> Optional[Principle]:
        """Get a principle by ID."""
        return next((p for p in self.principles if p.id == id), None)

    def get_rule(self, id: str) -> Optional[Rule]:
        """Get a rule by ID."""
        return next((r for r in self.rules if r.id == id), None)

    def get_metric(self, id: str) -> Optional[Metric]:
        """Get a metric by ID."""
        return next((m for m in self.metrics if m.id == id), None)

    def get_threshold(self, id: str) -> Optional[Threshold]:
        """Get a threshold by ID."""
        return next((t for t in self.thresholds if t.id == id), None)

    def get_rules_for_principle(self, principle_id: str) -> List[Rule]:
        """Get all rules for a principle."""
        return [r for r in self.rules if r.principle_id == principle_id]

    def get_enabled_rules(self) -> List[Rule]:
        """Get all enabled rules."""
        return [r for r in self.rules if r.enabled]

    def get_blocking_thresholds(self) -> List[Threshold]:
        """Get all blocking thresholds."""
        return [t for t in self.thresholds if t.blocking]
