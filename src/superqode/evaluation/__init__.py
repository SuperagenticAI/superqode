"""Optional evaluation integration APIs."""

try:
    from codeoptix.evaluation import EvaluationEngine as CodeOptiXEngine
    from codeoptix.behaviors import create_behavior
    from codeoptix.evaluation.bloom_integration import BloomIdeationIntegration
    from codeoptix.evolution import EvolutionEngine as CodeOptiXEvolutionEngine

    CODEOPTIX_AVAILABLE = True
except ImportError:
    CODEOPTIX_AVAILABLE = False
    CodeOptiXEngine = None
    create_behavior = None
    BloomIdeationIntegration = None
    CodeOptiXEvolutionEngine = None

__all__ = [
    "CODEOPTIX_AVAILABLE",
    "CodeOptiXEngine",
    "create_behavior",
    "BloomIdeationIntegration",
    "CodeOptiXEvolutionEngine",
]
