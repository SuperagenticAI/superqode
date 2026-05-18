"""Tests for the runtime field on SuperQodeConfig (parsed from superqode.yaml)."""

from __future__ import annotations

from pathlib import Path

import yaml

from superqode.config.loader import parse_config
from superqode.config.schema import SuperQodeConfig


def test_runtime_defaults_to_none_when_not_set():
    cfg = SuperQodeConfig()
    assert cfg.runtime is None


def test_runtime_parsed_from_yaml_when_present():
    data = {
        "superqode": {
            "version": "1.0",
            "runtime": "adk",
        }
    }
    config = parse_config(data)
    assert config.superqode.runtime == "adk"


def test_missing_runtime_yaml_key_leaves_field_none():
    data = {
        "superqode": {
            "version": "1.0",
        }
    }
    config = parse_config(data)
    assert config.superqode.runtime is None


def test_runtime_yaml_field_accepts_all_known_names():
    for name in ("builtin", "adk", "openai-agents"):
        config = parse_config({"superqode": {"runtime": name}})
        assert config.superqode.runtime == name


def test_real_yaml_roundtrip(tmp_path: Path):
    yaml_path = tmp_path / "superqode.yaml"
    yaml_path.write_text(yaml.safe_dump({"superqode": {"runtime": "openai-agents"}}))
    loaded = yaml.safe_load(yaml_path.read_text())
    config = parse_config(loaded)
    assert config.superqode.runtime == "openai-agents"
