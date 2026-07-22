"""Durable WorkOrder domain models.

A WorkOrder is the finish-line contract above harness runs and agent sessions.
It records what must be done, which tasks may run, the evidence they produced,
and the explicit accept/reject decision.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class WorkOrderStatus(str, Enum):
    """Lifecycle states for one unit of repository work."""

    DRAFT = "draft"
    QUEUED = "queued"
    RUNNING = "running"
    REVIEWING = "reviewing"
    CHECKING = "checking"
    READY_TO_MERGE = "ready_to_merge"
    MERGING = "merging"
    BLOCKED = "blocked"
    ACCEPTED = "accepted"
    MERGED = "merged"
    ROLLED_BACK = "rolled_back"
    REJECTED = "rejected"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkTaskStatus(str, Enum):
    """Lifecycle states for a worker-sized WorkOrder task."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    BLOCKED = "blocked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class WorkTaskRole(str, Enum):
    """Behavioral contract for one WorkOrder task."""

    INVESTIGATOR = "investigator"
    IMPLEMENTER = "implementer"
    SYNTHESIZER = "synthesizer"
    REVIEWER = "reviewer"
    TESTER = "tester"
    CUSTOM = "custom"


TERMINAL_WORK_ORDER_STATUSES = frozenset(
    {
        WorkOrderStatus.ACCEPTED,
        WorkOrderStatus.MERGED,
        WorkOrderStatus.ROLLED_BACK,
        WorkOrderStatus.REJECTED,
        WorkOrderStatus.FAILED,
        WorkOrderStatus.CANCELLED,
    }
)


@dataclass(frozen=True)
class WorkOrderBudget:
    """Declared limits attached to a WorkOrder contract."""

    max_cost_usd: float | None = None
    max_tokens: int | None = None
    max_seconds: int | None = None
    max_workers: int | None = 1
    max_tool_calls: int | None = None
    max_risk: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WorkOrderBudget":
        payload = data or {}
        return cls(
            max_cost_usd=_optional_float(payload.get("max_cost_usd")),
            max_tokens=_optional_int(payload.get("max_tokens")),
            max_seconds=_optional_int(payload.get("max_seconds")),
            max_workers=(
                _optional_int(payload.get("max_workers")) if "max_workers" in payload else 1
            ),
            max_tool_calls=_optional_int(payload.get("max_tool_calls")),
            max_risk=str(payload.get("max_risk") or ""),
        )


