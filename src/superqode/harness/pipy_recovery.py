"""Opt-in WorkOrder coding recovery through committed model/tool boundaries.

Reconstruct the original branch and reuse committed completions with their
original tool-call IDs. An unknown provider request or external effect blocks.
This is local process recovery, not a provider exactly-once guarantee.
"""

from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import asdict, replace, fields
from pathlib import Path

from superqode.execution_recovery import check_recovery_workspace, input_fingerprint
from superqode.pipy.messages import TextContent
from superqode.pipy.provider_events import (
    AssistantStartEvent,
    AssistantDoneEvent,
    AssistantErrorEvent,
    TextDeltaEvent,
)
from superqode.pipy.session.codec import encode_message, decode_message


class PiPyRecoveryRequired(ValueError):
    pass


class PiPyRunRecovery:
    def __init__(self, scope, coding, config):
        self.scope = replace(scope, workspace_root=str(coding.cwd))
        self.coding = coding
        self.config = config
        self.original_stream = coding.harness._stream_fn
        self.original_loop_config = coding.harness._create_loop_config
        self.index = 0
        self.failure = None

    def _rows(self):
        return self.scope.store.invocations(self.scope.work_order_id, self.scope.task_id)

    def _begin(self, identity, operation, fingerprint, *, workspace="", safe=False):
        s = self.scope
        return s.store.begin_invocation(
            s.work_order_id,
            s.task_id,
            worker_id=s.worker_id,
            attempt=s.attempt,
            invocation_id=identity,
            operation=operation,
            fingerprint=fingerprint,
            replay_safe=safe,
            workspace=workspace,
        )

    def _finish(self, identity, result, workspace):
        s = self.scope
        s.store.finish_invocation(
            s.work_order_id,
            s.task_id,
            worker_id=s.worker_id,
            attempt=s.attempt,
            invocation_id=identity,
            result=result,
            workspace=workspace,
        )

    def _uncertain(self, identity):
        s = self.scope
        with suppress(Exception):
            s.store.mark_invocation_uncertain(
                s.work_order_id,
                s.task_id,
                worker_id=s.worker_id,
                attempt=s.attempt,
                invocation_id=identity,
            )

    async def prepare(self, prompt, images=None):
        try:
            workspace = await check_recovery_workspace(self.scope)
            identity = "pipy.run.start"
            previous = next((r for r in self._rows() if r["invocation_id"] == identity), None)
            fingerprint = input_fingerprint(
                {
                    "prompt": prompt,
                    **({"images": [asdict(image) for image in images]} if images else {}),
                    "config": self.config,
                    "model": asdict(self.coding.harness.get_model()),
                    "tools": {t.name: dict(t.parameters) for t in self.coding.harness.get_tools()},
                    "cwd": str(self.coding.cwd),
                    "contract": 1,
                }
            )
            admission = self._begin(
                identity,
                "pipy.run",
                fingerprint,
                workspace=previous["workspace"] if previous else workspace,
                safe=True,
            )
            if admission["action"] == "reuse":
                saved = admission["result"]
                if str(self.coding.session_path) != saved["path"]:
                    raise ValueError("PiPy session storage moved")
                await self.coding.harness._session.move_to(saved["leaf"])
            else:
                self._finish(
                    identity,
                    {
                        "path": str(self.coding.session_path),
                        "leaf": await self.coding.harness._session.get_leaf_id(),
                    },
                    workspace,
                )
            self.coding.harness._stream_fn = self.stream
            original = self.original_loop_config
            self.coding.harness._create_loop_config = lambda *args: replace(
                original(*args), tool_execution="sequential"
            )
        except ValueError as error:
            raise PiPyRecoveryRequired(str(error)) from error

    def restore(self):
        self.coding.harness._stream_fn = self.original_stream
        self.coding.harness._create_loop_config = self.original_loop_config

    def _policy(self, phase, model, arguments):
        from superqode.governance import evaluate_active_policy

        decision = evaluate_active_policy(
            phase, provider=model.provider, runtime="pipy", arguments=arguments
        )
        if decision.action != "allow":
            raise PiPyRecoveryRequired(f"Current policy {decision.action}: {decision.reason}")

    async def stream(self, model, context, options):
        self.index += 1
        self.scope.invocation_namespace = f"model-{self.index}"
        identity = f"pipy.model/{self.index}"
        try:
            workspace = await check_recovery_workspace(self.scope)
            self._policy("request", model, {"model": model.id, "prompt": context.system_prompt})
            messages = [encode_message(m) for m in context.messages]
            # Timestamps are rebuilt during transcript replay; tool arguments,
            # signatures, usage and content remain part of the identity.
            for message in messages:
                message.pop("timestamp", None)
            option_values = {
                field.name: getattr(options, field.name)
                for field in fields(options)
                if field.name not in {"api_key", "signal", "headers", "session_id"}
            }
            fingerprint = input_fingerprint(
                {
                    "model": asdict(model),
                    "system": context.system_prompt,
                    "messages": messages,
                    "tools": {t.name: dict(t.parameters) for t in context.tools or []},
                    "options": option_values,
                }
            )
            row = next((r for r in self._rows() if r["invocation_id"] == identity), None)
            order = self.scope.store.get(self.scope.work_order_id)
            if not (row and row["status"] == "completed") and (
                order.budget.max_cost_usd is not None or order.budget.max_tokens is not None
            ):
                raise PiPyRecoveryRequired(
                    "New model requests cannot reserve unknown spend against a cost or token budget"
                )
            admission = self._begin(
                identity,
                "pipy.model",
                fingerprint,
                workspace=row["workspace"] if row and row["status"] == "completed" else workspace,
            )
            if admission["action"] == "reuse":
                message = decode_message(admission["result"]["message"])
                self._policy("response", model, {"output": message.text, "model": model.id})
                return self._replay(message)
            response = self.original_stream(model, context, options)
            if hasattr(response, "__await__"):
                response = await response
            return self._record(response, identity, model)
        except BaseException as error:
            self.failure = PiPyRecoveryRequired(str(error))
            raise self.failure from error

    async def _record(self, response, identity, model):
        committed = False
        try:
            async for event in response:
                if isinstance(event, (AssistantDoneEvent, AssistantErrorEvent)):
                    message = (
                        event.message if isinstance(event, AssistantDoneEvent) else event.error
                    )
                    self._policy("response", model, {"output": message.text, "model": model.id})
                    workspace = await check_recovery_workspace(self.scope)
                    self._finish(identity, {"message": encode_message(message)}, workspace)
                    committed = True
                yield event
            if not committed:
                raise PiPyRecoveryRequired("Provider stream ended without a committed completion")
        except BaseException as error:
            if committed and isinstance(error, GeneratorExit):
                raise
            if not committed:
                self._uncertain(identity)
            self.failure = PiPyRecoveryRequired(str(error))
            raise self.failure from error

    async def _replay(self, message):
        yield AssistantStartEvent(partial=replace(message, content=[]))
        for index, block in enumerate(message.content):
            if isinstance(block, TextContent):
                yield TextDeltaEvent(content_index=index, delta=block.text, partial=message)
        if message.stop_reason in {"error", "aborted"}:
            yield AssistantErrorEvent(reason=message.stop_reason, error=message)
        else:
            yield AssistantDoneEvent(reason=message.stop_reason, message=message)
