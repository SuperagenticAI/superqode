"""Tests for dangling tool-call repair (keeps message history provider-valid)."""

from superqode.agent.loop import AgentMessage, repair_dangling_tool_calls


def _assistant(*ids):
    return AgentMessage(
        role="assistant",
        content="",
        tool_calls=[{"id": i, "function": {"name": "read", "arguments": "{}"}} for i in ids],
    )


def _tool(tool_call_id=None):
    return AgentMessage(role="tool", content="ok", tool_call_id=tool_call_id, name="read")


def _synth(messages):
    return [m for m in messages if m.role == "tool" and "did not complete" in m.content]


def test_fully_answered_is_unchanged():
    seq = [AgentMessage("user", "hi"), _assistant("a"), _tool("a")]
    out = repair_dangling_tool_calls(seq)
    assert [m.role for m in out] == ["user", "assistant", "tool"]
    assert _synth(out) == []


def test_dangling_call_gets_synthetic_result():
    # Approval pause / cancellation: a tool_call with no result.
    out = repair_dangling_tool_calls([_assistant("a")])
    assert [m.role for m in out] == ["assistant", "tool"]
    synth = _synth(out)
    assert len(synth) == 1
    assert synth[0].tool_call_id == "a"


def test_partial_answer_synthesizes_only_missing():
    out = repair_dangling_tool_calls([_assistant("a", "b"), _tool("a")])
    synth = _synth(out)
    assert [m.tool_call_id for m in synth] == ["b"]  # only the unanswered one


def test_positional_match_for_idless_results():
    # Resumed sessions may store tool results without a tool_call_id.
    out = repair_dangling_tool_calls([_assistant("a"), _tool(None)])
    assert _synth(out) == []  # id-less result answers the call positionally
    assert len(out) == 2


def test_positional_partial_leaves_remainder_dangling():
    out = repair_dangling_tool_calls([_assistant("a", "b"), _tool(None)])
    assert len(_synth(out)) == 1  # second call still dangling


def test_idempotent():
    once = repair_dangling_tool_calls([_assistant("a")])
    twice = repair_dangling_tool_calls(once)
    assert len(once) == len(twice)
    assert len(_synth(twice)) == 1


def test_empty_and_no_tool_calls():
    assert repair_dangling_tool_calls([]) == []
    plain = [AgentMessage("user", "hi"), AgentMessage("assistant", "hello")]
    assert repair_dangling_tool_calls(plain) == plain


def test_synthetic_result_is_provider_valid():
    out = repair_dangling_tool_calls([_assistant("x")])
    synth = _synth(out)[0]
    assert synth.role == "tool"
    assert synth.tool_call_id == "x"
    assert synth.name == "read"
    assert synth.content  # non-empty
