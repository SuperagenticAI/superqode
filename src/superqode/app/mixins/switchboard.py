"""Model/harness switchboard helpers."""

from __future__ import annotations
import shlex
from typing import Any
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---


class SwitchboardMixin:
    """Switchboard option parsing and quick model/harness switching."""

    def _handle_switchboard(self, args: str, log: ConversationLog) -> None:
        """TUI session switchboard over the durable graph."""
        try:
            tokens = shlex.split((args or "").strip())
        except ValueError as exc:
            log.add_error(f"Could not parse :switchboard arguments: {exc}")
            return
        subcommand = tokens[0].lower() if tokens else "graph"
        rest = tokens[1:]

        if subcommand in {"", "graph", "tree", "ls", "list"}:
            self._show_switchboard_graph(log)
        elif subcommand in {"help", "?"}:
            self._show_switchboard_help(log)
        elif subcommand in {"active", "current"}:
            self._switchboard_active(log)
        elif subcommand in {"switch", "select", "resume"}:
            self._switchboard_switch(rest, log)
        elif subcommand == "info":
            self._switchboard_info(rest, log)
        elif subcommand in {"history", "tail"}:
            self._switchboard_history(rest, log)
        elif subcommand in {"children", "child"}:
            self._switchboard_children(rest, log)
        elif subcommand in {"handoff", "send"}:
            self._switchboard_handoff(rest, log)
        elif subcommand in {"fork-agent", "forkagent", "fork"}:
            self._switchboard_fork_agent(rest, log)
        elif subcommand in {"approvals", "approval", "inbox"}:
            self._switchboard_approval_inbox(log)
        elif subcommand in {"share-tree", "share"}:
            self._switchboard_share_tree(rest, log)
        else:
            log.add_info(
                "Usage: :switchboard [graph|switch|info|history|children|handoff|fork-agent|approvals|share-tree]"
            )
    def _switchboard(self):
        from superqode.session.switchboard import SessionSwitchboard

        return SessionSwitchboard(storage_dir=".superqode/sessions")
    def _show_switchboard_help(self, log: ConversationLog) -> None:
        t = Text()
        t.append("\n  Session Tree / Session Switchboard\n\n", style=f"bold {THEME['purple']}")
        commands = [
            (":switchboard", "graph cockpit with active marker, status, approvals, and previews"),
            (
                ":switchboard switch <id>",
                "mark a session active and resume it when local storage can",
            ),
            (":switchboard info <id>", "show graph metadata and child sessions"),
            (":switchboard history <id> [limit]", "show recent transcript messages"),
            (":switchboard children <id>", "list child/fork/agent sessions"),
            (
                ':switchboard handoff <source> --to <target> --goal "..."',
                "deliver context to another session",
            ),
            (
                ':switchboard fork-agent <source> --agent reviewer --goal "..."',
                "fork to a named coding agent",
            ),
            (":switchboard approvals", "show cross-agent approval inbox"),
            (":switchboard share-tree <id> [path]", "export a portable session subtree"),
        ]
        for command, desc in commands:
            t.append(f"  {command:<58}", style=f"bold {THEME['cyan']}")
            t.append(f"{desc}\n", style=THEME["muted"])
        self._show_command_output(log, t)
    def _show_switchboard_graph(self, log: ConversationLog) -> None:
        try:
            switchboard = self._switchboard()
            tree = switchboard.graph_tree()
            active = switchboard.active() or self._current_session_id()
        except Exception as exc:
            log.add_error(f"Could not load switchboard graph: {exc}")
            return

        t = Text()
        t.append("\n  Session Tree / Session Switchboard\n\n", style=f"bold {THEME['purple']}")
        if active:
            t.append("  Active  ", style=THEME["muted"])
            t.append(f"{active}\n\n", style=f"bold {THEME['cyan']}")
        if not tree:
            t.append("  No sessions found yet.\n", style=THEME["muted"])
            t.append("  Start a conversation, then use ", style=THEME["muted"])
            t.append(":switchboard", style=THEME["cyan"])
            t.append(" to control the graph.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return

        def add_node(node: dict[str, Any], prefix: str = "", depth: int = 0) -> None:
            session_id = str(node.get("session_id") or "")
            status = str(node.get("status") or "idle")
            marker = "* " if session_id == active else "  "
            connector = "+- " if depth else ""
            title = str(node.get("title") or "(unnamed)")
            kind = str(node.get("kind") or "session")
            agent = str(node.get("agent_id") or "")
            provider = str(node.get("provider") or "-")
            model = str(node.get("model") or "unknown")
            approvals = int(node.get("pending_approvals_count") or 0)
            preview = " ".join(str(node.get("last_result_preview") or "").split())
            status_style = {
                "running": THEME["warning"],
                "needs_approval": THEME["orange"],
                "error": THEME["error"],
                "closed": THEME["dim"],
            }.get(status, THEME["success"])
            t.append(f"  {prefix}{connector}{marker}", style=THEME["dim"])
            t.append(f"{session_id[:10]:<10}", style=f"bold {THEME['cyan']}")
            t.append(f" {status:<14}", style=f"bold {status_style}")
            t.append(f" {kind:<10}", style=THEME["muted"])
            if agent:
                t.append(f" agent={agent:<12}", style=THEME["purple"])
            if approvals:
                t.append(f" approvals={approvals}", style=f"bold {THEME['orange']}")
            t.append(f"  {title}\n", style=THEME["text"])
            t.append(f"  {prefix}{'   ' if depth else ''}   ", style=THEME["dim"])
            t.append(f"{provider}/{model}", style=THEME["muted"])
            t.append(f"  updated {str(node.get('updated_at') or '')[:19]}", style=THEME["dim"])
            if preview:
                t.append(f"  {preview[:120]}", style=THEME["dim"])
            t.append("\n")
            for child in node.get("children") or []:
                add_node(child, prefix + ("   " if depth else ""), depth + 1)

        for root in tree:
            add_node(root)

        t.append("\n  Keys-as-commands: ", style=THEME["muted"])
        t.append(":sw switch <id>", style=THEME["cyan"])
        t.append("  ", style=THEME["dim"])
        t.append(":sw fork-agent <id> --agent reviewer", style=THEME["cyan"])
        t.append("  ", style=THEME["dim"])
        t.append(":sw approvals", style=THEME["cyan"])
        t.append("\n", style="")
        self._show_command_output(log, t)
    def _switchboard_active(self, log: ConversationLog) -> None:
        active = self._switchboard().active() or self._current_session_id()
        if not active:
            log.add_info("No active switchboard session yet.")
            return
        self._switchboard_info([active], log)
    def _switchboard_switch(self, tokens: list[str], log: ConversationLog) -> None:
        if not tokens:
            self._show_switchboard_graph(log)
            return
        target = tokens[0]
        try:
            record = self._switchboard().switch(target)
        except Exception as exc:
            log.add_error(f"Could not switch session: {exc}")
            return
        log.add_success(f"Active switchboard session -> {record['session_id']}")
        try:
            self._handle_resume_session(record["session_id"], log)
        except Exception:
            pass
    def _switchboard_info(self, tokens: list[str], log: ConversationLog) -> None:
        target = tokens[0] if tokens else ""
        try:
            payload = self._switchboard().info(target)
        except Exception as exc:
            log.add_error(f"Could not load session info: {exc}")
            return
        t = Text()
        t.append("\n  Session Info\n\n", style=f"bold {THEME['purple']}")
        for key in (
            "session_id",
            "title",
            "kind",
            "status",
            "agent_id",
            "parent_session_id",
            "root_session_id",
            "provider",
            "model",
            "message_count",
            "pending_approvals_count",
            "updated_at",
        ):
            value = payload.get(key)
            if value in (None, ""):
                continue
            t.append(f"  {key:<24}", style=THEME["muted"])
            t.append(f"{value}\n", style=THEME["text"])
        children = payload.get("children") or []
        if children:
            t.append("\n  Children\n", style=f"bold {THEME['text']}")
            for child in children:
                t.append(f"    {child['session_id'][:10]:<12}", style=f"bold {THEME['cyan']}")
                t.append(f"{child.get('status') or '-':<14}", style=THEME["muted"])
                t.append(f"{child.get('agent_id') or '-':<16}", style=THEME["purple"])
                t.append(f"{child.get('title') or ''}\n", style=THEME["text"])
        self._show_command_output(log, t)
    def _switchboard_history(self, tokens: list[str], log: ConversationLog) -> None:
        target = tokens[0] if tokens else ""
        limit = 12
        if len(tokens) > 1:
            try:
                limit = int(tokens[1])
            except ValueError:
                pass
        try:
            payload = self._switchboard().history(target, limit=limit)
        except Exception as exc:
            log.add_error(f"Could not load session history: {exc}")
            return
        t = Text()
        t.append(f"\n  History {payload['session_id']}\n\n", style=f"bold {THEME['purple']}")
        for message in payload.get("messages") or []:
            role = str(message.get("role") or "?")
            content = " ".join(str(message.get("content") or "").split())
            t.append(f"  {role:<10}", style=f"bold {THEME['cyan']}")
            t.append(f"{content[:220]}\n", style=THEME["text"])
        self._show_command_output(log, t)
    def _switchboard_children(self, tokens: list[str], log: ConversationLog) -> None:
        target = tokens[0] if tokens else ""
        try:
            children = self._switchboard().children(target)
        except Exception as exc:
            log.add_error(f"Could not load child sessions: {exc}")
            return
        if not children:
            log.add_info("No child sessions.")
            return
        t = Text()
        t.append("\n  Child Sessions\n\n", style=f"bold {THEME['purple']}")
        for child in children:
            t.append(f"  {child['session_id'][:10]:<12}", style=f"bold {THEME['cyan']}")
            t.append(f"{child.get('status') or '-':<14}", style=THEME["muted"])
            t.append(f"{child.get('agent_id') or '-':<16}", style=THEME["purple"])
            t.append(f"{child.get('title') or ''}\n", style=THEME["text"])
        self._show_command_output(log, t)
    @staticmethod
    def _parse_switchboard_options(tokens: list[str]) -> tuple[list[str], dict[str, str | bool]]:
        positionals: list[str] = []
        options: dict[str, str | bool] = {}
        i = 0
        while i < len(tokens):
            token = tokens[i]
            if token.startswith("--"):
                key = token[2:].replace("-", "_")
                if i + 1 < len(tokens) and not tokens[i + 1].startswith("--"):
                    options[key] = tokens[i + 1]
                    i += 2
                else:
                    options[key] = True
                    i += 1
            else:
                positionals.append(token)
                i += 1
        return positionals, options
    def _switchboard_handoff(self, tokens: list[str], log: ConversationLog) -> None:
        positionals, options = self._parse_switchboard_options(tokens)
        source = positionals[0] if positionals else ""
        target = str(
            options.get("to") or options.get("target") or options.get("target_session_id") or ""
        )
        goal = str(options.get("goal") or " ".join(positionals[1:]) or "")
        reason = str(options.get("reason") or "")
        try:
            if target:
                payload = self._switchboard().handoff_to_session(
                    source, target, goal=goal, reason=reason
                )
                log.add_success(
                    f"Delivered handoff {payload['id']} to {payload['target_session_id']}"
                )
            else:
                packet = self._switchboard().make_handoff(
                    source,
                    target_agent=str(options.get("agent") or ""),
                    goal=goal,
                    reason=reason,
                )
                self._show_command_output(log, Text(packet.to_message()))
        except Exception as exc:
            log.add_error(f"Could not create handoff: {exc}")
    def _switchboard_fork_agent(self, tokens: list[str], log: ConversationLog) -> None:
        positionals, options = self._parse_switchboard_options(tokens)
        source = positionals[0] if positionals else ""
        agent = str(options.get("agent") or (positionals[1] if len(positionals) > 1 else ""))
        if not agent:
            log.add_info(
                'Usage: :switchboard fork-agent [source] --agent reviewer --goal "review this"'
            )
            return
        try:
            payload = self._switchboard().fork_to_agent(
                source,
                agent=agent,
                new_session_id=str(options.get("session_id") or ""),
                title=str(options.get("title") or ""),
                goal=str(options.get("goal") or ""),
            )
        except Exception as exc:
            log.add_error(f"Could not fork to agent: {exc}")
            return
        log.add_success(
            f"Forked to {payload['session']['session_id']} for {agent}; handoff {payload['handoff']['id']}"
        )
    def _switchboard_approval_inbox(self, log: ConversationLog) -> None:
        try:
            sessions = self._switchboard().list_sessions()
        except Exception as exc:
            log.add_error(f"Could not load approval inbox: {exc}")
            return
        blocked = [
            item
            for item in sessions
            if item.get("status") == "needs_approval"
            or int(item.get("pending_approvals_count") or 0) > 0
        ]
        t = Text()
        t.append("\n  Approval Inbox\n\n", style=f"bold {THEME['orange']}")
        if not blocked:
            t.append("  No child sessions are waiting for approval.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return
        for item in blocked:
            t.append(f"  {item['session_id'][:10]:<12}", style=f"bold {THEME['cyan']}")
            t.append(f"{item.get('status') or '-':<16}", style=f"bold {THEME['orange']}")
            t.append(
                f"approvals={item.get('pending_approvals_count') or 0:<3}", style=THEME["muted"]
            )
            t.append(f" {item.get('agent_id') or '-'}", style=THEME["purple"])
            t.append(f"  {item.get('title') or ''}\n", style=THEME["text"])
        t.append("\n  Use the parent session's ", style=THEME["muted"])
        t.append(":approve", style=THEME["cyan"])
        t.append(" / ", style=THEME["muted"])
        t.append(":reject", style=THEME["cyan"])
        t.append(" controls, or switch to the parent session first.\n", style=THEME["muted"])
        self._show_command_output(log, t)
    def _switchboard_share_tree(self, tokens: list[str], log: ConversationLog) -> None:
        session_arg, path_arg = self._parse_share_session_and_path(tokens)
        try:
            session_id = self._resolve_share_session_id(session_arg)
            artifact_path = self._write_share_artifact(session_id, path_arg, include_tree=True)
        except Exception as exc:
            log.add_error(f"Could not share session tree: {exc}")
            return
        log.add_success(f"Created share-tree artifact -> {artifact_path}")
