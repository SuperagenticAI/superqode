"""Agent-factory workflow commands and helpers."""

from __future__ import annotations
from rich.text import Text
from superqode.app.constants import (
    THEME,
)
from superqode.app.widgets import (
    ConversationLog,
)

# --- helpers extracted from app_main (A1) ---


class FactoryMixin:
    """Factory mode/route/fork commands and status helpers."""

    def _factory_help(self, log: ConversationLog) -> None:
        t = Text()
        t.append("\n  Software Factory\n\n", style=f"bold {THEME['purple']}")
        commands = [
            (":factory", "show current model/harness/route lineage"),
            (":factory init-policy", "create .superqode/factory.yaml with local-first defaults"),
            (":factory policy", "show merged factory policy and policy path"),
            (
                ":factory routes",
                "list private, cheap, best, review, long-context, no-subscription routes",
            ),
            (
                ":factory mode no-subscription",
                "prefer local OSS/BYOK and avoid subscription-only paths",
            ),
            (
                ":factory switch-model local/qwen3-coder",
                "record model/provider switch on the active session",
            ),
            (
                ":factory switch-harness coding",
                "record harness/orchestration switch on the active session",
            ),
            (
                ":factory fork-model --model local/deepseek --role coder",
                "fork work to another model worker",
            ),
            (
                ":factory fork-harness --harness review --role reviewer",
                "fork work to another harness worker",
            ),
            (":factory lineage", "show model/harness/mode changes over time"),
        ]
        for command, desc in commands:
            t.append(f"  {command:<62}", style=f"bold {THEME['cyan']}")
            t.append(f"{desc}\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _factory_status(self, tokens: list[str], log: ConversationLog) -> None:
        target = tokens[0] if tokens else ""
        try:
            payload = self._factory().status(target)
        except Exception as exc:
            log.add_error(f"Could not load factory status: {exc}")
            return
        factory_meta = payload.get("factory") or {}
        t = Text()
        t.append("\n  Software Factory\n\n", style=f"bold {THEME['purple']}")
        t.append("  Session  ", style=THEME["muted"])
        t.append(f"{payload['session_id']}\n", style=f"bold {THEME['cyan']}")
        for label, key in (
            ("Mode", "mode"),
            ("Route", "route"),
            ("Model", "model_ref"),
            ("Provider", "provider"),
            ("Runtime", "runtime"),
            ("Harness", "harness"),
        ):
            value = factory_meta.get(key)
            if value:
                t.append(f"  {label:<8}", style=THEME["muted"])
                t.append(f"{value}\n", style=THEME["text"])
        next_turn = factory_meta.get("next_turn") or {}
        if next_turn:
            t.append("\n  Next turn intent\n", style=f"bold {THEME['text']}")
            for key in ("route", "model_ref", "harness", "runtime"):
                value = next_turn.get(key)
                if value:
                    t.append(f"    {key:<10}", style=THEME["muted"])
                    t.append(f"{value}\n", style=THEME["text"])
        warnings = factory_meta.get("privacy_warnings") or []
        if warnings:
            t.append("\n  Privacy warnings\n", style=f"bold {THEME['orange']}")
            for warning in warnings:
                t.append(f"    {warning}\n", style=THEME["warning"])
        lineage = payload.get("lineage") or []
        t.append("  Lineage ", style=THEME["muted"])
        t.append(f"{len(lineage)} event(s)\n\n", style=THEME["text"])
        t.append("  Use ", style=THEME["muted"])
        t.append(":factory routes", style=THEME["cyan"])
        t.append(", ", style=THEME["muted"])
        t.append(":factory switch-model", style=THEME["cyan"])
        t.append(", or ", style=THEME["muted"])
        t.append(":factory switch-harness", style=THEME["cyan"])
        t.append(".\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _factory_policy(self, log: ConversationLog) -> None:
        try:
            factory_obj = self._factory()
            policy = factory_obj.policy()
        except Exception as exc:
            log.add_error(f"Could not load factory policy: {exc}")
            return
        t = Text()
        t.append("\n  Factory Policy\n\n", style=f"bold {THEME['purple']}")
        t.append("  Path  ", style=THEME["muted"])
        t.append(f"{factory_obj.policy_path}\n", style=f"bold {THEME['cyan']}")
        t.append("  Default route  ", style=THEME["muted"])
        t.append(f"{policy.get('default_route') or '-'}\n\n", style=THEME["text"])
        for name, route in (policy.get("routes") or {}).items():
            t.append(f"  {name:<16}", style=f"bold {THEME['cyan']}")
            t.append(f"allow_cloud={route.get('allow_cloud')}", style=THEME["muted"])
            prefer = ", ".join(route.get("prefer") or [])
            if prefer:
                t.append(f"  prefer={prefer}", style=THEME["dim"])
            t.append("\n")
        self._show_command_output(log, t)

    def _factory_init_policy(self, tokens: list[str], log: ConversationLog) -> None:
        force = any(token.lower() == "--force" for token in tokens)
        try:
            path = self._factory().init_policy(force=force)
        except Exception as exc:
            log.add_error(f"Could not initialize factory policy: {exc}")
            return
        log.add_success(f"Factory policy ready: {path}")

    def _factory_routes(self, log: ConversationLog) -> None:
        try:
            routes = self._factory().routes()
        except Exception as exc:
            log.add_error(f"Could not load factory routes: {exc}")
            return
        t = Text()
        t.append("\n  Factory Routes\n\n", style=f"bold {THEME['purple']}")
        for name, route in routes.items():
            tags = ", ".join(route.get("tags") or [])
            t.append(f"  {name:<16}", style=f"bold {THEME['cyan']}")
            t.append(f"{route.get('policy'):<18}", style=THEME["muted"])
            t.append(f"{tags}\n", style=THEME["purple"])
            t.append(f"    {route.get('description')}\n", style=THEME["muted"])
        self._show_command_output(log, t)

    def _factory_mode(self, tokens: list[str], log: ConversationLog) -> None:
        if not tokens:
            self._factory_routes(log)
            return
        mode = tokens[0]
        reason = " ".join(tokens[1:])
        try:
            payload = self._factory().set_mode(mode, reason=reason)
        except Exception as exc:
            log.add_error(f"Could not set factory mode: {exc}")
            return
        log.add_success(f"Factory mode for {payload['session_id']} -> {mode}")

    def _factory_switch_model(self, tokens: list[str], log: ConversationLog) -> None:
        if not tokens:
            log.add_info("Usage: :factory switch-model <provider/model> [session-id]")
            return
        model_ref = tokens[0]
        session_id = tokens[1] if len(tokens) > 1 else ""
        try:
            payload = self._factory().switch_model(model_ref, session_id=session_id)
        except Exception as exc:
            log.add_error(f"Could not switch model: {exc}")
            return
        log.add_success(f"Session {payload['session']['session_id']} model -> {model_ref}")
        log.add_info("Factory intent recorded for the next turn. Use :factory to inspect it.")
        for warning in payload.get("privacy_warnings") or []:
            log.add_warning(warning)

    def _factory_switch_harness(self, tokens: list[str], log: ConversationLog) -> None:
        if not tokens:
            log.add_info("Usage: :factory switch-harness <harness> [session-id]")
            return
        harness = tokens[0]
        session_id = tokens[1] if len(tokens) > 1 else ""
        try:
            payload = self._factory().switch_harness(harness, session_id=session_id)
        except Exception as exc:
            log.add_error(f"Could not switch harness: {exc}")
            return
        log.add_success(f"Session {payload['session']['session_id']} harness -> {harness}")
        log.add_info("Factory harness intent recorded for the next turn.")

    def _factory_fork_model(self, tokens: list[str], log: ConversationLog) -> None:
        positionals, options = self._parse_switchboard_options(tokens)
        source = positionals[0] if positionals else ""
        model_ref = str(options.get("model") or options.get("model_ref") or "")
        if not model_ref:
            log.add_info("Usage: :factory fork-model [source] --model local/qwen --role coder")
            return
        try:
            payload = self._factory().fork_model(
                source,
                model_ref=model_ref,
                role=str(options.get("role") or ""),
                title=str(options.get("title") or ""),
                goal=str(options.get("goal") or ""),
                new_session_id=str(options.get("session_id") or ""),
            )
        except Exception as exc:
            log.add_error(f"Could not fork model worker: {exc}")
            return
        log.add_success(f"Forked model worker -> {payload['fork']['session']['session_id']}")

    def _factory_fork_harness(self, tokens: list[str], log: ConversationLog) -> None:
        positionals, options = self._parse_switchboard_options(tokens)
        source = positionals[0] if positionals else ""
        harness = str(options.get("harness") or "")
        if not harness:
            log.add_info("Usage: :factory fork-harness [source] --harness review --role reviewer")
            return
        try:
            payload = self._factory().fork_harness(
                source,
                harness=harness,
                role=str(options.get("role") or ""),
                title=str(options.get("title") or ""),
                goal=str(options.get("goal") or ""),
                new_session_id=str(options.get("session_id") or ""),
            )
        except Exception as exc:
            log.add_error(f"Could not fork harness worker: {exc}")
            return
        log.add_success(f"Forked harness worker -> {payload['fork']['session']['session_id']}")

    def _factory_lineage(self, tokens: list[str], log: ConversationLog) -> None:
        target = tokens[0] if tokens else ""
        try:
            events = self._factory().lineage(target)
        except Exception as exc:
            log.add_error(f"Could not load factory lineage: {exc}")
            return
        t = Text()
        t.append("\n  Factory Lineage\n\n", style=f"bold {THEME['purple']}")
        if not events:
            t.append("  No model/harness/mode changes recorded yet.\n", style=THEME["muted"])
            self._show_command_output(log, t)
            return
        for event in events:
            t.append(f"  {event.get('created_at')}  ", style=THEME["dim"])
            t.append(f"{event.get('kind'):<8}", style=f"bold {THEME['cyan']}")
            t.append(f"{event.get('previous')} -> {event.get('new')}\n", style=THEME["text"])
        self._show_command_output(log, t)
