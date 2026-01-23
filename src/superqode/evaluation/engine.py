"""Enhanced evaluation engine integrating CodeOptiX capabilities."""

from pathlib import Path
from typing import Dict, Any, List, Optional
import logging

from superqode.evaluation import (
    CODEOPTIX_AVAILABLE,
    CodeOptiXEngine,
    create_behavior,
    BloomIdeationIntegration,
)

# Import CodeOptiX utilities if available
try:
    from codeoptix.utils.llm import create_llm_client, LLMProvider
    from codeoptix.adapters.factory import create_adapter
except ImportError:
    create_llm_client = None
    LLMProvider = None
    create_adapter = None

logger = logging.getLogger(__name__)


class EnhancedQEEngine:
    """Enhanced Quality Engineering engine with CodeOptiX integration."""

    def __init__(self):
        """Initialize the enhanced QE engine."""
        self.codeoptix_engine = None
        self.bloom_generator = None

        if CODEOPTIX_AVAILABLE and create_llm_client and create_adapter:
            try:
                # Try to create LLM client (try all available providers)
                llm_client = None
                import os

                # Provider priority: Ollama (free) -> OpenAI -> Anthropic -> Google
                provider_configs = [
                    (LLMProvider.OLLAMA, None, "llama3.1"),
                    (LLMProvider.OPENAI, os.getenv("OPENAI_API_KEY"), None),
                    (LLMProvider.ANTHROPIC, os.getenv("ANTHROPIC_API_KEY"), None),
                    (LLMProvider.GOOGLE, os.getenv("GOOGLE_API_KEY"), None),
                ]

                for provider, api_key, model in provider_configs:
                    try:
                        if provider == LLMProvider.OLLAMA or api_key:
                            llm_client = create_llm_client(provider, api_key=api_key, model=model)
                            break  # Successfully created client
                    except Exception:
                        continue  # Try next provider

                if llm_client:
                    # Create basic adapter for testing/development
                    # BasicAdapter needs llm_config to create its own llm_client
                    adapter_config = {
                        "llm_config": {
                            "provider": "ollama",  # Default to ollama
                            "model": "llama3.1",
                        }
                    }
                    adapter = create_adapter("basic", adapter_config)

                    # Initialize CodeOptiX evaluation engine
                    # Note: we're passing llm_client to EvaluationEngine, but BasicAdapter creates its own
                    # This might work if they're compatible
                    self.codeoptix_engine = CodeOptiXEngine(
                        adapter=adapter,
                        llm_client=llm_client,
                        config={"scenario_generator": {"use_bloom": True}},
                    )

                    # Initialize Bloom generator with the same llm_client
                    self.bloom_generator = BloomIdeationIntegration(llm_client=llm_client)

                    # Initialize enhanced behaviors
                    self.enhanced_behaviors = {
                        "security-vulnerabilities": self._create_security_behavior(),
                        "test-quality": self._create_test_behavior(),
                        "plan-adherence": self._create_plan_behavior(),
                    }
                else:
                    logger.warning("No LLM client available for CodeOptiX evaluation")
                    self.enhanced_behaviors = {}
            except Exception as e:
                logger.error(f"Failed to initialize CodeOptiX engine: {e}")
                self.enhanced_behaviors = {}
        else:
            self.enhanced_behaviors = {}

    def _create_security_behavior(self):
        """Create security vulnerability behavior."""
        if CODEOPTIX_AVAILABLE and create_behavior:
            return create_behavior("insecure-code")
        return None

    def _create_test_behavior(self):
        """Create test quality behavior."""
        if CODEOPTIX_AVAILABLE and create_behavior:
            return create_behavior("vacuous-tests")
        return None

    def _create_plan_behavior(self):
        """Create plan adherence behavior."""
        if CODEOPTIX_AVAILABLE and create_behavior:
            return create_behavior("plan-drift")
        return None

    def analyze_with_codeoptix(
        self, codebase_path: Path, config: Dict[str, Any], behaviors: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Perform enhanced analysis using CodeOptiX capabilities."""
        if not CODEOPTIX_AVAILABLE or not self.codeoptix_engine:
            return {"error": "CodeOptiX evaluation engine not available"}

        try:
            # Determine which behaviors to run
            if behaviors is None:
                behaviors = ["insecure-code", "vacuous-tests"]  # Use CodeOptiX behavior names

            # Map SuperQode behavior names to CodeOptiX behavior names
            behavior_mapping = {
                "security-vulnerabilities": "insecure-code",
                "test-quality": "vacuous-tests",
                "plan-adherence": "plan-drift",
            }

            # Convert to CodeOptiX behavior names
            codeoptix_behaviors = []
            for behavior in behaviors:
                codeoptix_name = behavior_mapping.get(behavior, behavior)
                codeoptix_behaviors.append(codeoptix_name)

            # Generate scenarios if requested
            scenarios = None
            if config.get("use_bloom_scenarios", False) and self.bloom_generator:
                try:
                    scenarios = self.bloom_generator.generate_scenarios(
                        behavior_name="comprehensive-quality",
                        behavior_description="Multi-dimensional code quality evaluation",
                        examples=config.get("scenario_examples", []),
                    )
                except Exception as e:
                    logger.warning(f"Bloom scenario generation failed: {e}")

            # Run CodeOptiX evaluation
            try:
                results = self.codeoptix_engine.evaluate_behaviors(
                    behavior_names=codeoptix_behaviors,
                    scenarios=scenarios,
                    context={"codebase_path": str(codebase_path)},
                )

                return {
                    "enhanced_analysis": True,
                    "behaviors_evaluated": behaviors,
                    "results": results,
                    "scenarios_used": len(scenarios) if scenarios else 0,
                }

            except Exception as e:
                error_msg = str(e)
                # Provide cleaner error messages for common issues
                if "Ollama" in error_msg and ("daemon" in error_msg or "contact" in error_msg):
                    clean_error = "LLM provider not available. Configure one of: Ollama (ollama serve), OpenAI (OPENAI_API_KEY), Anthropic (ANTHROPIC_API_KEY), or Google (GOOGLE_API_KEY)"
                else:
                    clean_error = f"CodeOptiX evaluation failed: {error_msg}"
                    logger.error(clean_error)

                return {"error": clean_error, "enhanced_analysis": False}

        except Exception as e:
            logger.error(f"Enhanced CodeOptiX analysis failed: {e}")
            return {"error": f"Enhanced analysis failed: {str(e)}", "enhanced_analysis": False}

    def get_available_behaviors(self) -> Dict[str, str]:
        """Get all available behaviors (basic + enhanced)."""
        behaviors = {
            # Basic behaviors (always available)
            "syntax-errors": "Basic syntax validation",
            "code-style": "PEP8 and style checking",
            "imports": "Import organization and dependencies",
            "documentation": "Documentation completeness",
        }

        # Add enhanced behaviors if available
        if CODEOPTIX_AVAILABLE:
            behaviors.update(
                {
                    "security-vulnerabilities": "Advanced security analysis (CodeOptiX)",
                    "test-quality": "Intelligent test evaluation (CodeOptiX)",
                    "plan-adherence": "Requirements alignment checking (CodeOptiX)",
                }
            )
        else:
            behaviors["codeoptix-integration"] = (
                "CodeOptiX integration is available (codeoptix dependency required)."
            )

        return behaviors

    def is_behavior_available(self, behavior_name: str) -> bool:
        """Check if a specific behavior is available."""
        if behavior_name in self.enhanced_behaviors:
            return self.enhanced_behaviors[behavior_name] is not None
        return behavior_name in ["syntax-errors", "code-style", "imports", "documentation"]
