"""Reusable conformance checks for Harness Protocol v1 adapters."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .events import HARNESS_PROTOCOL_VERSION
from .protocol import (
    TERMINAL_EVENT_TYPES,
    HarnessAdapter,
    HarnessCreateRequest,
    HarnessMessage,
)
from .protocol_controller import HarnessProtocolController, HarnessProtocolStore


@dataclass(frozen=True)
class HarnessConformanceCheck:
    name: str
    passed: bool
    detail: str = ""

    def to_dict(self) -> dict[str, object]:
        return {"name": self.name, "passed": self.passed, "detail": self.detail}


@dataclass(frozen=True)
class HarnessConformanceReport:
    harness_id: str
    protocol_version: str
    checks: tuple[HarnessConformanceCheck, ...]
    session_id: str = ""
    run_id: str = ""

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)

    def to_dict(self) -> dict[str, object]:
        return {
            "harness_id": self.harness_id,
            "protocol_version": self.protocol_version,
            "passed": self.passed,
            "session_id": self.session_id,
            "run_id": self.run_id,
            "checks": [check.to_dict() for check in self.checks],
        }


async def run_harness_conformance(
    adapter: HarnessAdapter,
    *,
    store: HarnessProtocolStore | None = None,
    prompt: str = "Return the exact text: protocol-ok",
    provider: str = "conformance",
    model: str = "deterministic",
    working_directory: Path | None = None,
) -> HarnessConformanceReport:
    """Exercise lifecycle, ledger, resume, checkpoint, and export invariants."""
    controller = HarnessProtocolController([adapter], store=store)
    descriptor = adapter.descriptor
    checks: list[HarnessConformanceCheck] = []
    checks.append(
        _check(
            "protocol-version",
            descriptor.protocol_version == HARNESS_PROTOCOL_VERSION,
            descriptor.protocol_version,
        )
    )
    session = await controller.create(
        HarnessCreateRequest(
            harness_id=descriptor.id,
            provider=provider,
            model=model,
            working_directory=working_directory or Path.cwd(),
        )
    )
    events = [
        event
        async for event in controller.send(
            session,
            HarnessMessage(role="user", content=prompt),
        )
    ]
    run_id = events[0].run_id if events else ""
    checks.extend(
        [
            _check("events-emitted", bool(events), f"count={len(events)}"),
            _check(
                "canonical-envelope",
                all(
                    event.protocol_version == HARNESS_PROTOCOL_VERSION
                    and bool(event.event_id)
                    and event.session_id == session.session_id
                    and event.run_id == run_id
                    and event.harness_id == descriptor.id
                    for event in events
                ),
            ),
            _check(
                "monotonic-sequence",
                [event.sequence for event in events] == list(range(1, len(events) + 1)),
            ),
            _check(
                "unique-event-ids",
                len({event.event_id for event in events}) == len(events),
            ),
            _check(
                "lifecycle-boundaries",
                bool(events)
                and events[0].type == "run.started"
                and events[-1].type in TERMINAL_EVENT_TYPES
                and sum(event.type in TERMINAL_EVENT_TYPES for event in events) == 1,
            ),
            _check(
                "messages-preserved",
                {event.data.get("role") for event in events if event.type == "message.created"}
                >= {"user", "assistant"},
            ),
        ]
    )
    stored = controller.store.get_run(run_id) if run_id else None
    checks.append(
        _check(
            "durable-ledger",
            stored is not None
            and [event.event_id for event in stored.events] == [event.event_id for event in events],
        )
    )
    bundle = controller.export(session)
    try:
        json.dumps(bundle.to_dict(), sort_keys=True)
        serializable = True
    except (TypeError, ValueError):
        serializable = False
    checks.append(_check("portable-export", serializable and bool(bundle.runs)))
    if descriptor.capabilities.resume:
        resumed = await controller.resume(session.session_id)
        checks.append(
            _check(
                "resume",
                resumed.session_id == session.session_id
                and resumed.harness_id == session.harness_id,
            )
        )
    else:
        checks.append(_check("resume-declared-unsupported", True))
    if descriptor.capabilities.checkpoint:
        checkpoint = await controller.checkpoint(session)
        exported = controller.export(session)
        checks.append(
            _check(
                "checkpoint",
                checkpoint.session_id == session.session_id
                and any(
                    item.checkpoint_id == checkpoint.checkpoint_id for item in exported.checkpoints
                ),
            )
        )
    else:
        checks.append(_check("checkpoint-declared-unsupported", True))
    return HarnessConformanceReport(
        harness_id=descriptor.id,
        protocol_version=descriptor.protocol_version,
        checks=tuple(checks),
        session_id=session.session_id,
        run_id=run_id or "",
    )


def render_harness_conformance(report: HarnessConformanceReport) -> str:
    lines = [
        f"Harness Protocol {report.protocol_version}: {report.harness_id}",
        f"Result: {'PASS' if report.passed else 'FAIL'}",
    ]
    for check in report.checks:
        suffix = f" — {check.detail}" if check.detail else ""
        lines.append(f"[{'pass' if check.passed else 'FAIL'}] {check.name}{suffix}")
    return "\n".join(lines)


def _check(name: str, passed: bool, detail: str = "") -> HarnessConformanceCheck:
    return HarnessConformanceCheck(name=name, passed=bool(passed), detail=detail)
