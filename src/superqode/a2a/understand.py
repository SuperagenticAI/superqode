"""Turn a free-text request into shortlist constraints using a model.

The keyword parser in :mod:`superqode.a2a.shortlist` matches substrings, so
"we are a Rust shop with a monorepo and strict compliance rules" becomes a bag
of tokens and nothing more. A model reads that sentence properly.

The division of labour is the point. The model interprets the human and
returns constraints; it is never shown the catalogue and never asked to name a
harness. Facts about what a harness does come from the curated Hub or they are
not stated at all, so a confident invention about some agent's sandbox cannot
reach the answer.

Extraction is also allowed to fail. A model call that errors, times out, or
returns nonsense falls back to the keyword parser, because a slightly worse
shortlist is a better outcome than an error page.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from superqode.a2a.shortlist import (
    _CAPABILITY_LABELS,
    ShortlistConstraints,
    parse_constraints,
)

logger = logging.getLogger(__name__)

#: Cap on what is sent to the model. A shortlist request is a sentence or two;
#: anything longer is being used as a free text box and should not be paid for.
MAX_REQUEST_CHARS = 800

#: Cap on what is read back. The reply is a small JSON object.
MAX_OUTPUT_TOKENS = 200

_KNOWN_CAPABILITIES = sorted(_CAPABILITY_LABELS)

_SYSTEM_PROMPT = f"""You extract search constraints from a request about coding agents.

Return only a JSON object with these keys:
  "terms": up to 8 lowercase keywords describing languages, tooling, or repository shape
  "capabilities": any of {_KNOWN_CAPABILITIES}, only when the request asks for them
  "open_source_preferred": true when the request prefers open source or self-hosting
  "own_requested": true when the request asks to build a custom or in-house harness

Rules:
- Never name a product, vendor, or harness.
- Never invent capabilities that were not asked for.
- Omit a key rather than guessing.
- Return the JSON object alone, with no prose and no code fence.
"""


def _coerce(payload: dict[str, Any], fallback: ShortlistConstraints) -> ShortlistConstraints:
    """Build constraints from model output, discarding anything unexpected."""
    raw_terms = payload.get("terms")
    terms: tuple[str, ...] = ()
    if isinstance(raw_terms, list):
        terms = tuple(
            dict.fromkeys(
                str(item).strip().casefold()
                for item in raw_terms
                if isinstance(item, (str, int, float)) and str(item).strip()
            )
        )[:8]

    raw_capabilities = payload.get("capabilities")
    capabilities: tuple[str, ...] = ()
    if isinstance(raw_capabilities, list):
        # Only capabilities the Hub can actually answer survive. A model that
        # invents "gpu" or "compliance" must not produce a constraint that
        # silently matches nothing.
        capabilities = tuple(
            dict.fromkeys(
                str(item).strip().casefold()
                for item in raw_capabilities
                if str(item).strip().casefold() in _CAPABILITY_LABELS
            )
        )

    return ShortlistConstraints(
        terms=terms or fallback.terms,
        capabilities=capabilities,
        open_source_preferred=bool(payload.get("open_source_preferred", False)),
        own_requested=bool(payload.get("own_requested", False)),
    )


def _extract_json(text: str) -> dict[str, Any] | None:
    """Read the first JSON object out of a model reply."""
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", candidate).strip()
    start = candidate.find("{")
    end = candidate.rfind("}")
    if start == -1 or end <= start:
        return None
    try:
        parsed = json.loads(candidate[start : end + 1])
    except ValueError:
        return None
    return parsed if isinstance(parsed, dict) else None


def understand_request(
    request: str,
    *,
    provider: str,
    model: str,
    completion: Any | None = None,
) -> tuple[ShortlistConstraints, bool]:
    """Return constraints and whether a model produced them.

    ``completion`` is injectable so callers and tests can supply their own
    transport. It is called as ``completion(provider, model, messages, **kw)``
    and must return the reply text.
    """
    fallback = parse_constraints(request)
    trimmed = request.strip()[:MAX_REQUEST_CHARS]
    if not trimmed:
        return fallback, False

    call = completion
    if call is None:
        try:
            from superqode.providers import ProviderManager

            call = ProviderManager().chat_completion
        except Exception as error:  # pragma: no cover - import guard
            logger.debug("shortlist understanding unavailable: %s", error)
            return fallback, False

    try:
        reply = call(
            provider,
            model,
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": trimmed},
            ],
            max_tokens=MAX_OUTPUT_TOKENS,
            temperature=0,
        )
    except Exception as error:
        # Never fail the request because understanding failed. A keyword
        # shortlist is a worse answer than a model-read one and a far better
        # answer than an error.
        logger.info("shortlist understanding failed, using keyword parsing: %s", error)
        return fallback, False

    payload = _extract_json(str(reply or ""))
    if payload is None:
        logger.info("shortlist understanding returned no JSON object, using keyword parsing")
        return fallback, False

    return _coerce(payload, fallback), True
