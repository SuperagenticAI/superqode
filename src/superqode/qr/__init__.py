"""
Quality Report (QR) Module.

Generates research-grade QA reports that document:
- Investigation objective and scope
- Attack and exploration methodology
- Reproduction steps and evidence
- Root cause and failure analysis
- Suggested fixes and alternatives
- Benchmark and validation results
- Production-readiness assessment
"""

from .generator import QRGenerator, QRSection, QRVerdict
from .templates import QRTemplate, get_template

__all__ = [
    "QRGenerator",
    "QRSection",
    "QRVerdict",
    "QRTemplate",
    "get_template",
]
