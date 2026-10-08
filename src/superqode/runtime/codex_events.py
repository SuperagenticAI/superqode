"""Map Codex's public wire events without importing an optional SDK."""

from __future__ import annotations

from typing import Any

from superqode.harness.events import HarnessEvent


class CodexEvents:
    def __init__(self, baseline=None):
        self.text_items: set[str] = set()
        self.usage: dict[str, Any] = {}
        self._previous_total = baseline
        self._usage_incomplete = False

    def map(self, method: str, data: dict[str, Any]) -> list[HarnessEvent]:
        def event(kind, **payload):
            return [HarnessEvent(type=kind, data={"source_event": method, **payload})]

        item_id = data.get("itemId")
        if method == "thread/status/changed":
            return event("run_status", status=data.get("status") or {})
        if method in {"hook/started", "hook/completed"}:
            run = data.get("run") or {}
            return event(
                "hook",
                run=run,
                text=f"Codex hook {run.get('eventName', '')}: {run.get('status', '')}",
            )
        if method == "error":
            error = data.get("error") or {}
            return event(
                "error",
                error=error.get("message", "Codex error"),
                error_info=error.get("codexErrorInfo"),
                will_retry=data.get("willRetry", False),
                details=error,
            )
        if method in {"item/agentMessage/delta", "item/plan/delta"}:
            if item_id:
                self.text_items.add(item_id)
            return event("model_delta", text=data.get("delta", ""), item_id=item_id)
        if method == "item/reasoning/summaryTextDelta":
            return event("thinking", text=data.get("delta", ""), item_id=item_id)
        if method in {"item/commandExecution/outputDelta", "item/fileChange/outputDelta"}:
            return event(
                "tool_delta",
                tool_name="bash" if "commandExecution" in method else "patch",
                tool_call_id=item_id,
                text=data.get("delta", ""),
            )
        if method in {"turn/diff/updated", "item/fileChange/patchUpdated"}:
            return event(
                "diff",
                tool_name="patch",
                tool_call_id=item_id,
                changes=data.get("changes", []),
                diff_text=data.get("diff", ""),
            )
        if method == "turn/plan/updated":
            todos = [
                {
                    "id": str(i),
                    "content": step.get("step", ""),
                    "status": {"inProgress": "in_progress"}.get(
                        step.get("status"), step.get("status", "pending")
                    ),
                    "priority": "medium",
                }
                for i, step in enumerate(data.get("plan", []), 1)
            ]
            return event("plan_update", todos=todos, explanation=data.get("explanation", ""))
        if method == "thread/tokenUsage/updated":
            reported = data.get("tokenUsage") or {}
            total, last = reported.get("total"), reported.get("last")
            if isinstance(total, dict):
                # Totals include every model call, including tool iterations.
                previous = self._previous_total
                if previous is None:
                    if not isinstance(last, dict):
                        self._previous_total = total
                        self._usage_incomplete = True
                        return event("usage", usage={}, token_usage=reported)
                    previous = {
                        key: max(0, value - (last or {}).get(key, value))
                        for key, value in total.items()
                        if isinstance(value, int)
                    }
                for key, value in total.items():
                    if isinstance(value, int):
                        delta = value - previous.get(key, 0)
                        if delta < 0:
                            delta = (last or {}).get(key)
                            if delta is None:
                                self._usage_incomplete = True
                                continue
                        self.usage[key] = self.usage.get(key, 0) + delta
                self._previous_total = total
            elif isinstance(last, dict):
                for key, value in last.items():
                    if isinstance(value, int):
                        self.usage[key] = self.usage.get(key, 0) + value
            return event("usage", usage=self.usage, token_usage=data.get("tokenUsage", {}))
        if method == "turn/completed":
            turn = data.get("turn", {})
            error = turn.get("error") or {}
            return event(
                "turn_complete",
                status=turn.get("status", ""),
                error=error.get("message", ""),
                error_info=error.get("codexErrorInfo"),
                usage=None
                if self._usage_incomplete
                else {
                    target: self.usage[source]
                    for source, target in {
                        "inputTokens": "input_tokens",
                        "outputTokens": "output_tokens",
                        "cachedInputTokens": "cached_input_tokens",
                        "reasoningOutputTokens": "reasoning_output_tokens",
                        "totalTokens": "total_tokens",
                    }.items()
                    if source in self.usage
                }
                or None,
            )
        if method in {"warning", "error", "configWarning", "model/rerouted"}:
            error = data.get("error") or {}
            text = data.get("message") or data.get("summary") or error.get("message")
            if method == "model/rerouted":
                text = f"Codex model changed: {data.get('fromModel')} → {data.get('toModel')}"
            return event("thinking", text=text or "Codex status updated")
        if method not in {"item/started", "item/completed"}:
            return []
        item = data.get("item") or {}
        kind = item.get("type")
        completed = method == "item/completed"
        item_id = item.get("id")
        if kind in {"agentMessage", "plan"}:
            if completed and item_id not in self.text_items:
                return event("model_delta", text=item.get("text", ""), item_id=item_id)
            return []
        if kind == "reasoning":
            return []  # Summaries stream separately; never expose hidden reasoning.
        status = item.get("status", "")
        if kind == "commandExecution":
            name, args = "bash", {"command": item.get("command", "")}
            output = item.get("aggregatedOutput") or ""
            success = status == "completed" and item.get("exitCode") in {None, 0}
        elif kind == "fileChange":
            changes = item.get("changes", [])
            name, args = "patch", {"path": changes[0].get("path", "") if changes else ""}
            output = "\n".join(str(change.get("diff") or "") for change in changes)
            success = status == "completed"
        elif kind == "mcpToolCall":
            name = f"mcp:{item.get('server', '')}/{item.get('tool', '')}"
            arguments = item.get("arguments")
            args = arguments if isinstance(arguments, dict) else {"input": arguments}
            output = item.get("result") or ""
            success = status == "completed"
        elif kind == "dynamicToolCall":
            name = f"codex:{item.get('tool', 'tool')}"
            arguments = item.get("arguments")
            args = arguments if isinstance(arguments, dict) else {"input": arguments}
            output = item.get("contentItems") or ""
            success = item.get("success") is True
        elif kind == "webSearch":
            name = "web_search"
            args = {"query": item.get("query", ""), "action": item.get("action")}
            output, success = item.get("results") or item.get("query", ""), True
        elif kind == "collabAgentToolCall":
            name = f"codex:{item.get('tool', 'agent')}"
            args = {
                "prompt": item.get("prompt", ""),
                "agent_ids": item.get("receiverThreadIds", []),
            }
            output, success = item.get("agentsStates") or "", status == "completed"
        elif kind in {"enteredReviewMode", "exitedReviewMode"}:
            return event(
                "model_delta" if kind == "exitedReviewMode" and completed else "thinking",
                text=item.get("review", "Codex review started"),
            )
        elif kind == "contextCompaction":
            return event("thinking", text="Codex compacted context") if completed else []
        else:
            return []
        common = {"tool_name": name, "tool_call_id": item_id, "arguments": args}
        if not completed:
            return event("tool_call", **common)
        return event(
            "tool_result",
            **common,
            **(
                {key: args[key] for key in ("command", "path") if key in args}
                if kind in {"commandExecution", "fileChange"}
                else {}
            ),
            success=success,
            output=output,
            status=status,
            error=item.get("error"),
            changes=item.get("changes", []),
            exit_code=item.get("exitCode"),
        )
