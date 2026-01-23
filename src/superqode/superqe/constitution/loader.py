"""
Constitution Loader - Load and parse constitution files.

Supports:
- YAML and JSON formats
- Inheritance (extends)
- Merging strategies
- Validation
"""

from pathlib import Path
from typing import Any, Dict, List, Optional
import json
import logging

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

logger = logging.getLogger(__name__)


class ConstitutionLoader:
    """
    Loader for constitution files.

    Supports YAML and JSON formats with inheritance.
    """

    _cache: Dict[str, Constitution] = {}

    def __init__(self, search_paths: Optional[List[Path]] = None):
        """Initialize with optional search paths."""
        self.search_paths = search_paths or [
            Path.cwd() / ".superqode",
            Path.cwd(),
            Path.home() / ".superqode",
        ]

    def load(self, path: str) -> Constitution:
        """
        Load a constitution from a file.

        Args:
            path: Path to constitution file or name to search

        Returns:
            Loaded Constitution
        """
        # Check cache
        if path in self._cache:
            return self._cache[path]

        # Find the file
        file_path = self._find_file(path)
        if not file_path:
            raise FileNotFoundError(f"Constitution not found: {path}")

        # Load and parse
        constitution = self._load_file(file_path)

        # Handle inheritance
        if constitution.extends:
            parent = self.load(constitution.extends)
            constitution = self._merge(parent, constitution)

        # Cache and return
        self._cache[path] = constitution
        return constitution

    def _find_file(self, path: str) -> Optional[Path]:
        """Find a constitution file."""
        # Direct path
        direct = Path(path)
        if direct.exists():
            return direct

        # Search in search paths
        for search_path in self.search_paths:
            for ext in ["", ".yaml", ".yml", ".json"]:
                candidate = search_path / f"{path}{ext}"
                if candidate.exists():
                    return candidate

            # Also try constitution subdirectory
            for ext in ["", ".yaml", ".yml", ".json"]:
                candidate = search_path / "constitution" / f"{path}{ext}"
                if candidate.exists():
                    return candidate

        return None

    def _load_file(self, path: Path) -> Constitution:
        """Load a constitution from a file."""
        content = path.read_text()

        if path.suffix == ".json":
            data = json.loads(content)
        else:
            import yaml

            data = yaml.safe_load(content)

        return self._parse_constitution(data)

    def _parse_constitution(self, data: Dict[str, Any]) -> Constitution:
        """Parse constitution from dictionary."""
        # Parse principles
        principles = []
        for p_data in data.get("principles", []):
            principles.append(
                Principle(
                    id=p_data["id"],
                    name=p_data["name"],
                    description=p_data.get("description", ""),
                    priority=PriorityLevel(p_data.get("priority", "medium")),
                    category=p_data.get("category", "general"),
                    mandatory=p_data.get("mandatory", False),
                    related_principles=p_data.get("related_principles", []),
                    tags=p_data.get("tags", []),
                )
            )

        # Parse rules
        rules = []
        for r_data in data.get("rules", []):
            conditions = []
            for c_data in r_data.get("conditions", []):
                conditions.append(
                    Condition(
                        field=c_data["field"],
                        operator=ConditionOperator(c_data["operator"]),
                        value=c_data["value"],
                        description=c_data.get("description"),
                    )
                )

            action_data = r_data.get("action", {})
            action = Action(
                type=ActionType(action_data.get("type", "warn")),
                message=action_data.get("message"),
                severity=SeverityLevel(action_data.get("severity", "error")),
                remediation=action_data.get("remediation"),
                auto_fix_command=action_data.get("auto_fix_command"),
                notify_channels=action_data.get("notify_channels", []),
            )

            rules.append(
                Rule(
                    id=r_data["id"],
                    name=r_data["name"],
                    description=r_data.get("description", ""),
                    principle_id=r_data.get("principle_id", ""),
                    conditions=conditions,
                    action=action,
                    enabled=r_data.get("enabled", True),
                    severity=SeverityLevel(r_data.get("severity", "error")),
                    tags=r_data.get("tags", []),
                    environments=r_data.get("environments", []),
                )
            )

        # Parse metrics
        metrics = []
        for m_data in data.get("metrics", []):
            metrics.append(
                Metric(
                    id=m_data["id"],
                    name=m_data["name"],
                    description=m_data.get("description", ""),
                    data_type=m_data.get("data_type", "number"),
                    aggregation=m_data.get("aggregation", "avg"),
                    warning_threshold=m_data.get("warning_threshold"),
                    critical_threshold=m_data.get("critical_threshold"),
                    target_threshold=m_data.get("target_threshold"),
                    unit=m_data.get("unit"),
                    dependencies=m_data.get("dependencies", []),
                )
            )

        # Parse thresholds
        thresholds = []
        for t_data in data.get("thresholds", []):
            thresholds.append(
                Threshold(
                    id=t_data["id"],
                    name=t_data["name"],
                    description=t_data.get("description", ""),
                    metric_id=t_data["metric_id"],
                    mode=ThresholdMode(t_data.get("mode", "absolute")),
                    value=t_data.get("value", 0),
                    operator=ConditionOperator(t_data.get("operator", "greater_than_or_equal")),
                    blocking=t_data.get("blocking", True),
                    environments=t_data.get("environments", []),
                    period=t_data.get("period"),
                )
            )

        return Constitution(
            name=data.get("name", "default"),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            principles=principles,
            rules=rules,
            metrics=metrics,
            thresholds=thresholds,
            extends=data.get("extends"),
            metadata=data.get("metadata", {}),
        )

    def _merge(self, parent: Constitution, child: Constitution) -> Constitution:
        """Merge child constitution with parent."""
        # Merge principles (child overrides parent)
        principles = {p.id: p for p in parent.principles}
        for p in child.principles:
            principles[p.id] = p

        # Merge rules
        rules = {r.id: r for r in parent.rules}
        for r in child.rules:
            rules[r.id] = r

        # Merge metrics
        metrics = {m.id: m for m in parent.metrics}
        for m in child.metrics:
            metrics[m.id] = m

        # Merge thresholds
        thresholds = {t.id: t for t in parent.thresholds}
        for t in child.thresholds:
            thresholds[t.id] = t

        return Constitution(
            name=child.name,
            version=child.version,
            description=child.description or parent.description,
            principles=list(principles.values()),
            rules=list(rules.values()),
            metrics=list(metrics.values()),
            thresholds=list(thresholds.values()),
            extends=None,  # Already merged
            metadata={**parent.metadata, **child.metadata},
        )


