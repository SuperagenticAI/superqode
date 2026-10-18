"""Versioned native Harness² job contract. Model routes belong to the executor."""

from __future__ import annotations

import math
import os
from dataclasses import dataclass, replace
from pathlib import Path

from ..spec import HarnessSpec

METHOD = "harness2-superqode-v1"
UPSTREAM = "1cfe254e8d25b15f37048c3730134686abe60335"
COMPONENTS = ("instructions.md", "memory.md", "tool_guidance.md")


@dataclass(frozen=True)
class RefinementRequest:
    task: str
    source: Path
    output: Path
    spec: HarnessSpec
    provider: str
    model: str
    mode: str = "sequential"
    k: int = 1
    max_parallel: int = 1
    max_wall_seconds: float = 900
    max_sessions: int = 64
    max_turns: int = 12
    max_output_tokens: int = 4096
    checks: tuple[tuple[str, ...], ...] = ()
    protected_paths: tuple[str, ...] = ()
    resume: bool = False
    retry_interrupted: bool = False

    def frozen_route(self):
        """Resolve ambient endpoint defaults once, then persist and execute them."""
        config = dict(self.spec.runtime.config)
        if self.provider == "ollama":
            config.setdefault(
                "ollama_base_url", os.environ.get("OLLAMA_HOST", "http://localhost:11434")
            )
        elif self.provider in {"lmstudio", "llamacpp", "vllm"}:
            from superqode.codegem.provider import compatible_base_url

            config["base_url"] = compatible_base_url(self.provider, config)
        elif self.provider in {"google", "gemini"}:
            config.setdefault("gemini_base_url", "https://generativelanguage.googleapis.com/v1beta")
        return replace(
            self, spec=replace(self.spec, runtime=replace(self.spec.runtime, config=config))
        )

    def validate(self):
        for name in ("k", "max_parallel", "max_sessions", "max_turns", "max_output_tokens"):
            if type(getattr(self, name)) is not int:
                raise ValueError(f"{name} must be an integer")
        if not self.task.strip() or not self.provider or not self.model:
            raise ValueError("Task, provider, and model are required")
        if not self.source.is_dir():
            raise ValueError("Source must be an existing directory")
        if self.mode not in {"parallel", "sequential"} or not 1 <= self.k <= 4:
            raise ValueError("Use parallel/sequential mode and k between 1 and 4")
        if not 1 <= self.max_parallel <= 4 or not 1 <= self.max_turns <= 128:
            raise ValueError("Parallelism must be 1..4 and max_turns must be 1..128")
        if (
            type(self.max_wall_seconds) not in (float, int)
            or not math.isfinite(self.max_wall_seconds)
            or self.max_wall_seconds <= 0
        ):
            raise ValueError("Wall time must be a finite positive number")
        if not 128 <= self.max_output_tokens <= 32768:
            raise ValueError("max_output_tokens must be between 128 and 32768")
        if self.max_sessions < self.nominal_sessions:
            raise ValueError(
                f"This job needs at least {self.nominal_sessions} sessions before retries"
            )
        if self.spec.runtime.backend != "codegem":
            raise ValueError(
                "This refinement release supports CodeGem; other executors require conformance first"
            )
        from superqode.codegem.profiles import resolve_profile

        resolve_profile(self.model, self.provider)
        source, output = self.source.resolve(), self.output.resolve()
        if output == source or source.is_relative_to(output):
            raise ValueError("Output cannot contain the source directory")
        if output.is_relative_to(source) and output.relative_to(source).parts[0] != ".superqode":
            raise ValueError("Output inside the source must be under .superqode/")
        for path in self.protected_paths:
            relpath(path)
        if any(
            not argv or any(not isinstance(a, str) or not a for a in argv) for argv in self.checks
        ):
            raise ValueError("Checks must be nonempty argument arrays")

    @property
    def nominal_sessions(self):
        return 7 * self.k + (1 if self.k > 1 else 0)

    def plan(self):
        self.validate()
        config = self.frozen_route().spec.runtime.config
        return {
            "method": METHOD,
            "upstream": UPSTREAM,
            "executor": self.spec.runtime.backend,
            "provider": self.provider,
            "model": self.model,
            "endpoint": config.get("ollama_base_url")
            if self.provider == "ollama"
            else config.get("gemini_base_url")
            if self.provider in {"google", "gemini"}
            else config.get("base_url"),
            "mode": self.mode,
            "k": self.k,
            "solver_runs": 4 * self.k,
            "improvement_stages": 3 * self.k,
            "selector_sessions": int(self.k > 1),
            "nominal_sessions": self.nominal_sessions,
            "max_sessions": self.max_sessions,
            "max_parallel": self.max_parallel,
            "max_wall_seconds": self.max_wall_seconds,
            "max_turns": self.max_turns,
            "max_output_tokens": self.max_output_tokens,
            "components": list(COMPONENTS),
            "library": "off",
            "output": str(self.output.resolve()),
            "source": str(self.source.resolve()),
            "checks": [list(argv) for argv in self.checks],
            "protected_paths": list(self.protected_paths),
            "source_exclusions": [
                "Git ignored files",
                ".git",
                ".superqode",
                ".venv",
                "node_modules",
                "Python caches",
                ".env*",
                "*.pem",
                "*.key",
            ],
            "execution": "host permissions"
            if self.spec.runtime.backend == "codegem"
            else self.spec.execution_policy.sandbox,
        }


def relpath(value: str) -> str:
    path = Path(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or "\x00" in value:
        raise ValueError(f"Unsafe relative path: {value!r}")
    return path.as_posix()


def refinement_options(spec):
    """Validate the explicit native method settings without swallowing typos."""
    config = spec.optimization.config
    if not config.get("method"):
        return {}
    if config["method"] != "harness2":
        raise ValueError("The spec selects a different optimization method")
    allowed = {
        "mode",
        "k",
        "max_parallel",
        "max_wall_seconds",
        "max_sessions",
        "max_turns",
        "max_output_tokens",
    }
    unknown = set(config) - allowed - {"method"}
    if unknown:
        raise ValueError("Unsupported Harness² settings: " + ", ".join(sorted(unknown)))
    return {key: config[key] for key in allowed if key in config}


def resume_request(output: Path, *, retry_interrupted=False, max_wall_seconds=900, max_sessions=64):
    from ..loader import harness_spec_from_dict
    from .store import read_json

    data = read_json(output / "manifest.json")
    return RefinementRequest(
        task=data["task"],
        source=Path(data["source"]),
        output=output,
        spec=harness_spec_from_dict(data["spec"]),
        provider=data["provider"],
        model=data["model"],
        mode=data["mode"],
        k=data["k"],
        max_parallel=data["plan"]["max_parallel"],
        max_wall_seconds=max_wall_seconds,
        max_sessions=max_sessions,
        max_turns=data["max_turns"],
        max_output_tokens=data["max_output_tokens"],
        checks=tuple(tuple(argv) for argv in data["checks"]),
        protected_paths=tuple(data["protected_paths"]),
        resume=True,
        retry_interrupted=retry_interrupted,
    )
