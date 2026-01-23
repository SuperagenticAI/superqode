"""
Skill Registry - Central registry for QE skills.

Provides skill lookup, registration, and discovery.
"""

from typing import Dict, List, Optional, Type

from .base import Skill, SkillConfig


class SkillRegistry:
    """Registry for QE skills."""

    _skills: Dict[str, Type[Skill]] = {}

    @classmethod
    def register(cls, skill_class: Type[Skill]) -> None:
        """Register a skill."""
        cls._skills[skill_class.NAME] = skill_class

    @classmethod
    def get(cls, name: str, config: Optional[SkillConfig] = None) -> Optional[Skill]:
        """Get a skill by name."""
        skill_class = cls._skills.get(name)
        if skill_class:
            return skill_class(config)
        return None

    @classmethod
    def list_all(cls) -> List[Dict[str, str]]:
        """List all registered skills."""
        return [skill().get_info() for skill in cls._skills.values()]

    @classmethod
    def get_by_category(cls, category: str) -> List[Type[Skill]]:
        """Get skills by category."""
        return [skill for skill in cls._skills.values() if skill.CATEGORY == category]

    @classmethod
    def get_categories(cls) -> List[str]:
        """Get all skill categories."""
        return list(set(skill.CATEGORY for skill in cls._skills.values()))


def get_skill(name: str, config: Optional[SkillConfig] = None) -> Optional[Skill]:
    """Get a skill by name."""
    return SkillRegistry.get(name, config)


def list_skills() -> List[Dict[str, str]]:
    """List all skills."""
    return SkillRegistry.list_all()


def register_skill(skill_class: Type[Skill]) -> None:
    """Register a skill."""
    SkillRegistry.register(skill_class)


def get_skills_by_category(category: str) -> List[Type[Skill]]:
    """Get skills by category."""
    return SkillRegistry.get_by_category(category)


# Auto-register skills when module is imported
def _register_all_skills():
    """Register all built-in skills."""
    from .core_skills import (
        TestabilityScoring,
        TDDLondonChicago,
        APITestingPatterns,
        AccessibilityTesting,
        ShiftLeftTesting,
        ChaosEngineeringResilience,
        VisualTestingAdvanced,
        ComplianceTesting,
    )

    SkillRegistry.register(TestabilityScoring)
    SkillRegistry.register(TDDLondonChicago)
    SkillRegistry.register(APITestingPatterns)
    SkillRegistry.register(AccessibilityTesting)
    SkillRegistry.register(ShiftLeftTesting)
    SkillRegistry.register(ChaosEngineeringResilience)
    SkillRegistry.register(VisualTestingAdvanced)
    SkillRegistry.register(ComplianceTesting)


_register_all_skills()
