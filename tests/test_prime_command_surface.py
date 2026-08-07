""":prime command routing.

The dispatcher is exercised directly rather than through the Textual app so
routing regressions surface without a running TUI.
"""

import pytest

from superqode.app.mixins.commands_impl import CommandImplMixin


class FakeLog:
    def __init__(self) -> None:
        self.errors: list[str] = []
        self.infos: list[str] = []
        self.successes: list[str] = []

    def add_error(self, message: str) -> None:
        self.errors.append(str(message))

    def add_info(self, message: str) -> None:
        self.infos.append(str(message))

    def add_success(self, message: str) -> None:
        self.successes.append(str(message))


class PrimeHarness(CommandImplMixin):
    """Records which handler the dispatcher reached."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def _prime_depth_cmd(self, rest, log):  # type: ignore[override]
        self.calls.append(("depth", rest))

    def _prime_goal_cmd(self, rest, log):  # type: ignore[override]
        self.calls.append(("goal", rest))

    def _prime_autonomous_cmd(self, rest, log):  # type: ignore[override]
        self.calls.append(("autonomous", rest))

    def _prime_connect(self, selector, log):  # type: ignore[override]
        self.calls.append(("connect", selector))

    def _show_prime_models(self, log, search=""):  # type: ignore[override]
        self.calls.append(("models", search))

    def _show_prime_model_picker(self, log, search=""):  # type: ignore[override]
        self.calls.append(("picker", search))

    def _prime_local_cmd(self, log):  # type: ignore[override]
        self.calls.append(("local", ""))

    def _show_prime_status(self, log):  # type: ignore[override]
        self.calls.append(("status", ""))

    def _show_prime_agents(self, log):  # type: ignore[override]
        self.calls.append(("agents", ""))

    def _show_prime_doctor(self, log):  # type: ignore[override]
        self.calls.append(("doctor", ""))

    def _show_prime_schedules(self, log):  # type: ignore[override]
        self.calls.append(("schedule", ""))

    def _show_prime_packages(self, log):  # type: ignore[override]
        self.calls.append(("packages", ""))

    def _prime_update(self, log):  # type: ignore[override]
        self.calls.append(("update", ""))

    def _show_prime_login(self, log):  # type: ignore[override]
        self.calls.append(("login-help", ""))

    def _prime_login_cmd(self, log):  # type: ignore[override]
        self.calls.append(("login", ""))

    def _show_prime_help(self, log):  # type: ignore[override]
        self.calls.append(("help", ""))


@pytest.fixture
def harness():
    return PrimeHarness()


@pytest.fixture
def log():
    return FakeLog()


class TestPrimeDispatch:
    """Tests for ``:prime`` subcommand routing."""

    @pytest.mark.parametrize(
        "args,expected",
        [
            ("", ("help", "")),
            ("help", ("help", "")),
            ("?", ("help", "")),
            ("connect", ("connect", "")),
            ("start", ("connect", "")),
            ("connect ollama/qwen3.5:9b", ("connect", "ollama/qwen3.5:9b")),
            ("models", ("models", "")),
            ("ls", ("models", "")),
            ("models qwen", ("models", "qwen")),
            ("model", ("picker", "")),
            ("model gpt-4.1", ("connect", "gpt-4.1")),
            ("local", ("local", "")),
            ("sync", ("local", "")),
            ("depth", ("depth", "")),
            ("depth 3", ("depth", "3")),
            ("goal", ("goal", "")),
            ("goal ship the release", ("goal", "ship the release")),
            ("autonomous", ("autonomous", "")),
            ("auto pytest -q", ("autonomous", "pytest -q")),
            ("status", ("status", "")),
            ("agents", ("agents", "")),
            ("sessions", ("agents", "")),
            ("subagents", ("agents", "")),
            ("doctor", ("doctor", "")),
            ("services", ("doctor", "")),
            ("schedule", ("schedule", "")),
            ("schedules", ("schedule", "")),
            ("packages", ("packages", "")),
            ("package", ("packages", "")),
            ("update", ("update", "")),
            ("login", ("login", "")),
            ("auth", ("login", "")),
        ],
    )
    def test_routes(self, harness, log, args, expected):
        harness._prime_cmd(args, log)

        assert harness.calls == [expected]

    def test_unknown_subcommand_explains(self, harness, log):
        harness._prime_cmd("wat", log)

        assert harness.calls == []
        assert log.errors and "wat" in log.errors[0]
        assert log.infos and "Usage: :prime" in log.infos[0]

    def test_case_is_ignored(self, harness, log):
        harness._prime_cmd("MODELS", log)

        assert harness.calls == [("models", "")]


class OptionHarness(CommandImplMixin):
    """Exercises the real depth, goal and autonomous handlers."""

    def __init__(self) -> None:
        self.connect_commands: list[str] = []

    def _connect_acp_cmd(self, args, log):  # type: ignore[override]
        self.connect_commands.append(args)


@pytest.fixture
def opts_app():
    return OptionHarness()


class TestPrimeLaunchSettings:
    """Tests for the start-time settings the commands pin."""

    def test_depth_is_stored(self, opts_app, log):
        opts_app._prime_depth_cmd("3", log)

        assert opts_app._prime_opts().max_depth == 3
        assert opts_app._prime_opts().env() == {"RLM_MAX_DEPTH": "3"}

    def test_depth_zero_disables_recursion(self, opts_app, log):
        opts_app._prime_depth_cmd("0", log)

        assert opts_app._prime_opts().max_depth == 0
        assert any("disabled" in message for message in log.successes)

    def test_depth_reset(self, opts_app, log):
        opts_app._prime_depth_cmd("4", log)
        opts_app._prime_depth_cmd("default", log)

        assert opts_app._prime_opts().max_depth is None

    def test_negative_depth_rejected(self, opts_app, log):
        opts_app._prime_depth_cmd("-1", log)

        assert opts_app._prime_opts().max_depth is None
        assert log.errors

    def test_non_numeric_depth_rejected(self, opts_app, log):
        opts_app._prime_depth_cmd("deep", log)

        assert opts_app._prime_opts().max_depth is None
        assert log.errors

    def test_goal_set_and_cleared(self, opts_app, log):
        opts_app._prime_goal_cmd('"Ship the release"', log)
        assert opts_app._prime_opts().goal == "Ship the release"

        opts_app._prime_goal_cmd("off", log)
        assert opts_app._prime_opts().goal == ""

    def test_autonomous_gates_accumulate(self, opts_app, log):
        opts_app._prime_autonomous_cmd("pytest -q", log)
        opts_app._prime_autonomous_cmd("ruff check .", log)

        opts = opts_app._prime_opts()
        assert opts.autonomous is True
        assert opts.gates == ("pytest -q", "ruff check .")

    def test_autonomous_off_clears_gates(self, opts_app, log):
        opts_app._prime_autonomous_cmd("pytest -q", log)
        opts_app._prime_autonomous_cmd("off", log)

        opts = opts_app._prime_opts()
        assert opts.autonomous is False
        assert opts.gates == ()

    def test_settings_are_independent(self, opts_app, log):
        """Setting one option must not reset the others."""
        opts_app._prime_depth_cmd("2", log)
        opts_app._prime_goal_cmd("Fix CI", log)
        opts_app._prime_autonomous_cmd("pytest", log)

        opts = opts_app._prime_opts()
        assert (opts.max_depth, opts.goal, opts.autonomous) == (2, "Fix CI", True)

    def test_bare_query_does_not_mutate(self, opts_app, log):
        opts_app._prime_depth_cmd("5", log)
        opts_app._prime_depth_cmd("", log)

        assert opts_app._prime_opts().max_depth == 5


class TestPrimeLaunchCommandFromTui:
    """The command the TUI actually builds when a prompt is sent.

    The first release passed SuperQode's "auto" sentinel straight through as a
    model id, so every default connection launched ``--model auto`` and failed
    on a provider the user had never chosen. These pin the resolution that the
    Prime branch of the agent-run path performs.
    """

    @staticmethod
    def _command(app, model):
        """Mirror the resolution in the agent-run Prime branch."""
        from superqode.providers import prime_agent as prime

        requested = (model or "").strip()
        if requested.lower() in {"auto", "default", "none"}:
            requested = ""
        opts = app._prime_opts()
        return prime.acp_command(requested or opts.model, options=opts)

    def test_auto_produces_a_bare_launch(self, opts_app):
        assert self._command(opts_app, "auto") == "prime-agent --mode acp"

    def test_empty_model_produces_a_bare_launch(self, opts_app):
        assert self._command(opts_app, "") == "prime-agent --mode acp"

    def test_pinned_model_survives_the_auto_sentinel(self, opts_app, log, monkeypatch):
        """A pinned selection must not be erased by the default sentinel.

        ``_prime_connect`` returns early when the binary is missing, so this
        forces it present rather than depending on the machine running the
        tests having Prime Agent installed.
        """
        from superqode.providers import prime_agent as prime

        monkeypatch.setattr(prime, "is_installed", lambda: True)
        opts_app._prime_connect("ollama/qwen3.5:9b", log)

        assert self._command(opts_app, "auto") == (
            "prime-agent --mode acp --provider ollama --model qwen3.5:9b"
        )

    def test_pinned_settings_reach_the_launch(self, opts_app, log):
        opts_app._prime_depth_cmd("2", log)
        opts_app._prime_goal_cmd("ship it", log)
        opts_app._prime_autonomous_cmd("pytest -q", log)

        command = self._command(opts_app, "auto")

        assert "--goal 'ship it'" in command
        assert "--autonomous-gate 'pytest -q'" in command
        assert opts_app._prime_opts().env() == {"RLM_MAX_DEPTH": "2"}


class TestPrimeCommandCompletions:
    """The command palette must offer the family."""

    def test_registered(self):
        from superqode.app.constants import COMMANDS

        for entry in (
            ":prime",
            ":prime connect",
            ":prime models",
            ":prime local",
            ":prime depth",
            ":prime goal",
            ":prime autonomous",
            ":prime agents",
            ":prime schedule",
            ":prime packages",
            ":prime status",
            ":prime doctor",
            ":prime update",
            ":prime login",
            ":prime help",
        ):
            assert entry in COMMANDS
