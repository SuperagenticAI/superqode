"""Tests for Prime Agent CLI introspection behind the ``:prime`` commands."""

import json

from superqode.providers import prime_agent as prime


SAMPLE_TABLE = """provider        model                    context  max-out  thinking  images
github-copilot  claude-fable-5           1M       128K     yes       yes
github-copilot  gpt-4.1                  128K     16.4K    no        yes
ollama          qwen3.5:9b               128K     16.4K    no        no
"""


class TestParseModelTable:
    """Tests for ``prime-agent model list`` parsing."""

    def test_parses_rows(self):
        models = prime.parse_model_table(SAMPLE_TABLE)

        assert [m.id for m in models] == [
            "github-copilot/claude-fable-5",
            "github-copilot/gpt-4.1",
            "ollama/qwen3.5:9b",
        ]

    def test_header_is_skipped(self):
        """The header row must never become a model."""
        models = prime.parse_model_table(SAMPLE_TABLE)

        assert all(m.model != "model" for m in models)

    def test_traits(self):
        models = {m.model: m for m in prime.parse_model_table(SAMPLE_TABLE)}

        assert models["claude-fable-5"].thinking is True
        assert models["claude-fable-5"].images is True
        assert models["gpt-4.1"].thinking is False
        assert models["gpt-4.1"].images is True
        assert models["qwen3.5:9b"].context == "128K"

    def test_empty_and_noise(self):
        assert prime.parse_model_table("") == []
        assert prime.parse_model_table("loading...\n") == []

    def test_model_ids_with_colons_survive(self):
        """Ollama tags contain colons and must not be split."""
        models = prime.parse_model_table(SAMPLE_TABLE)

        assert "ollama/qwen3.5:9b" in {m.id for m in models}


class TestListModels:
    """Tests for probing the installed CLI."""

    def test_reads_table_from_stderr(self, monkeypatch):
        """Prime keeps stdout clear for protocol output and lists on stderr."""
        monkeypatch.setattr(prime, "is_installed", lambda: True)
        monkeypatch.setattr(
            prime.subprocess,
            "run",
            lambda *a, **k: subprocess_result(stdout="", stderr=SAMPLE_TABLE),
        )

        assert [m.id for m in prime.list_models()] == [
            "github-copilot/claude-fable-5",
            "github-copilot/gpt-4.1",
            "ollama/qwen3.5:9b",
        ]

    def test_reads_table_from_stdout(self, monkeypatch):
        """A future release that moves the table to stdout must keep working."""
        monkeypatch.setattr(prime, "is_installed", lambda: True)
        monkeypatch.setattr(
            prime.subprocess,
            "run",
            lambda *a, **k: subprocess_result(stdout=SAMPLE_TABLE, stderr=""),
        )

        assert len(prime.list_models()) == 3

    def test_missing_binary_returns_empty(self, monkeypatch):
        monkeypatch.setattr(prime, "is_installed", lambda: False)

        assert prime.list_models() == []

    def test_probe_failure_returns_empty(self, monkeypatch):
        monkeypatch.setattr(prime, "is_installed", lambda: True)

        def boom(*a, **k):
            raise OSError("no such binary")

        monkeypatch.setattr(prime.subprocess, "run", boom)

        assert prime.list_models() == []


class SubprocessResult:
    """Stand-in for ``subprocess.CompletedProcess``."""

    def __init__(self, stdout: str, stderr: str) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = 0


def subprocess_result(stdout: str = "", stderr: str = "") -> SubprocessResult:
    return SubprocessResult(stdout, stderr)


