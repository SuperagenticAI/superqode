"""Native campaign management; live work uses the existing desktop job owner."""

from superqode.factory import campaigns


def handle(service, root, method, params):
    action = method.removeprefix("factory.campaign.")
    if action == "list":
        return {"campaigns": campaigns.inventory(root)}
    if action == "inspect":
        return campaigns.inspect(root, params["id"])
    if action == "event.preview":
        return campaigns.preview_event(
            root,
            params["id"],
            expected=params["digest"],
            kind=params["kind"],
            source=params.get("source", ""),
        )
    if action not in {"create", "enqueue", "stop"} or params.get("confirmed") is not True:
        raise ValueError("Explicitly confirm a supported campaign action")
    if action == "stop":
        # A drain request must remain available while the worker owns the
        # project writer. It only writes the campaign's stop marker.
        return campaigns.stop(root, params["id"], params["digest"])
    from .ownership import Lease, project_lease_path
    from .ship import assert_idle

    with service.lock:
        assert_idle(service, params["project"])
        lease = Lease(project_lease_path(service.root, root))
        try:
            if action == "create":
                return campaigns.create(root)
            return campaigns.enqueue(
                root,
                params["id"],
                expected=params["digest"],
                **{k: params[k] for k in ("kind", "key", "source", "source_digest")},
                parent=params.get("parent", ""),
            )
        finally:
            lease.close()
