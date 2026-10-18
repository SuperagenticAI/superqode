"""Opt-in, process-scoped reservations for small real Gemini experiments.

Only text/function-call, non-streaming requests are supported. Reserve the
model's complete published token limits before each HTTP attempt, then settle
using response usage at explicitly verified prices. An uncertain attempt keeps
its reservation and closes admission. This is an API-cost bound under the
declared model limits/prices, not an authoritative Google billing receipt.
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from contextvars import ContextVar
from decimal import Decimal
from pathlib import Path

import httpx

_active = ContextVar("codegem_request_budget", default=None)


def active_request_budget():
    return _active.get()


class RequestBudgetExceeded(RuntimeError):
    pass


class GeminiRequestBudget:
    def __init__(
        self,
        *,
        limit_usd,
        model,
        input_per_million,
        output_per_million,
        max_input_tokens,
        max_output_tokens,
        path: Path,
        api_key=None,
    ):
        self.limit = Decimal(str(limit_usd))
        self.input_rate = Decimal(str(input_per_million)) / 1_000_000
        self.output_rate = Decimal(str(output_per_million)) / 1_000_000
        if any(
            not value.is_finite() or value <= 0
            for value in (self.limit, self.input_rate, self.output_rate)
        ):
            raise ValueError("Budget and verified prices must be finite positive numbers")
        if any(
            type(value) is not int or value <= 0 for value in (max_input_tokens, max_output_tokens)
        ):
            raise ValueError("Published model token limits must be positive integers")
        self.model = model
        self.max_input = max_input_tokens
        self.max_output = max_output_tokens
        # Allow a full output limit for candidates AND a full limit for thoughts.
        self.reservation = self.max_input * self.input_rate + 2 * self.max_output * self.output_rate
        self.path = Path(path)
        if self.path.exists():
            raise ValueError("A budget ledger already exists; never reset it implicitly")
        self.api_key = api_key
        self.observed = Decimal(0)
        self.pending = Decimal(0)
        self.uncertain = Decimal(0)
        self.closed_reason = None
        self.attempts = []
        self._save()

    @contextmanager
    def scope(self):
        token = _active.set(self)
        try:
            yield self
        finally:
            _active.reset(token)

    def snapshot(self):
        return {
            "model": self.model,
            "limit_usd": float(self.limit),
            "input_per_million": float(self.input_rate * 1_000_000),
            "output_per_million": float(self.output_rate * 1_000_000),
            "max_input_tokens": self.max_input,
            "max_output_tokens": self.max_output,
            "reservation_per_request_usd": float(self.reservation),
            "observed_usd": float(self.observed),
            "pending_reserved_usd": float(self.pending),
            "uncertain_reserved_usd": float(self.uncertain),
            "accounted_upper_bound_usd": float(self.observed + self.pending + self.uncertain),
            "closed_reason": self.closed_reason,
            "attempts": self.attempts,
        }

    def _save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_name(self.path.name + ".tmp")
        temporary.write_text(json.dumps(self.snapshot(), indent=2, allow_nan=False) + "\n")
        temporary.replace(self.path)

    def _admit(self, request):
        if self.closed_reason:
            raise RequestBudgetExceeded("Gemini budget admission is closed: " + self.closed_reason)
        expected = f"/v1beta/models/{self.model}:generateContent"
        if (
            request.method != "POST"
            or request.url.host != "generativelanguage.googleapis.com"
            or request.url.scheme != "https"
            or request.url.path != expected
            or request.url.query
        ):
            raise RequestBudgetExceeded(
                "Budget permits only the selected official non-streaming Gemini endpoint"
            )
        body = json.loads(request.content)
        if set(body) - {"contents", "systemInstruction", "generationConfig", "tools", "toolConfig"}:
            raise RequestBudgetExceeded("Unsupported paid request features")
        generation = body.get("generationConfig", {})
        if (
            generation.get("candidateCount", 1) != 1
            or type(generation.get("maxOutputTokens")) is not int
            or not 1 <= generation["maxOutputTokens"] <= self.max_output
        ):
            raise RequestBudgetExceeded(
                "A single candidate and explicit bounded output are required"
            )
        for tool in body.get("tools", []):
            if set(tool) != {"functionDeclarations"}:
                raise RequestBudgetExceeded(
                    "Grounding and other separately priced API tools are disabled"
                )

        # Reject media even if it is nested inside a tool response.
        def has_media(value):
            if isinstance(value, dict):
                return any(
                    key in {"inlineData", "fileData", "inline_data", "file_data"} or has_media(item)
                    for key, item in value.items()
                )
            return isinstance(value, list) and any(has_media(item) for item in value)

        if has_media(body):
            raise RequestBudgetExceeded("This price reservation supports text-only requests")
        if self.observed + self.pending + self.uncertain + self.reservation > self.limit:
            self.closed_reason = "Insufficient remaining budget for the next worst-case request"
            self._save()
            raise RequestBudgetExceeded(self.closed_reason)
        row = {
            "attempt": len(self.attempts) + 1,
            "state": "reserved",
            "reserved_usd": float(self.reservation),
        }
        self.attempts.append(row)
        self.pending += self.reservation
        self._save()  # Durable reservation precedes network activity.
        return row

    def _unknown(self, row, reason):
        if row["state"] != "reserved":
            return
        row.update(state="uncertain", reason=reason)
        self.pending -= self.reservation
        self.uncertain += self.reservation
        self.closed_reason = reason
        self._save()

    def _settle(self, row, response):
        if response.status_code != 200:
            raise ValueError(f"HTTP {response.status_code}; usage uncertain")
        usage = response.json().get("usageMetadata")
        if not isinstance(usage, dict):
            raise ValueError("Missing Gemini usage metadata")
        values = [
            usage.get("promptTokenCount"),
            usage.get("candidatesTokenCount"),
            usage.get("thoughtsTokenCount", 0),
        ]
        if any(type(value) is not int or value < 0 for value in values):
            raise ValueError("Missing or invalid Gemini token measurements")
        inputs, outputs, thoughts = values
        if inputs > self.max_input or outputs > self.max_output or thoughts > self.max_output:
            raise ValueError("Returned usage exceeds the declared model limits")
        # Charge cached tokens at the full input rate for a conservative estimate.
        cost = inputs * self.input_rate + (outputs + thoughts) * self.output_rate
        if cost > self.reservation:
            raise ValueError("Returned usage exceeds the reserved cost")
        row.update(
            state="settled",
            tokens_in=inputs,
            tokens_out=outputs,
            thinking_tokens=thoughts,
            cost_usd=float(cost),
        )
        self.pending -= self.reservation
        self.observed += cost
        self._save()

    def transport(self, inner=None):
        return _BudgetTransport(self, inner or httpx.AsyncHTTPTransport())


class _BudgetTransport(httpx.AsyncBaseTransport):
    def __init__(self, budget, inner):
        self.budget, self.inner = budget, inner

    async def handle_async_request(self, request):
        row = self.budget._admit(request)
        response = None
        try:
            response = await self.inner.handle_async_request(request)
            row["http_status"] = response.status_code
            await response.aread()
            self.budget._settle(row, response)
            return response
        except BaseException as exc:
            # Exception strings and provider error bodies can contain credentials.
            row["error_type"] = type(exc).__name__
            self.budget._unknown(row, "HTTP attempt did not produce verified usage")
            if response is not None:
                await response.aclose()
            if not isinstance(exc, Exception):
                raise
            raise RequestBudgetExceeded(
                "Gemini request usage is uncertain; further spending is blocked"
            ) from None

    async def aclose(self):
        await self.inner.aclose()
