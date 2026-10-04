"""Persist new RLM routing profiles without changing an existing worker."""

from copy import deepcopy
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

from superqode.harness.loader import save_harness_spec
from superqode.rlm.delegation_policy import DelegationPolicy


def save_routing_profile(spec, config: dict, root: Path) -> Path:
    if spec is None or spec.runtime.backend != "rlm":
        raise ValueError("Select a native RLM harness before configuring A2A.")
    DelegationPolicy.from_config(config)
    name = f"rlm-routing-{uuid4().hex[:12]}"
    profile = replace(
        spec,
        name=name,
        description="Native RLM with explicitly configured optional A2A routing.",
        runtime=replace(
            spec.runtime, config={**deepcopy(spec.runtime.config), "a2a": deepcopy(config)}
        ),
        metadata={**deepcopy(spec.metadata), "customized_from": spec.name},
    )
    return save_harness_spec(profile, root / ".superqode" / "harnesses" / f"{name}.yaml")
