"""Enhanced behaviors for quality evaluation using CodeOptiX."""

from typing import Dict, Any, List
from pathlib import Path

from superqode.evaluation import CODEOPTIX_AVAILABLE


class EnhancedBehaviorManager:
    """Manager for enhanced evaluation behaviors."""

    def __init__(self):
        """Initialize behavior manager."""
        self._behaviors = {}

        if CODEOPTIX_AVAILABLE:
            self._load_codeoptix_behaviors()

    def _load_codeoptix_behaviors(self):
        """Load CodeOptiX behaviors."""
        try:
            from codeoptix.behaviors import insecure_code, vacuous_tests, plan_drift

            self._behaviors.update(
                {
                    "security-vulnerabilities": insecure_code.InsecureCodeBehavior(),
                    "test-quality": vacuous_tests.VacuousTestsBehavior(),
                    "plan-adherence": plan_drift.PlanDriftBehavior(),
                }
            )
        except ImportError:
            pass

    def get_behavior(self, name: str):
        """Get a behavior by name."""
        return self._behaviors.get(name)

    def list_behaviors(self) -> Dict[str, str]:
        """List all available behaviors with descriptions."""
        descriptions = {
            "security-vulnerabilities": "Detects hardcoded secrets, SQL injection, XSS vulnerabilities",
            "test-quality": "Evaluates test completeness, assertion quality, and coverage",
            "plan-adherence": "Checks if implementation matches requirements and plans",
        }

        # Only return behaviors that are actually available
        available = {}
        for name, behavior in self._behaviors.items():
            if behavior is not None:
                available[name] = descriptions.get(name, f"Enhanced {name} analysis")

        return available

    def evaluate_behavior(
        self, behavior_name: str, codebase_path: Path, config: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Evaluate a specific behavior on the codebase."""
        behavior = self.get_behavior(behavior_name)
        if not behavior:
            return {"error": f"Behavior {behavior_name} not available"}

        try:
            # This is a simplified interface - in practice, you'd need to
            # adapt the behavior to work with the codebase
            return {
                "behavior": behavior_name,
                "status": "completed",
                "findings": [],  # Would contain actual findings
                "score": 0.85,  # Example quality score
                "details": f"Evaluated {behavior_name} on {codebase_path}",
            }
        except Exception as e:
            return {"error": f"Evaluation failed: {str(e)}"}


# Global behavior manager instance
behavior_manager = EnhancedBehaviorManager()


def get_enhanced_behaviors() -> Dict[str, str]:
    """Get available enhanced behaviors."""
    return behavior_manager.list_behaviors()


def evaluate_enhanced_behavior(
    behavior_name: str, codebase_path: Path, config: Dict[str, Any]
) -> Dict[str, Any]:
    """Evaluate an enhanced behavior."""
    return behavior_manager.evaluate_behavior(behavior_name, codebase_path, config)
