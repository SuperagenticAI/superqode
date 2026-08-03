"""PiPy provider layer.

Everything here satisfies :class:`~superqode.pipy.stream.StreamFn`:

- :class:`FakeStream` replays a script, for tests and offline runs
- :class:`GatewayStream` bridges SuperQode's LiteLLM gateway, which is what
  makes PiPy work on every provider SuperQode already supports

Native Anthropic and OpenAI-compatible streams land behind the same contract.
"""

from .fake import FakeStream, text_response, tool_response
from .gateway import GatewayStream, create_gateway_stream, map_stop_reason
from .models import resolve_model
from .transform import NO_RESULT_TEXT, transform_messages

__all__ = [
    "NO_RESULT_TEXT",
    "FakeStream",
    "GatewayStream",
    "create_gateway_stream",
    "map_stop_reason",
    "resolve_model",
    "text_response",
    "tool_response",
    "transform_messages",
]
