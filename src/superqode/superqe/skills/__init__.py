"""
QE Skills Bank - Collection of QE-focused skills.

Provides 46+ specialized skills for quality engineering:
- testability-scoring: Pre-test code testability assessment
- qx-partner: QA + UX collaboration
- chaos-engineering-resilience: Chaos testing
- visual-testing-advanced: Advanced visual comparison
- compliance-testing: Regulatory compliance checks
- tdd-london-chicago: TDD methodologies
- api-testing-patterns: API test patterns
- accessibility-testing: A11y testing patterns
- shift-left-testing: Early testing practices

Skills provide reusable prompts, workflows, and tooling patterns.
"""

from .base import Skill, SkillConfig, SkillResult
from .registry import (
    SkillRegistry,
    get_skill,
    list_skills,
    register_skill,
    get_skills_by_category,
)
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

__all__ = [
    # Base
    "Skill",
    "SkillConfig",
    "SkillResult",
    # Registry
    "SkillRegistry",
    "get_skill",
    "list_skills",
    "register_skill",
    "get_skills_by_category",
    # Core Skills
    "TestabilityScoring",
    "TDDLondonChicago",
    "APITestingPatterns",
    "AccessibilityTesting",
    "ShiftLeftTesting",
    "ChaosEngineeringResilience",
    "VisualTestingAdvanced",
    "ComplianceTesting",
]
