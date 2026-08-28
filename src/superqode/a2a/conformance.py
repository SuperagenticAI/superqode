"""Client checks against one Agent Card.

These answer whether SuperQode can fetch the card, speak an advertised
binding, and complete one task. They are not an A2A specification suite.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from superqode.a2a.connection import A2ASettings, normalize_url
from superqode.a2a.types import TaskStatusValue

DEFAULT_PROBE = "ping"

_TERMINAL = {
    TaskStatusValue.COMPLETED,
    TaskStatusValue.FAILED,
    TaskStatusValue.REJECTED,
    TaskStatusValue.CANCELED,
    TaskStatusValue.INPUT_REQUIRED,
}


@dataclass(frozen=True)
class A2AConformanceCheck:
    """One named check in the pack."""

    name: str
    passed: bool
    detail: str = ""
    skipped: bool = False

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "name": self.name,
            "passed": self.passed,
            "detail": self.detail,
        }
        if self.skipped:
            payload["skipped"] = True
        return payload


@dataclass(frozen=True)
class A2AConformanceReport:
    """Result of running the pack against one origin."""

    url: str
    name: str = ""
    binding: str = ""
    protocol_version: str = ""
    interface_url: str = ""
    checks: tuple[A2AConformanceCheck, ...] = ()
    inspect: dict[str, Any] | None = None

    @property
    def passed(self) -> bool:
        runnable = [check for check in self.checks if not check.skipped]
        return bool(runnable) and all(check.passed for check in runnable)

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "url": self.url,
            "name": self.name,
            "binding": self.binding,
            "protocol_version": self.protocol_version,
            "interface_url": self.interface_url,
            "passed": self.passed,
            "checks": [check.to_dict() for check in self.checks],
        }
        if self.inspect:
            payload["inspect"] = self.inspect
        return payload


async def run_a2a_conformance(
    settings: A2ASettings,
    *,
    message: str | None = None,
    send: bool = True,
    http_client=None,
    timeout: float = 180.0,
) -> A2AConformanceReport:
    """Run the four checks against ``settings.url``."""
    from superqode.a2a.client import A2AClient, A2AClientError

    origin = normalize_url(settings.url)
    probe = (message or DEFAULT_PROBE).strip() or DEFAULT_PROBE
    checks: list[A2AConformanceCheck] = []
    name = ""
    binding = ""
    version = ""
    interface_url = ""

    async with A2AClient(
        origin,
        http_client=http_client,
        bearer_token=settings.token or None,
        timeout=timeout,
    ) as client:
        try:
            card = await client.get_agent_card()
        except A2AClientError as exc:
            return _failed_discovery(origin, client, exc)

        name = card.name
        binding = client._binding or ""
        version = client._protocol_version or ""
        interface_url = card.url
        checks.append(_ok("card-fetch", _response_detail(client, "200")))
        shape_missing = []
        if not (card.name or "").strip():
            shape_missing.append("name")
        if not (card.url or "").strip():
            shape_missing.append("interface url")
        skill_count = len(card.skills)
        checks.append(
            _check(
                "card-shape",
                not shape_missing,
                ", ".join(shape_missing)
                if shape_missing
                else f"{skill_count} skill{'s' if skill_count != 1 else ''}",
            )
        )
        checks.append(
            _check(
                "binding",
                bool(binding and version and interface_url),
                f"{binding} {version} at {interface_url}".strip(),
            )
        )
        if not send:
            checks.append(_skip("send", "not requested"))
        elif not checks[-1].passed:
            checks.append(_skip("send", "no speakable interface"))
        else:
            checks.append(await _send_check(client, probe))
        inspect = client.inspect.to_dict()

    return A2AConformanceReport(
        url=origin,
        name=name,
        binding=binding,
        protocol_version=version,
        interface_url=interface_url,
        checks=tuple(checks),
        inspect=inspect,
    )


def render_a2a_conformance(report: A2AConformanceReport) -> str:
    lines = [
        f"A2A client checks: {'PASS' if report.passed else 'FAIL'}",
        f"Card:     {report.url}",
    ]
    if report.name:
        lines.append(f"Agent:    {report.name}")
    if report.binding:
        lines.append(f"Binding:  {report.binding} {report.protocol_version}")
    lines.append("")
    for check in report.checks:
        if check.skipped:
            mark = "skip"
        elif check.passed:
            mark = "pass"
        else:
            mark = "FAIL"
        suffix = f": {check.detail}" if check.detail else ""
        lines.append(f"[{mark}] {check.name}{suffix}")
    return "\n".join(lines)


def _failed_discovery(origin: str, client, exc: BaseException) -> A2AConformanceReport:
    status = _response_status(client)
    message = str(exc)
    checks: list[A2AConformanceCheck]
    if status == 200:
        shape_ok = "was not JSON" not in message and "not an object" not in message
        checks = [
            _ok("card-fetch", "200"),
            _check("card-shape", shape_ok, message if not shape_ok else "JSON object"),
        ]
        if shape_ok:
            checks.append(_check("binding", False, message))
            checks.append(_skip("send", "no speakable interface"))
        else:
            checks.append(_skip("binding", "card is not a usable object"))
            checks.append(_skip("send", "card is not a usable object"))
    else:
        checks = [
            _check("card-fetch", False, message),
            _skip("card-shape", "no card"),
            _skip("binding", "no card"),
            _skip("send", "no card"),
        ]
    return A2AConformanceReport(
        url=origin,
        checks=tuple(checks),
        inspect=client.inspect.to_dict(),
    )


async def _send_check(client, probe: str) -> A2AConformanceCheck:
    from superqode.a2a.client import A2AClientError

    try:
        task = await client.send_message(probe)
    except A2AClientError as exc:
        return _check("send", False, str(exc))
    state = task.status.state
    if isinstance(state, TaskStatusValue):
        value = state.value
        terminal = state in _TERMINAL
    else:
        value = str(state)
        terminal = value.lower() in {item.value for item in _TERMINAL}
    detail = f"{task.task_id} {value}".strip()
    return _check("send", terminal, detail)


def _response_status(client) -> int | None:
    for event in reversed(client.inspect.events):
        if event.kind == "response":
            status = event.detail.get("status")
            return int(status) if status is not None else None
    return None


def _response_detail(client, fallback: str) -> str:
    status = _response_status(client)
    return str(status) if status is not None else fallback


def _check(name: str, passed: bool, detail: str = "") -> A2AConformanceCheck:
    return A2AConformanceCheck(name=name, passed=bool(passed), detail=detail)


def _ok(name: str, detail: str = "") -> A2AConformanceCheck:
    return A2AConformanceCheck(name=name, passed=True, detail=detail)


def _skip(name: str, detail: str) -> A2AConformanceCheck:
    return A2AConformanceCheck(name=name, passed=True, detail=detail, skipped=True)
