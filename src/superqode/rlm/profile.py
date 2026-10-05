"""Validated native RLM experiment settings, portable across workers."""

from dataclasses import dataclass
import os
from typing import Any, Mapping


@dataclass(frozen=True)
class RLMProfile:
    tool_surface: str = "python"
    observations: str = "transcript"
    recent_messages: int = 12
    observation_chars: int = 2000

    def __post_init__(self):
        if self.tool_surface not in {"python", "python-bash"}:
            raise ValueError("RLM tool_surface must be python or python-bash")
        if self.observations not in {"transcript", "selective"}:
            raise ValueError("RLM observations must be transcript or selective")
        if not 2 <= self.recent_messages <= 100 or not 256 <= self.observation_chars <= 20000:
            raise ValueError("RLM recent_messages must be 2..100 and observation_chars 256..20000")

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None = None):
        data = dict(config or {})
        surface = str(data.get("tool_surface", "python"))
        observations = str(data.get("observations", "transcript"))
        if surface not in {"python", "python-bash"}:
            raise ValueError("RLM tool_surface must be python or python-bash")
        if observations not in {"transcript", "selective"}:
            raise ValueError("RLM observations must be transcript or selective")
        recent = int(data.get("recent_messages", 12))
        chars = int(data.get("observation_chars", 2000))
        if not 2 <= recent <= 100 or not 256 <= chars <= 20000:
            raise ValueError("RLM recent_messages must be 2..100 and observation_chars 256..20000")
        return cls(surface, observations, recent, chars)

    @property
    def tools(self) -> tuple[str, ...]:
        return ("python", "bash") if self.tool_surface == "python-bash" else ("python",)

    def to_dict(self):
        return {
            "tool_surface": self.tool_surface,
            "observations": self.observations,
            "recent_messages": self.recent_messages,
            "observation_chars": self.observation_chars,
        }

    def validate_sandbox(self, sandbox):
        if self.tool_surface == "python-bash" and sandbox.backend == "host" and os.name != "posix":
            raise ValueError(
                "Host Python+Bash requires POSIX process groups; use Docker on Windows"
            )
        if self.tool_surface == "python-bash" and (
            sandbox.backend == "monty" or not sandbox.policy.allow_shell
        ):
            raise ValueError("Python+Bash requires a host or Docker profile with shell permission")
