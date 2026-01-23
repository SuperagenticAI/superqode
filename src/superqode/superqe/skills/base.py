"""
Base classes for QE Skills.

Skills are reusable capabilities that can be applied
to quality engineering tasks.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import uuid


@dataclass
class SkillConfig:
    """Configuration for a skill execution."""

    verbose: bool = False
    dry_run: bool = False
    timeout_seconds: int = 300
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SkillResult:
    """Result of a skill execution."""

    skill_name: str
    success: bool
    output: str = ""
    artifacts: List[str] = field(default_factory=list)
    metrics: Dict[str, Any] = field(default_factory=dict)
    errors: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "skill": self.skill_name,
            "success": self.success,
            "output": self.output,
            "artifacts": self.artifacts,
            "metrics": self.metrics,
            "errors": self.errors,
        }


class Skill(ABC):
    """
    Base class for QE skills.

    Skills encapsulate reusable quality engineering capabilities
    that can be applied to code, tests, or processes.
    """

    # Skill metadata - override in subclasses
    NAME = "base"
    DISPLAY_NAME = "Base Skill"
    DESCRIPTION = "Base skill class"
    CATEGORY = "general"
    VERSION = "1.0.0"
    TAGS: List[str] = []

    def __init__(self, config: Optional[SkillConfig] = None):
        """Initialize the skill."""
        self.config = config or SkillConfig()
        self.skill_id = str(uuid.uuid4())[:8]

    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        """
        Execute the skill.

        Args:
            **kwargs: Skill-specific parameters

        Returns:
            SkillResult with output and metrics
        """
        pass

    def get_prompt(self) -> str:
        """
        Get the system prompt for this skill.

        Override to provide skill-specific prompting.
        """
        return f"You are an expert in {self.DISPLAY_NAME}."

    def get_examples(self) -> List[str]:
        """
        Get usage examples for this skill.

        Override to provide skill-specific examples.
        """
        return []

    def get_info(self) -> Dict[str, Any]:
        """Get skill information."""
        return {
            "name": self.NAME,
            "display_name": self.DISPLAY_NAME,
            "description": self.DESCRIPTION,
            "category": self.CATEGORY,
            "version": self.VERSION,
            "tags": self.TAGS,
        }
