"""Shared operational inspection of retained RLM work."""

from __future__ import annotations


async def retained_admin(session, sub, rest, log):
    from .coding_session import supervisor_for_session

    supervisor = supervisor_for_session(session.session_path)
    manager = getattr(session, "delegation_manager", None)
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
