"""
QE Guidance Prompts - Minimal OSS guidance.

This provides lightweight, non-proprietary guidance for QE agents.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config import GuidanceConfig, GuidanceMode, ModeGuidanceConfig, load_guidance_config


@dataclass
class QEGuidance:
    """Minimal QE guidance for OSS."""

    config: GuidanceConfig
    mode: GuidanceMode

    @property
    def mode_config(self) -> ModeGuidanceConfig:
        return self.config.get_mode_config(self.mode)

    def get_system_prompt(self) -> str:
        mode_name = "Quick Scan" if self.mode == GuidanceMode.QUICK_SCAN else "Deep QE"
        timeout = self.mode_config.timeout_seconds
        return (
            f"SYSTEM: SuperQode {mode_name} QE Mode ({timeout}s)\n\n"
            "Focus on finding real issues with evidence. "
            "Prefer concrete reproduction steps and avoid speculation."
        )

    def get_review_prompt(self) -> str:
        return (
            "SYSTEM: SuperQode QE Review Mode\n\n"
            "Validate that findings are evidence-backed and reproducible. "
            "Call out any unverifiable claims."
        )

    def get_goal_suffix(self) -> str:
        return (
            "\n\nCOMPLETION GATE:\n"
            "1. Run relevant checks/tests where feasible\n"
            "2. Document evidence for findings\n"
            "3. Report any limitations clearly\n"
        )


def get_qe_system_prompt(
    project_root: Path,
    mode: GuidanceMode = GuidanceMode.QUICK_SCAN,
) -> str:
    config = load_guidance_config(project_root)
    guidance = QEGuidance(config=config, mode=mode)
    return guidance.get_system_prompt()


def get_qe_review_prompt(project_root: Path) -> str:
    config = load_guidance_config(project_root)
    guidance = QEGuidance(config=config, mode=GuidanceMode.DEEP_QE)
    return guidance.get_review_prompt()


def get_qe_goal_suffix(
    project_root: Path,
    mode: GuidanceMode = GuidanceMode.QUICK_SCAN,
) -> str:
    config = load_guidance_config(project_root)
    guidance = QEGuidance(config=config, mode=mode)
    return guidance.get_goal_suffix()
