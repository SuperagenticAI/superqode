"""CodeGem: a six-tool coding harness for Gemini and Gemma only."""

from .profiles import CodeGemProfile, resolve_profile

__all__ = ["CodeGemProfile", "TOOL_NAMES", "create_tools", "resolve_profile"]


def __getattr__(name):
    # Indexing needs only the retrieval module; don't import the coding tools,
    # process helpers, and session stack when the embedding CLI starts.
    if name in {"TOOL_NAMES", "create_tools"}:
        from . import tools

        return getattr(tools, name)
    raise AttributeError(name)
