"""Read-only model onboarding shared by Factory authoring clients."""

from pathlib import Path

from superqode.providers.dynamic import resolve_provider_def
from superqode.providers.model_specs import split_provider_model_ref
from superqode.session.factory import default_policy

from .definition import read_mapping, validate_definition, project_path
from .generation import check_generation_route


def inspect_models(
    root, *, yaml_text=None, drafting_model="", check_connection=None, allow_cloud=False
):
    """Explain drafting and pinned execution routes without inference or edits.

    A supplied connection checker may perform model discovery. Its results
    describe configuration/discovery only, never successful inference/tool use.
    """
    root = Path(root).resolve()
    if not isinstance(drafting_model, str):
        raise ValueError("Choose a drafting model as provider/model")
    if yaml_text is not None and not isinstance(yaml_text, str):
        raise ValueError("Factory YAML must be text")
    if yaml_text is None:
        path = project_path(root, ".superqode/factory.yaml")
        if path.is_file():
            if path.stat().st_size > 250000:
                raise ValueError("Factory definition exceeds 250 KB")
            yaml_text = path.read_text(encoding="utf-8")
    data = read_mapping(yaml_text) if yaml_text and yaml_text.strip() else {}
    if "apiVersion" in data:
        validate_definition(data)
    elif set(data) - {"default_route", "routes"}:
        raise ValueError("Expected a FactorySpec or a routing-only policy")
    defaults = default_policy()
    if allow_cloud is True and "default_route" not in data:
        route = "best"
        route_data = {**data, "default_route": "best"}
    else:
        route = data.get("default_route", defaults["default_route"])
        route_data = data
    if route not in defaults["routes"] and route not in data.get("routes", {}):
        raise ValueError(f"Unknown factory default route: {route}")
    cache = {}

    def inspect(reference, purpose, *, binding="", fallback=False):
        parsed = split_provider_model_ref(reference)
        provider, model = parsed.provider, parsed.model
        row = {
            "purpose": purpose,
            "binding": binding,
            "fallback": fallback,
            "reference": reference,
            "provider": provider,
            "model": model,
            "state": "unchecked",
            "eligible": True,
            "inference_verified": False,
            "message": (
                "Check the connection, then generate a proposal to verify drafting."
                if purpose == "drafting"
                else "Check the connection, then run a small trial to verify inference and tool use."
            ),
            "next_step": "check-connection",
        }
        if not reference:
            row.update(
                state="model-required",
                eligible=False,
                next_step="choose-model",
                message="Choose an execution model for this harness before preparing a trial.",
            )
            return row
        definition = resolve_provider_def(provider) if provider else None
        if not provider or not model or not definition or definition.harness_only:
            row.update(
                state="unsupported",
                eligible=False,
                next_step="choose-model",
                message="Choose a direct model provider and model. Agent subscription connections are separate from Factory model routes.",
            )
            return row
        row["docs_url"] = definition.docs_url
        try:
            check_generation_route(route_data, provider, model)
        except ValueError:
            row.update(
                state="privacy-blocked",
                eligible=False,
                next_step="review-privacy",
                message=f"Route '{route}' allows local models only. Choose a local model, or explicitly review and save a cloud-enabled Factory route such as 'best'. Credentials alone do not enable cloud use.",
            )
            return row
        if any(word in model.lower() for word in ("embed", "rerank")):
            row.update(
                state="unsupported",
                eligible=False,
                next_step="choose-model",
                message="Choose a chat or coding model; embedding and reranking models cannot draft or execute a Factory.",
            )
            return row
        if check_connection is not None:
            key = (provider, model, binding)
            if key not in cache:
                try:
                    cache[key] = check_connection(provider, model, binding)
                except (OSError, ValueError, TimeoutError):
                    # Provider diagnostics can contain URLs or auth material.
                    # Preserve other routes and use the existing connection UI
                    # for detailed troubleshooting rather than echoing errors.
                    cache[key] = {
                        "ready": False,
                        "state": "connection-unavailable",
                        "message": "Could not check this connection. Review its endpoint and authentication in Connections or Local AI, then retry.",
                    }
            connection = cache[key]
            row.update(
                state=connection.get("state", "needs-test"),
                message=connection.get("message", row["message"]),
            )
            if connection.get("ready") is False:
                row["eligible"] = False
                row["next_step"] = (
                    "connect-provider"
                    if row["state"] == "missing-credential"
                    else "check-connection"
                )
            else:
                row["next_step"] = "generate-draft" if purpose == "drafting" else "run-trial"
        return row

    drafting = (
        inspect(drafting_model, "drafting")
        if drafting_model
        else {
            "purpose": "drafting",
            "reference": "",
            "state": "starter-only",
            "eligible": True,
            "inference_verified": False,
            "next_step": "optional-model",
            "message": "Starter generation and repository inspection work without a model. Connect a model for AI-assisted drafting; execution models are configured separately.",
        }
    )
    execution = []
    execution_error = ""
    if "apiVersion" in data:
        from .definition import FactoryDefinition
        from .snapshot import resolve_factory

        try:
            resolved = resolve_factory(
                FactoryDefinition(root, project_path(root, ".superqode/factory.yaml"), data),
                source_text=yaml_text,
            )
            harnesses = resolved.payload["harnesses"]
        except (ValueError, OSError):
            # AI drafting can repair an incomplete definition. A missing runtime
            # component must not prevent the user from connecting its drafter.
            harnesses = {}
            execution_error = "A referenced Factory component could not be resolved. Validate the definition to review execution bindings before preparing a trial."
        for binding, harness in harnesses.items():
            policy = harness["model_policy"]
            for index, reference in enumerate(
                [policy.get("primary", ""), *policy.get("fallbacks", [])]
            ):
                execution.append(
                    inspect(reference, "execution", binding=binding, fallback=index > 0)
                )
    return {
        "format": "superqode.factory-model-setup/1",
        "default_route": route,
        "drafting": drafting,
        "execution": execution,
        "execution_error": execution_error,
        "execution_configured": bool(execution) and all(row["reference"] for row in execution),
        "connections_checked": check_connection is not None,
        "model_calls": 0,
        "written": False,
        "guidance": "The drafting model designs a proposal. Each harness binding selects its own execution models. Connection checks establish availability; a reviewed trial establishes execution evidence.",
    }
