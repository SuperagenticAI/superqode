"""PiPy provider / streaming layer (pi-ai style)."""

from .fake import FakeProvider
from .openai_compat import OpenAICompatProvider

__all__ = ["FakeProvider", "OpenAICompatProvider"]
