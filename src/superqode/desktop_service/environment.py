"""Limit credentials passed to desktop jobs; this is not an OS sandbox."""

from superqode.tools.env_policy import is_secret_name


def selected_providers(kind, request):
    providers = {str(request.get("provider") or "")}
    if kind == "studio":
        route = (request.get("studio_plan") or {}).get("route") or {}
        return (
            {route["provider"]}
            if route.get("source") != "local" and route.get("provider")
            else set()
        )
    if kind == "local":
        plan = request.get("local_plan") or {}
        return (
            {"huggingface"}
            if plan.get("action") == "download" and plan.get("source") == "hf"
            else set()
        )
    models = [request.get("reflection_model"), request.get("optimizer_model")]
    if kind == "optimization":
        models = [
            request.get("reflection_model") or "openai/gpt-5.1",
            request.get("optimizer_model") or "anthropic/claude-sonnet-4-6",
        ]
    for model in models:
        if model and "/" in model:
            providers.add(model.split("/", 1)[0])
        elif model and str(model).startswith("claude-"):
            providers.add("anthropic")
    return providers


def job_environment(base, credentials, *, check=False, allowed=()):
    """Checks get no provider secrets, even when inherited by the GUI process."""
    allowed = set() if check else set(allowed) | set(credentials)
    result = {
        name: value
        for name, value in base.items()
        if name in allowed or name == "SSH_AUTH_SOCK" or not is_secret_name(name)
    }
    if not check:
        result.update(credentials)
    return result