class TestListAgents:
    """Tests for reading Prime's live session list."""

    def _payload(self, monkeypatch, payload):
        monkeypatch.setattr(prime, "is_installed", lambda: True)
        monkeypatch.setattr(
            prime.subprocess,
            "run",
            lambda *a, **k: subprocess_result(stdout=json.dumps(payload)),
        )

    def test_reads_rlm_subagent_tree(self, monkeypatch):
        """Depth and runtime kind identify RLM children."""
        self._payload(
            monkeypatch,
            {
                "sessions": [
                    {
                        "sessionId": "root-1",
                        "sessionName": "main",
                        "lifecycle": "running",
                        "runtimeKind": "top-level",
                        "rlmDepth": 0,
                        "isSessionActive": True,
                    },
                    {
                        "sessionId": "child-1",
                        "sessionName": "reviewer",
                        "lifecycle": "running",
                        "runtimeKind": "subagent",
                        "rlmDepth": 1,
                    },
                ]
            },
        )

        sessions = prime.list_agents()

        assert [s.name for s in sessions] == ["main", "reviewer"]
        assert sessions[0].is_subagent is False
        assert sessions[0].active is True
        assert sessions[1].is_subagent is True
        assert sessions[1].rlm_depth == 1

    def test_depth_alone_marks_a_subagent(self, monkeypatch):
        """A child that omits runtimeKind is still a child."""
        self._payload(monkeypatch, {"sessions": [{"sessionId": "c", "rlmDepth": 2}]})

        assert prime.list_agents()[0].is_subagent is True

    def test_bad_depth_does_not_raise(self, monkeypatch):
        self._payload(monkeypatch, {"sessions": [{"sessionId": "c", "rlmDepth": "deep"}]})

        assert prime.list_agents()[0].rlm_depth == 0

    def test_empty_and_malformed(self, monkeypatch):
        self._payload(monkeypatch, {"sessions": []})
        assert prime.list_agents() == []

        self._payload(monkeypatch, {"unexpected": 1})
        assert prime.list_agents() == []

    def test_missing_binary(self, monkeypatch):
        monkeypatch.setattr(prime, "is_installed", lambda: False)

        assert prime.list_agents() == []
        assert prime.daemon_status() == []
        assert prime.list_schedules() == []
        assert prime.list_packages() == []


class TestServiceProbes:
    """Tests for the remaining ``--json`` probes."""

    def _stdout(self, monkeypatch, text):
        monkeypatch.setattr(prime, "is_installed", lambda: True)
        monkeypatch.setattr(prime.subprocess, "run", lambda *a, **k: subprocess_result(stdout=text))

    def test_daemon_status(self, monkeypatch):
        self._stdout(monkeypatch, json.dumps([{"pid": 1, "version": "0.7.0"}]))

        assert prime.daemon_status() == [{"pid": 1, "version": "0.7.0"}]

    def test_schedules(self, monkeypatch):
        self._stdout(monkeypatch, json.dumps({"jobs": [{"id": "j1", "prompt": "run tests"}]}))

        assert prime.list_schedules() == [{"id": "j1", "prompt": "run tests"}]

    def test_json_on_stderr(self, monkeypatch):
        """Prime prints to stderr in places, so both streams are read."""
        monkeypatch.setattr(prime, "is_installed", lambda: True)
        monkeypatch.setattr(
            prime.subprocess,
            "run",
            lambda *a, **k: subprocess_result(stdout="", stderr=json.dumps({"jobs": []})),
        )

        assert prime.list_schedules() == []

    def test_non_json_output_is_ignored(self, monkeypatch):
        """A fallthrough to prompt mode returns prose, which must not parse."""
        self._stdout(monkeypatch, "I could not find that command. Did you mean...")

        assert prime.daemon_status() == []
        assert prime.list_agents() == []

    def test_packages_drops_empty_state_sentence(self, monkeypatch):
        self._stdout(monkeypatch, "No packages installed.")

        assert prime.list_packages() == []

    def test_packages_lists_entries(self, monkeypatch):
        self._stdout(monkeypatch, "team-skills 1.2.0\nreview-prompts 0.4.1")

        assert prime.list_packages() == ["team-skills 1.2.0", "review-prompts 0.4.1"]


class TestSplitSelector:
    """Tests for provider/model selector parsing."""

    def test_provider_and_model(self):
        assert prime.split_selector("ollama/qwen3.5:9b") == ("ollama", "qwen3.5:9b")

    def test_bare_model(self):
        """A bare id leaves the provider to Prime."""
        assert prime.split_selector("gpt-4.1") == ("", "gpt-4.1")

    def test_empty(self):
        assert prime.split_selector("") == ("", "")
        assert prime.split_selector("   ") == ("", "")


class TestAcpCommand:
    """Tests for building the ACP launch command."""

    def test_default(self):
        assert prime.acp_command() == "prime-agent --mode acp"

    def test_pins_provider_and_model(self):
        assert prime.acp_command("ollama/qwen3.5:9b") == (
            "prime-agent --mode acp --provider ollama --model qwen3.5:9b"
        )

    def test_bare_model_omits_provider(self):
        assert prime.acp_command("gpt-4.1") == "prime-agent --mode acp --model gpt-4.1"

    def test_respects_base_command(self):
        assert prime.acp_command("ollama/qwen3:8b", base="prime-agent --mode acp --cwd /tmp") == (
            "prime-agent --mode acp --cwd /tmp --provider ollama --model qwen3:8b"
        )


