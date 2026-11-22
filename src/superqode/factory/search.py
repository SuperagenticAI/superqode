"""Metered adapters for GEPA reflection and native evaluator/optimizer control."""

from __future__ import annotations

import asyncio
from copy import deepcopy
import json
from uuid import uuid4

import yaml

from superqode.evaluation.usage_scope import usage_scope
from superqode.harness.eval import load_eval_tasks
from superqode.harness.eval_workspace import EvaluationWorkspace
from superqode.harness.loader import harness_spec_from_dict
from superqode.providers.gateway import GatewayFactory, Message
from superqode.providers.model_specs import split_provider_model_ref
from .metering import BudgetHalt


class ReflectionModel:
    """GEPA's callable LM contract, with Factory-owned inference and accounting."""

    def __init__(self, ledger, route):
        self.ledger, self.route = ledger, route

    @property
    def total_cost(self):
        data = self.ledger.detail()
        reflections = {o["id"] for o in data["operations"] if o["phase"] == "reflection"}
        return sum(
            r.get("cost_usd") or 0 for r in data["requests"] if r["operation"] in reflections
        )

    async def generate(self, prompt):
        route = split_provider_model_ref(self.route)
        if isinstance(prompt, str):
            messages = [Message(role="user", content=prompt)]
        elif isinstance(prompt, list) and 0 < len(prompt) <= 128:
            if any(
                not isinstance(v, dict)
                or v.get("role") not in {"system", "user", "assistant"}
                or not isinstance(v.get("content"), str)
                for v in prompt
            ):
                raise ValueError("Reflection requires bounded text messages without tools")
            messages = [Message(role=v["role"], content=v["content"]) for v in prompt]
        else:
            raise ValueError("Reflection requires text or message-list input")
        if sum(len(m.content.encode()) for m in messages) > 500000:
            raise ValueError("Reflection prompt exceeds its evidence bound")
        scope = self.ledger.begin("reflection", {"provider": route.provider, "model": route.model})
        try:
            with usage_scope(scope):
                response = await GatewayFactory.create(timeout=60).chat_completion(
                    messages=messages,
                    provider=route.provider,
                    model=route.model,
                    max_tokens=6000,
                    temperature=0,
                    tools=[],
                    reasoning_effort="none",
                )
            usage = response.usage
            self.ledger.finish(
                scope,
                {
                    "total_tokens": getattr(usage, "total_tokens", None),
                    "tokens_in": getattr(usage, "prompt_tokens", None),
                    "tokens_out": getattr(usage, "completion_tokens", None),
                    "tool_calls": 0,
                },
            )
        except BaseException:
            data = self.ledger.detail()
            if any(
                o["id"] == scope.identity and o["status"] == "pending" for o in data["operations"]
            ):
                self.ledger.finish(scope, failed=True)
            raise
        summary = self.ledger.summary()
        if summary["issues"]:
            raise BudgetHalt("; ".join(summary["issues"]))
        if response.tool_calls:
            raise ValueError("Reflection cannot execute tools")
        if not response.content or len(response.content.encode()) > 250000:
            raise ValueError("Reflection returned an empty or oversized proposal")
        return response.content

    def __call__(self, prompt):
        return asyncio.run(self.generate(prompt))


def _objective(plan):
    return {
        "harness": "Edit only agent system_prompt, role or description in the resolved harness YAML.",
        "skill": "Edit only the bound skill Markdown body; preserve every frontmatter field.",
        "route": "Return YAML with only model, selecting one of these pinned routes: "
        + json.dumps(plan["route_models"]),
        "workflow": "Return YAML with only stage and goal; preserve the selected stage identity.",
    }[plan.get("target_kind", "harness")]


