"""Agent adapters for CodeOptiX integration."""

from typing import Dict, Any, Optional
import logging

from superqode.evaluation import CODEOPTIX_AVAILABLE

logger = logging.getLogger(__name__)


class SuperQodeCodeOptiXAdapter:
    """Adapter to connect SuperQode agents with CodeOptiX evaluation."""

    def __init__(self):
        """Initialize the adapter."""
        self.codeoptix_adapter = None

        if CODEOPTIX_AVAILABLE:
            try:
                from codeoptix.adapters.factory import create_adapter

                self.create_adapter = create_adapter
                self.codeoptix_adapter = create_adapter("basic")  # Default adapter
            except Exception as e:
                logger.warning(f"CodeOptiX adapter creation failed: {e}")

    def create_agent_adapter(self, agent_config: Dict[str, Any]):
        """Create a CodeOptiX adapter for a specific agent configuration."""
        if not self.codeoptix_adapter:
            return None

        try:
            agent_type = agent_config.get("type", "basic")

            # Map SuperQode agent types to CodeOptiX adapter types
            adapter_mapping = {
                "claude-code": "claude-code",
                "codex": "codex",
                "gemini-cli": "gemini-cli",
                "basic": "basic",
            }

            codeoptix_type = adapter_mapping.get(agent_type, "basic")

            adapter = self.create_adapter(codeoptix_type, agent_config)
            logger.info(f"Created CodeOptiX adapter for {agent_type}")
            return adapter

        except Exception as e:
            logger.error(f"Failed to create agent adapter: {e}")
            return None

    def adapt_agent_output(self, agent_output: Any) -> Optional[Dict[str, Any]]:
        """Adapt SuperQode agent output to CodeOptiX format."""
        if not agent_output:
            return None

        try:
            # Convert SuperQode output format to CodeOptiX expected format
            adapted = {
                "content": getattr(agent_output, "content", str(agent_output)),
                "metadata": getattr(agent_output, "metadata", {}),
                "success": getattr(agent_output, "success", True),
                "timestamp": getattr(agent_output, "timestamp", None),
            }
            return adapted

        except Exception as e:
            logger.error(f"Agent output adaptation failed: {e}")
            return None

    def is_adapter_available(self) -> bool:
        """Check if CodeOptiX adapter is available."""
        return self.codeoptix_adapter is not None


# Global adapter instance
adapter_manager = SuperQodeCodeOptiXAdapter()


def get_codeoptix_adapter(agent_config: Dict[str, Any]):
    """Get a CodeOptiX adapter for the given agent configuration."""
    return adapter_manager.create_agent_adapter(agent_config)


def adapt_agent_output_for_evaluation(agent_output: Any) -> Optional[Dict[str, Any]]:
    """Adapt agent output for CodeOptiX evaluation."""
    return adapter_manager.adapt_agent_output(agent_output)


def is_codeoptix_integration_available() -> bool:
    """Check if CodeOptiX integration is available."""
    return adapter_manager.is_adapter_available()
