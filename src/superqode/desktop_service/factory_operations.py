"""Native Factory operations, without installing services or replaying work."""

from superqode.factory import handover, operations, recovery, lifecycle


def handle(service, root, method, params):
    action = method.removeprefix("factory.operations.")
    if action == "inspect":
        return {"readiness": operations.readiness(root), "packages": handover.inventory(root)}
    if action == "verify":
        return handover.inspect(root, params["id"], expected=params["sha256"])
    if action == "retention.preview":
        return handover.retention(root, keep=params.get("keep", 2), days=params.get("days", 30))
    if action == "retire.preview":
        return lifecycle.review(root)
    if action not in {
        "check",
        "handover",
        "restore",
        "deploy",
        "retention.apply",
        "checkpoint",
        "retire",
        "reactivate",
        "recovery.acknowledge",
    }:
        raise ValueError("Unknown Factory operations action")
    if params.get("confirmed") is not True:
        raise ValueError("Explicitly confirm the Factory operations action")
    from .ownership import Lease, project_lease_path
    from .ship import assert_idle

    with service.lock:
        assert_idle(service, params["project"])
        lease = Lease(project_lease_path(service.root, root))
        try:
            if action == "check":
                return operations.readiness(
                    root,
                    probe=True,
                    application=params.get("application") is True,
                    timeout=int(params.get("timeout", 300)),
                )
            if action == "handover":
                return handover.create(
                    root, runs=params.get("runs", []), improvements=params.get("improvements", [])
                )
            if action == "restore":
                return handover.restore(
                    root, params["id"], expected=params["sha256"], destination=params["destination"]
                )
            if action == "retention.apply":
                return handover.prune(root, params["review"])
            if action == "checkpoint":
                return recovery.create(root)
            if action == "retire":
                return lifecycle.retire(root, params["digest"])
            if action == "reactivate":
                return lifecycle.reactivate(root, params["digest"], probe=True)
            if action == "recovery.acknowledge":
                return recovery.acknowledge(root, params["digest"], probe=True)
            return operations.deployment(
                root,
                target_platform=params["platform"],
                target_project=params.get("target_project") or str(root),
                python=params["python"],
                reference=params["reference"],
                user=params.get("user", "superqode"),
            )
        finally:
            lease.close()
