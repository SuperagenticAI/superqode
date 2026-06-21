"""Cross-runtime parallel compare.

Run the same prompt across several provider/model targets concurrently and
collect their answers. This is read-only (a plain chat completion per target,
no tools, no file mutation) so it is safe to fan out, and it leans on
SuperQode's ability to mix providers/runtimes in a single comparison.

The orchestrator is runtime-agnostic: it takes an async ``runner`` callable so
it is fully unit-testable, with :func:`default_compare_runner` providing the
real LiteLLM-backed implementation.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from ..providers.model_specs import split_provider_model_ref


@dataclass(frozen=True)
class CompareSpec:
    """A single provider/model target to compare."""

    provider: str
    model: str

    @property
    def label(self) -> str:
        return f"{self.provider}/{self.model}" if self.provider else self.model


@dataclass
class CompareResult:
    """The outcome of one target in a comparison."""

    spec: CompareSpec
    text: str = ""
    error: str = ""
    elapsed: float = 0.0

    @property
    def ok(self) -> bool:
        return not self.error


Runner = Callable[[CompareSpec, str], Awaitable[str]]


def parse_compare_specs(tokens: list[str], default_provider: str = "") -> list[CompareSpec]:
    """Parse ``:compare`` tokens into specs.

    A token may be ``provider/model`` or a bare ``model`` (which uses
    ``default_provider``). Duplicates and blanks are dropped, order preserved.
    """
    specs: list[CompareSpec] = []
    seen: set[tuple[str, str]] = set()
    for token in tokens:
        token = token.strip()
        if not token:
            continue
        parsed = split_provider_model_ref(token, default_provider=default_provider)
        provider, model = parsed.provider, parsed.model
        if not model or (provider, model) in seen:
            continue
        seen.add((provider, model))
        specs.append(CompareSpec(provider=provider, model=model))
    return specs


async def run_parallel_compare(
    prompt: str,
    specs: list[CompareSpec],
    runner: Runner,
    *,
    timeout: float = 120.0,
) -> list[CompareResult]:
    """Run *prompt* against every spec concurrently, preserving input order.

    Each target's failure or timeout is captured in its own ``CompareResult``
    rather than failing the whole batch.
    """

    async def _one(spec: CompareSpec) -> CompareResult:
        started = time.monotonic()
        try:
            text = await asyncio.wait_for(runner(spec, prompt), timeout=timeout)
            return CompareResult(
                spec=spec, text=str(text).strip(), elapsed=time.monotonic() - started
            )
        except asyncio.TimeoutError:
            return CompareResult(
                spec=spec,
                error=f"timed out after {timeout:.0f}s",
                elapsed=time.monotonic() - started,
            )
        except Exception as exc:  # capture per-target so siblings still complete
            return CompareResult(spec=spec, error=str(exc), elapsed=time.monotonic() - started)

    if not specs:
        return []
    return list(await asyncio.gather(*(_one(spec) for spec in specs)))


async def default_compare_runner(spec: CompareSpec, prompt: str) -> str:
    """Real runner: a single read-only chat completion via the provider manager."""
    from superqode.providers.manager import ProviderManager

    manager = ProviderManager()
    messages = [
        {
            "role": "system",
            "content": "You are a coding assistant. Answer the user concisely and correctly.",
        },
        {"role": "user", "content": prompt},
    ]
    # ProviderManager.chat_completion is synchronous (LiteLLM); run off the loop.
    return await asyncio.to_thread(manager.chat_completion, spec.provider, spec.model, messages)
