"""
SuperQode QE Guidance - System prompts for time-constrained QE.

Provides verification-first guidance for QE agents to prevent:
- False positives (claiming success without proof)
- Shallow testing (skipping edge cases)
- Time wasting (long speculative work before feedback)

Configuration is driven entirely by superqode.yaml:

```yaml
superqode:
  qe:
    guidance:
      enabled: true

      # Mode-specific timeouts
      quick_scan:
        timeout_seconds: 60
        verification_first: true
        fail_fast: true

      deep_qe:
        timeout_seconds: 1800
        exploration_allowed: true
        destructive_testing: true

      # Anti-patterns to detect
      anti_patterns:
        - skip_verification
        - unconditional_success
        - broad_exception_swallow
        - weaken_tests
```

Integrates with:
- CI: `superqe run --mode quick` (proactive)
- TUI: Interactive QE sessions (reactive)
"""

from .prompts import (
    QEGuidance,
    GuidanceMode,
    get_qe_system_prompt,
    get_qe_review_prompt,
    get_qe_goal_suffix,
)
from .config import GuidanceConfig, load_guidance_config

__all__ = [
    "QEGuidance",
    "GuidanceMode",
    "get_qe_system_prompt",
    "get_qe_review_prompt",
    "get_qe_goal_suffix",
    "GuidanceConfig",
    "load_guidance_config",
]
