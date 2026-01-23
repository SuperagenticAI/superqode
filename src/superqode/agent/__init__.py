"""
SuperQode Agent - Minimal, Transparent Agent Loop.

Design Philosophy:
- MINIMAL HARNESS: No heavy system prompts, no opinionated formatting
- TRANSPARENT: What you see is what the model gets
- FAIR TESTING: Compare models on equal footing
- SIMPLE LOOP: prompt → model → tools → repeat

This is NOT trying to be the best coding agent.
This IS trying to be the fairest way to test model coding capabilities.
"""

from .loop import AgentLoop, AgentConfig
from .system_prompts import SystemPromptLevel, get_system_prompt

__all__ = [
    "AgentLoop",
    "AgentConfig",
    "SystemPromptLevel",
    "get_system_prompt",
]
