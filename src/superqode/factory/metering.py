"""Durable request accounting shared by Factory search and held-out comparison.

Limits control admission. Provider usage is observed after a request completes;
one in-flight request can overrun a limit. Unknown work is never replayed here.
"""

from __future__ import annotations

from contextlib import contextmanager
import json
import math
import os
from urllib.parse import urlparse
from pathlib import Path
import time
from uuid import uuid4

from superqode.desktop_service.ownership import Lease
from superqode.evaluation.usage_scope import usage_scope
from .definition import project_path
from .snapshot import canonical, digest


class BudgetHalt(ValueError):
    """No additional work can be admitted under the pinned budget."""


def number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def route_identity(provider, model):
    from superqode.providers.model_specs import normalize_provider_id, normalize_model_for_provider

    provider = normalize_provider_id(provider)
    return provider, normalize_model_for_provider(provider, model)


def local_api_fee(provider, model, endpoint=None):
    """Recognized on-device endpoints only; remote/cloud routes are not free."""
    if provider not in {"ollama", "lmstudio", "apple-foundation", "swift-mlx"}:
        return False
    if "cloud" in model.lower():
        return False
    if provider in {"apple-foundation", "swift-mlx"}:
        return endpoint is None
    from superqode.providers.registry import PROVIDERS

    definition = PROVIDERS.get(provider)
    base = (
        endpoint
        or (os.environ.get(definition.base_url_env) if definition.base_url_env else None)
        or definition.default_base_url
    )
    host = urlparse(base if "://" in base else "http://" + base).hostname if base else None
    return host in {"localhost", "127.0.0.1", "::1"}


