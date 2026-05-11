"""
A2A Skill to SuperQode Role Mapping.

Maps A2A agent skills to SuperQode QE/Dev/DevOps roles for seamless integration.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# Skill keywords that map to SuperQode roles
ROLE_SKILL_MAPPING = {
    "dev": {
        "keywords": ["development", "coding", "programming", "write code", "implement"],
        "role": "dev",
        "description": "Software development and implementation",
    },
    "qe_unit": {
        "keywords": ["unit test", "unit testing", "test", "junit", "pytest", "unittest"],
        "role": "qe_unit",
        "description": "Unit testing and code coverage",
    },
    "qe_integration": {
        "keywords": ["integration test", "api test", "rest test", "e2e"],
        "role": "qe_integration",
        "description": "Integration and API testing",
    },
    "qe_security": {
        "keywords": ["security", "vulnerability", "scan", "penetration", "owasp"],
        "role": "qe_security",
        "description": "Security testing and vulnerability detection",
    },
    "qe_accessibility": {
        "keywords": ["accessibility", "a11y", "wcag", "screen reader"],
        "role": "qe_accessibility",
        "description": "Accessibility compliance testing",
    },
    "qe_performance": {
        "keywords": ["performance", "load test", "stress", "benchmark", "profiling"],
        "role": "qe_performance",
        "description": "Performance and load testing",
    },
    "code_review": {
        "keywords": ["review", "review code", "inspect", "audit"],
        "role": "code_review",
        "description": "Code review and quality assessment",
    },
    "debug": {
        "keywords": ["debug", "fix", "troubleshoot", "issue", "problem"],
        "role": "debug",
        "description": "Debugging and issue resolution",
    },
    "devops": {
        "keywords": ["deploy", "ci/cd", "pipeline", "infrastructure", "docker", "k8s"],
        "role": "devops",
        "description": "DevOps and deployment automation",
    },
    "docs": {
        "keywords": ["documentation", "docs", "readme", "spec"],
        "role": "docs",
        "description": "Documentation generation",
    },
}


@dataclass
class RoleMapping:
    """Mapping from A2A skill to SuperQode role."""

    skill_keyword: str
    superqode_role: str
    description: str
    confidence: float  # 0.0 - 1.0


class SkillMapper:
    """Map A2A agent skills to SuperQode roles.

    Usage:
        mapper = SkillMapper()

        # Map skills from agent card
        roles = mapper.map_skills(agent_card.skills)

        # Get role for specific skill
        role = mapper.get_role_for_skill("security scanning")
    """

    def __init__(self):
        self._mappings = ROLE_SKILL_MAPPING

    def map_skills(self, skills: List[Dict[str, str]]) -> List[RoleMapping]:
        """Map a list of A2A skills to SuperQode roles.

        Args:
            skills: List of {"id": "...", "name": "...", "description": "..."}

        Returns:
            List of RoleMapping with matched roles
        """
        mappings = []

        for skill in skills:
            skill_name = skill.get("name", "").lower()
            skill_desc = skill.get("description", "").lower()
            skill_id = skill.get("id", "").lower()

            # Check each role mapping
            best_match = None
            best_confidence = 0.0

            for role_key, mapping in self._mappings.items():
                confidence = self._calculate_confidence(
                    skill_name, skill_desc, skill_id, mapping["keywords"]
                )

                if confidence > best_confidence:
                    best_confidence = confidence
                    best_match = RoleMapping(
                        skill_keyword=skill.get("name", ""),
                        superqode_role=mapping["role"],
                        description=mapping["description"],
                        confidence=confidence,
                    )

            if best_match and best_match.confidence > 0.3:
                mappings.append(best_match)

        return mappings

    def _calculate_confidence(
        self,
        skill_name: str,
        skill_desc: str,
        skill_id: str,
        keywords: List[str],
    ) -> float:
        """Calculate confidence that skill matches role."""
        text = f"{skill_name} {skill_desc} {skill_id}"

        matches = sum(1 for kw in keywords if kw.lower() in text)
        return min(matches / len(keywords), 1.0)

    def get_role_for_skill(self, skill_text: str) -> Optional[str]:
        """Get SuperQode role for a skill description.

        Args:
            skill_text: Skill name or description

        Returns:
            SuperQode role name or None
        """
        skill_lower = skill_text.lower()

        best_role = None
        best_confidence = 0.0

        for role_key, mapping in self._mappings.items():
            confidence = self._calculate_confidence(
                skill_lower, skill_lower, "", mapping["keywords"]
            )

            if confidence > best_confidence:
                best_confidence = confidence
                best_role = mapping["role"]

        return best_role if best_confidence > 0.3 else None

    def get_all_mappings(self) -> Dict[str, Dict[str, Any]]:
        """Get all available role mappings."""
        return self._mappings

    def suggest_agents_for_role(self, role: str) -> List[str]:
        """Suggest keywords to search for agents that can fulfill a role.

        Args:
            role: SuperQode role (e.g., "qe_security")

        Returns:
            List of search keywords
        """
        mapping = self._mappings.get(role)
        if not mapping:
            return []

        return mapping["keywords"]


# Singleton instance
_skill_mapper: Optional[SkillMapper] = None


def get_skill_mapper() -> SkillMapper:
    """Get the skill mapper singleton."""
    global _skill_mapper
    if _skill_mapper is None:
        _skill_mapper = SkillMapper()
    return _skill_mapper
