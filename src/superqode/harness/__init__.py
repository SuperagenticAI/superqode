"""
SuperQode Patch Harness - Fast validation for QE artifacts.

The harness runs user-defined commands on patches/changes BEFORE they're suggested in QIRs.
This keeps OSS flexible without shipping proprietary validators.

Key principle from PRD:
> "SuperQode never edits, rewrites, or commits code."
> "All fixes are suggested, validated, and proven, never auto-applied."

The harness VALIDATES suggestions, it doesn't apply them.

Configuration is driven entirely by superqode.yaml:

```yaml
superqode:
  qe:
    harness:
      enabled: true
      timeout_seconds: 30

      custom_steps:
        - name: "pytest"
          command: "pytest -q"
        - name: "contract-check"
          command: "schemathesis run openapi.yaml"
```
"""

from .validator import PatchHarness, HarnessFinding, HarnessResult
from .config import HarnessConfig, ValidationCategory, load_harness_config
from .accelerator import (
    Accelerator,
    AcceleratorConfig,
    get_accelerator,
    prewarm,
    cached_system_prompt,
)

__all__ = [
    # Validation
    "PatchHarness",
    "HarnessFinding",
    "HarnessResult",
    "ValidationCategory",
    "HarnessConfig",
    "load_harness_config",
    # Performance
    "Accelerator",
    "AcceleratorConfig",
    "get_accelerator",
    "prewarm",
    "cached_system_prompt",
]