class TestLaunchOptions:
    """Tests for start-time settings Prime accepts only at launch."""

    def test_depth_travels_as_environment(self):
        """``/rlm-max-depth`` has no flag; it is read from the environment."""
        opts = prime.PrimeLaunchOptions(max_depth=3)

        assert opts.env() == {"RLM_MAX_DEPTH": "3"}
        assert "--depth" not in prime.acp_command(options=opts)

    def test_depth_zero_is_not_treated_as_unset(self):
        """Depth 0 disables recursion and must survive a falsy check."""
        assert prime.PrimeLaunchOptions(max_depth=0).env() == {"RLM_MAX_DEPTH": "0"}

    def test_unset_depth_adds_no_environment(self):
        assert prime.PrimeLaunchOptions().env() == {}

    def test_goal_and_budget(self):
        opts = prime.PrimeLaunchOptions(goal="Ship the release", goal_token_budget=5000)

        command = prime.acp_command(options=opts)

        assert "--goal 'Ship the release'" in command
        assert "--goal-token-budget 5000" in command

    def test_budget_needs_a_goal_to_appear(self):
        command = prime.acp_command(options=prime.PrimeLaunchOptions(goal_token_budget=5000))

        assert "--goal-token-budget" not in command

    def test_autonomous_gates_repeat(self):
        opts = prime.PrimeLaunchOptions(autonomous=True, gates=("pytest -q", "ruff check ."))

        command = prime.acp_command(options=opts)

        assert command.count("--autonomous-gate") == 2
        assert "--autonomous-gate 'pytest -q'" in command

    def test_autonomous_without_gates(self):
        command = prime.acp_command(options=prime.PrimeLaunchOptions(autonomous=True))

        assert "--autonomous" in command
        assert "--autonomous-gate" not in command

    def test_arguments_are_quoted(self):
        """A goal is free text and must not be able to add arguments."""
        opts = prime.PrimeLaunchOptions(goal="done; rm -rf /")

        command = prime.acp_command(options=opts)

        assert "--goal 'done; rm -rf /'" in command

    def test_selector_argument_overrides_pinned_model(self):
        opts = prime.PrimeLaunchOptions(model="ollama/qwen3:8b")

        command = prime.acp_command("github-copilot/gpt-4.1", options=opts)

        assert "--model gpt-4.1" in command
        assert "qwen3:8b" not in command

    def test_describe_summarizes_what_is_pinned(self):
        opts = prime.PrimeLaunchOptions(
            model="ollama/qwen3.5:9b", max_depth=2, goal="Fix CI", autonomous=True, gates=("a",)
        )

        summary = opts.describe()

        assert "model ollama/qwen3.5:9b" in summary
        assert "depth 2" in summary
        assert "autonomous with 1 gate(s)" in summary

    def test_describe_is_empty_by_default(self):
        assert prime.PrimeLaunchOptions().describe() == []


class TestAuthIntrospection:
    """Tests for reading Prime's config without touching secrets."""

    def test_auth_providers_lists_names_only(self, tmp_path, monkeypatch):
        home = tmp_path / "agent"
        home.mkdir()
        (home / "auth.json").write_text(
            json.dumps({"github-copilot": {"type": "oauth", "access": "secret-token"}})
        )
        monkeypatch.setenv("PRIME_AGENT_CODING_AGENT_DIR", str(home))

        assert prime.auth_providers() == ["github-copilot"]

    def test_custom_providers(self, tmp_path, monkeypatch):
        home = tmp_path / "agent"
        home.mkdir()
        (home / "models.json").write_text(
            json.dumps({"providers": {"ollama": {"baseUrl": "http://localhost:11434/v1"}}})
        )
        monkeypatch.setenv("PRIME_AGENT_CODING_AGENT_DIR", str(home))

        assert prime.custom_providers() == ["ollama"]

    def test_missing_files_are_not_errors(self, tmp_path, monkeypatch):
        monkeypatch.setenv("PRIME_AGENT_CODING_AGENT_DIR", str(tmp_path / "absent"))

        assert prime.auth_providers() == []
        assert prime.custom_providers() == []

    def test_malformed_json_is_not_an_error(self, tmp_path, monkeypatch):
        home = tmp_path / "agent"
        home.mkdir()
        (home / "auth.json").write_text("{not json")
        monkeypatch.setenv("PRIME_AGENT_CODING_AGENT_DIR", str(home))

        assert prime.auth_providers() == []
