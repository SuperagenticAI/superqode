"""Shared operational inspection of retained RLM work."""

from __future__ import annotations


async def retained_admin(session, sub, rest, log):
    from .coding_session import supervisor_for_session

    supervisor = supervisor_for_session(session.session_path)
    manager = getattr(session, "delegation_manager", None)
    if sub in {"profile", "budget", "history", "jobs", "job"} or (
        sub == "usage" and hasattr(session, "budget")
    ):
        import json
        import shlex

        if sub == "profile":
            profile = session.profile
            log.add_info(f"tools      {', '.join(profile.tools)}")
            log.add_info(f"observations {profile.observations}")
            log.add_info(
                f"sandbox    {session.options.sandbox.backend if session.options.sandbox else 'host'}"
            )
            log.add_info(
                "Configure a new session with :rlm settings; optional routing with :rlm a2a"
            )
        elif sub in {"budget", "usage"}:
            from .budget import budget_lines

            args = shlex.split(rest)
            if args and args[0] == "reconcile":
                if len(args) < 5:
                    raise ValueError(
                        "budget reconcile <call-id> <tokens> <USD> <verification reason>"
                    )
                session.budget.reconcile(
                    args[1], tokens=args[2], cost_usd=args[3], reason=" ".join(args[4:])
                )
                log.add_success("Verified inference usage recorded")
            offset = int(args[1]) if args and args[0] == "unresolved" and len(args) > 1 else 0
            snapshot = session.budget.snapshot(unsettled_offset=offset)
            for line in budget_lines(snapshot):
                log.add_info(line)
            for call in snapshot["unsettled"]:
                log.add_info(
                    f"unresolved {call['id']} {call['lane']} {call['model']} {call['state']}"
                )
            if snapshot["unsettled_count"] > offset + len(snapshot["unsettled"]):
                log.add_info(
                    f"More unresolved reports: :rlm budget unresolved {offset + len(snapshot['unsettled'])}"
                )
            subcalls = session.subcall_usage
            if subcalls:
                usage = subcalls.get("root_usage", subcalls["usage"])
                log.add_info(
                    f"subcalls   {usage['calls']} of {subcalls['policy']['max_calls']} calls, {usage['total_tokens']} tokens, ${usage['cost_usd']:.4f} known cost"
                )
            from .context import RLMContext

            stats = RLMContext(session.cwd, policy=session.options.context_policy).stats()
            log.add_info(f"context    {stats['files']} files, {stats['bytes']} bytes in scope")
            records = supervisor.snapshots() if supervisor is not None else []
            log.add_info(
                f"children   {len(records)} retained agents" if records else "children   none"
            )
            log.add_info(
                "Root conversation and compaction usage are included in the family ledger."
            )
            if manager is not None:
                records = manager.store.records(manager.root)
                log.add_info(
                    f"a2a        {len(records)} tasks; {sum(r['credits'] for r in records)} admitted credits; remote token/USD usage unknown"
                )
        elif sub == "history":
            args = shlex.split(rest)
            if args and args[0] == "read":
                if len(args) < 2:
                    raise ValueError("history read <id> [start] [size]")
                result = await session.history.dispatch(
                    "history.read",
                    {
                        "id": args[1],
                        "start": int(args[2]) if len(args) > 2 else 0,
                        "size": int(args[3]) if len(args) > 3 else 4000,
                    },
                )
            else:
                result = await session.history.dispatch("history.search", {"query": rest})
            log.add_info(json.dumps(result, ensure_ascii=False))
        else:
            args = shlex.split(rest)
            payload = {"action": "list"}
            if sub == "job":
                if len(args) < 2:
                    raise ValueError(
                        "job status|read|cancel|wait <id>; job reconcile <id> <returncode> <reason>"
                    )
                action, identity = args[:2]
                if action not in {"status", "read", "cancel", "wait", "reconcile"}:
                    raise ValueError("Unknown job action")
                payload = {"action": action, "job_id": identity}
                if action == "read":
                    payload.update(
                        stream=args[2] if len(args) > 2 else "stdout",
                        start=int(args[3]) if len(args) > 3 else 0,
                        size=int(args[4]) if len(args) > 4 else 4000,
                    )
                if action == "reconcile":
                    if len(args) < 4:
                        raise ValueError("job reconcile <id> <returncode> <verification reason>")
                    payload.update(returncode=int(args[2]), reason=" ".join(args[3:]))
            log.add_info(
                json.dumps(await session.command_request(payload, admin=True), ensure_ascii=False)
            )
        return True
    if sub == "routing":
        from .delegation_policy import DelegationPolicy

        policy = manager.policy if manager is not None else DelegationPolicy()
        log.add_info(f"Active worker A2A: {'on' if policy.enabled else 'off'}")
        log.add_info(
            f"Paid routing: {'on' if policy.hosted_enabled else 'off'}; "
            f"credit limit {policy.max_hosted_credits}; "
            f"tasks {policy.max_tasks}; parallel {policy.max_parallel}"
        )
        log.add_info(f"Allowed peers: {', '.join(p['name'] for p in policy.inventory()) or 'none'}")
        return True
    if sub == "peers":
        for peer in manager.inventory() if manager is not None else []:
            log.add_info(
                f"{peer['name']}  hosted={peer['hosted']} tariff={peer['credits']} credits  {peer['description']}"
            )
        if manager is None or not manager.inventory():
            log.add_info("No A2A routes enabled. Open :rlm a2a to configure optional routing.")
        return True
    if sub == "delegations":
        for record in manager.evidence() if manager is not None else []:
            log.add_info(
                f"{record['id']}  {record['state']} peer={record['peer']} owner={record['owner']} required={record['required']} reserved={record['credits']} credits usage=unknown"
            )
        if manager is None or not manager.evidence():
            log.add_info("No A2A tasks admitted in this root.")
        return True
    if sub == "reconcile":
        identifier, task_id, reason = rest.split(maxsplit=2)
        record = next(
            (r for r in manager.store.records(manager.root) if r["id"] == identifier), None
        )
        if record is None:
            raise ValueError("Unknown local delegation handle")
        manager.reconcile(record["owner"], identifier, task_id=task_id, reason=reason)
        await manager.poll(record["owner"], identifier)
        log.add_success("Verified task attached; no remote submission was repeated.")
        return True
    if sub == "inbox":
        for item in supervisor.mailbox.read("root"):
            log.add_info(f"{item['id']} from {item['sender']}: {item['message']}")
        return True
    if sub in {"message", "follow-up"}:
        target, text = rest.split(maxsplit=1)
        if sub == "message":
            identity = supervisor.mailbox.send("root", target, text)
            log.add_success(f"Inbox delivery queued: {identity}")
        else:
            handle = supervisor.follow_up(target, text)
            log.add_success(f"Continuation admitted: {handle.id}")
        return True
    return False