def load_constitution(path: str) -> Constitution:
    """Load a constitution from a file."""
    loader = ConstitutionLoader()
    return loader.load(path)


def get_default_constitution() -> Constitution:
    """Get the default constitution with standard rules."""
    return Constitution(
        name="default",
        version="1.0.0",
        description="Default quality constitution",
        principles=[
            Principle(
                id="P001",
                name="Code Quality",
                description="Maintain high code quality standards",
                priority=PriorityLevel.HIGH,
                category="quality",
                mandatory=True,
            ),
            Principle(
                id="P002",
                name="Test Coverage",
                description="Ensure adequate test coverage",
                priority=PriorityLevel.HIGH,
                category="testing",
                mandatory=True,
            ),
            Principle(
                id="P003",
                name="Security",
                description="Follow security best practices",
                priority=PriorityLevel.CRITICAL,
                category="security",
                mandatory=True,
            ),
            Principle(
                id="P004",
                name="Performance",
                description="Maintain acceptable performance",
                priority=PriorityLevel.MEDIUM,
                category="performance",
            ),
        ],
        rules=[
            Rule(
                id="R001",
                name="Minimum Test Coverage",
                description="Code must have at least 80% test coverage",
                principle_id="P002",
                conditions=[
                    Condition(
                        field="coverage.percentage",
                        operator=ConditionOperator.GREATER_THAN_OR_EQUAL,
                        value=80,
                    )
                ],
                action=Action(
                    type=ActionType.BLOCK,
                    message="Test coverage below 80%",
                    severity=SeverityLevel.ERROR,
                    remediation="Add more tests to increase coverage",
                ),
            ),
            Rule(
                id="R002",
                name="No Critical Vulnerabilities",
                description="No critical security vulnerabilities allowed",
                principle_id="P003",
                conditions=[
                    Condition(
                        field="security.critical_count",
                        operator=ConditionOperator.EQUALS,
                        value=0,
                    )
                ],
                action=Action(
                    type=ActionType.BLOCK,
                    message="Critical vulnerabilities detected",
                    severity=SeverityLevel.ERROR,
                    remediation="Fix all critical vulnerabilities before deployment",
                ),
            ),
            Rule(
                id="R003",
                name="Max Cyclomatic Complexity",
                description="Functions should not exceed complexity threshold",
                principle_id="P001",
                conditions=[
                    Condition(
                        field="complexity.max_cyclomatic",
                        operator=ConditionOperator.LESS_THAN_OR_EQUAL,
                        value=15,
                    )
                ],
                action=Action(
                    type=ActionType.WARN,
                    message="High cyclomatic complexity detected",
                    severity=SeverityLevel.WARNING,
                    remediation="Refactor complex functions",
                ),
            ),
            Rule(
                id="R004",
                name="No Flaky Tests",
                description="All tests must be stable",
                principle_id="P002",
                conditions=[
                    Condition(
                        field="tests.flaky_count",
                        operator=ConditionOperator.EQUALS,
                        value=0,
                    )
                ],
                action=Action(
                    type=ActionType.WARN,
                    message="Flaky tests detected",
                    severity=SeverityLevel.WARNING,
                    remediation="Fix or quarantine flaky tests",
                ),
            ),
        ],
        metrics=[
            Metric(
                id="M001",
                name="Test Coverage",
                description="Percentage of code covered by tests",
                data_type="percentage",
                warning_threshold=85,
                critical_threshold=80,
                target_threshold=90,
                unit="%",
            ),
            Metric(
                id="M002",
                name="Cyclomatic Complexity",
                description="Average cyclomatic complexity",
                data_type="number",
                aggregation="avg",
                warning_threshold=10,
                critical_threshold=15,
            ),
            Metric(
                id="M003",
                name="Security Vulnerabilities",
                description="Count of security vulnerabilities",
                data_type="count",
                aggregation="sum",
                warning_threshold=5,
                critical_threshold=1,
            ),
        ],
        thresholds=[
            Threshold(
                id="T001",
                name="Coverage Gate",
                description="Minimum test coverage for deployment",
                metric_id="M001",
                mode=ThresholdMode.ABSOLUTE,
                value=80,
                operator=ConditionOperator.GREATER_THAN_OR_EQUAL,
                blocking=True,
            ),
            Threshold(
                id="T002",
                name="Security Gate",
                description="No critical vulnerabilities",
                metric_id="M003",
                mode=ThresholdMode.ABSOLUTE,
                value=0,
                operator=ConditionOperator.EQUALS,
                blocking=True,
            ),
        ],
    )
