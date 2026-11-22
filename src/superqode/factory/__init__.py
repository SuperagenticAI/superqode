"""Factories-as-code contracts over the existing SuperQode execution engine.

Loading, resolution and compilation never execute harnesses or acceptance checks.
"""

from .definition import FactoryDefinition, load_factory
from .snapshot import FactorySnapshot, resolve_factory
from .compiler import CompiledFactory, compile_factory, materialize_snapshot
from .runtime import admit_factory, factory_store, load_compiled_plan, validate_factory_order

__all__ = [
    "FactoryDefinition",
    "FactorySnapshot",
    "CompiledFactory",
    "load_factory",
    "resolve_factory",
    "compile_factory",
    "materialize_snapshot",
    "admit_factory",
    "factory_store",
    "load_compiled_plan",
    "validate_factory_order",
]
