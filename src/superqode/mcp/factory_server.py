"""Project-scoped Factory tools; startup never grants model execution."""

from pathlib import Path


def build_factory_mcp_server(project, *, allow_execution=False):
    from fastmcp import FastMCP
    from superqode.factory import improvement as imp
    from superqode.factory.definition import load_factory
    from superqode.factory.snapshot import resolve_factory
    from superqode.factory.runtime import factory_store, validate_factory_order

    root = Path(project).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Choose one existing Factory project")
    server = FastMCP("superqode-factory")

    @server.tool()
    def factory_evidence_trace(work_order: str) -> dict:
        """Trace requirements to pinned stages, checks and verification artifacts."""
        from superqode.factory.evidence import trace

        return trace(root, work_order)

    @server.tool()
    def factory_outcomes() -> dict:
        """Compare recorded business outcomes and known costs by Factory revision."""
        from superqode.factory.evidence import outcomes

        return outcomes(root)

    @server.tool()
    def factory_record_outcome(
        work_order: str,
        observation: str,
        outcome: str,
        human_minutes: float | None = None,
        confirmed: bool = False,
    ) -> dict:
        """Record an operator observation; never manufacture verifier or release evidence."""
        from superqode.factory.evidence import record_outcome

        if confirmed is not True:
            raise ValueError("Confirm recording the attributed outcome")
        return record_outcome(
            root,
            work_order,
            observation=observation,
            outcome=outcome,
            human_minutes=human_minutes,
            actor="mcp operator",
        )

    @server.tool()
    def factory_intake_receipts() -> dict:
        """Read bounded authenticated intake decision codes without payloads or secrets."""
        from superqode.factory.intake import receipts

        return receipts(root)

    @server.tool()
    def factory_verifier_draft(checks: dict) -> dict:
        """Propose protected evaluator files for existing final checks, without writes."""
        from superqode.factory.verifiers import draft

        return draft(root, checks)

    @server.tool()
    def factory_verifier_install(proposal: dict, digest: str, confirmed: bool = False) -> dict:
        """Save exact reviewed verifier configuration; no execution or release activation."""
        from superqode.factory.verifiers import install

        return install(root, proposal, expected=digest, confirmed=confirmed)

    @server.tool()
    async def factory_verifier_generate(
        description: str, provider: str, model: str, confirmed: bool = False
    ) -> dict:
        """Use a selected model to draft unmeasured verifiers; live opt-in required."""
        from superqode.factory.verifiers import generate

        authorize(confirmed)
        return await generate(root, description=description, provider=provider, model=model)

    @server.tool()
    def factory_capabilities() -> dict:
        """Return implemented methods and whether live execution is enabled."""
        return {
            **imp.capabilities(),
            "execution_enabled": allow_execution,
            "project": str(root),
            "release_authority": False,
        }

    @server.tool()
    def factory_resolve() -> dict:
        """Validate and resolve this server's project without submitting work."""
        snapshot = resolve_factory(load_factory(root=root))
        return {
            "digest": snapshot.digest,
            "engine_version": snapshot.payload["engine_version"],
            "definition": snapshot.payload["definition"],
            "sources": {
                name: {"digest": value["digest"]}
                for name, value in snapshot.payload["sources"].items()
            },
            "protected_source_contents_included": False,
        }

    @server.tool()
    def factory_compile(goal: str, persist: bool = False, confirmed: bool = False) -> dict:
        """Compile a pinned plan; persistence requires confirmation, no models."""
        from superqode.factory.compiler import compile_factory, materialize_snapshot

        plan = compile_factory(resolve_factory(load_factory(root=root)), root=root, goal=goal)
        if persist:
            if confirmed is not True:
                raise ValueError("Confirm materializing the compiled plan")
            materialize_snapshot(plan)
        return plan.to_dict()

    @server.tool()
    def factory_submit(plan: dict, request_id: str, confirmed: bool = False) -> dict:
        """Queue exactly the compiled contract; never execute or approve a gate."""
        from superqode.factory.runtime import load_compiled_plan, admit_factory

        if confirmed is not True:
            raise ValueError("Confirm submitting this exact compiled contract")
        compiled = load_compiled_plan(plan, root=root)
        order = admit_factory(compiled, request_id=request_id, actor="project-scoped MCP client")
        return {
            "work_order_id": order.work_order_id,
            "status": order.status.value,
            "execution_started": False,
        }

    @server.tool()
    def factory_inspect_run(work_order: str) -> dict:
        """Inspect a pinned run; never approve a gate or execute models."""
        order = factory_store(root, read_only=True).get(work_order)
        if order.repository != str(root):
            raise ValueError("Run belongs to a different project")
        validate_factory_order(order, check_baseline=False)
        return {
            "work_order_id": order.work_order_id,
            "status": order.status.value,
            "goal": order.goal,
            "tasks": [
                {"id": t.task_id, "status": t.status.value, "attempts": t.attempts}
                for t in order.tasks
            ],
            "artifact_count": len(order.artifacts),
            "protected_artifact_contents_included": False,
            "release_authorized": False,
        }

    @server.tool()
    def factory_benchmark_history() -> dict:
        """List past task identities without returning protected evaluator contents."""
        from superqode.factory.benchmarks import history

        return history(root)

    @server.tool()
    def factory_benchmark_prepare(
        held_in: list[str], held_out: list[str], candidate: str, confirmed: bool = False
    ) -> dict:
        """Prepare local dataset review; return task text and digests, withholding probe contents."""
        from superqode.factory.benchmarks import prepare_review

        return prepare_review(
            root, held_in=held_in, held_out=held_out, candidate=candidate, confirmed=confirmed
        )

    @server.tool()
    def factory_benchmark_install(proposal_id: str, confirmed: bool = False) -> dict:
        """Save the explicitly reviewed dataset; no worker, optimizer or release executes."""
        from superqode.factory.benchmarks import install_review

        return install_review(root, proposal_id, confirmed=confirmed)

    @server.tool()
    def factory_improvement_inspect(plan: str) -> dict:
        """Inspect the pinned experiment and its cumulative usage."""
        value, _ = imp.load(root, plan)
        return {"plan": value, "budget": imp.budget_summary(root, value, detail=True)}

    @server.tool()
    def factory_improvement_baseline(plan: str) -> dict:
        """Read the editable baseline surface, without evaluation task contents."""
        value, _ = imp.load(root, plan)
        return {"plan": value["id"], "baseline": imp.baseline_proposal(root, value)}

    @server.tool()
    def factory_improvement_prepare(
        binding: str,
        tasks: str,
        fixture: str,
        reflection_model: str = "",
        target_kind: str = "harness",
        skill: str = "",
        stage: str = "",
        engine: str = "evaluator-optimizer",
        max_evals: int = 4,
        max_seconds: int = 120,
        objective: str = "quality",
        confirmed: bool = False,
    ) -> dict:
        """Pin an experiment without model calls; requires explicit confirmation."""
        if confirmed is not True:
            raise ValueError("Confirm preparing the pinned experiment")
        return imp.prepare(
            root,
            binding=binding,
            tasks=tasks,
            fixture=fixture,
            reflection_model=reflection_model,
            target_kind=target_kind,
            skill=skill,
            stage=stage,
            optimizer_engine=engine,
            max_evals=max_evals,
            max_seconds=max_seconds,
            objective=objective,
        )

    @server.tool()
    def factory_improvement_stage(plan: str, proposal: str, confirmed: bool = False) -> dict:
        """Stage a policy-audited proposal; this cannot authorize adoption."""
        if confirmed is not True:
            raise ValueError("Confirm staging the proposal")
        return imp.stage(root, plan, proposal)

    def authorize(confirmed):
        if not allow_execution or confirmed is not True:
            raise ValueError("Start with --allow-execution and explicitly confirm this live action")

    @server.tool()
    async def factory_run(work_order: str, confirmed: bool = False) -> dict:
        """Run a bounded worker; human waits require a separate operator interface."""
        from superqode.workorders.worker import WorkOrderWorker, WorkOrderWorkerConfig

        authorize(confirmed)
        order = factory_store(root, read_only=True).get(work_order)
        if order.repository != str(root):
            raise ValueError("Run belongs to a different project")
        validate_factory_order(order)
        worker = WorkOrderWorker(
            factory_store(root),
            WorkOrderWorkerConfig(
                reference=order.work_order_id,
                once=True,
                retry=False,
                isolation="worktree",
                concurrency=1,
                max_tasks=64,
            ),
        )
        return {"stats": (await worker.run()).to_dict(), "release_authorized": False}

    @server.tool()
    def factory_improvement_search(plan: str, digest: str, confirmed: bool = False) -> dict:
        """Run bounded held-in search; never adopt or activate its proposal."""
        authorize(confirmed)
        return imp.optimize(root, plan, digest)

    @server.tool()
    async def factory_improvement_compare(
        plan: str, digest: str, candidate: str, confirmed: bool = False
    ) -> dict:
        """Consume the plan's single held-out comparison; no release authority."""
        authorize(confirmed)
        return await imp.compare(root, plan, candidate, digest)

    return server
