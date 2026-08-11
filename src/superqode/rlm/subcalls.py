"""Bounded semantic subcalls: the primitive that makes this an RLM.

A recursive language model works by holding context as data and issuing many
small model calls over it, rather than by pushing everything through one
conversation. ``llm_query`` is that call. It is deliberately not a child agent:

* ``rlm.run`` starts a full coding session with its own kernel, repository
  access, worker lifecycle and budget.
* ``llm_query`` asks a model one question about text the caller already has. No
  tools, no session, no repository.

Two rules shape the design.

**Limits live here, not in the namespace.** The model writes the Python that
calls these, so a counter it can reach is a suggestion. The executor holds the
quota, and under an isolated profile it sits on the host where sandboxed code
cannot touch it at all. Under the host profile it is advisory, like every other
host-mode control.

**Answers stay as data.** A subcall's whole point is to keep large text out of
the root conversation, so a query returns a handle with a compact ``repr``.
Printing ``response.text`` still puts it in the transcript, which no design can
prevent, but nothing does it by accident.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from superqode.pipy.messages import UserMessage
from superqode.pipy.stream import Context, Model, StreamOptions

DEFAULT_SYSTEM_PROMPT = (
    "You answer one focused question about the text you are given. Be accurate "
    "and concise, quote evidence from the text when it matters, and say plainly "
    "when the text does not contain the answer."
)


class SubcallLimitError(RuntimeError):
    """A subcall exceeded a limit the host owns."""


@dataclass(frozen=True, slots=True)
class SubcallPolicy:
    """Host-owned limits for semantic subcalls."""

    max_calls: int = 64
    max_batch: int = 16
    max_concurrency: int = 4
    max_prompt_chars: int = 200_000
    max_response_chars: int = 200_000
    timeout: float = 120.0
    token_budget: int = 0
    models: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, config: Mapping[str, Any] | None = None) -> "SubcallPolicy":
        data = {str(key): value for key, value in dict(config or {}).items()}
        default = cls()

        def number(name: str, fallback: int | float) -> Any:
            value = data.get(f"subcall_{name}", data.get(name))
            return fallback if value is None else value

        return cls(
            max_calls=max(0, int(number("max_calls", default.max_calls))),
            max_batch=max(1, int(number("max_batch", default.max_batch))),
            max_concurrency=max(1, int(number("max_concurrency", default.max_concurrency))),
            max_prompt_chars=max(1, int(number("max_prompt_chars", default.max_prompt_chars))),
            max_response_chars=max(
                1, int(number("max_response_chars", default.max_response_chars))
            ),
            timeout=max(1.0, float(number("timeout", default.timeout))),
            token_budget=max(0, int(number("token_budget", default.token_budget))),
            models=tuple(
                str(item) for item in data.get("subcall_models") or () if str(item).strip()
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "max_calls": self.max_calls,
            "max_batch": self.max_batch,
            "max_concurrency": self.max_concurrency,
            "max_prompt_chars": self.max_prompt_chars,
            "max_response_chars": self.max_response_chars,
            "timeout": self.timeout,
            "token_budget": self.token_budget,
            "models": list(self.models),
        }


@dataclass(slots=True)
class SubcallUsage:
    """Subcall cost, kept apart from root and child-agent usage."""

    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    failures: int = 0

    def record(self, usage: Any) -> None:
        if usage is None:
            return
        cost = getattr(usage, "cost", None)
        self.input_tokens += int(getattr(usage, "input", 0) or 0)
        self.output_tokens += int(getattr(usage, "output", 0) or 0)
        self.total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        self.cost_usd += float(getattr(cost, "total", 0.0) or 0.0)

    def to_dict(self) -> dict[str, Any]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": round(self.cost_usd, 6),
            "failures": self.failures,
        }


@dataclass(slots=True)
class RLMResponse:
    """A subcall answer that stays in the environment as data.

    ``repr`` is a summary on purpose: returning one of these from a Python call
    puts a one-line description in the transcript, not the whole answer, while
    the text remains available to Python that wants to work with it.
    """

    id: str
    text: str
    model: str = ""
    prompt_chars: int = 0
    truncated: bool = False
    error: str = ""
    usage: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.error

    def size(self) -> int:
        """Portable alternative to ``len``: Monty has no user ``__len__``."""
        return len(self.text)

    def __len__(self) -> int:
        return len(self.text)

    def __str__(self) -> str:
        return self.text

    def __repr__(self) -> str:
        if self.error:
            return f"RLMResponse(id={self.id!r}, error={self.error!r})"
        preview = self.text[:80].replace("\n", " ")
        suffix = "..." if len(self.text) > 80 else ""
        flag = ", truncated=True" if self.truncated else ""
        return f"RLMResponse(id={self.id!r}, chars={len(self.text)}{flag}, preview={preview + suffix!r})"

    def lines(self) -> list[str]:
        return self.text.splitlines()

    def chunk(self, start: int = 0, size: int = 4000) -> str:
        return self.text[start : start + size]

    def search(self, pattern: str) -> list[str]:
        regex = re.compile(pattern)
        return [line for line in self.text.splitlines() if regex.search(line)]


class SubcallExecutor:
    """Runs semantic subcalls and owns their limits.

    One executor serves a session, so a batch and a loop of single queries draw
    on the same quota. That matters: a per-call limit is trivially defeated by
    calling more often.
    """

    def __init__(
        self,
        *,
        model: Model,
        stream_fn: Any,
        policy: SubcallPolicy | None = None,
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
    ) -> None:
        self.model = model
        self.stream_fn = stream_fn
        self.policy = policy or SubcallPolicy()
        self.system_prompt = system_prompt
        self.usage = SubcallUsage()
        self._counter = 0
        self._lock = asyncio.Lock()

    async def query(
        self,
        prompt: str,
        *,
        context: str = "",
        model: str | None = None,
    ) -> RLMResponse:
        [response] = await self.query_batch([prompt], contexts=[context], model=model)
        return response

    async def query_batch(
        self,
        prompts: Sequence[str],
        *,
        contexts: Sequence[str] | None = None,
        model: str | None = None,
    ) -> list[RLMResponse]:
        """Run subcalls concurrently and return them in the order given."""
        requests = [str(item) for item in prompts]
        if not requests:
            return []
        if len(requests) > self.policy.max_batch:
            raise SubcallLimitError(
                f"Batch of {len(requests)} exceeds the subcall batch limit "
                f"({self.policy.max_batch})"
            )
        supplied = list(contexts or ())
        supplied += [""] * (len(requests) - len(supplied))
        selected = self._resolve_model(model)
        start = await self._reserve(len(requests))

        semaphore = asyncio.Semaphore(self.policy.max_concurrency)

        async def run(index: int) -> RLMResponse:
            async with semaphore:
                return await self._one(start + index, requests[index], supplied[index], selected)

        # gather preserves input order, which a caller zipping prompts to
        # answers depends on.
        return list(await asyncio.gather(*(run(index) for index in range(len(requests)))))

    def snapshot(self) -> dict[str, Any]:
        return {"policy": self.policy.to_dict(), "usage": self.usage.to_dict()}

    async def _reserve(self, count: int) -> int:
        """Claim ``count`` calls against the quota and return the first number."""
        async with self._lock:
            if self.policy.max_calls and self._counter + count > self.policy.max_calls:
                raise SubcallLimitError(
                    f"Subcall limit reached: {self._counter} of {self.policy.max_calls} used, "
                    f"{count} more requested"
                )
            budget = self.policy.token_budget
            if budget and self.usage.total_tokens >= budget:
                raise SubcallLimitError(
                    f"Subcall token budget exhausted ({self.usage.total_tokens} of {budget})"
                )
            start = self._counter + 1
            self._counter += count
            # Calls means quota consumed, including failed calls. Otherwise a
            # timeout could report zero calls while still exhausting max_calls.
            self.usage.calls = self._counter
            return start

    def _resolve_model(self, model: str | None) -> Model:
        if not model:
            return self.model
        if self.policy.models and model not in self.policy.models:
            raise SubcallLimitError(
                f"Model {model!r} is not in the subcall allowlist ({', '.join(self.policy.models)})"
            )
        from superqode.pipy.ai.models import resolve_model

        provider, separator, identifier = str(model).partition("/")
        return resolve_model(
            identifier if separator else model, provider=provider if separator else ""
        )

    async def _one(self, number: int, prompt: str, context: str, model: Model) -> RLMResponse:
        identifier = f"query-{number}"
        body = f"{context}\n\n{prompt}" if context else prompt
        if len(body) > self.policy.max_prompt_chars:
            self.usage.failures += 1
            return RLMResponse(
                id=identifier,
                text="",
                model=model.id,
                prompt_chars=len(body),
                error=(
                    f"Prompt of {len(body)} characters exceeds the subcall limit "
                    f"({self.policy.max_prompt_chars}). Chunk the context and query each part."
                ),
            )
        try:
            message = await asyncio.wait_for(self._stream(body, model), timeout=self.policy.timeout)
        except TimeoutError:
            self.usage.failures += 1
            return RLMResponse(
                id=identifier,
                text="",
                model=model.id,
                prompt_chars=len(body),
                error=f"Subcall timed out after {self.policy.timeout:g}s",
            )
        except Exception as error:  # noqa: BLE001 - a failed subcall is data, not a crash
            self.usage.failures += 1
            return RLMResponse(
                id=identifier,
                text="",
                model=model.id,
                prompt_chars=len(body),
                error=str(error),
            )

        usage = getattr(message, "usage", None)
        self.usage.record(usage)
        text = str(getattr(message, "text", "") or "")
        truncated = len(text) > self.policy.max_response_chars
        return RLMResponse(
            id=identifier,
            text=text[: self.policy.max_response_chars] if truncated else text,
            model=model.id,
            prompt_chars=len(body),
            truncated=truncated,
            usage=_usage_dict(usage),
        )

    async def _stream(self, body: str, model: Model) -> Any:
        source = self.stream_fn(
            model,
            Context(system_prompt=self.system_prompt, messages=[UserMessage(body)], tools=None),
            StreamOptions(),
        )
        if asyncio.iscoroutine(source):
            source = await source
        message: Any = None
        async for event in source:
            kind = getattr(event, "type", "")
            if kind == "done":
                message = getattr(event, "message", None)
            elif kind == "error":
                failure = getattr(event, "error", None)
                raise RuntimeError(
                    str(getattr(failure, "error_message", "") or "The subcall failed")
                )
        if message is None:
            raise RuntimeError("The subcall produced no response")
        return message


def _usage_dict(usage: Any) -> dict[str, Any]:
    if usage is None:
        return {}
    cost = getattr(usage, "cost", None)
    return {
        "input_tokens": int(getattr(usage, "input", 0) or 0),
        "output_tokens": int(getattr(usage, "output", 0) or 0),
        "total_tokens": int(getattr(usage, "total_tokens", 0) or 0),
        "cost_usd": float(getattr(cost, "total", 0.0) or 0.0),
    }


__all__ = [
    "DEFAULT_SYSTEM_PROMPT",
    "RLMResponse",
    "SubcallExecutor",
    "SubcallLimitError",
    "SubcallPolicy",
    "SubcallUsage",
]
