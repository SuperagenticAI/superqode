"""Persisted goal and autonomous-completion policy for native RLM sessions."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Any, Sequence


@dataclass(frozen=True, slots=True)
class RLMPolicy:
    """Runtime policy reloaded before every root turn."""

    goal: str = ""
    autonomous: bool = False
    gates: tuple[str, ...] = ()
    max_rounds: int = 3
    gate_timeout: float = 120.0

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> "RLMPolicy":
        data = value or {}
        gates = tuple(gate for item in data.get("gates") or () if (gate := str(item).strip()))
        return cls(
            goal=str(data.get("goal") or "").strip(),
            autonomous=bool(data.get("autonomous", False)),
            gates=gates,
            max_rounds=max(1, min(20, int(data.get("max_rounds") or 3))),
            gate_timeout=max(1.0, min(3600.0, float(data.get("gate_timeout") or 120.0))),
        )

    def updated(self, **changes: Any) -> "RLMPolicy":
        return self.from_dict(asdict(replace(self, **changes)))


@dataclass(frozen=True, slots=True)
class GateResult:
    command: str
    returncode: int
    stdout: str
    stderr: str
    timed_out: bool = False

    @property
    def ok(self) -> bool:
        return self.returncode == 0 and not self.timed_out

    def to_dict(self) -> dict[str, Any]:
        return asdict(self) | {"ok": self.ok}


class RLMPolicyStore:
    """Small JSON sidecar; corrupt files safely fall back to defaults."""

    def __init__(self, path: str | Path, *, defaults: RLMPolicy | None = None) -> None:
        self.path = Path(path).expanduser()
        self.defaults = defaults or RLMPolicy()

    def load(self) -> RLMPolicy:
        if not self.path.is_file():
            return self.defaults
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return self.defaults
        return RLMPolicy.from_dict(value if isinstance(value, dict) else None)

    def save(self, policy: RLMPolicy) -> RLMPolicy:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(policy), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temporary.replace(self.path)
        return policy

    def update(self, **changes: Any) -> RLMPolicy:
        return self.save(self.load().updated(**changes))


async def run_completion_gates(
    gates: Sequence[str],
    *,
    cwd: str | Path,
    timeout: float,
    output_limit: int = 12_000,
) -> list[GateResult]:
    """Run configured host gates in order and retain bounded diagnostic output."""
    results: list[GateResult] = []
    for command in gates:
        results.append(
            await asyncio.to_thread(
                _run_gate,
                str(command),
                Path(cwd).expanduser().resolve(),
                timeout,
                output_limit,
            )
        )
    return results


def gate_feedback(results: Sequence[GateResult]) -> str:
    """Build the next-turn message from failed completion evidence."""
    sections = [
        "Autonomous completion gates failed. Continue working on the same goal, "
        "fix these failures, and run appropriate verification before finishing."
    ]
    for result in results:
        if result.ok:
            continue
        output = "\n".join(part for part in (result.stdout, result.stderr) if part).strip()
        sections.append(
            f"$ {result.command}\nexit={result.returncode}"
            + (" (timed out)" if result.timed_out else "")
            + (f"\n{output}" if output else "")
        )
    return "\n\n".join(sections)


def _run_gate(command: str, cwd: Path, timeout: float, output_limit: int) -> GateResult:
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        return GateResult(
            command=command,
            returncode=124,
            stdout=_bounded(error.stdout, output_limit),
            stderr=_bounded(error.stderr, output_limit),
            timed_out=True,
        )
    return GateResult(
        command=command,
        returncode=completed.returncode,
        stdout=_bounded(completed.stdout, output_limit),
        stderr=_bounded(completed.stderr, output_limit),
    )


def _bounded(value: str | bytes | None, limit: int) -> str:
    if isinstance(value, bytes):
        text = value.decode(errors="replace")
    else:
        text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... output truncated ({len(text) - limit} characters omitted)"


__all__ = [
    "GateResult",
    "RLMPolicy",
    "RLMPolicyStore",
    "gate_feedback",
    "run_completion_gates",
]
