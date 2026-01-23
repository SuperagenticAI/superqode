"""Bloom scenario generation integration for enhanced testing."""

from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

from superqode.evaluation import CODEOPTIX_AVAILABLE, BloomIdeationIntegration

logger = logging.getLogger(__name__)


class EnhancedScenarioGenerator:
    """Enhanced scenario generator using Bloom ideation."""

    def __init__(self):
        """Initialize the scenario generator."""
        self.bloom_generator = None

        if CODEOPTIX_AVAILABLE:
            try:
                self.bloom_generator = BloomIdeationIntegration()
            except Exception as e:
                logger.warning(f"Bloom integration failed: {e}")

    def generate_bloom_scenarios(
        self,
        behavior_name: str,
        behavior_description: str,
        codebase_path: Path,
        examples: Optional[List[Dict[str, Any]]] = None,
    ) -> List[Dict[str, Any]]:
        """Generate intelligent test scenarios using Bloom."""
        if not self.bloom_generator:
            logger.info("Bloom generator not available, using basic scenarios")
            return self._generate_basic_scenarios(behavior_name, codebase_path)

        try:
            scenarios = self.bloom_generator.generate_scenarios(
                behavior_name=behavior_name,
                behavior_description=behavior_description,
                examples=examples or [],
            )

            logger.info(f"Generated {len(scenarios)} Bloom scenarios for {behavior_name}")
            return scenarios

        except Exception as e:
            logger.error(f"Bloom scenario generation failed: {e}")
            return self._generate_basic_scenarios(behavior_name, codebase_path)

    def _generate_basic_scenarios(
        self, behavior_name: str, codebase_path: Path
    ) -> List[Dict[str, Any]]:
        """Generate basic fallback scenarios."""
        # Basic scenarios as fallback when Bloom is not available
        base_scenarios = [
            {
                "name": f"basic-{behavior_name}-scenario-1",
                "description": f"Basic scenario for {behavior_name}",
                "complexity": "low",
                "tags": ["basic", behavior_name],
            },
            {
                "name": f"basic-{behavior_name}-scenario-2",
                "description": f"Alternative scenario for {behavior_name}",
                "complexity": "medium",
                "tags": ["basic", "alternative", behavior_name],
            },
        ]

        logger.info(f"Generated {len(base_scenarios)} basic scenarios as fallback")
        return base_scenarios

    def is_bloom_available(self) -> bool:
        """Check if Bloom scenario generation is available."""
        return self.bloom_generator is not None


# Global scenario generator instance
scenario_generator = EnhancedScenarioGenerator()


def generate_enhanced_scenarios(
    behavior_name: str,
    behavior_description: str,
    codebase_path: Path,
    examples: Optional[List[Dict[str, Any]]] = None,
    use_bloom: bool = True,
) -> List[Dict[str, Any]]:
    """Generate enhanced scenarios with optional Bloom integration."""
    if use_bloom and scenario_generator.is_bloom_available():
        return scenario_generator.generate_bloom_scenarios(
            behavior_name, behavior_description, codebase_path, examples
        )
    else:
        return scenario_generator._generate_basic_scenarios(behavior_name, codebase_path)