@dataclass(frozen=True)
class WorkArtifact:
    """Typed evidence produced while completing a WorkOrder."""

    artifact_id: str
    kind: str
    created_at: float
    task_id: str = ""
    path: str = ""
    content: str = ""
    digest: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkArtifact":
        return cls(
            artifact_id=str(data["artifact_id"]),
            kind=str(data.get("kind") or "other"),
            created_at=float(data.get("created_at") or time.time()),
            task_id=str(data.get("task_id") or ""),
            path=str(data.get("path") or ""),
            content=str(data.get("content") or ""),
            digest=str(data.get("digest") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WorkOrderDecision:
    """Human or policy decision that closes a WorkOrder."""

    verdict: str
    decided_at: float
    actor: str = ""
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "WorkOrderDecision | None":
        if not data:
            return None
        return cls(
            verdict=str(data.get("verdict") or ""),
            decided_at=float(data.get("decided_at") or time.time()),
            actor=str(data.get("actor") or ""),
            reason=str(data.get("reason") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WorkOrderTask:
    """One dependency-aware task claimable by a worker."""

    task_id: str
    title: str
    goal: str
    role: WorkTaskRole = WorkTaskRole.IMPLEMENTER
    risk: str = ""
    dependencies: tuple[str, ...] = ()
    harness: str = ""
    provider: str = ""
    model: str = ""
    runtime: str = ""
    acceptance_tests: tuple[str, ...] = ()
    status: WorkTaskStatus = WorkTaskStatus.PENDING
    max_attempts: int = 2
    attempts: int = 0
    worker_id: str = ""
    lease_expires_at: float | None = None
    heartbeat_at: float | None = None
    session_id: str = ""
    run_id: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    started_at: float | None = None
    ended_at: float | None = None
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["status"] = self.status.value
        payload["role"] = self.role.value
        payload["dependencies"] = list(self.dependencies)
        payload["acceptance_tests"] = list(self.acceptance_tests)
        return payload

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkOrderTask":
        return cls(
            task_id=str(data["task_id"]),
            title=str(data.get("title") or data["task_id"]),
            goal=str(data.get("goal") or ""),
            role=WorkTaskRole(str(data.get("role") or WorkTaskRole.IMPLEMENTER.value)),
            risk=str(data.get("risk") or ""),
            dependencies=tuple(str(item) for item in data.get("dependencies") or ()),
            harness=str(data.get("harness") or ""),
            provider=str(data.get("provider") or ""),
            model=str(data.get("model") or ""),
            runtime=str(data.get("runtime") or ""),
            acceptance_tests=tuple(str(item) for item in data.get("acceptance_tests") or ()),
            status=WorkTaskStatus(str(data.get("status") or WorkTaskStatus.PENDING.value)),
            max_attempts=max(1, int(data.get("max_attempts") or 1)),
            attempts=max(0, int(data.get("attempts") or 0)),
            worker_id=str(data.get("worker_id") or ""),
            lease_expires_at=_optional_float(data.get("lease_expires_at")),
            heartbeat_at=_optional_float(data.get("heartbeat_at")),
            session_id=str(data.get("session_id") or ""),
            run_id=str(data.get("run_id") or ""),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            started_at=_optional_float(data.get("started_at")),
            ended_at=_optional_float(data.get("ended_at")),
            error=str(data.get("error") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WorkOrder:
    """Repository-owned contract for multi-harness work."""

    work_order_id: str
    goal: str
    repository: str
    status: WorkOrderStatus = WorkOrderStatus.DRAFT
    acceptance_tests: tuple[str, ...] = ()
    harness: str = "coding"
    harness_version: str = ""
    policy_lineage: tuple[dict[str, Any], ...] = ()
    budget: WorkOrderBudget = field(default_factory=WorkOrderBudget)
    tasks: tuple[WorkOrderTask, ...] = ()
    artifacts: tuple[WorkArtifact, ...] = ()
    decision: WorkOrderDecision | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    error: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "work_order_id": self.work_order_id,
            "goal": self.goal,
            "repository": self.repository,
            "status": self.status.value,
            "acceptance_tests": list(self.acceptance_tests),
            "harness": self.harness,
            "harness_version": self.harness_version,
            "policy_lineage": [dict(item) for item in self.policy_lineage],
            "budget": self.budget.to_dict(),
            "tasks": [task.to_dict() for task in self.tasks],
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
            "decision": self.decision.to_dict() if self.decision else None,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "error": self.error,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkOrder":
        return cls(
            work_order_id=str(data["work_order_id"]),
            goal=str(data.get("goal") or ""),
            repository=str(data.get("repository") or "."),
            status=WorkOrderStatus(str(data.get("status") or WorkOrderStatus.DRAFT.value)),
            acceptance_tests=tuple(str(item) for item in data.get("acceptance_tests") or ()),
            harness=str(data.get("harness") or "coding"),
            harness_version=str(data.get("harness_version") or ""),
            policy_lineage=tuple(dict(item) for item in data.get("policy_lineage") or ()),
            budget=WorkOrderBudget.from_dict(data.get("budget")),
            tasks=tuple(WorkOrderTask.from_dict(item) for item in data.get("tasks") or ()),
            artifacts=tuple(WorkArtifact.from_dict(item) for item in data.get("artifacts") or ()),
            decision=WorkOrderDecision.from_dict(data.get("decision")),
            created_at=float(data.get("created_at") or time.time()),
            updated_at=float(data.get("updated_at") or time.time()),
            error=str(data.get("error") or ""),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class WorkOrderEvent:
    """Append-only lifecycle evidence for a WorkOrder."""

    event_id: str
    work_order_id: str
    type: str
    created_at: float
    task_id: str = ""
    actor: str = ""
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def generate_work_order_id() -> str:
    return _sortable_id("work")


def generate_artifact_id() -> str:
    return _sortable_id("artifact")


def generate_event_id() -> str:
    return _sortable_id("event")


def _sortable_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000):013d}{secrets.token_hex(6)}"


def _optional_int(value: Any) -> int | None:
    return int(value) if value is not None and value != "" else None


def _optional_float(value: Any) -> float | None:
    return float(value) if value is not None and value != "" else None
