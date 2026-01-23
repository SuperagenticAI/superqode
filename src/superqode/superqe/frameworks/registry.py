"""
Framework Registry - Central registry for test frameworks.

Provides:
- Framework registration
- Auto-detection
- Framework lookup
"""

from pathlib import Path
from typing import Dict, List, Optional, Type

from .base import TestFramework, FrameworkConfig


class FrameworkRegistry:
    """Registry for test frameworks."""

    _frameworks: Dict[str, Type[TestFramework]] = {}

    @classmethod
    def register(cls, framework_class: Type[TestFramework]) -> None:
        """Register a framework."""
        cls._frameworks[framework_class.NAME] = framework_class

    @classmethod
    def get(cls, name: str, config: Optional[FrameworkConfig] = None) -> Optional[TestFramework]:
        """Get a framework by name."""
        framework_class = cls._frameworks.get(name)
        if framework_class:
            return framework_class(config)
        return None

    @classmethod
    def detect(
        cls, project_root: Path, config: Optional[FrameworkConfig] = None
    ) -> List[TestFramework]:
        """Detect frameworks in a project."""
        detected = []
        for framework_class in cls._frameworks.values():
            if framework_class.detect(project_root):
                cfg = config or FrameworkConfig(project_root=project_root)
                detected.append(framework_class(cfg))
        return detected

    @classmethod
    def list_all(cls) -> List[Dict[str, str]]:
        """List all registered frameworks."""
        return [
            {
                "name": fw.NAME,
                "display_name": fw.DISPLAY_NAME,
                "language": fw.LANGUAGE,
            }
            for fw in cls._frameworks.values()
        ]


def get_framework(name: str, config: Optional[FrameworkConfig] = None) -> Optional[TestFramework]:
    """Get a framework by name."""
    return FrameworkRegistry.get(name, config)


def detect_framework(
    project_root: Path, config: Optional[FrameworkConfig] = None
) -> List[TestFramework]:
    """Detect frameworks in a project."""
    return FrameworkRegistry.detect(project_root, config)


def list_frameworks() -> List[Dict[str, str]]:
    """List all available frameworks."""
    return FrameworkRegistry.list_all()


# Auto-register frameworks when module is imported
def _register_all_frameworks():
    """Register all built-in frameworks."""
    from .python import PytestFramework, UnittestFramework
    from .javascript import JestFramework, MochaFramework, VitestFramework
    from .e2e import CypressFramework, PlaywrightFramework

    FrameworkRegistry.register(PytestFramework)
    FrameworkRegistry.register(UnittestFramework)
    FrameworkRegistry.register(JestFramework)
    FrameworkRegistry.register(MochaFramework)
    FrameworkRegistry.register(VitestFramework)
    FrameworkRegistry.register(CypressFramework)
    FrameworkRegistry.register(PlaywrightFramework)


_register_all_frameworks()
