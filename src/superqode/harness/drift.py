"""Detect disagreement between what a HarnessSpec declares and what resolves.

``harness doctor`` answers whether a harness *can* run. This module answers a
different question: does the harness do what its spec claims?

A spec is a promise. It declares a sandbox, a set of tools, a network stance,
a runtime. Nothing has been checking that the resolved harness honours those
promises, so a spec could claim ``sandbox: docker`` on a machine without Docker,
or declare a tool the runtime never registers, and the first sign of trouble
would be a production run behaving unlike its own definition.

Drift is reported per declaration, so a failure names the field that lied
rather than the symptom that followed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .spec import HarnessSpec


DRIFT_OK = "ok"
DRIFT_DRIFT = "drift"
DRIFT_UNKNOWN = "unknown"


@dataclass(frozen=True)
class DriftCheck:
    """One declaration compared against what actually resolved."""

    name: str
    status: str
    declared: str
    observed: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "declared": self.declared,
            "observed": self.observed,
            "detail": self.detail,
        }


@dataclass(frozen=True)
class DriftReport:
    """Every declaration in a spec, checked against the resolved harness."""

    name: str
    status: str
    checks: tuple[DriftCheck, ...] = field(default_factory=tuple)

    @property
    def drifted(self) -> tuple[DriftCheck, ...]:
        return tuple(check for check in self.checks if check.status == DRIFT_DRIFT)

    def to_dict(self) -> dict[str, Any]:
        unknown = sum(1 for check in self.checks if check.status == DRIFT_UNKNOWN)
        return {
            "name": self.name,
            "status": self.status,
            "clean": self.status != DRIFT_DRIFT,
            "summary": {
                "checks": len(self.checks),
                "drift": len(self.drifted),
                "unknown": unknown,
            },
            "checks": [check.to_dict() for check in self.checks],
        }


def _enum_value(value: Any) -> str:
    return str(getattr(value, "value", value))


def _check(
    name: str,
    declared: Any,
    observed: Any,
    *,
    detail: str = "",
    unknown: bool = False,
) -> DriftCheck:
    declared_text = _enum_value(declared)
    observed_text = _enum_value(observed)
    if unknown:
        status = DRIFT_UNKNOWN
    else:
        status = DRIFT_OK if declared_text == observed_text else DRIFT_DRIFT
    return DriftCheck(
        name=name,
        status=status,
        declared=declared_text,
        observed=observed_text,
        detail=detail,
    )


def _runtime_check(spec: HarnessSpec) -> DriftCheck:
    """A spec naming a runtime it cannot load is the most consequential drift."""
    declared = str(getattr(spec.runtime, "backend", "") or "builtin")
    try:
        from superqode.runtime import list_runtimes

        runtimes = {item.name: item for item in list_runtimes()}
    except Exception as exc:  # noqa: BLE001 - reporting beats crashing
        return _check(
            "runtime",
            declared,
            "unavailable",
            detail=f"Could not enumerate runtimes: {exc}",
            unknown=True,
        )

    info = runtimes.get(declared)
    if info is None:
        return _check(
            "runtime",
            declared,
            "unknown backend",
            detail="The declared backend is not a runtime SuperQode knows.",
        )
    if not getattr(info, "installed", False):
        return _check(
            "runtime",
            declared,
            "not installed",
            detail=str(getattr(info, "install_hint", "") or "The runtime is not installed here."),
        )
    return _check(
        "runtime", declared, declared, detail="Declared runtime resolves and is installed."
    )


def _sandbox_check(spec: HarnessSpec) -> DriftCheck:
    """A declared sandbox that is not present silently downgrades isolation."""
    declared = _enum_value(getattr(spec.execution_policy, "sandbox", "local"))
    # The spec writes "local"; the provider registry calls the same thing
    # "local-os". Comparing the raw strings would report drift on every spec
    # that asks for local execution.
    probed = "local-os" if declared == "local" else declared
    try:
        from superqode.sandbox.execution import sandbox_provider_status

        status = sandbox_provider_status(probed)
    except Exception as exc:  # noqa: BLE001 - reporting beats crashing
        return _check(
            "sandbox",
            declared,
            "unknown",
            detail=f"Could not probe sandbox backends: {exc}",
            unknown=True,
        )

    if not getattr(status, "available", False):
        return _check(
            "sandbox",
            declared,
            "not available",
            detail=str(getattr(status, "detail", "") or "Declared sandbox is unusable here.")
            + " Runs fall back to a weaker boundary than the spec promises.",
        )
    return _check(
        "sandbox",
        declared,
        declared,
        detail=str(getattr(status, "detail", "") or "Declared sandbox is available."),
    )


def _known_tool_names() -> set[str]:
    """Every tool name SuperQode can resolve.

    Tool classes live across ``superqode.tools`` submodules and only some are
    re-exported from the package, so the whole package is walked. Two naming
    vocabularies coexist: the core harness registers short names (read, write,
    edit, bash) while the wider set uses longer ones (read_file, edit_file). A
    spec may use either, so drift is reported only when a name belongs to
    neither.
    """
    import importlib
    import inspect
    import pkgutil

    import superqode.tools as tools_package
    from superqode.tools.base import Tool, ToolRegistry

    names = set(ToolRegistry.core()._tools)

    def collect(module: Any) -> None:
        for attribute in dir(module):
            candidate = getattr(module, attribute, None)
            if inspect.isclass(candidate) and issubclass(candidate, Tool) and candidate is not Tool:
                try:
                    names.add(candidate().name)
                except Exception:  # noqa: BLE001 - a tool needing arguments is still known
                    continue

    collect(tools_package)
    for info in pkgutil.iter_modules(tools_package.__path__):
        try:
            collect(importlib.import_module(f"superqode.tools.{info.name}"))
        except Exception:  # noqa: BLE001 - an unimportable optional tool is not drift
            continue
    return names


def _tool_checks(spec: HarnessSpec) -> list[DriftCheck]:
    """Tools a spec declares that SuperQode cannot resolve.

    ``ToolRegistry.filtered`` keeps only the names that exist and drops the
    rest without complaint, so a typo in a spec removes a tool silently. This
    turns that into a reported disagreement.
    """
    declared = tuple(
        dict.fromkeys(str(tool) for agent in spec.agents for tool in getattr(agent, "tools", ()))
    )
    if not declared or declared == ("full",):
        return [
            DriftCheck(
                "tools",
                DRIFT_OK,
                "full" if declared else "none declared",
                "resolved by the runtime",
                detail="The spec pins no explicit tool list.",
            )
        ]
    try:
        known = _known_tool_names()
    except Exception as exc:  # noqa: BLE001 - reporting beats crashing
        return [
            DriftCheck(
                "tools",
                DRIFT_UNKNOWN,
                ", ".join(declared),
                "unknown",
                detail=f"Could not enumerate tools: {exc}",
            )
        ]

    # Tools published by an MCP server are registered when the server connects,
    # so a static check cannot see them. Absence is not evidence of drift.
    runtime_provided = tuple(tool for tool in declared if tool.startswith("mcp_"))
    missing = [tool for tool in declared if tool not in known and tool not in runtime_provided]
    if missing:
        return [
            DriftCheck(
                "tools",
                DRIFT_DRIFT,
                ", ".join(declared),
                ", ".join(tool for tool in declared if tool in known) or "none",
                detail=(f"Declared but not resolvable, so silently dropped: {', '.join(missing)}."),
            )
        ]
    detail = "Every declared tool resolves."
    if runtime_provided:
        detail = (
            "Every declared tool resolves. "
            f"{len(runtime_provided)} supplied by MCP servers at run time and not checked here."
        )
    return [
        DriftCheck(
            "tools",
            DRIFT_OK,
            ", ".join(declared),
            ", ".join(declared),
            detail=detail,
        )
    ]


def _permission_checks(spec: HarnessSpec) -> list[DriftCheck]:
    """Shell and network stances, compared against the tools that need them."""
    policy = spec.execution_policy
    declared_tools = {str(tool) for agent in spec.agents for tool in getattr(agent, "tools", ())}
    checks: list[DriftCheck] = []

    allow_shell = bool(getattr(policy, "allow_shell", False))
    needs_shell = bool(declared_tools & {"bash", "shell", "run"})
    if needs_shell and not allow_shell:
        checks.append(
            DriftCheck(
                "allow_shell",
                DRIFT_DRIFT,
                "blocked",
                "a shell tool is declared",
                detail="A shell tool is declared while execution_policy blocks shell access.",
            )
        )
    else:
        checks.append(
            _check(
                "allow_shell",
                "allowed" if allow_shell else "blocked",
                "allowed" if allow_shell else "blocked",
                detail="Shell stance matches the declared tools.",
            )
        )

    allow_write = bool(getattr(policy, "allow_write", False))
    needs_write = bool(declared_tools & {"write", "edit", "apply_patch"})
    if needs_write and not allow_write:
        checks.append(
            DriftCheck(
                "allow_write",
                DRIFT_DRIFT,
                "blocked",
                "a write tool is declared",
                detail="A write tool is declared while execution_policy blocks writes.",
            )
        )
    else:
        checks.append(
            _check(
                "allow_write",
                "allowed" if allow_write else "blocked",
                "allowed" if allow_write else "blocked",
                detail="Write stance matches the declared tools.",
            )
        )
    return checks


def _observability_check(spec: HarnessSpec) -> DriftCheck:
    """Evidence claims are worthless if events were never turned on."""
    declared = bool(getattr(getattr(spec, "observability", None), "events", False))
    if not declared:
        return DriftCheck(
            "observability",
            DRIFT_OK,
            "events off",
            "events off",
            detail="The spec does not claim run events.",
        )
    run_store = str(getattr(getattr(spec, "observability", None), "run_store", "") or "")
    if not run_store:
        return DriftCheck(
            "observability",
            DRIFT_DRIFT,
            "events on",
            "no run store",
            detail="Events are declared but no run store is configured to receive them.",
        )
    return DriftCheck(
        "observability",
        DRIFT_OK,
        "events on",
        f"run store: {run_store}",
        detail="Declared events have somewhere to land.",
    )


def _checks_check(spec: HarnessSpec) -> DriftCheck:
    """A checks block that is enabled but empty passes everything."""
    checks_spec = getattr(spec, "checks", None)
    enabled = bool(getattr(checks_spec, "enabled", False))
    steps = tuple(getattr(checks_spec, "custom_steps", ()) or ())
    if not enabled:
        return DriftCheck(
            "checks",
            DRIFT_OK,
            "disabled",
            "disabled",
            detail="The spec does not claim checks.",
        )
    if not steps:
        if bool(getattr(checks_spec, "fail_on_error", False)):
            return DriftCheck(
                "checks",
                DRIFT_DRIFT,
                "enabled, fail on error",
                "no steps defined",
                detail="The spec promises to fail a run on check errors while defining no check.",
            )
        return DriftCheck(
            "checks",
            DRIFT_OK,
            "enabled",
            "no steps defined",
            detail="Enabled without custom steps is a supported configuration.",
        )
    return DriftCheck(
        "checks",
        DRIFT_OK,
        "enabled",
        f"{len(steps)} step(s)",
        detail="Declared checks have steps behind them.",
    )


def detect_drift(spec: HarnessSpec) -> DriftReport:
    """Compare every declaration in ``spec`` against what actually resolves."""
    checks: list[DriftCheck] = [
        _runtime_check(spec),
        _sandbox_check(spec),
        *_tool_checks(spec),
        *_permission_checks(spec),
        _observability_check(spec),
        _checks_check(spec),
    ]
    if any(check.status == DRIFT_DRIFT for check in checks):
        status = DRIFT_DRIFT
    elif any(check.status == DRIFT_UNKNOWN for check in checks):
        status = DRIFT_UNKNOWN
    else:
        status = DRIFT_OK
    return DriftReport(name=spec.name, status=status, checks=tuple(checks))


def render_drift(report: DriftReport) -> str:
    """Human-readable drift report, one line per declaration."""
    symbols = {DRIFT_OK: "ok", DRIFT_DRIFT: "DRIFT", DRIFT_UNKNOWN: "?"}
    lines = [f"Harness: {report.name}", ""]
    for check in report.checks:
        lines.append(f"  {symbols[check.status]:<6} {check.name}")
        lines.append(f"         declared: {check.declared}")
        lines.append(f"         observed: {check.observed}")
        if check.detail:
            lines.append(f"         {check.detail}")
        lines.append("")
    drifted = len(report.drifted)
    if drifted:
        lines.append(f"{drifted} declaration(s) do not match the resolved harness.")
    else:
        lines.append("Every declaration matches the resolved harness.")
    return "\n".join(lines)


__all__ = [
    "DRIFT_DRIFT",
    "DRIFT_OK",
    "DRIFT_UNKNOWN",
    "DriftCheck",
    "DriftReport",
    "detect_drift",
    "render_drift",
]