class BudgetLedger:
    def __init__(self, directory, plan):
        self.directory = Path(directory)
        self.path = project_path(self.directory, "usage.json")
        self.plan = plan

    def initialize(self):
        if self.path.exists():
            raise ValueError("An improvement usage ledger already exists")
        self._save(
            {
                "format": "superqode.factory-usage/1",
                "plan_digest": self.plan["digest"],
                "limits": {**self.plan["limits"], "max_seconds": self.plan["max_seconds"]},
                "started": None,
                "finished": None,
                "metrics": 0,
                "operations": [],
                "requests": [],
            }
        )

    def _load(self):
        from .improvement import _read

        value = json.loads(_read(self.path))
        if (
            value.get("format") != "superqode.factory-usage/1"
            or value.get("plan_digest") != self.plan["digest"]
            or value.get("limits")
            != {**self.plan["limits"], "max_seconds": self.plan["max_seconds"]}
        ):
            raise ValueError("Improvement usage ledger differs from its pinned plan")
        return value

    def _save(self, data):
        from superqode.desktop_service.studio import _atomic

        text = canonical(data)
        if len(text.encode()) > 4_000_000:
            raise BudgetHalt("Usage ledger reached its evidence bound")
        _atomic(self.path, text)

    @contextmanager
    def _edit(self):
        lease = Lease(project_path(self.directory, "usage.writer.lock"))
        try:
            data = self._load()
            yield data
            self._save(data)
        finally:
            lease.close()

    @contextmanager
    def action(self):
        lease = Lease(project_path(self.directory, "usage.action.lock"))
        try:
            yield self
        finally:
            lease.close()

    def _summary(self, data):
        requests = data["requests"]
        operations = data["operations"]
        totals = {
            field: sum(r.get(field, 0) for r in requests if number(r.get(field)))
            for field in ("tokens", "cost_usd")
        }
        observed_tools = sum(
            o.get("tool_calls", 0) for o in operations if number(o.get("tool_calls"))
        )
        reserved_tools = sum(
            max(
                o.get("tool_calls", 0) if number(o.get("tool_calls")) else 0,
                sum(r.get("planned_tools", 0) for r in requests if r["operation"] == o["id"]),
            )
            for o in operations
        )
        totals["tool_calls"] = reserved_tools
        unknown_requests = sum(
            r["status"] != "settled" or not all(number(r.get(k)) for k in ("tokens", "cost_usd"))
            for r in requests
        )
        unknown_operations = sum(
            o["status"] == "uncertain"
            or (o["status"] == "settled" and not number(o.get("tool_calls")))
            for o in operations
        )
        pending = sum(o["status"] == "pending" for o in operations)
        issues = []
        if unknown_requests or unknown_operations:
            issues.append(
                "Request or operation usage is unknown; reconcile outside this plan before new work"
            )
        for key, field in (
            ("max_tokens", "tokens"),
            ("max_cost_usd", "cost_usd"),
            ("max_tool_calls", "tool_calls"),
        ):
            if key in data["limits"] and totals[field] > data["limits"][key]:
                issues.append("Aggregate improvement budget exceeded: " + key)
        end = data["finished"] or time.time()
        elapsed = max(0, end - data["started"]) if data["started"] else 0
        if elapsed > data["limits"]["max_seconds"]:
            issues.append("Shared improvement wall-time budget expired")
        if self.plan.get("absolute_deadline") is not None and end > self.plan["absolute_deadline"]:
            issues.append("Aggregate campaign deadline expired")
        return {
            "plan_digest": data["plan_digest"],
            "limits": data["limits"],
            "observed": {**totals, "tool_calls": observed_tools},
            "accounted": totals,
            "observed_tool_calls": observed_tools,
            "reserved_tool_calls": reserved_tools,
            "unknown_requests": unknown_requests,
            "unknown_operations": unknown_operations,
            "pending_operations": pending,
            "request_count": len(requests),
            "operation_count": len(operations),
            "metric_calls": data["metrics"],
            "elapsed_seconds": elapsed,
            "started": data["started"],
            "finished": data["finished"],
            "issues": issues,
            "evidence_complete": not issues and not pending,
            "digest": digest(canonical(data)),
            "enforcement": "Admission between requests; in-flight overruns remain recorded; not a billing guarantee",
        }

    def summary(self):
        return self._summary(self._load())

    def check_admission(self):
        self._check(self._load())

    def detail(self):
        data = self._load()
        return {
            **self._summary(data),
            "operations": data["operations"],
            "requests": data["requests"],
        }

    def mark_unobserved(self, phase):
        with self._edit() as data:
            if len(data["operations"]) >= 256:
                raise BudgetHalt("Unobserved execution exceeded the ledger bound")
            data["started"] = data["started"] or time.time()
            data["operations"].append(
                {
                    "id": uuid4().hex,
                    "phase": phase,
                    "metadata": {
                        "reason": "Evaluation returned without complete request accounting"
                    },
                    "status": "uncertain",
                    "started": time.time(),
                    "finished": time.time(),
                    "tool_calls": None,
                }
            )

    def report_issues(self, report):
        data = self._load()
        summary = self._summary(data)
        issues = list(summary["issues"])
        if summary["pending_operations"]:
            issues.append("Improvement has unsettled usage operations")
        expected = {o["id"]: o for o in data["operations"] if o["phase"] == "held-out"}
        seen = []
        for variant in report.get("variants", []):
            for row in variant.get("tasks", []):
                identity = row.get("factory_usage_operation")
                op = expected.get(identity)
                if (
                    op is None
                    or op["status"] != "settled"
                    or op["metadata"].get("spec") != variant.get("spec")
                    or op["metadata"].get("task") != row.get("id")
                    or op["metadata"].get("split") != "held-out"
                ):
                    issues.append("Held-out grading row has no matching settled usage operation")
                elif op["metadata"].get("provider"):
                    from superqode.providers.model_specs import split_provider_model_ref

                    route = report.get("inference_routes", {}).get(variant.get("spec"))
                    expected_route = split_provider_model_ref(route) if route else None
                    expected_provider, expected_model = (
                        (expected_route.provider, expected_route.model)
                        if expected_route
                        else (self.plan["provider"], self.plan["model"])
                    )
                    if route_identity(
                        op["metadata"]["provider"], op["metadata"]["model"]
                    ) != route_identity(expected_provider, expected_model):
                        issues.append(
                            "Held-out usage route differs from the pinned inference route"
                        )
                seen.append(identity)
        if len(seen) != len(set(seen)) or set(seen) != set(expected):
            issues.append("Held-out usage operation coverage differs from the comparison")
        if not data["finished"]:
            issues.append("Improvement budget is not finalized")
        return list(dict.fromkeys(issues))

    def _check(self, data, *, allow_operation=None, completion=False):
        summary = self._summary(data)
        if summary["issues"]:
            raise BudgetHalt("; ".join(summary["issues"]))
        if not completion:
            if data["finished"]:
                raise BudgetHalt("This improvement budget has been finalized")
            if any(
                o["status"] == "pending" and o["id"] != allow_operation for o in data["operations"]
            ):
                raise BudgetHalt("An earlier operation is still unsettled; do not replay it")
            for key, field in (
                ("max_tokens", "tokens"),
                ("max_cost_usd", "cost_usd"),
                ("max_tool_calls", "tool_calls"),
            ):
                if key in data["limits"] and summary["accounted"][field] >= data["limits"][key]:
                    raise BudgetHalt("Aggregate improvement budget exhausted: " + key)

    def metric(self):
        with self._edit() as data:
            self._check(data)
            if data["metrics"] >= self.plan["max_evals"]:
                raise BudgetHalt("Optimizer metric-call limit reached")
            data["metrics"] += 1
            return data["metrics"]

    def begin(self, phase, metadata):
        with self._edit() as data:
            self._check(data)
            if len(data["operations"]) >= 256:
                raise BudgetHalt("Improvement operation limit reached")
            if (
                phase == "reflection"
                and sum(o["phase"] == "reflection" for o in data["operations"])
                >= self.plan["max_evals"]
            ):
                raise BudgetHalt("Optimizer reflection-call limit reached")
            identity = uuid4().hex
            now = time.time()
            data["started"] = data["started"] or now
            data["operations"].append(
                {
                    "id": identity,
                    "phase": phase,
                    "metadata": metadata,
                    "status": "pending",
                    "started": now,
                }
            )
        return RequestScope(self, identity)

    def begin_request(self, operation, provider, model, endpoint=None):
        with self._edit() as data:
            self._check(data, allow_operation=operation)
            op = next(o for o in data["operations"] if o["id"] == operation)
            if op["status"] != "pending":
                raise BudgetHalt("Usage operation is not active")
            if op["metadata"].get("provider") and route_identity(provider, model) != route_identity(
                op["metadata"]["provider"], op["metadata"]["model"]
            ):
                raise BudgetHalt("Model request differs from the admitted operation route")
            if len(data["requests"]) >= 4096:
                raise BudgetHalt("Model request evidence limit reached")
            identity = uuid4().hex
            data["requests"].append(
                {
                    "id": identity,
                    "operation": operation,
                    "provider": provider,
                    "model": model,
                    "api_cost_kind": "on-device-api-fee"
                    if local_api_fee(provider, model, endpoint)
                    else "gateway-estimate",
                    "status": "pending",
                    "started": time.time(),
                }
            )
        return identity

    def finish_request(self, identity, response=None):
        with self._edit() as data:
            row = next(r for r in data["requests"] if r["id"] == identity)
            if row["status"] != "pending":
                raise ValueError("Model request already has a durable outcome")
            usage = getattr(response, "usage", None)
            cost = getattr(response, "cost", None)
            tokens = getattr(usage, "total_tokens", None)
            if tokens in (None, 0) and all(
                number(getattr(usage, k, None)) for k in ("prompt_tokens", "completion_tokens")
            ):
                tokens = usage.prompt_tokens + usage.completion_tokens
            if not number(tokens) or (
                tokens == 0
                and (getattr(response, "content", "") or getattr(response, "tool_calls", None))
            ):
                tokens = None
            value = getattr(cost, "total_cost", None)
            if row.get("api_cost_kind") == "on-device-api-fee" and value in (None, 0):
                value = 0.0  # API fee only; no hardware/energy claim
            elif not number(value) or value == 0 or getattr(cost, "currency", "") != "USD":
                value = None
            else:
                row["api_cost_kind"] = "gateway-estimate"
            row.update(
                status="settled" if response is not None else "uncertain",
                tokens=tokens,
                cost_usd=value,
                planned_tools=len(getattr(response, "tool_calls", None) or []),
                finished=time.time(),
            )

    def finish(self, scope, usage=None, *, failed=False):
        with self._edit() as data:
            op = next(o for o in data["operations"] if o["id"] == scope.identity)
            if op["status"] != "pending":
                raise ValueError("Usage operation already has an outcome")
            requests = [r for r in data["requests"] if r["operation"] == scope.identity]
            tools = (usage or {}).get("tool_calls")
            op.update(
                status="uncertain" if failed or not requests else "settled",
                finished=time.time(),
                tool_calls=tools if number(tools) else None,
            )
            # Native eval totals must agree with independently observed requests.
            if usage and requests and all(number(r.get("tokens")) for r in requests):
                reported = usage.get("total_tokens")
                if reported is None and all(
                    number(usage.get(k)) for k in ("tokens_in", "tokens_out")
                ):
                    reported = usage["tokens_in"] + usage["tokens_out"]
                if not number(reported) or reported != sum(r["tokens"] for r in requests):
                    op["status"] = "uncertain"
            if (
                usage
                and requests
                and number(usage.get("cost_usd"))
                and all(number(r.get("cost_usd")) for r in requests)
            ):
                if not math.isclose(
                    usage["cost_usd"],
                    sum(r["cost_usd"] for r in requests),
                    rel_tol=1e-8,
                    abs_tol=1e-10,
                ):
                    op["status"] = "uncertain"
        return self.summary()

    def finalize(self):
        with self._edit() as data:
            if not data["finished"]:
                data["finished"] = time.time()
        return self.summary()

    def observer(self, phase):
        return EvaluationObserver(self, phase)


class RequestScope:
    def __init__(self, ledger, identity):
        self.ledger, self.identity = ledger, identity

    async def request(self, call, provider, model, endpoint=None):
        identity = self.ledger.begin_request(self.identity, provider, model, endpoint)
        try:
            response = await call()
        except BaseException:
            self.ledger.finish_request(identity)
            raise
        self.ledger.finish_request(identity, response)
        issues = self.ledger.summary()["issues"]
        if issues:
            raise BudgetHalt("; ".join(issues))
        return response


class EvaluationObserver:
    def __init__(self, ledger, phase):
        self.ledger, self.phase = ledger, phase

    @contextmanager
    def operation(self, *, spec, task, provider, model):
        scope = self.ledger.begin(
            self.phase,
            {
                "spec": str(spec),
                "task": task["id"],
                "split": task.get("split"),
                "provider": provider,
                "model": model,
            },
        )
        try:
            with usage_scope(scope):
                yield scope
        except BaseException:
            self.ledger.finish(scope, failed=True)
            raise

    def complete(self, scope, row):
        self.ledger.finish(scope, row.get("usage"))
        row["factory_usage_operation"] = scope.identity