class NativeSearchSession:
    """Adapt native evaluator/optimizer steps to proposal and deterministic scoring."""

    def __init__(self, *, reflection, seed, objective, dataset, score, spec):
        self.reflection, self.seed, self.objective, self.dataset, self.score, self.spec = (
            reflection,
            seed,
            objective,
            dataset,
            score,
            spec,
        )
        self.current = seed
        self.best = None
        self.best_score = -1
        self.proposals = 0
        self.reused = 0

    async def session(self, *args):
        return self

    async def evaluate(self, text):
        values = []
        for example in self.dataset:
            value, feedback = await asyncio.to_thread(self.score, text, example)
            values.append((value, feedback))
        score = sum(v[0] for v in values) / len(values)
        if score > self.best_score and all(isinstance(v[1].get("Feedback"), dict) for v in values):
            self.best, self.best_score = text, score
        return score, values

    async def prompt(self, prompt, *, metadata, **kwargs):
        from superqode.agent.loop import AgentResponse
        from superqode.harness.kernel import HarnessRunResult

        step = metadata["workflow_step"]
        if step == "evaluator":
            score, feedback = await self.evaluate(self.current)
            content = (
                "PASS" if score == 1 else json.dumps({"held_in_score": score, "feedback": feedback})
            )
        else:
            self.proposals += 1
            content = await self.reflection.generate(
                self.objective
                + "\nPinned baseline proposal:\n"
                + self.seed
                + "\nHeld-in examples only:\n"
                + json.dumps(self.dataset)
                + "\n"
                + prompt
            )
            if content.strip().startswith("```") and content.strip().endswith("```"):
                content = content.strip().split("\n", 1)[1].rsplit("```", 1)[0]
            self.current = content
        # This is a workflow control result, not an invented agent/model usage receipt.
        response = AgentResponse(
            content=content, messages=[], tool_calls_made=0, iterations=0, stopped_reason="complete"
        )
        return HarnessRunResult(
            content=content,
            response=response,
            spec=self.spec,
            session_id="factory-search",
            run_id=uuid4().hex,
        )


