"""Optional kernels receive only Factory-owned inference and evaluation calls."""

import asyncio
from pathlib import Path

from .definition import project_path
from .metering import BudgetHalt


class PhaseHalt(BudgetHalt):
    """A portfolio phase ended; enclosing accounting stays in force."""


def gepa_search(**options):
    from superqode.skillopt import _run_modern_optimizer, _best_skill_text

    try:
        return _best_skill_text(_run_modern_optimizer(**options))
    except RuntimeError as exc:
        if not isinstance(exc.__cause__, ImportError):
            raise
    # PyPI GEPA 0.1.x has the supported callable-LM API, but not the newer
    # engine-pluggable API. No inference occurred in the failed import above.
    from gepa.optimize_anything import optimize_anything, GEPAConfig

    result = optimize_anything(
        options["seed_candidate"],
        evaluator=options["evaluator"],
        dataset=options["dataset"],
        valset=options["valset"],
        objective=options["objective"],
        background=options["background"],
        config=GEPAConfig(
            engine={
                "max_metric_calls": options["max_evals"],
                "max_workers": 1,
                "parallel": False,
                "seed": 0,
                "display_progress_bar": False,
                "cache_evaluation": False,
                "use_cloudpickle": False,
                "raise_on_exception": True,
                "run_dir": str(options["output_dir"] / "gepa"),
                "max_candidate_proposals": options["max_evals"],
            },
            reflection={
                "reflection_lm": options["reflection_lm"],
                "module_selector": "all",
                "reflection_minibatch_size": 1,
            },
            merge=None,
            refiner=None,
        ),
    )
    return _best_skill_text(result)


def metaharness_search(
    *, root, output_dir, seed, reflection, objective, dataset, score, max_evals, audit
):
    from metaharness import optimize_harness
    from metaharness.models import (
        ProposalExecution,
        ProposalResult,
        EvaluationResult,
        ValidationResult,
    )
    from . import improvement as imp

    output_dir = Path(output_dir)
    baseline = output_dir / "baseline"
    baseline.mkdir(parents=True)
    imp._write(baseline / "proposal.txt", seed)
    feedback = []

    def proposal(workspace):
        path = Path(workspace) / "proposal.txt"
        return project_path(Path(root).resolve(), path.relative_to(Path(root).resolve()).as_posix())

    class Proposer:
        name = "superqode-metered-gateway"

        def prepare(self, request):
            return request

        def invoke(self, request):
            import json

            current = imp._read(proposal(request.workspace_dir), 250000)
            value = reflection(
                objective
                + "\nReturn only the complete proposal, without commentary.\n"
                + "Current proposal:\n"
                + current
                + "\nHeld-in examples only:\n"
                + json.dumps(dataset)
                + "\nRecorded held-in feedback:\n"
                + json.dumps(feedback[-24:])
            )
            if value.strip().startswith("```") and value.strip().endswith("```"):
                value = value.strip().split("\n", 1)[1].rsplit("```", 1)[0]
            from .operations import write

            write(proposal(request.workspace_dir), value)
            logs = Path(request.candidate_dir) / "gateway"
            logs.mkdir()
            imp._write(
                logs / "stdout.txt", "Factory-owned gateway; see the durable usage ledger.\n"
            )
            imp._write(logs / "stderr.txt", "")
            return ProposalExecution(
                command=[],
                cwd=request.workspace_dir,
                stdout_path=logs / "stdout.txt",
                stderr_path=logs / "stderr.txt",
                returncode=0,
            )

        def collect(self, execution):
            return ProposalResult(
                applied=True,
                summary="Metered Factory proposal",
                changed_files=["proposal.txt"],
                metadata={"usage_authority": "Factory plan ledger"},
            )

    class Validator:
        def validate(self, workspace):
            try:
                audit(proposal(workspace))
                return ValidationResult(ok=True, summary="Factory surface policy accepted")
            except ValueError as exc:
                return ValidationResult(ok=False, summary=str(exc))

    class Evaluator:
        def evaluate(self, workspace):
            text = imp._read(proposal(workspace), 250000)
            rows = [score(text, example) for example in dataset]
            feedback.append({"scores": [r[0] for r in rows], "feedback": [r[1] for r in rows]})
            return EvaluationResult(
                objective=sum(r[0] for r in rows) / len(rows),
                summary="Pinned held-in Factory evaluation",
            )

    # The upstream kernel's test evaluator is deliberately not supplied.
    result = optimize_harness(
        baseline=baseline,
        proposer=Proposer(),
        evaluator=Evaluator(),
        validator=Validator(),
        run_dir=output_dir / "run",
        budget=max(0, max_evals // len(dataset) - 1),
        objective=objective,
        allowed_write_paths=["proposal.txt"],
        proposal_batch_size=1,
    )
    return imp._read(proposal(result.best_workspace_dir), 250000)


def native_search(*, reflection, seed, objective, dataset, score, spec):
    from superqode.harness.workflow import _run_evaluator_optimizer, WorkflowStep
    from .search import NativeSearchSession

    session = NativeSearchSession(
        reflection=reflection,
        seed=seed,
        objective=objective,
        dataset=dataset,
        score=score,
        spec=spec,
    )

    async def run():
        try:
            await _run_evaluator_optimizer(
                session,
                [
                    WorkflowStep(
                        "Propose an improvement; return only the complete proposal.", id="candidate"
                    ),
                    WorkflowStep("Grade on pinned held-in examples.", id="evaluator"),
                    WorkflowStep(
                        "Revise using the deterministic feedback; return only the complete proposal.",
                        id="optimizer",
                    ),
                ],
                provider="",
                model="",
                evaluation_acceptance=lambda value: value == "PASS",
            )
            if session.current != session.best:
                await session.evaluate(session.current)
            elif session.proposals > 1:
                session.reused += 1
        except PhaseHalt:
            pass
        return session.best, session.reused

    return asyncio.run(run())


def portfolio(*, seed, dataset, score, max_evals, output_dir, engines):
    """Omni-style composition of three metered kernels and a GEPA continuation."""
    from .snapshot import digest

    if max_evals < 4 * len(dataset):
        raise ValueError("Omni portfolio needs at least four metric calls per held-in case")
    observations = {}
    proposals = {}
    identities = {example["id"] for example in dataset}

    def measured(text, example):
        value = score(text, example)
        if isinstance(value[1].get("Feedback"), dict):
            token = digest(str(text))
            proposals[token] = str(text)
            observations.setdefault(token, {})[example["id"]] = value[0]
        return value

    def best():
        complete = {
            token: sum(values.values()) / len(values)
            for token, values in observations.items()
            if set(values) == identities
        }
        return proposals[max(complete, key=complete.get)] if complete else None

    allocation = max_evals // 4
    names = ["evaluator-optimizer", "gepa", "metaharness", "gepa"]
    for index, name in enumerate(names):
        cap = allocation if index < 3 else max_evals - 3 * allocation
        used = 0

        def bounded(text, example):
            nonlocal used
            if used >= cap:
                raise PhaseHalt("Portfolio phase metric allocation exhausted")
            used += 1
            return measured(text, example)

        try:
            engines[name](
                seed if index < 3 else best() or seed,
                bounded,
                cap,
                Path(output_dir) / (str(index) + "-" + name),
            )
        except PhaseHalt:
            pass
    return best()
