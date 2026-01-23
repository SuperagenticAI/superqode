"""
Constitution Evaluator - Evaluate code/tests against constitution.

Provides:
- Rule evaluation
- Threshold checking
- Violation reporting
- Quality gate assessment
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import logging

from .schema import (
    Constitution,
    Rule,
    Threshold,
    Action,
    ActionType,
    SeverityLevel,
)

logger = logging.getLogger(__name__)


@dataclass
class RuleViolation:
    """A rule violation."""

    rule_id: str
    rule_name: str
    principle_id: str
    message: str
    severity: SeverityLevel
    action: Action
    context: Dict[str, Any] = field(default_factory=dict)
    remediation: Optional[str] = None


@dataclass
class ThresholdViolation:
    """A threshold violation."""

    threshold_id: str
    threshold_name: str
    metric_id: str
    expected_value: float
    actual_value: float
    blocking: bool
    message: str


@dataclass
class EvaluationResult:
    """Result of evaluating against a constitution."""

    constitution_name: str
    constitution_version: str
    passed: bool
    rule_violations: List[RuleViolation] = field(default_factory=list)
    threshold_violations: List[ThresholdViolation] = field(default_factory=list)
    metrics_evaluated: Dict[str, Any] = field(default_factory=dict)
    warnings: List[str] = field(default_factory=list)

    @property
    def blocking_violations(self) -> int:
        """Count of blocking violations."""
        blocking_rules = sum(1 for v in self.rule_violations if v.action.type == ActionType.BLOCK)
        blocking_thresholds = sum(1 for v in self.threshold_violations if v.blocking)
        return blocking_rules + blocking_thresholds

    @property
    def can_deploy(self) -> bool:
        """Check if deployment is allowed."""
        return self.blocking_violations == 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "constitution": self.constitution_name,
            "version": self.constitution_version,
            "passed": self.passed,
            "can_deploy": self.can_deploy,
            "blocking_violations": self.blocking_violations,
            "rule_violations": [
                {
                    "rule_id": v.rule_id,
                    "rule_name": v.rule_name,
                    "message": v.message,
                    "severity": v.severity.value,
                    "action": v.action.type.value,
                    "remediation": v.remediation,
                }
                for v in self.rule_violations
            ],
            "threshold_violations": [
                {
                    "threshold_id": v.threshold_id,
                    "threshold_name": v.threshold_name,
                    "expected": v.expected_value,
                    "actual": v.actual_value,
                    "blocking": v.blocking,
                }
                for v in self.threshold_violations
            ],
            "metrics": self.metrics_evaluated,
            "warnings": self.warnings,
        }


class ConstitutionEvaluator:
    """
    Evaluator for constitutions.

    Evaluates code and test results against constitution
    rules and thresholds.
    """

    def __init__(self, constitution: Constitution):
        """Initialize with a constitution."""
        self.constitution = constitution

    def evaluate(
        self, context: Dict[str, Any], environment: Optional[str] = None
    ) -> EvaluationResult:
        """
        Evaluate context against the constitution.

        Args:
            context: Dictionary with metrics and state to evaluate
            environment: Optional environment name for filtering

        Returns:
            EvaluationResult with violations and assessment
        """
        result = EvaluationResult(
            constitution_name=self.constitution.name,
            constitution_version=self.constitution.version,
            passed=True,
        )

        # Evaluate rules
        for rule in self.constitution.get_enabled_rules():
            # Skip if not applicable to environment
            if environment and rule.environments and environment not in rule.environments:
                continue

            if not rule.evaluate(context):
                violation = RuleViolation(
                    rule_id=rule.id,
                    rule_name=rule.name,
                    principle_id=rule.principle_id,
                    message=rule.action.message or f"Rule {rule.id} violated",
                    severity=rule.severity,
                    action=rule.action,
                    context=context,
                    remediation=rule.action.remediation,
                )
                result.rule_violations.append(violation)

                if rule.action.type == ActionType.BLOCK:
                    result.passed = False
                elif rule.action.type == ActionType.WARN:
                    result.warnings.append(violation.message)

        # Evaluate thresholds
        for threshold in self.constitution.thresholds:
            # Skip if not applicable to environment
            if environment and threshold.environments and environment not in threshold.environments:
                continue

            # Get metric value from context
            metric = self.constitution.get_metric(threshold.metric_id)
            if not metric:
                continue

            metric_value = self._get_metric_value(context, metric.id)
            if metric_value is None:
                result.warnings.append(f"Metric {metric.id} not found in context")
                continue

            result.metrics_evaluated[metric.id] = metric_value

            # Evaluate threshold
            passes = self._evaluate_threshold(threshold, metric_value)

            if not passes:
                violation = ThresholdViolation(
                    threshold_id=threshold.id,
                    threshold_name=threshold.name,
                    metric_id=threshold.metric_id,
                    expected_value=threshold.value,
                    actual_value=metric_value,
                    blocking=threshold.blocking,
                    message=f"{threshold.name}: expected {threshold.value}, got {metric_value}",
                )
                result.threshold_violations.append(violation)

                if threshold.blocking:
                    result.passed = False

        return result

    def _get_metric_value(self, context: Dict[str, Any], metric_id: str) -> Optional[float]:
        """Get metric value from context."""
        # Try direct access
        if metric_id in context:
            return context[metric_id]

        # Try nested access (metrics.coverage, etc.)
        metrics = context.get("metrics", {})
        if metric_id in metrics:
            return metrics[metric_id]

        # Try by metric name patterns
        patterns = {
            "M001": ["coverage", "coverage.percentage", "test_coverage"],
            "M002": ["complexity", "complexity.avg", "cyclomatic_complexity"],
            "M003": ["security", "security.vulnerabilities", "vulnerability_count"],
        }

        for pattern in patterns.get(metric_id, []):
            parts = pattern.split(".")
            value = context
            for part in parts:
                if isinstance(value, dict):
                    value = value.get(part)
                else:
                    value = None
                    break
            if value is not None:
                return float(value)

        return None

    def _evaluate_threshold(self, threshold: Threshold, value: float) -> bool:
        """Evaluate a threshold condition."""
        from .schema import ConditionOperator

        target = threshold.value

        if threshold.operator == ConditionOperator.EQUALS:
            return value == target
        elif threshold.operator == ConditionOperator.NOT_EQUALS:
            return value != target
        elif threshold.operator == ConditionOperator.GREATER_THAN:
            return value > target
        elif threshold.operator == ConditionOperator.GREATER_THAN_OR_EQUAL:
            return value >= target
        elif threshold.operator == ConditionOperator.LESS_THAN:
            return value < target
        elif threshold.operator == ConditionOperator.LESS_THAN_OR_EQUAL:
            return value <= target

        return True

    def get_applicable_rules(self, environment: Optional[str] = None) -> List[Rule]:
        """Get rules applicable to an environment."""
        rules = []
        for rule in self.constitution.get_enabled_rules():
            if not environment or not rule.environments or environment in rule.environments:
                rules.append(rule)
        return rules

    def get_blocking_thresholds(self, environment: Optional[str] = None) -> List[Threshold]:
        """Get blocking thresholds for an environment."""
        thresholds = []
        for threshold in self.constitution.get_blocking_thresholds():
            if (
                not environment
                or not threshold.environments
                or environment in threshold.environments
            ):
                thresholds.append(threshold)
        return thresholds


def evaluate_against_constitution(
    context: Dict[str, Any],
    constitution: Optional[Constitution] = None,
    constitution_path: Optional[str] = None,
    environment: Optional[str] = None,
) -> EvaluationResult:
    """
    Evaluate context against a constitution.

    Args:
        context: Metrics and state to evaluate
        constitution: Constitution to use (or load from path)
        constitution_path: Path to constitution file
        environment: Environment for filtering rules

    Returns:
        EvaluationResult
    """
    if constitution is None:
        if constitution_path:
            from .loader import load_constitution

            constitution = load_constitution(constitution_path)
        else:
            from .loader import get_default_constitution

            constitution = get_default_constitution()

    evaluator = ConstitutionEvaluator(constitution)
    return evaluator.evaluate(context, environment)
