"""Patch validation harness compatibility namespace.

The agent harness v2 API lives under ``superqode.harness``. Older patch and
project validation primitives are exposed here so the two concepts have clear
names without breaking existing imports.
"""

from superqode.harness.config import HarnessConfig, ValidationCategory, load_harness_config
from superqode.harness.validator import HarnessFinding, HarnessResult, PatchHarness

__all__ = [
    "HarnessConfig",
    "HarnessFinding",
    "HarnessResult",
    "PatchHarness",
    "ValidationCategory",
    "load_harness_config",
]
