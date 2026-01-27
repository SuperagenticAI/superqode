import os
import sys
import inspect
from types import ModuleType

# --- Frozen Environment Configuration ---
# These must be set before any heavy imports
os.environ["LOGFIRE_DISABLE"] = "1"
os.environ["LOGFIRE_IGNORE_NO_CONFIG"] = "1"
os.environ["PYDANTIC_DISABLE_ERRORS"] = "1"
os.environ["PYDANTIC_SKIP_VALIDATING_CORE_SCHEMAS"] = "1"
os.environ["PYDANTIC_DISABLE_VALIDATION_ON_REPR"] = "1"

# LiteLLM environment flags
os.environ["LITELLM_LOG_SILENT"] = "True"
os.environ["LITELLM_LOCAL_RESOURCES"] = "True"
os.environ["LITELLM_DISABLE_TIKTOKEN"] = "True"

# --- Tiktoken Ghost Patch ---
# This prevents "ValueError: Unknown encoding cl100k_base" in frozen binaries


class GhostEncoding:
    def __init__(self, name="ghost"):
        self.name = name

    def encode(self, text, *args, **kwargs):
        return [0] * (len(text) // 3)  # Dummy tokens

    def decode(self, tokens, *args, **kwargs):
        return ""

    def encode_batch(self, texts, *args, **kwargs):
        return [[0]] * len(texts)

    def encode_ordinary(self, text, *args, **kwargs):
        return [0] * (len(text) // 3)


def apply_tiktoken_ghost_patch():
    try:
        import tiktoken

        tiktoken.get_encoding = lambda name: GhostEncoding(name)
        tiktoken.encoding_for_model = lambda model: GhostEncoding(model)
        # Patch the registry too if it exists
        if hasattr(tiktoken, "registry"):
            tiktoken.registry.get_encoding = lambda name: GhostEncoding(name)
    except Exception:
        pass


# --- LiteLLM Token Counter Patch ---
def apply_litellm_patch():
    try:
        import litellm

        # Force disable token counting at the library level
        litellm.disable_token_counting = True
        litellm.set_verbose = False
        litellm.suppress_warnings = True

        # Patch the internal encoding getter
        if hasattr(litellm, "utils"):
            litellm.utils.get_encoding = lambda model: GhostEncoding(model)
            litellm.utils.token_counter = lambda *args, **kwargs: 0
    except Exception:
        pass


# --- Pydantic/Inspect Patch ---
def apply_inspect_patch():
    original_getsource = inspect.getsource
    original_findsource = inspect.findsource

    def patched_getsource(obj):
        try:
            return original_getsource(obj)
        except (OSError, TypeError, IOError):
            return ""

    def patched_findsource(obj):
        try:
            return original_findsource(obj)
        except (OSError, TypeError, IOError):
            return ([""], 0)

    inspect.getsource = patched_getsource
    inspect.findsource = patched_findsource


# --- Execute Patches ---
apply_inspect_patch()
apply_tiktoken_ghost_patch()
apply_litellm_patch()
