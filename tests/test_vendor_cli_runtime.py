"""Vendor CLI runtime: subscription billing, permissions, and wire formats.

The JSON fixtures are recorded from the real CLIs (Grok streaming-json and
GitHub Copilot JSONL, both verified against live subscriptions), so the parsers
stay honest without needing a vendor CLI installed in CI.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

import pytest

from superqode.runtime.vendor_cli import (
    VENDOR_CLI_SPECS,
    VendorCLIRuntime,
    grok_rule_from_pattern,
    parse_copilot_event,
    parse_generic_event,
    parse_grok_event,
    spec_for,
)


def _events(parser, raw: str):
    return parser(json.loads(raw))


class TestGrokWireFormat:
    """Recorded from `grok -p ... --output-format streaming-json`."""

    def test_text_becomes_assistant_output(self):
        events = _events(parse_grok_event, '{"type":"text","data":"OK"}')

        assert [(e.type, e.data["text"]) for e in events] == [("model_delta", "OK")]

    def test_thought_is_reasoning_not_assistant_output(self):
        events = _events(parse_grok_event, '{"type":"thought","data":"pondering"}')

        assert [e.type for e in events] == ["thinking"]

    def test_end_carries_stop_reason_and_session(self):
        events = _events(
            parse_grok_event,
            '{"type":"end","stopReason":"EndTurn","sessionId":"abc","usage":{"input_tokens":7}}',
        )

        assert len(events) == 1
        assert events[0].type == "turn_complete"
        assert events[0].data["stop_reason"] == "EndTurn"
        assert events[0].data["session_id"] == "abc"
        assert events[0].data["usage"] == {"input_tokens": 7}

    def test_tool_call_becomes_harness_tool_call(self):
        events = _events(
            parse_grok_event,
            json.dumps(
                {
                    "type": "tool_call",
                    "toolCallId": "call-1",
                    "toolName": "list_dir",
                    "kind": "list",
                    "status": "pending",
                    "title": "List",
                    "rawInput": {"target_directory": "."},
                }
            ),
        )

        assert len(events) == 1
        assert events[0].type == "tool_call"
        assert events[0].data["tool_name"] == "list_dir"
        assert events[0].data["tool_call_id"] == "call-1"
        assert events[0].data["args"] == {"target_directory": "."}

    def test_tool_call_update_pending_is_silent(self):
        assert (
            _events(
                parse_grok_event,
                '{"type":"tool_call_update","toolCallId":"call-1","status":"in_progress"}',
            )
            == []
        )

    def test_tool_call_update_completed_is_tool_result(self):
        events = _events(
            parse_grok_event,
            json.dumps(
                {
                    "type": "tool_call_update",
                    "toolCallId": "call-1",
                    "status": "completed",
                    "rawOutput": {"entries": ["a"]},
                }
            ),
        )

        assert events[0].type == "tool_result"
        assert events[0].data["tool_call_id"] == "call-1"
        assert events[0].data["success"] is True
        assert "entries" in events[0].data["output"]

    def test_plan_maps_to_plan_update(self):
        events = _events(
            parse_grok_event,
            json.dumps(
                {
                    "type": "plan",
                    "entries": [{"content": "List files", "status": "pending", "priority": "high"}],
                }
            ),
        )

        assert events[0].type == "plan_update"
        assert events[0].data["todos"][0]["content"] == "List files"

    def test_error_is_a_failed_turn(self):
        events = _events(parse_grok_event, '{"type":"error","message":"auth failed"}')

        assert events[0].type == "turn_complete"
        assert events[0].data["status"] == "failed"
        assert events[0].data["error"] == "auth failed"

    def test_end_keeps_spend_and_does_not_invent_cost(self):
        events = _events(
            parse_grok_event,
            json.dumps(
                {
                    "type": "end",
                    "stopReason": "end_turn",
                    "sessionId": "s1",
                    "usage": {"input_tokens": 10, "output_tokens": 2},
                    "num_turns": 2,
                    "modelUsage": {"grok-4.6-build": {"inputTokens": 10}},
                    "total_cost_usd": 0.017,
                }
            ),
        )

        assert events[0].data["total_cost_usd"] == 0.017
        assert events[0].data["num_turns"] == 2
        assert "grok-4.6-build" in events[0].data["model_usage"]

    def test_partial_cost_is_not_surfaced_as_a_total(self):
        events = _events(
            parse_grok_event,
            json.dumps(
                {
                    "type": "end",
                    "sessionId": "s1",
                    "cost_is_partial": True,
                    "total_cost_usd": 0.01,
                }
            ),
        )

        assert events[0].data.get("cost_is_partial") is True
        assert "total_cost_usd" not in events[0].data

    def test_available_commands_are_not_harness_events(self):
        assert (
            _events(
                parse_grok_event,
                json.dumps(
                    {"type": "available_commands", "tools": ["list_dir"], "commands": ["review"]}
                ),
            )
            == []
        )

    def test_available_commands_land_on_runtime_metadata(self, monkeypatch):
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )

        class _Stdout:
            def __init__(self):
                self.lines = [
                    b'{"type":"available_commands","tools":["list_dir"],"commands":["review"]}\n',
                    b"",
                ]

            async def readline(self):
                return self.lines.pop(0) if self.lines else b""

        class _Proc:
            stdout = _Stdout()

        runtime = VendorCLIRuntime(spec=spec_for("grok"), config=None)
        runtime._process = _Proc()

        async def drain():
            return [event async for event in runtime._stream(parse_grok_event)]

        events = asyncio.run(drain())
        assert events == []
        assert runtime.metadata["available_commands"]["tools"] == ["list_dir"]


class TestCopilotWireFormat:
    """Recorded from `copilot -p ... --output-format json`."""

    def test_message_delta_becomes_assistant_output(self):
        events = _events(
            parse_copilot_event,
            '{"type":"assistant.message_delta","data":{"deltaContent":"CLI"}}',
        )

        assert [(e.type, e.data["text"]) for e in events] == [("model_delta", "CLI")]

    def test_auto_mode_reports_the_model_actually_used(self):
        """Copilot Free advertises no catalog, so this is the only model signal."""
        events = _events(
            parse_copilot_event,
            '{"type":"session.auto_mode_resolved","data":{"chosenModel":"gpt-5-mini"}}',
        )

        assert [(e.type, e.data["model"]) for e in events] == [("model_request", "gpt-5-mini")]

    def test_usage_checkpoint_is_reported(self):
        events = _events(
            parse_copilot_event,
            '{"type":"session.usage_checkpoint","data":{"totalPremiumRequests":0}}',
        )

        assert events[0].type == "turn_usage"

    def test_unrecognised_events_are_ignored(self):
        assert _events(parse_copilot_event, '{"type":"session.skills_loaded","data":{}}') == []


class TestGenericWireFormat:
    def test_claude_code_style_content_blocks(self):
        events = _events(
            parse_generic_event,
            '{"type":"assistant","message":{"content":[{"type":"text","text":"hi"}]}}',
        )

        assert [(e.type, e.data["text"]) for e in events] == [("model_delta", "hi")]

    def test_unknown_object_produces_nothing(self):
        """An unknown field must never be rendered as if it were the answer."""
        assert _events(parse_generic_event, '{"type":"telemetry","fooBar":123}') == []


class TestCommandConstruction:
    def _runtime(self, vendor, monkeypatch, model=""):
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )

        class Config:
            def __init__(self):
                self.model = model
                self.working_directory = Path("/tmp")

        return VendorCLIRuntime(spec=spec_for(vendor), config=Config())

    def test_grok_uses_streaming_json_and_the_prompt_flag(self, monkeypatch):
        argv = self._runtime("grok", monkeypatch).build_command("hello")

        assert "--output-format" in argv and "streaming-json" in argv
        assert argv[-2:] == ["-p", "hello"]

    def test_droid_passes_the_prompt_positionally_after_exec(self, monkeypatch):
        argv = self._runtime("droid", monkeypatch).build_command("hello")

        assert argv[1] == "exec"
        assert argv[-1] == "hello"

    def test_auto_model_is_not_forwarded(self, monkeypatch):
        """'auto' is a SuperQode placeholder, not a vendor model id."""
        argv = self._runtime("grok", monkeypatch, model="auto").build_command("hi")

        assert "--model" not in argv

    def test_explicit_model_is_forwarded(self, monkeypatch):
        argv = self._runtime("grok", monkeypatch, model="grok-build-1").build_command("hi")

        assert argv[argv.index("--model") + 1] == "grok-build-1"

    def test_missing_binary_is_reported_with_install_help(self, monkeypatch):
        from superqode.runtime.errors import RuntimeNotInstalledError

        monkeypatch.setattr("superqode.runtime.vendor_cli.shutil.which", lambda _n: None)

        with pytest.raises(RuntimeNotInstalledError, match="grok login"):
            VendorCLIRuntime(spec=spec_for("grok"), config=None)


class TestPermissionTransparency:
    def test_pre_authorisation_is_announced_once(self, monkeypatch):
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )
        runtime = VendorCLIRuntime(spec=spec_for("copilot"), config=None)

        first = runtime._permission_notice()
        second = runtime._permission_notice()

        assert first is not None
        assert "not individually approved" in first.data["text"]
        assert second is None, "the notice must not repeat every turn"

    def test_copilot_is_marked_as_requiring_pre_authorisation(self):
        """Its own help says --allow-all-tools is required for non-interactive."""
        spec = VENDOR_CLI_SPECS["copilot"]
        assert spec.requires_pre_authorisation is True
        assert "--allow-all-tools" in spec.flags_for_approval("auto")
        # Copilot offers no gradation non-interactively, so every approval mode
        # resolves to the same flags and the notice must say so.
        assert spec.has_gradated_permissions is False
        assert spec.flags_for_approval("deny") == spec.flags_for_approval("auto")

    def test_grok_deny_is_dont_ask_not_plan(self):
        spec = VENDOR_CLI_SPECS["grok"]
        assert spec.flags_for_approval("deny") == ("--permission-mode", "dontAsk")
        assert spec.flags_for_approval("ask") == ("--permission-mode", "auto")
        assert spec.flags_for_approval("auto") == ("--permission-mode", "bypassPermissions")
        assert spec.has_gradated_permissions is True

    def test_grok_notice_names_dont_ask_and_acp(self, monkeypatch):
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )
        runtime = VendorCLIRuntime(spec=spec_for("grok"), config=None, approval_mode="deny")
        notice = runtime._permission_notice()
        assert notice is not None
        assert "dontAsk" in notice.data["text"]
        assert ":connect grok" in notice.data["text"]

    def test_grok_allow_deny_patterns_are_projected(self, monkeypatch):
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )

        class _Perms:
            config = type(
                "C",
                (),
                {
                    "deny_patterns": ["Bash(rm*)", "mystery-glob-*", "bash"],
                    "allow_patterns": ["Read"],
                },
            )()

        runtime = VendorCLIRuntime(
            spec=spec_for("grok"),
            config=None,
            permission_manager=_Perms(),
        )
        argv = runtime.build_command("hi")
        assert argv[argv.index("--deny") + 1] == "Bash(rm*)"
        assert "Bash" in argv
        assert "Read" in argv
        assert "mystery-glob-*" not in argv

    def test_grok_rule_map_is_conservative(self):
        assert grok_rule_from_pattern("Bash(rm*)") == "Bash(rm*)"
        assert grok_rule_from_pattern("bash") == "Bash"
        assert grok_rule_from_pattern("src/**/*.py") is None


class TestSubscriptionBilling:
    def test_child_env_drops_the_key_while_os_environ_is_untouched(self, monkeypatch):
        """SuperQode must never modify the user's own API keys."""
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )
        monkeypatch.setenv("XAI_API_KEY", "user-key")
        captured = {}

        async def fake_exec(*argv, **kwargs):
            captured["env"] = kwargs.get("env", {})
            raise OSError("stop after env capture")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        class Config:
            model = ""
            working_directory = Path("/tmp")

        runtime = VendorCLIRuntime(spec=spec_for("grok"), config=Config())

        async def drain():
            return [event async for event in runtime.run_harness_events("hi")]

        events = asyncio.run(drain())

        assert "XAI_API_KEY" not in captured["env"]
        assert os.environ["XAI_API_KEY"] == "user-key", "the user's key must survive"
        assert runtime.stripped_api_keys == ["XAI_API_KEY"]
        assert events[-1].data["status"] == "failed"

    def test_sigint_exit_is_cancelled(self, monkeypatch):
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )

        class _Stdout:
            async def readline(self):
                return b""

        class _Proc:
            returncode = 130
            stdout = _Stdout()
            stderr = None

            async def wait(self):
                return 130

            def kill(self):
                return None

        async def fake_exec(*_argv, **_kwargs):
            return _Proc()

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        class Config:
            model = ""
            working_directory = Path("/tmp")

        runtime = VendorCLIRuntime(spec=spec_for("grok"), config=Config())

        async def drain():
            return [event async for event in runtime.run_harness_events("hi")]

        events = asyncio.run(drain())
        assert events[-1].data["status"] == "cancelled"

    def test_other_providers_keys_reach_the_child_untouched(self, monkeypatch):
        """A Grok subscription must not disturb an unrelated BYOK key."""
        monkeypatch.setattr(
            "superqode.runtime.vendor_cli.shutil.which", lambda name: f"/usr/bin/{name}"
        )
        monkeypatch.setenv("XAI_API_KEY", "xai")
        monkeypatch.setenv("OPENAI_API_KEY", "byok-key")
        captured = {}

        async def fake_exec(*argv, **kwargs):
            captured["env"] = kwargs.get("env", {})
            raise OSError("stop")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)

        class Config:
            model = ""
            working_directory = Path("/tmp")

        runtime = VendorCLIRuntime(spec=spec_for("grok"), config=Config())

        async def drain():
            return [event async for event in runtime.run_harness_events("hi")]

        asyncio.run(drain())

        assert captured["env"]["OPENAI_API_KEY"] == "byok-key"


class TestSpecTable:
    def test_every_spec_resolves_from_its_vendor_and_runtime_name(self):
        for vendor, spec in VENDOR_CLI_SPECS.items():
            assert spec_for(vendor) is spec
            assert spec_for(spec.name) is spec

    def test_every_spec_names_a_parser_that_exists(self):
        from superqode.runtime.vendor_cli import PARSERS

        for spec in VENDOR_CLI_SPECS.values():
            assert spec.parser in PARSERS

    def test_every_spec_has_install_help(self):
        for spec in VENDOR_CLI_SPECS.values():
            assert spec.install_hint.strip()
