"""Additional controls for the native Codex connection."""

from __future__ import annotations

import json
import inspect
import shlex

from rich.text import Text

from superqode.codex_commands import CODEX_COMMANDS, redact_codex_data


def codex_options(args, *, flags=(), values=()):
    words = iter(shlex.split(args))
    options = {}
    for word in words:
        if word in flags:
            options[word] = True
        elif word in values:
            value = next(words, None)
            if value is None or value.startswith("--"):
                raise ValueError(f"{word} requires a value")
            options[word] = value
        else:
            raise ValueError(f"Unknown option: {word}")
    return options


class CodexControlsMixin:
    def _codex_help(self, log):
        text = Text("\nCodex commands\n\n")
        for command, description in CODEX_COMMANDS:
            text.append(f"  :codex {command:<13} {description}\n")
        text.append(
            "\nNew controls use Codex CLI. SDK connections retain their existing session controls.\n"
            "Codex owns these inventories; SuperQode's :mcp and :skills manage separate tools.\n"
            "Cloud, daemon, deletion, worktrees, updates and terminal customization stay in Codex CLI.\n"
            "Run !codex --help to inspect your installed CLI.\n"
        )
        log.write(text)

    def _codex_control_result(self, log, label, result, *, command=None):
        safe = redact_codex_data(result)
        content = json.dumps(safe, indent=2, ensure_ascii=False, default=str)
        text = Text(f"\nCodex {label}\n\n")
        text.append(content[:32000])
        if len(content) > 32000:
            text.append("\nDisplay shortened; use a narrower query or Codex CLI for full output.")
        if isinstance(result, dict) and result.get("nextCursor") and command:
            text.append(f"\nNext page: :codex {command} --cursor {result['nextCursor']}")
        log.write(text)

    def _codex_extended_cmd(self, sub, rest, log):
        supported = {
            "help",
            "doctor",
            "new",
            "unarchive",
            "login",
            "usage",
            "mcp",
            "skills",
            "plugins",
            "apps",
            "hooks",
            "features",
            "config",
            "permissions",
            "plan",
            "ps",
            "stop",
            "cancel",
            "agents",
            "rollout",
            "pwd",
            "diff",
            "copy",
        }
        if sub not in supported:
            return False
        try:
            if sub == "help":
                self._codex_help(log)
                return True
            if sub == "diff":
                pending = self._handle_diff(rest, log)
                if inspect.isawaitable(pending):
                    self.run_worker(pending, exclusive=False)
                return True
            if sub == "copy":
                self._handle_copy(log, rest or "response")
                return True
            # Parse before connecting: invalid input must not start an agent.
            if sub in {
                "skills",
                "plugins",
                "apps",
                "hooks",
                "features",
                "mcp",
                "permissions",
                "ps",
                "agents",
            }:
                options = None
                if sub == "mcp" and rest in {"reload", "verbose"}:
                    options = {}
                elif sub == "permissions" and rest in {"on-request", "never"}:
                    options = {}
                else:
                    flags = ("--reload",) if sub in {"skills", "plugins", "apps"} else ()
                    values = (
                        ("--cursor",)
                        if sub in {"apps", "features", "mcp", "permissions", "ps", "agents"}
                        else ()
                    )
                    options = codex_options(rest, flags=flags, values=values)
            elif sub == "login":
                if rest not in {"", "--device-auth", "status", "cancel"}:
                    raise ValueError("Usage: :codex login [--device-auth|status|cancel]")
            elif sub == "plan":
                if rest not in {"", "on", "off"}:
                    raise ValueError("Usage: :codex plan [on|off]")
            elif sub == "usage":
                options = codex_options(rest, flags=("--tokens",))
            elif sub == "unarchive":
                if not rest or len(rest.split()) != 1 or rest.startswith("-"):
                    raise ValueError("Usage: :codex unarchive <thread_id>")
            elif sub not in {"new"} and rest:
                raise ValueError(f"Usage: :codex {sub}")

            runtime = self._codex_runtime_or_connect(log)
            if getattr(runtime, "name", "") != "codex-cli":
                log.add_info(
                    f":codex {sub} requires Codex CLI. Select :connect codex to use it; your SDK connection is still active."
                )
                return True
            idle_only = {"new", "plan", "login", "permissions", "unarchive"}
            if (
                sub in idle_only
                and not (sub == "login" and rest in {"status", "cancel"})
                or sub == "mcp"
                and rest == "reload"
            ) and self.is_busy:
                raise ValueError(
                    "A Codex task is running; cancel it or wait before changing the session"
                )

            def read(operation, label=None, command=None):
                self._codex_async_read(
                    log,
                    sub,
                    runtime,
                    operation,
                    lambda result: self._codex_control_result(
                        log, label or sub, result, command=command
                    ),
                )

            if sub == "new":
                read(lambda: runtime.new_thread(rest), "new chat")
            elif sub == "unarchive":
                read(lambda: runtime.unarchive_thread(rest), "unarchive")
            elif sub == "login":
                if rest == "status":
                    self._codex_account_cmd(log)
                elif rest == "cancel":
                    read(runtime.cancel_login, "sign-in cancelled")
                else:
                    self._codex_async_read(
                        log,
                        "login",
                        runtime,
                        lambda: runtime.login(device=rest == "--device-auth"),
                        lambda result: self._codex_show_login(log, result),
                    )
            elif sub == "usage":
                read(
                    lambda: runtime.usage(tokens=bool(options.get("--tokens"))),
                    "token activity" if options.get("--tokens") else "rate limits",
                )
            elif sub == "config":
                read(runtime.read_config, "configuration and requirements (redacted)")
            elif sub == "doctor":
                read(runtime.doctor, "installation health (redacted)")
            elif sub == "plan":
                if not rest:
                    log.add_info(
                        f"Codex collaboration mode: {runtime._collaboration_mode or 'configured default'}. Use :codex plan on or :codex plan off."
                    )
                else:
                    read(lambda: runtime.set_plan_mode(rest == "on"), "collaboration mode")
            elif sub == "permissions" and rest in {"on-request", "never"}:
                runtime.set_approval_policy(rest)
                log.add_success(
                    f"Codex approval policy: {rest} (next turn). Sandbox unchanged; :codex sandbox controls filesystem access."
                )
            elif sub == "mcp" and rest == "reload":
                read(runtime.reload_mcp, "MCP configuration reloaded")
            elif sub in {"ps", "stop"}:
                read(
                    lambda: runtime.background_terminals(
                        stop=sub == "stop", cursor=options.get("--cursor") if sub == "ps" else None
                    ),
                    "background terminals",
                    command="ps" if sub == "ps" else None,
                )
            elif sub == "cancel":
                runtime.cancel()
                log.add_info("Codex turn interruption requested.")
            elif sub == "agents":
                read(
                    lambda: runtime.list_threads(
                        descendants=True, all_cwds=True, cursor=options.get("--cursor")
                    ),
                    "descendant agent sessions; :codex resume <id> switches thread",
                    command="agents",
                )
            elif sub == "pwd":
                log.add_info(f"Codex directory: {runtime.config.working_directory}")
            elif sub == "rollout":

                async def path():
                    if not runtime.thread_id:
                        return {"path": None, "message": "No Codex thread is active"}
                    result = await runtime.read_thread()
                    return {
                        "threadId": runtime.thread_id,
                        "path": result.get("thread", {}).get("path"),
                    }

                read(path, "saved transcript")
            else:
                read(
                    lambda: runtime.inspect(
                        sub, reload=bool(options.get("--reload")), cursor=options.get("--cursor")
                    ),
                    command=sub,
                )
        except Exception as exc:
            log.add_error(f"Codex {sub}: {exc}")
        return True

    @staticmethod
    def _codex_show_login(log, result):
        # Show only the public sign-in URL and one-time code, never tokens.
        url = result.get("authUrl") or result.get("verificationUrl")
        if not url:
            log.add_error("Codex returned no sign-in URL. Run codex login in another terminal.")
            return
        text = Text("\nSign in to Codex with ChatGPT\n\n")
        text.append(url)
        if result.get("userCode"):
            text.append(f"\nOne-time code: {result['userCode']}")
        text.append(
            "\nComplete sign-in, then use :codex account to check it. :codex login cancel cancels this sign-in.\n"
        )
        log.write(text)
