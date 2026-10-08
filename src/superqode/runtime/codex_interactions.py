"""Host-owned approval and input handling shared by Codex transports."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections import deque
from urllib.parse import urlsplit

from superqode.tools.approval_receipts import ApprovalReceipt, argument_digest, policy_revision
from superqode.tools.permissions import Permission
from superqode.tools.question_tool import Question, QuestionType, get_question_handler


class CodexInteractions:
    @staticmethod
    def _app_reviewer_overrides(apps):
        # RPC config keys use dot-separated paths, not TOML-quoted paths.
        # A nested value also preserves app ids containing dots or quotes.
        return {"apps": {key: {"approvals_reviewer": "user"} for key in {"_default", *apps}}}

    @staticmethod
    def _cancelled_server_request(method):
        if method == "item/tool/requestUserInput":
            return {"answers": {}}
        if method == "mcpServer/elicitation/request":
            return {"action": "cancel", "content": None}
        if method == "item/permissions/requestApproval":
            return {"permissions": {}, "scope": "turn"}
        if method == "item/tool/call":
            return {
                "success": False,
                "contentItems": [{"type": "inputText", "text": "SuperQode tool cancelled"}],
            }
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            return {"decision": "cancel"}
        raise RuntimeError(f"SuperQode does not support Codex server request {method}")

    def _init_interactions(self):
        self.approval_receipts = deque(maxlen=200)
        self._session_consents = set()

    def _consent_key(self, tool, args):
        # RPC ids/timestamps change between calls. Consent binds actual scope,
        # host policy and permission configuration, never a blanket tool grant.
        rpc_metadata = (
            {
                "itemId",
                "turnId",
                "threadId",
                "approvalId",
                "callId",
                "availableDecisions",
                "startedAtMs",
            }
            if tool in {"bash", "patch", "network", "codex_permissions", "mcp_elicitation"}
            else set()
        )
        if tool in {"bash", "patch", "network"}:
            # Codex's explanation is presentation metadata. The action still
            # binds command, cwd, paths, destinations and requested permissions.
            rpc_metadata.add("reason")
        scope = {
            key: value
            for key, value in args.items()
            if key not in rpc_metadata | {"_codex_call_id", "_codex_available_decisions"}
        }
        if tool == "network":
            from superqode.agent.network_policy import strict_mode, load_allowlist

            scope["networkPolicy"] = {
                "strict": strict_mode(),
                "allowlist": sorted(load_allowlist()),
            }
        config = vars(self._permission_manager.config) if self._permission_manager else {}
        return argument_digest(
            {"tool": tool, "scope": scope, "policy": policy_revision(), "permissions": config}
        )

    async def _approval_choice(self, tool, arguments, permission, *, choices=None):
        if permission == Permission.DENY:
            return "decline"
        key = self._consent_key(tool, arguments)
        cached = key in self._session_consents and (choices is None or "accept" in choices)
        decision = "accept" if permission == Permission.ALLOW or cached else "decline"
        revision = policy_revision()
        if permission == Permission.ASK and not cached and self._approval_callback:
            payload = {
                **arguments,
                "_codex_available_decisions": choices
                or ["accept", "acceptForSession", "decline", "cancel"],
            }
            if inspect.iscoroutinefunction(self._approval_callback):
                value = await self._approval_callback(tool, payload)
            else:
                value = await asyncio.to_thread(self._approval_callback, tool, payload)
                if inspect.isawaitable(value):
                    value = await value
            decision = (
                "accept"
                if value is True
                else "decline"
                if value is False or value is None
                else value
            )
            if isinstance(decision, dict) and set(decision) == {"decision"}:
                decision = decision["decision"]
        available = (
            choices if choices is not None else ["accept", "acceptForSession", "decline", "cancel"]
        )
        if (
            decision not in available
            or revision != policy_revision()
            or key != self._consent_key(tool, arguments)
        ):
            return "decline"
        if isinstance(decision, dict):
            # Persistent Codex rules always need a separate explicit human confirmation.
            handler = get_question_handler()
            if handler is None:
                return "decline"
            confirmed = await handler(
                Question(
                    question="Apply this persistent Codex rule?\n" + json.dumps(decision, indent=2),
                    question_type=QuestionType.CHOICE,
                    options=["Decline", "Apply rule"],
                    allow_custom=False,
                )
            )
            return (
                decision
                if confirmed.value == "Apply rule"
                and revision == policy_revision()
                and key == self._consent_key(tool, arguments)
                else "decline"
            )
        if decision in {"accept", "acceptForSession"}:
            invocation = str(
                arguments.get("approvalId")
                or arguments.get("itemId")
                or arguments.get("_codex_call_id")
                or arguments.get("callId")
                or key
            )
            receipt = ApprovalReceipt(invocation, tool, argument_digest(arguments), revision)
            self.approval_receipts.append(receipt)
            if decision == "acceptForSession":
                self._session_consents.add(key)
                # Keep Codex asking the host so changed policies still apply.
                # Only SuperQode's exact-scope consent cache skips the UI.
                return "accept"
        return decision

    async def _handle_server_request(self, method, params):
        if method in {"item/commandExecution/requestApproval", "item/fileChange/requestApproval"}:
            item = self._items.get(params.get("itemId"), {})
            changes = item.get("changes") or params.get("changes") or []
            arguments = {
                **params,
                "command": params.get("command") or item.get("command", ""),
                "path": params.get("path") or (changes[0].get("path", "") if changes else ""),
                "changes": changes,
            }
            network = params.get("networkApprovalContext")
            tool = "network" if network else "bash" if "commandExecution" in method else "patch"
            if network:
                from superqode.agent.network_policy import check_destination, strict_mode

                destination = check_destination(
                    network.get("host", ""), network.get("protocol", "")
                )
                if destination is None:
                    return {"decision": "decline"}
                arguments.update(destination)
                if arguments["network_status"] == "untrusted" and strict_mode():
                    return {"decision": "decline"}
            if tool == "bash" and not arguments["command"]:
                return {"decision": "decline"}
            paths = [change.get("path") for change in changes] or [arguments["path"]]
            if tool == "patch" and not all(paths):
                return {"decision": "decline"}
            permissions = (
                [
                    self._permission_manager.check_permission(tool, {**arguments, "path": path})
                    for path in paths
                ]
                if tool == "patch"
                else [self._permission_manager.check_permission(tool, arguments)]
            )
            permission = (
                Permission.DENY
                if Permission.DENY in permissions
                else Permission.ASK
                if Permission.ASK in permissions
                else Permission.ALLOW
            )
            if (
                permission == Permission.ALLOW
                and self._permission_manager.config.get_permission(tool) == Permission.ASK
            ):
                permission = Permission.ASK
            return {
                "decision": await self._approval_choice(
                    tool, arguments, permission, choices=params.get("availableDecisions")
                )
            }
        if method == "item/tool/requestUserInput":
            handler = get_question_handler()
            if handler is None:
                raise RuntimeError(
                    "Codex requested user input outside an interactive SuperQode session"
                )
            answers = {}
            for question in params.get("questions", []):
                options = question.get("options") or []
                try:
                    answer = await handler(
                        Question(
                            question=question.get("question", ""),
                            question_type=QuestionType.CHOICE if options else QuestionType.TEXT,
                            options=[option["label"] for option in options],
                            allow_custom=question.get("isOther", True),
                        )
                    )
                except asyncio.CancelledError:
                    if asyncio.current_task().cancelling():
                        raise
                    return {"answers": {}}
                values = answer.value if isinstance(answer.value, list) else [str(answer.value)]
                answers[question["id"]] = {"answers": values}
            return {"answers": answers}
        if method == "mcpServer/elicitation/request":
            return await self._mcp_elicitation(params)
        if method == "item/permissions/requestApproval":
            # Permission profiles can grant unobserved reads, writes and egress.
            # They require explicit scoped human consent, even in auto mode.
            permissions = params.get("permissions") or {}
            handler = get_question_handler()
            permission = self._permission_manager.check_permission("codex_permissions", params)
            if not permissions or handler is None or permission == Permission.DENY:
                return {"permissions": {}, "scope": "turn"}
            revision = policy_revision()
            key = self._consent_key("codex_permissions", params)
            answer = await handler(
                Question(
                    question="Grant Codex these additional permissions for this turn?\n"
                    + json.dumps(permissions, indent=2)
                    + "\n"
                    + str(params.get("reason") or ""),
                    question_type=QuestionType.CHOICE,
                    options=["Decline", "Approve this turn"],
                    allow_custom=False,
                )
            )
            return {
                "permissions": permissions
                if answer.value == "Approve this turn"
                and revision == policy_revision()
                and key == self._consent_key("codex_permissions", params)
                and self._permission_manager.check_permission("codex_permissions", params)
                != Permission.DENY
                else {},
                "scope": "turn",
            }
        if method == "item/tool/call" and hasattr(self, "_dynamic_tool_call"):
            return await self._dynamic_tool_call(params)
        raise RuntimeError(f"SuperQode does not support Codex server request {method}")

    async def _mcp_elicitation(self, params):
        handler = get_question_handler()
        cancelled = {"action": "cancel", "content": None}
        if handler is None:
            return cancelled
        permission = self._permission_manager.check_permission("mcp_elicitation", params)
        if permission == Permission.DENY:
            return {"action": "decline", "content": None}
        key = self._consent_key("mcp_elicitation", params)
        mode = params.get("mode", "form")
        if mode not in {"form", "openai/form", "openaiForm", "url"}:
            return cancelled
        context = f"Codex MCP server {params.get('serverName', '')}: {params.get('message', '')}"
        if mode == "url":
            url = params.get("url", "")
            parsed = urlsplit(url)
            if (
                parsed.scheme not in {"https", "http"}
                or not parsed.hostname
                or parsed.username
                or parsed.password
            ):
                return cancelled
            answer = await handler(
                Question(
                    question=context
                    + "\nOpen this URL yourself and confirm only after completing it:\n"
                    + url,
                    question_type=QuestionType.CHOICE,
                    options=["Cancel", "Completed", "Decline"],
                    allow_custom=False,
                )
            )
            if key != self._consent_key("mcp_elicitation", params):
                return cancelled
            return {
                "action": {"Completed": "accept", "Decline": "decline"}.get(answer.value, "cancel"),
                "content": None,
            }
        schema = params.get("requestedSchema") or {}
        answer = await handler(
            Question(
                question=context + "\nShare form data with this MCP server?",
                question_type=QuestionType.CHOICE,
                options=["Cancel", "Continue", "Decline"],
                allow_custom=False,
            )
        )
        if answer.value != "Continue":
            return {"action": "decline" if answer.value == "Decline" else "cancel", "content": None}
        # JSON entry supports arbitrary form shapes, including OpenAI form mode;
        # validate the complete payload before anything is returned to the server.
        answer = await handler(
            Question(
                question=context
                + "\nEnter form data as JSON matching:\n"
                + json.dumps(schema, indent=2)
            )
        )
        try:
            import jsonschema

            content = json.loads(answer.value) if isinstance(answer.value, str) else answer.value
            jsonschema.validate(content, schema)
        except (ValueError, TypeError, jsonschema.ValidationError, jsonschema.SchemaError):
            return cancelled
        if key != self._consent_key("mcp_elicitation", params):
            return cancelled
        return {"action": "accept", "content": content}
