"""Expose a SuperQode Harness Protocol session through A2A 1.0.

The wire protocol is implemented by the official ``a2a-sdk`` package.  This
module is deliberately only an adapter: A2A owns discovery, task lifecycle,
streaming, and transport semantics while SuperQode owns harness execution and
its durable event ledger.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from fastapi import FastAPI

    from superqode.agent.loop import AgentConfig
    from superqode.harness import HarnessProtocolController, HarnessSessionRef, HarnessSpec

from superqode.a2a.keys import ANONYMOUS_TIER, AccessDecision, decide_access
from superqode.a2a.limits import RateLimiter, RateLimitPolicy, caller_identity


#: The version reported in the Agent Card.
#:
#: This is deliberately not the SuperQode package version.  A2A defines this
#: field as the version of the *agent*, and callers use it to notice that the
#: interface changed.  Tying it to the package version meant every PyPI
#: release invalidated the published card, which is how the card at the
#: discovery origin drifted out of date: the release cadence set the
#: republication cadence, rather than actual interface changes doing so.
#:
#: Bump this by hand when the interface URL, capabilities, auth policy, or
#: skills change.  Nothing else should move it.
AGENT_CARD_VERSION = "1.0"


def _package_version() -> str:
    """Return the running SuperQode version, for diagnostics only."""
    from superqode import __version__

    return __version__


class A2AServerConfig(BaseModel):
    """Runtime and discovery settings for the A2A bridge."""

    name: str = "SuperQode"
    description: str = "The Harness Layer for Coding Agents"
    version: str = AGENT_CARD_VERSION
    url: str = "http://127.0.0.1:8000"
    documentation_url: str = "https://github.com/SuperagenticAI/superqode"
    skill_id: str = "superqode-harness"
    skill_name: str = "SuperQode Harness"
    skill_description: str = (
        "Run versioned coding-agent harnesses with controlled execution, evaluation, and evidence"
    )
    provider: str = "openai"
    model: str = "gpt-5.4"
    working_directory: Path = Field(default_factory=Path.cwd)
    task_store_path: Path | None = Path(".superqode/a2a/tasks.sqlite3")
    streaming: bool = True
    push_notifications: bool = False
    #: Operator token. Predates signed keys; kept so an existing deployment
    #: keeps working, and useful as a break-glass credential.
    bearer_token: str | None = None
    #: Secret that signs and verifies customer keys. Falls back to
    #: SUPERQODE_A2A_KEY_SECRET when unset.
    key_secret: str | None = None
    #: Serve callers who present no credential at all.
    #:
    #: The anonymous tier answers from the local Hub with no model call, so it
    #: costs nothing to serve.  Keeping it open is also what makes the agent
    #: registrable on platforms whose registration offers OAuth or nothing,
    #: with no field for a bearer token.
    allow_anonymous: bool = True
    #: Requests per minute for a caller with no credential.
    anonymous_per_minute: int = 10
    #: Requests per minute for a caller presenting a valid key.
    keyed_per_minute: int = 60
    #: Requests per day across every caller, as a backstop for the case where
    #: per-caller accounting has a gap. Zero disables it.
    global_per_day: int = 5_000
    #: Read a keyed caller's request with a model before ranking.  Anonymous
    #: callers always use the keyword parser, so the open tier stays free.
    understand_requests: bool = True
    shortlist_skill_id: str = "harness-shortlist"
    shortlist_skill_name: str = "Harness Shortlist"
    shortlist_skill_description: str = (
        "Search the curated Harness Hub for third-party coding agents and harnesses "
        "matching stated constraints. Returns a ranked catalogue shortlist with "
        "licence and setup details. SuperQode's own harnesses are excluded from the "
        "ranking and disclosed separately"
    )
    #: Serve the shortlist skill.  It needs no repository, no model call and no
    #: sandbox, which is what makes it answerable on a public endpoint.
    shortlist_enabled: bool = True
    #: Serve the harness skill, which executes a HarnessSpec against
    #: ``working_directory``.
    #:
    #: The default is permissive because the library is normally embedded or
    #: bound to loopback, where the caller and the repository are the same
    #: person.  Exposing it on a remote endpoint is a different proposition:
    #: the bound spec decides what an accepted request may do, and the default
    #: coding template allows shell and writes with no sandbox isolation.  The
    #: CLI therefore turns this off for remote binds unless asked otherwise.
    harness_skill_enabled: bool = True
    #: How long a fetched Agent Card may be reused, in seconds.
    #:
    #: Registries and gateways poll the card. Without a freshness window they
    #: either refetch on every call or cache it forever at their own
    #: discretion, and the specification asks the server to say which it wants
    #: (section 8.6.1). The card only changes when the process restarts, so
    #: this can be generous.
    card_cache_max_age: int = 300
    #: Must resolve.  Host platforms render this in their agent gallery, and a
    #: dead URL shows as a broken image rather than as no image.
    #: ``scripts/check_published_agent_card.py`` verifies it.
    icon_url: str = "https://super-agentic.ai/uploads/superqode.png"
    jsonrpc_path: str = "/"
    #: Also advertise and serve the A2A 0.3 wire format.  Gemini Enterprise,
    #: Foundry Agent Service, and Agent Registry all still accept 0.3 cards,
    #: and some of their documented flows only show 0.3.
    legacy_v0_3: bool = True


#: JSON-RPC error code for ContentTypeNotSupportedError, from the A2A
#: specification's error table.
CONTENT_TYPE_NOT_SUPPORTED = -32005


def _unsupported_content_type(request: Any, config: "A2AServerConfig", sdk: dict[str, Any]) -> Any:
    """Reject a JSON-RPC POST whose media type is not JSON.

    Returned as a JSON-RPC envelope rather than an HTTP 415 because the error
    belongs to the JSON-RPC layer: the caller reached the right endpoint and
    framed the request wrongly, and a JSON-RPC client reads ``error.code``.
    """
    if request.method != "POST" or request.url.path != config.jsonrpc_path:
        return None
    media_type = (request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
    # An absent header is tolerated: some clients omit it and the body still
    # parses. Only a media type that is present and wrong is refused.
    if not media_type or media_type == "application/json" or media_type.endswith("+json"):
        return None
    return sdk["JSONResponse"](
        status_code=200,
        content={
            "jsonrpc": "2.0",
            "id": None,
            "error": {
                "code": CONTENT_TYPE_NOT_SUPPORTED,
                "message": "ContentTypeNotSupportedError",
                "data": {
                    "received": media_type,
                    "supported": ["application/json"],
                },
            },
        },
    )


#: Paths the SDK serves the Agent Card on. The 0.3 name is still fetched by
#: hosts that have not moved to the 1.0 filename.
AGENT_CARD_PATHS = frozenset({"/.well-known/agent-card.json", "/.well-known/agent.json"})


def _card_validators(server: "A2AServer") -> tuple[str, str]:
    """Return a stable ``(etag, last_modified)`` pair for the Agent Card.

    The card is fixed for the life of the process, so both are computed once
    and reused. The ETag is a hash of the exact bytes served, which is what
    makes a conditional request answerable without re-serializing.
    """
    cached = getattr(server, "_card_validators_cache", None)
    if cached is not None:
        return cached
    import hashlib
    from email.utils import formatdate

    digest = hashlib.sha256(server.agent_card_json().encode("utf-8")).hexdigest()[:32]
    validators = (f'"{digest}"', formatdate(usegmt=True))
    server._card_validators_cache = validators
    return validators


class SuperQodeA2AExecutor:
    """Map each A2A context to one resumable Harness Protocol session."""

    def __init__(self, controller: HarnessProtocolController, config: A2AServerConfig) -> None:
        self.controller = controller
        self.config = config
        self._sessions: dict[str, HarnessSessionRef] = {}
        self._task_sessions: dict[str, HarnessSessionRef] = {}
        self._session_lock = asyncio.Lock()

    async def execute(self, context: Any, event_queue: Any) -> None:
        sdk = _a2a_sdk()
        task_id = _required_id(context.task_id, "task")
        context_id = _required_id(context.context_id, "context")
        updater = sdk["TaskUpdater"](event_queue, task_id, context_id)

        if context.current_task is None:
            await event_queue.enqueue_event(
                sdk["Task"](
                    id=task_id,
                    context_id=context_id,
                    status=sdk["TaskStatus"](state=sdk["TaskState"].TASK_STATE_SUBMITTED),
                )
            )
        await updater.start_work()

        user_input = context.get_user_input()
        if self._wants_shortlist(context, user_input):
            await self._answer_shortlist(
                updater,
                sdk,
                user_input,
                artifact_id=f"shortlist-{task_id}",
                tier=caller_tier(context),
            )
            return

        if not self.config.harness_skill_enabled:
            # Refuse rather than fall through.  The card does not advertise
            # the harness skill in this mode, so a request that reaches here
            # asked for work this deployment does not offer.
            await updater.failed(
                updater.new_agent_message(
                    [
                        sdk["Part"](
                            text=(
                                "This endpoint does not run harnesses. It answers "
                                f"the '{self.config.shortlist_skill_id}' skill only. "
                                "Run SuperQode against your own repository to execute "
                                "a harness."
                            )
                        )
                    ]
                )
            )
            return

        session = await self._session_for(context_id)
        self._task_sessions[task_id] = session
        artifact_id = f"superqode-{task_id}"
        content: list[str] = []
        artifact_started = False
        pending_chunk: str | None = None

        try:
            async for event in self.controller.send(session, user_input):
                if event.type == "message.delta":
                    chunk = str(event.data.get("text") or "")
                    if chunk:
                        content.append(chunk)
                        if pending_chunk is not None:
                            await updater.add_artifact(
                                [sdk["Part"](text=pending_chunk)],
                                artifact_id=artifact_id,
                                name="SuperQode response",
                                append=artifact_started,
                                last_chunk=False,
                            )
                            artifact_started = True
                        pending_chunk = chunk
                elif event.type == "message.created" and event.data.get("role") == "assistant":
                    final_text = str(event.data.get("content") or "")
                    if final_text and not content:
                        content.append(final_text)
                elif event.type == "run.failed":
                    await updater.failed(
                        updater.new_agent_message(
                            [sdk["Part"](text=str(event.data.get("error") or "Harness run failed"))]
                        )
                    )
                    return
                elif event.type == "run.cancelled":
                    await updater.cancel()
                    return
                elif event.type == "run.completed" and event.data.get("status") == "needs_approval":
                    await updater.requires_input(
                        updater.new_agent_message(
                            [
                                sdk["Part"](
                                    text="SuperQode requires approval before it can continue."
                                )
                            ]
                        )
                    )
                    return

            final_text = "".join(content)
            if pending_chunk is not None:
                await updater.add_artifact(
                    [sdk["Part"](text=pending_chunk)],
                    artifact_id=artifact_id,
                    name="SuperQode response",
                    append=artifact_started,
                    last_chunk=True,
                )
            elif final_text:
                await updater.add_artifact(
                    [sdk["Part"](text=final_text)],
                    artifact_id=artifact_id,
                    name="SuperQode response",
                    last_chunk=True,
                )
            await updater.complete(
                updater.new_agent_message(
                    [sdk["Part"](text=final_text or "SuperQode completed the harness run.")],
                    # camelCase: the A2A spec requires it for JSON field names
                    # (specification 5.5), and the TCK's DM-SERIAL-001 check
                    # rejects any snake_case key anywhere in a response.
                    metadata={"superqodeSessionId": session.session_id},
                )
            )
        finally:
            self._task_sessions.pop(task_id, None)

    def _wants_shortlist(self, context: Any, user_input: str) -> bool:
        """Decide whether this turn is a shortlist question.

        An explicit skill id in the message metadata always wins, because a
        calling agent that names the skill should not be second-guessed.  A
        chat surface sends plain prose instead, so fall back to a deliberately
        narrow phrase match and let anything ambiguous run the harness, which
        is the behaviour callers already depend on.
        """
        if not self.config.shortlist_enabled:
            return False
        requested = _requested_skill(context)
        if requested:
            return requested == self.config.shortlist_skill_id

        if not self.config.harness_skill_enabled:
            # Nothing else is served, so there is nothing to route away to.
            # Phrase matching here would refuse a caller for describing their
            # situation in their own words rather than using a magic phrase,
            # which is the opposite of what a shortlist skill is for.
            return True

        lowered = user_input.casefold()
        asks_for_choice = any(
            phrase in lowered
            for phrase in (
                "which harness",
                "what harness",
                "which coding agent",
                "what coding agent",
                "recommend a harness",
                "recommend an harness",
                "harness recommendation",
                "shortlist",
                "which runtime",
                "what are our options",
            )
        )
        return asks_for_choice

    async def _answer_shortlist(
        self,
        updater: Any,
        sdk: dict[str, Any],
        user_input: str,
        *,
        artifact_id: str,
        tier: str = ANONYMOUS_TIER,
    ) -> None:
        """Answer from the Harness Hub without touching a repository.

        A caller presenting a key has their request read by a model, which
        turns prose into constraints properly instead of matching substrings.
        An anonymous caller gets the keyword parser, which costs nothing to
        run and is what keeps the open tier free to serve.
        """
        from superqode.a2a.shortlist import build_shortlist, render_shortlist

        constraints = None
        understood = False
        if tier != ANONYMOUS_TIER and self.config.understand_requests:
            from superqode.a2a.understand import understand_request

            constraints, understood = await asyncio.to_thread(
                understand_request,
                user_input,
                provider=self.config.provider,
                model=self.config.model,
            )

        shortlist = await asyncio.to_thread(build_shortlist, user_input, constraints=constraints)
        text = render_shortlist(shortlist)
        await updater.add_artifact(
            [sdk["Part"](text=text)],
            artifact_id=artifact_id,
            name="Harness shortlist",
            last_chunk=True,
        )
        await updater.complete(
            updater.new_agent_message(
                [sdk["Part"](text=text)],
                metadata={
                    "superqodeSkill": self.config.shortlist_skill_id,
                    "superqodeShortlist": shortlist.to_dict(),
                    "superqodeUnderstood": understood,
                },
            )
        )

    async def cancel(self, context: Any, event_queue: Any) -> None:
        from superqode.harness import HarnessCapabilityError

        sdk = _a2a_sdk()
        task_id = _required_id(context.task_id, "task")
        context_id = _required_id(context.context_id, "context")
        session = self._task_sessions.get(task_id)
        if session is not None:
            try:
                await self.controller.cancel(session)
            except HarnessCapabilityError:
                # The official handler already cancels execute().  Some harness
                # adapters do not also expose an out-of-band cancel capability.
                pass
        await sdk["TaskUpdater"](event_queue, task_id, context_id).cancel()

    async def _session_for(self, context_id: str) -> HarnessSessionRef:
        from superqode.harness import HarnessCreateRequest

        async with self._session_lock:
            cached = self._sessions.get(context_id)
            if cached is not None:
                return cached

            session_id = f"a2a-{context_id}"
            if self.controller.store.get_session(session_id) is not None:
                session = await self.controller.resume(session_id)
            else:
                descriptor = self.controller.descriptors()[0]
                session = await self.controller.create(
                    HarnessCreateRequest(
                        harness_id=descriptor.id,
                        provider=self.config.provider,
                        model=self.config.model,
                        working_directory=self.config.working_directory.resolve(),
                        session_id=session_id,
                        metadata={"transport": "a2a", "a2a_context_id": context_id},
                    )
                )
            self._sessions[context_id] = session
            return session


class A2AServer:
    """A2A 1.0 FastAPI application backed by a Harness Protocol controller."""

    def __init__(
        self,
        controller: HarnessProtocolController,
        config: A2AServerConfig | None = None,
        task_store: Any | None = None,
    ) -> None:
        self.controller = controller
        self.config = config or A2AServerConfig()
        if not controller.descriptors():
            raise ValueError("A2A serving requires at least one Harness Protocol adapter")
        self._task_store_override = task_store
        self._task_engine: Any | None = None
        self.limiter = RateLimiter(
            RateLimitPolicy(
                anonymous_per_minute=self.config.anonymous_per_minute,
                keyed_per_minute=self.config.keyed_per_minute,
                global_per_day=self.config.global_per_day,
            )
        )
        self.executor = SuperQodeA2AExecutor(controller, self.config)
        self.app = self._build_app()

    def _build_app(self) -> FastAPI:
        from fastapi.middleware.cors import CORSMiddleware
        from starlette.responses import Response as StarletteResponse

        sdk = _a2a_sdk()
        app = sdk["FastAPI"](title="SuperQode A2A Server", version=_package_version())
        card = _agent_card(self.controller, self.config, sdk)
        self.agent_card = card
        task_store = self._task_store_override or self._create_task_store(sdk)
        handler = sdk["DefaultRequestHandler"](
            agent_executor=self.executor,
            task_store=task_store,
            agent_card=card,
        )
        compat = self.config.legacy_v0_3

        # The 0.3 discovery filename. The SDK routes only the 1.0 name, but the
        # card still advertises a 0.3 interface and hosts from that era look
        # here first. SuperQode's own client falls back to this path too, so
        # serving it costs one route and removes a discovery failure.
        #
        # Registered before the SDK routes because those include a catch-all
        # ``Mount`` at ``/{tenant}``, which matches any single leading segment.
        # A route added afterwards is shadowed by that mount and never runs.
        @app.get("/.well-known/agent.json")
        async def legacy_agent_card() -> Any:
            return sdk["JSONResponse"](
                content=json.loads(self.agent_card_json()),
                media_type="application/json",
            )

        context_builder = _AccessContextBuilder(sdk)
        sdk["add_a2a_routes_to_fastapi"](
            app,
            agent_card_routes=sdk["create_agent_card_routes"](card),
            jsonrpc_routes=sdk["create_jsonrpc_routes"](
                handler,
                rpc_url=self.config.jsonrpc_path,
                enable_v0_3_compat=compat,
                context_builder=context_builder,
            ),
            rest_routes=sdk["create_rest_routes"](
                handler, enable_v0_3_compat=compat, context_builder=context_builder
            ),
        )

        @app.api_route("/health", methods=["GET", "HEAD"])
        async def health() -> dict[str, Any]:
            return {
                "status": "ok",
                "superqode_version": _package_version(),
                "agent_card_version": self.config.version,
                "a2a_protocol_version": "1.0",
                "a2a_protocol_versions": ["1.0", "0.3"] if self.config.legacy_v0_3 else ["1.0"],
                "a2a_protocol_bindings": ["JSONRPC", "HTTP+JSON"],
                "harnesses": [item.id for item in self.controller.descriptors()],
                "limits": self.limiter.snapshot(),
            }

        config = self.config
        limiter = self.limiter

        def _card_cache_headers() -> dict[str, str]:
            etag, last_modified = _card_validators(self)
            return {
                "ETag": etag,
                "Last-Modified": last_modified,
                "Cache-Control": f"public, max-age={self.config.card_cache_max_age}",
            }

        @app.middleware("http")
        async def resolve_access(request: Any, call_next: Any) -> Any:
            # Discovery and health stay open regardless of policy.  Host
            # platforms fetch the Agent Card anonymously before they hold any
            # credential, so gating it would make the agent unregistrable.
            if request.url.path in AGENT_CARD_PATHS:
                headers = _card_cache_headers()
                # Registries probe with HEAD. The SDK card routes are GET-only,
                # so HEAD would 404 through call_next. Serve GET and HEAD from
                # the same bytes the ETag is hashed from.
                if request.method in {"GET", "HEAD"}:
                    if request.headers.get("if-none-match") == headers["ETag"]:
                        return StarletteResponse(status_code=304, headers=headers)
                    body = self.agent_card_json().encode("utf-8")
                    return StarletteResponse(
                        content=b"" if request.method == "HEAD" else body,
                        status_code=200,
                        media_type="application/json",
                        headers={**headers, "Content-Length": str(len(body))},
                    )
                response = await call_next(request)
                if response.status_code == 200:
                    for name, value in headers.items():
                        response.headers[name] = value
                return response

            if request.url.path in {"/health", "/docs", "/openapi.json"}:
                return await call_next(request)

            # A JSON-RPC caller that sends the wrong media type gets the
            # spec's ContentTypeNotSupportedError. Without this the body was
            # parsed anyway and the failure surfaced as ParseError (-32700),
            # which tells the caller their JSON is malformed rather than that
            # this endpoint only speaks application/json.
            unsupported = _unsupported_content_type(request, config, sdk)
            if unsupported is not None:
                return unsupported

            decision = decide_access(
                request.headers.get("authorization"),
                static_token=config.bearer_token,
                secret=config.key_secret,
                allow_anonymous=config.allow_anonymous,
            )
            if not decision.allowed:
                return sdk["JSONResponse"](
                    status_code=401,
                    content={"detail": f"Unauthorized: {decision.reason}"},
                    headers={"WWW-Authenticate": "Bearer"},
                )
            identity = caller_identity(
                decision.key_id,
                getattr(getattr(request, "client", None), "host", None),
                request.headers.get("x-forwarded-for"),
            )
            limit = limiter.check(identity, decision.tier)
            if not limit.allowed:
                return sdk["JSONResponse"](
                    status_code=429,
                    content={"detail": limit.reason},
                    headers={"Retry-After": str(limit.retry_after_seconds)},
                )

            # Carried on the scope so the call-context builder, and through it
            # the executor, can see which tier is asking.
            request.state.superqode_access = decision
            return await call_next(request)

        if self._task_engine is not None:
            app.router.add_event_handler("shutdown", self._task_engine.dispose)

        # Outermost so OPTIONS preflight never hits auth or the SDK catch-all.
        # Browser clients, and the marketing site fetching the operational
        # card, need this; the static discovery host already sends it.
        app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=[
                "ETag",
                "Last-Modified",
                "Cache-Control",
                "Retry-After",
                "WWW-Authenticate",
            ],
        )

        return app

    def _create_task_store(self, sdk: dict[str, Any]) -> Any:
        if self.config.task_store_path is None:
            return sdk["InMemoryTaskStore"]()
        path = self.config.task_store_path.expanduser().resolve()
        path.parent.mkdir(parents=True, exist_ok=True)
        database_url = sdk["URL"].create("sqlite+aiosqlite", database=str(path))
        self._task_engine = sdk["create_async_engine"](database_url)
        try:
            return sdk["DatabaseTaskStore"](self._task_engine)
        except ImportError as exc:
            raise RuntimeError(
                "Durable A2A task storage requires the SQLite dependencies from the 'a2a' extra"
            ) from exc

    def agent_card_json(self) -> str:
        """Serialize the exact runtime Agent Card for static publication.

        This must use the SDK's own card serializer rather than a plain
        protobuf conversion.  With 0.3 compatibility enabled the SDK emits a
        hybrid card that also carries the 0.3 discovery fields (`url`,
        `preferredTransport`, `protocolVersion`), and those are the fields
        host platforms read when they only speak 0.3.  Serializing the
        protobuf directly silently drops them, so the published card would
        promise less than the running server actually serves.
        """
        from a2a.server.request_handlers.response_helpers import agent_card_to_dict

        payload = agent_card_to_dict(self.agent_card)
        return json.dumps(payload, indent=2, sort_keys=False) + "\n"

    def run(self, host: str = "127.0.0.1", port: int = 8000) -> None:
        """Run the bridge with uvicorn."""
        try:
            import uvicorn
        except ImportError as exc:  # pragma: no cover - import guard
            raise RuntimeError("Install SuperQode with the 'a2a' extra") from exc
        uvicorn.run(self.app, host=host, port=port)


async def create_a2a_server(
    agent_config: AgentConfig | None = None,
    server_url: str = "http://127.0.0.1:8000",
    runtime: str | None = None,
    *,
    spec: HarnessSpec | str | Path | None = None,
    controller: HarnessProtocolController | None = None,
    store_path: str | Path = ".superqode/a2a/store.sqlite3",
    task_store_path: str | Path | None = ".superqode/a2a/tasks.sqlite3",
    bearer_token: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    working_directory: str | Path | None = None,
    harness_skill_enabled: bool = True,
    key_secret: str | None = None,
    anonymous_per_minute: int | None = None,
    keyed_per_minute: int | None = None,
    global_per_day: int | None = None,
) -> A2AServer:
    """Create an A2A server over a real HarnessSpec or supplied controller.

    ``agent_config`` remains accepted for source compatibility; its provider,
    model, and working directory become the A2A session defaults.  New callers
    should pass ``spec`` (or a preconfigured ``controller``) explicitly.
    """
    from superqode.harness import (
        CoreHarnessProtocolAdapter,
        HarnessProtocolController,
        create_harness_store,
        get_harness_template,
        load_harness_spec,
    )

    if controller is None:
        if spec is None:
            loaded_spec = get_harness_template("coding")
        elif isinstance(spec, (str, Path)):
            loaded_spec = load_harness_spec(spec)
        else:
            loaded_spec = spec
        if runtime:
            from dataclasses import replace

            loaded_spec = replace(
                loaded_spec,
                runtime=replace(loaded_spec.runtime, backend=runtime),
            )
        adapter = CoreHarnessProtocolAdapter(loaded_spec, adapter_id="superqode")
        controller = HarnessProtocolController(
            [adapter], store=create_harness_store("sqlite", store_path)
        )

    provider = provider or (agent_config.provider if agent_config else "openai")
    model = model or (agent_config.model if agent_config else "gpt-5.4")
    working_directory = Path(
        working_directory or (agent_config.working_directory if agent_config else Path.cwd())
    )
    return A2AServer(
        controller,
        A2AServerConfig(
            url=server_url,
            provider=provider,
            model=model,
            working_directory=working_directory,
            task_store_path=Path(task_store_path) if task_store_path is not None else None,
            bearer_token=bearer_token,
            key_secret=key_secret,
            harness_skill_enabled=harness_skill_enabled,
            **{
                name: value
                for name, value in (
                    ("anonymous_per_minute", anonymous_per_minute),
                    ("keyed_per_minute", keyed_per_minute),
                    ("global_per_day", global_per_day),
                )
                if value is not None
            },
        ),
    )


def _agent_card(
    controller: HarnessProtocolController, config: A2AServerConfig, sdk: dict[str, Any]
) -> Any:
    # Discovery skill text is product-facing and stable across harness templates.
    # The bound HarnessSpec still controls execution policy and runtime behavior.
    if not controller.descriptors():
        raise ValueError("A2A serving requires at least one Harness Protocol adapter")
    if not (config.harness_skill_enabled or config.shortlist_enabled):
        raise ValueError("A2A serving requires at least one enabled skill")
    skill = sdk["AgentSkill"](
        id=config.skill_id,
        name=config.skill_name,
        description=config.skill_description,
        tags=["coding", "harness", "evaluation", "software-engineering"],
        examples=[
            "Inspect this repository and implement the requested change.",
            "Run this task through the configured SuperQode harness.",
            "Evaluate two coding-agent configurations and compare their evidence.",
        ],
        input_modes=["text/plain"],
        output_modes=["text/plain"],
    )
    skills = [skill] if config.harness_skill_enabled else []
    if config.shortlist_enabled:
        skills.append(
            sdk["AgentSkill"](
                id=config.shortlist_skill_id,
                name=config.shortlist_skill_name,
                description=config.shortlist_skill_description,
                tags=["harness", "recommendation", "evaluation", "discovery"],
                examples=[
                    "Which coding agents in the catalogue are open source?",
                    "Which harness should we shortlist for a Python monorepo?",
                    "We run local models only. What are our options?",
                ],
                input_modes=["text/plain"],
                output_modes=["text/plain", "application/json"],
            )
        )

    kwargs: dict[str, Any] = {}
    if config.bearer_token or config.key_secret:
        # Schemes say Bearer is accepted. Requirements say it is mandatory.
        # An open deployment advertises the scheme so keyed callers know how
        # to send a credential, and omits requirements so host platforms can
        # register with no auth field.
        kwargs["security_schemes"] = {
            "bearer": sdk["SecurityScheme"](
                http_auth_security_scheme=sdk["HTTPAuthSecurityScheme"](
                    description="Bearer token issued by the SuperQode operator",
                    scheme="bearer",
                )
            )
        }
        if not config.allow_anonymous:
            kwargs["security_requirements"] = [
                sdk["SecurityRequirement"](schemes={"bearer": sdk["StringList"]()})
            ]
    # Ordered by preference; A2A clients take the first entry they understand.
    # JSONRPC leads because it is the default binding for A2A clients and the
    # binding every major host platform documents.  The 0.3 entry is what makes
    # the card registrable where only 0.3 is accepted.
    interfaces = [
        sdk["AgentInterface"](
            url=config.url,
            protocol_binding="JSONRPC",
            protocol_version="1.0",
        )
    ]
    if config.legacy_v0_3:
        interfaces.append(
            sdk["AgentInterface"](
                url=config.url,
                protocol_binding="JSONRPC",
                protocol_version="0.3",
            )
        )
    interfaces.append(
        sdk["AgentInterface"](
            url=config.url,
            protocol_binding="HTTP+JSON",
            protocol_version="1.0",
        )
    )
    return sdk["AgentCard"](
        name=config.name,
        description=config.description,
        supported_interfaces=interfaces,
        provider=sdk["AgentProvider"](
            organization="Superagentic AI",
            url="https://super-agentic.ai",
        ),
        version=config.version,
        documentation_url=config.documentation_url,
        icon_url=config.icon_url,
        capabilities=sdk["AgentCapabilities"](
            streaming=config.streaming,
            push_notifications=config.push_notifications,
        ),
        default_input_modes=["text/plain"],
        default_output_modes=["text/plain"],
        skills=skills,
        **kwargs,
    )


def _AccessContextBuilder(sdk: dict[str, Any]) -> Any:
    """Build a call-context builder that carries the access decision through.

    The middleware has already decided who is calling; this copies that onto
    the SDK's own call context so the executor sees it without reaching for
    the raw request.
    """
    base = sdk["DefaultServerCallContextBuilder"]

    class _Builder(base):  # type: ignore[misc, valid-type]
        def build(self, request: Any) -> Any:
            context = super().build(request)
            decision = getattr(request.state, "superqode_access", None)
            if isinstance(decision, AccessDecision):
                context.state.update(decision.to_state())
            return context

    return _Builder()


def caller_tier(context: Any) -> str:
    """Return the tier of the caller behind an executor context."""
    call_context = getattr(context, "call_context", None)
    state = getattr(call_context, "state", None) or {}
    return str(state.get("tier") or ANONYMOUS_TIER)


def _requested_skill(context: Any) -> str:
    """Read an explicitly requested skill id from a request.

    A2A carries no skill routing field, so callers name the skill in metadata.
    ``RequestContext.metadata`` exposes the request-level metadata only, and a
    client may just as reasonably attach it to the message, so both are read.
    """
    sources: list[dict[str, Any]] = []
    request_metadata = getattr(context, "metadata", None)
    if isinstance(request_metadata, dict):
        sources.append(request_metadata)

    message = getattr(context, "message", None)
    message_metadata = getattr(message, "metadata", None)
    if message_metadata is not None:
        try:
            sources.append(sdk_message_to_dict(message_metadata))
        except Exception:  # pragma: no cover - defensive, metadata is optional
            pass

    for source in sources:
        value = source.get("superqodeSkill") or source.get("superqode_skill") or source.get("skill")
        if value:
            return str(value).strip()
    return ""


def _required_id(value: str | None, label: str) -> str:
    if not value:
        raise ValueError(f"A2A request did not provide a {label} id")
    return value


def sdk_message_to_dict(message: Any) -> dict[str, Any]:
    """Convert an official A2A protobuf message to its JSON wire shape."""
    from google.protobuf.json_format import MessageToDict

    return MessageToDict(message)


def _a2a_sdk() -> dict[str, Any]:
    try:
        from a2a.server.request_handlers import DefaultRequestHandler
        from a2a.server.routes import (
            add_a2a_routes_to_fastapi,
            create_agent_card_routes,
            create_jsonrpc_routes,
            create_rest_routes,
        )
        from a2a.server.routes.common import DefaultServerCallContextBuilder
        from a2a.server.tasks import DatabaseTaskStore, InMemoryTaskStore, TaskUpdater
        from a2a.types import (
            AgentCapabilities,
            AgentCard,
            AgentInterface,
            AgentProvider,
            AgentSkill,
            HTTPAuthSecurityScheme,
            Part,
            SecurityRequirement,
            SecurityScheme,
            StringList,
            Task,
            TaskState,
            TaskStatus,
        )
        from fastapi import FastAPI
        from fastapi.responses import JSONResponse
        from sqlalchemy.engine import URL
        from sqlalchemy.ext.asyncio import create_async_engine
    except ImportError as exc:  # pragma: no cover - import guard
        raise RuntimeError(
            "A2A support requires the optional dependency: pip install 'superqode[a2a]'"
        ) from exc
    return locals()
