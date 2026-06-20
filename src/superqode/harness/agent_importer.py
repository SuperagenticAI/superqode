"""Compile concise SuperQode agent YAML into HarnessSpec objects."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .loader import save_harness_spec
from .omnigent_importer import omnigent_agent_to_harness_spec
from .spec import HarnessSpec


def load_agent_yaml(path: str | Path) -> dict[str, Any]:
    """Load a SuperQode agent YAML file as a mapping."""
    spec_path = Path(path).expanduser()
    data = yaml.safe_load(spec_path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Agent spec must be a mapping: {spec_path}")
    return data


def import_agent_yaml(
    path: str | Path,
    *,
    output: str | Path | None = None,
    name: str | None = None,
) -> HarnessSpec | Path:
    """Compile a concise SuperQode agent YAML file and optionally write it."""
    source_path = Path(path).expanduser()
    spec = agent_yaml_to_harness_spec(
        load_agent_yaml(source_path),
        source_path=source_path,
        name=name,
    )
    if output is None:
        return spec
    return save_harness_spec(spec, output)


def agent_yaml_to_harness_spec(
    data: dict[str, Any],
    *,
    source_path: str | Path | None = None,
    name: str | None = None,
) -> HarnessSpec:
    """Convert SuperQode's concise agent YAML shape into a HarnessSpec.

    The authoring format intentionally accepts the Omnigent-style fields we
    want to keep: ``executor``, ``tools``, ``skills``, ``os_env``, ``policies``,
    and agent-valued tools. The result is always a normal SuperQode
    ``HarnessSpec``.
    """
    return omnigent_agent_to_harness_spec(
        data,
        source_path=source_path,
        name=name,
        source_label="superqode-agent",
        metadata_key="agent",
    )
