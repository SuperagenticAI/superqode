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
        t.append("\n  Code Factory\n\n", style=f"bold {THEME['purple']}")
        commands = [
            (":factory status", "FactorySpec, acceptance checks, release rule and recent runs"),
            (":factory init [--template NAME] [--force]", "create a full FactorySpec"),
            (':factory describe "<team process>" --model p/m', "draft a FactorySpec to review"),
            (":factory describe --apply DIGEST --confirm", "save a reviewed draft"),
            (":factory check [--application]", "readiness, with build, start and health runs"),
            (':factory trial "<goal>"', "queue one WorkOrder from the Factory; no agent runs"),
            (":factory run <work-order-id>", "run the queued WorkOrder with live agents"),
            (":factory evidence <work-order-id>", "checks and requirements by status"),
            (":factory decide <work-order-id>", "SuperGauge verdict and release blockers"),
            (":factory session", "show current model/harness/route lineage"),
            (":factory init-policy [--routes-only]", "create .superqode/factory.yaml"),
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
            t.append(f"  {command:<52}", style=f"bold {THEME['cyan']}")
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
        t.append("\n  Code Factory\n\n", style=f"bold {THEME['purple']}")
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
        routes_only = any(token.lower() == "--routes-only" for token in tokens)
        try:
            path = self._factory().init_policy(force=force, routes_only=routes_only)
        except Exception as exc:
            log.add_error(f"Could not initialize factory policy: {exc}")
            return
        log.add_success(f"Factory policy ready: {path}")

    def _factory_lines(self, log: ConversationLog, title: str, lines: list[str]) -> None:
        t = Text()
        t.append(f"\n  {title}\n\n", style=f"bold {THEME['purple']}")
        for line in lines:
            t.append(f"  {line}\n", style=THEME["text"])
        self._show_command_output(log, t)

    def _factory_overview(self, tokens: list[str], log: ConversationLog) -> None:
        """FactorySpec summary first, then the active session route if there is one."""
        from pathlib import Path

        from superqode.factory.summaries import overview, overview_lines

        try:
            if not (Path.cwd() / ".superqode" / "factory.yaml").exists():
                raise FileNotFoundError
            lines = overview_lines(overview(Path.cwd()))
        except FileNotFoundError:
            lines = ["➖ No Factory in this project yet. Next: :factory init"]
        except Exception as exc:
            lines = [f"⛔ Factory definition problem: {exc}"]
        try:
            meta = (self._factory().status(tokens[0] if tokens else "").get("factory")) or {}
        except Exception:
            meta = {}
        if meta:
            lines.append(
                "   Session: "
                + "  ".join(
                    f"{key} {meta[key]}"
                    for key in ("mode", "route", "model_ref", "harness")
                    if meta.get(key)
                )
                + "  (:factory session for lineage)"
            )
        self._factory_lines(log, "Software Factory", lines)

    def _factory_init_spec(self, tokens: list[str], log: ConversationLog) -> None:
        from pathlib import Path

        from superqode.factory.authoring import init_from_template

        template = "fix-and-verify"
        if "--template" in tokens:
            index = tokens.index("--template")
            if index + 1 >= len(tokens):
                log.add_info("Usage: :factory init [--template fix-and-verify|continuous-outcomes]")
                return
            template = tokens[index + 1]
        try:
            result = init_from_template(Path.cwd(), template, force="--force" in tokens)
        except Exception as exc:
            log.add_error(f"Could not create the Factory: {exc}")
            return
        log.add_success(
            f"✅ FactorySpec {result['template']} saved to {result['path']}"
            + (" (route policy kept)" if result.get("upgraded_route_policy") else "")
            + ". Next: :factory check"
        )

    def _factory_cli(self, subcommand: str, tokens: list[str], log: ConversationLog) -> None:
        """Commands that may run models, agents or project processes go through the CLI."""
        if subcommand == "run":
            if len(tokens) != 1:
                log.add_info("Usage: :factory run <work-order-id>")
                return
            parts = ["factory", "worker", tokens[0], "--live"]
        else:
            parts = ["factory", subcommand, *tokens]
        self._run_cli_passthrough(parts, log, f"Factory {subcommand}")

    def _factory_trial(self, tokens: list[str], log: ConversationLog) -> None:
        from pathlib import Path

        from superqode.factory.authoring import queue_trial

        goal = " ".join(tokens).strip()
        if not goal:
            log.add_info('Usage: :factory trial "<goal>"')
            return
        try:
            result = queue_trial(Path.cwd(), goal, actor="tui")
        except Exception as exc:
            log.add_error(f"⛔ Could not queue the trial: {exc}")
            return
        self._factory_lines(
            log,
            "Factory trial",
            [
                f"⏸️ Queued {result['work_order_id']} ({result['status']}); no agent has run.",
                f"   Next: :factory run {result['work_order_id']}",
            ],
        )

    def _factory_evidence(self, tokens: list[str], log: ConversationLog) -> None:
        from pathlib import Path

        from superqode.factory.evidence import trace
        from superqode.factory.summaries import trace_lines

        if tokens and tokens[0] in {"trace", "outcomes", "record-outcome"}:
            self._run_cli_passthrough(["factory", "evidence", *tokens], log, "Factory evidence")
            return
        if len(tokens) != 1:
            log.add_info("Usage: :factory evidence <work-order-id>")
            return
        try:
            lines = trace_lines(trace(Path.cwd(), tokens[0]))
        except Exception as exc:
            log.add_error(f"Could not load Factory evidence: {exc}")
            return
        self._factory_lines(log, f"Factory evidence {tokens[0]}", lines)

    def _factory_decide(self, tokens: list[str], log: ConversationLog) -> None:
        from pathlib import Path

        from superqode.factory.release import release_status
        from superqode.factory.summaries import decision_lines

        if len(tokens) != 1:
            log.add_info("Usage: :factory decide <work-order-id>")
            return
        try:
            lines = decision_lines(release_status(tokens[0], root=Path.cwd()))
        except Exception as exc:
            log.add_error(f"Could not load the release decision: {exc}")
            return
        self._factory_lines(log, f"Release decision {tokens[0]}", lines)

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
