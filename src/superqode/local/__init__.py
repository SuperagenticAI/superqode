"""Local stack intelligence: hardware detection, engine and model inventory,
recommendations, and benchmarking for local coding agents.

The flagship entry point is :func:`superqode.local.doctor.run_doctor`, which
turns "I have this machine" into a ranked engine + model recommendation and
a tuned harness. The recommendation matrix ships as updatable data
(``data/stack_matrix.yaml``) so it can track the model landscape without
code changes.
"""

from .hardware import HardwareProfile, detect_hardware
from .engines import EngineStatus, detect_engines
from .inventory import LocalModel, inventory_models
from .matrix import StackRecommendation, load_matrix, recommend
from .doctor import DoctorReport, run_doctor
from .guardrails import LocalGuardrails, build_guardrails, render_guardrails
from .optimize import OptimizationReport, RoleRecommendation, recommend_roles
from .repo import RepoProfile, analyze_repository, render_repo_profile

__all__ = [
    "DoctorReport",
    "EngineStatus",
    "HardwareProfile",
    "LocalModel",
    "LocalGuardrails",
    "OptimizationReport",
    "RoleRecommendation",
    "RepoProfile",
    "StackRecommendation",
    "analyze_repository",
    "build_guardrails",
    "detect_engines",
    "detect_hardware",
    "inventory_models",
    "load_matrix",
    "recommend",
    "recommend_roles",
    "render_guardrails",
    "render_repo_profile",
    "run_doctor",
]
