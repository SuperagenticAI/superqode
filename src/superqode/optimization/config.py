"""SuperOpt configuration loader (OSS command-based)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

import yaml

from superqode.config.schema import OptimizeConfig


def load_optimize_config(project_root: Path) -> OptimizeConfig:
    """Load SuperOpt config from superqode.yaml."""
    config_path = project_root / "superqode.yaml"
    if not config_path.exists():
        return OptimizeConfig()

    try:
        data: Dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
    except Exception:
        return OptimizeConfig()

    optimize_data = data.get("superqode", {}).get("qe", {}).get("optimize", {})

    if not isinstance(optimize_data, dict):
        return OptimizeConfig()

    return OptimizeConfig(
        enabled=optimize_data.get("enabled", False),
        command=optimize_data.get("command", optimize_data.get("cmd", "")),
        timeout_seconds=optimize_data.get("timeout_seconds", optimize_data.get("timeout", 300)),
    )