def run_search(root, identity, expected):
    from . import improvement as imp
    from superqode.skillopt import _optimization_splits

    plan, snapshot = imp.load(root, identity, expected, fresh=True)
    if "optimizer_versions" in plan and plan["optimizer_versions"] != imp.optimizer_versions(
        plan.get("optimizer_engine", "gepa")
    ):
        raise ValueError("Optimizer dependency versions changed; prepare a new pinned experiment")
    if not plan["reflection_model"]:
        raise ValueError("Explicitly select a reflection model before search")
    ledger = imp.budget(root, plan)
    ledger.check_admission()
    directory = imp.folder(root, identity)
    if (directory / "comparison.claim").exists():
        raise ValueError(
            "Held-out comparison was already exposed; prepare a new plan before search"
        )
    search_dir = directory / "search"
    search_dir.mkdir()
    suite = load_eval_tasks(directory / "tasks.yaml")
    train, validation, _ = _optimization_splits(suite["tasks"])
    heldin = {t["id"]: t for t in suite["tasks"] if t["split"] != "held-out"}
    reflection = ReflectionModel(ledger, plan["reflection_model"])
    seed = imp.baseline_proposal(root, plan)
    engine = plan.get("optimizer_engine", "gepa")
    best = None
    reused = 0
    failure = ""
    scored_candidates = {}
    scored_text = {}
    with EvaluationWorkspace(
        directory / "fixture", temporary_dir=directory / "temporary", git_discovery=False
    ) as workspace:

        def score(candidate, example):
            if example.get("id") not in heldin or example.get("split") == "held-out":
                raise ValueError("Only pinned held-in examples may enter optimizer scoring")
            index = ledger.metric()
            text = (
                str(next(iter(candidate.values()), ""))
                if isinstance(candidate, dict)
                else str(candidate)
            )
            attempt = search_dir / f"attempt-{index}"
            attempt.mkdir()
            try:
                text = imp.candidate_text(root, plan, text)
                path = attempt / ("proposal" + imp.proposal_suffix(plan))
                imp._write(path, text)
                if not imp._audit(root, plan, path)["accepted"]:
                    return 0.0, {"Feedback": "Proposal violates pinned Factory policy"}
                specs = imp._effective_files(root, plan, path, attempt)
                tasks = attempt / "tasks.yaml"
                imp._write(
                    tasks,
                    yaml.safe_dump({"tasks": [deepcopy(heldin[example["id"]])]}, sort_keys=False),
                )
                before = {o["id"] for o in ledger.detail()["operations"]}
                report = asyncio.run(
                    imp.run_harness_eval(
                        spec_paths=[specs[1]],
                        tasks_path=tasks,
                        provider=plan["provider"],
                        model=plan["model"],
                        working_dir=directory / "fixture",
                        live=True,
                        eval_split="held-in",
                        workspace_snapshot=workspace,
                        evaluation_observer=ledger.observer("held-in"),
                        **imp._evaluation_context(root, plan, text, [specs[1]], tasks, "held-in"),
                    )
                )
                operations = [o for o in ledger.detail()["operations"] if o["id"] not in before]
                rows = [row for v in report.get("variants", []) for row in v.get("tasks", [])]
                if (
                    len(operations) != 1
                    or len(rows) != 1
                    or rows[0].get("factory_usage_operation") != operations[0]["id"]
                ):
                    ledger.mark_unobserved("held-in")
                    raise BudgetHalt("Held-in evaluation returned without exact usage coverage")
                if ledger.summary()["issues"]:
                    raise BudgetHalt("; ".join(ledger.summary()["issues"]))
                row = report["variants"][0]["tasks"][0]
                token = imp.digest(text)
                scored_candidates.setdefault(token, {})[example["id"]] = float(row.get("score", 0))
                scored_text[token] = text
                return float(row.get("score", 0)), {
                    "Feedback": {"status": row["status"], "reason": row.get("reason")}
                }
            except BudgetHalt:
                raise
            except (ValueError, KeyError, TypeError) as exc:
                return 0.0, {"Feedback": str(exc)}

        from .optimizer_engines import gepa_search, native_search, metaharness_search, portfolio

        def gepa(seed_value, evaluator, cap, output):
            return gepa_search(
                engine="gepa",
                continuation_engine="gepa",
                seed_candidate=seed_value,
                evaluator=evaluator,
                dataset=train,
                valset=validation,
                test_set=[],
                objective=_objective(plan),
                background="Only the selected proposal surface is editable. No held-out data is available.",
                output_dir=output,
                max_evals=cap,
                explore_max_evals=None,
                max_token_cost=None,
                reflection_lm=reflection,
                optimizer_model="",
                optimizer_effort=None,
                agent_sandbox=True,
                max_workers=1,
                seed=0,
                max_candidate_proposals=cap,
                candidate_selection_strategy="pareto",
                frontier_type="hybrid",
                acceptance_criterion="strict_improvement",
                cache_evaluation=False,
                use_merge=False,
                max_merge_invocations=0,
                reflection_minibatch_size=1,
            )

        def native(seed_value, evaluator, cap, output):
            nonlocal reused
            value, count = native_search(
                reflection=reflection,
                seed=seed_value,
                objective=_objective(plan),
                dataset=list(heldin.values()),
                score=evaluator,
                spec=harness_spec_from_dict(snapshot.payload["harnesses"][plan["binding"]]),
            )
            reused += count
            return value

        def metaharness(seed_value, evaluator, cap, output):
            def audit(path):
                if not imp._audit(root, plan, path)["accepted"]:
                    raise ValueError("Proposal violates pinned Factory surfaces")

            return metaharness_search(
                root=root,
                output_dir=output,
                seed=seed_value,
                reflection=reflection,
                objective=_objective(plan),
                dataset=list(heldin.values()),
                score=evaluator,
                max_evals=cap,
                audit=audit,
            )

        engines = {"gepa": gepa, "evaluator-optimizer": native, "metaharness": metaharness}
        try:
            if engine == "omni":
                best = portfolio(
                    seed=seed,
                    dataset=list(heldin.values()),
                    score=score,
                    max_evals=plan["max_evals"],
                    output_dir=search_dir,
                    engines=engines,
                )
            elif engine in engines:
                best = engines[engine](seed, score, plan["max_evals"], search_dir)
            else:
                raise ValueError("Unsupported Factory search engine")
        except BudgetHalt as exc:
            failure = str(exc)
            # An upstream kernel may ask for one more metric after its nominal
            # limit. The ledger refuses it before inference. Retain only a
            # completely scored proposal; usage issues still hold the result.
            complete = {
                token: sum(values.values()) / len(values)
                for token, values in scored_candidates.items()
                if set(values) == set(heldin)
            }
            if complete:
                best = scored_text[max(complete, key=complete.get)]
        except Exception as exc:
            cursor = exc
            while cursor is not None and not isinstance(cursor, BudgetHalt):
                cursor = cursor.__cause__
            summary = ledger.summary()
            if cursor is not None or summary["issues"] or summary["pending_operations"]:
                failure = str(cursor or exc)
            else:
                imp._write(search_dir / "failed-budget.json", imp.canonical(summary))
                raise
    imp.load(root, identity, expected, fresh=True)
    summary = ledger.summary()
    if summary["issues"] or summary["pending_operations"] or not best:
        return {
            "plan": identity,
            "held": True,
            "candidate": "",
            "optimizer": engine,
            "budget": summary,
            "issues": summary["issues"] + [failure or "No complete staged proposal was produced"],
            "heldout_exposed": False,
        }
    proposed = imp.stage(root, identity, best)
    return {
        **proposed,
        "optimizer": engine,
        "metric_calls": summary["metric_calls"],
        "deduplicated_proposals": reused,
        "budget": summary,
        "heldout_exposed": False,
        "notice": "Search staged a proposal. A separate metered held-out comparison is required before draft adoption.",
    }
