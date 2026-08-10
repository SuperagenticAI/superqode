"""Contract tests for the Monty research and evaluation profile.

This profile is defined as much by what it refuses as by what it does. It can
hold a corpus, chunk it and query it; it cannot run a command or change a file.
An agent that cannot run tests must not be able to imply it verified anything,
so the refusals are asserted as carefully as the capabilities.
"""

from __future__ import annotations

import importlib.util

import pytest

from superqode.pipy.messages import AssistantMessage, TextContent
from superqode.pipy.provider_events import AssistantDoneEvent
from superqode.pipy.stream import Model
from superqode.rlm.context import RLMContext
from superqode.rlm.kernel_monty import MontyKernelBackend
from superqode.rlm.sandbox import RLMSandboxConfig
from superqode.rlm.subcalls import SubcallExecutor

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pydantic_monty") is None,
    reason="pydantic-monty is not installed",
)


def _stream(model, context, options):
    async def events():
        yield AssistantDoneEvent(
            reason="stop",
            message=AssistantMessage(
                content=[TextContent(text=f"answered:{context.messages[0].text[:12]}")]
            ),
        )

    return events()


@pytest.fixture
async def backend(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "a.py").write_text("alpha = 1\n", encoding="utf-8")
    (repo / "b.py").write_text("beta = 2\n", encoding="utf-8")
    instance = MontyKernelBackend(
        repo,
        config=RLMSandboxConfig.from_config({"sandbox": "monty"}),
        session_id="test",
        state_dir=tmp_path / "state",
        executor=SubcallExecutor(model=Model(id="fake", provider="fake"), stream_fn=_stream),
        context=RLMContext(repo),
    )
    try:
        yield instance
    finally:
        await instance.close()


async def test_python_state_persists_between_calls(backend):
    await backend.execute("root", "value = 40")

    result = await backend.execute("root", "value + 2")

    assert result.value_repr == "42"
    assert result.error is None


async def test_the_corpus_is_available_as_data(backend):
    listed = await backend.execute("root", "context.files()")
    size = await backend.execute("root", "context.size()")
    chunks = await backend.execute("root", "[c.path for c in context.chunk(size=5)][:2]")

    assert listed.value_repr == "['a.py', 'b.py']"
    assert size.value_repr == "19"
    assert chunks.value_repr == "['a.py', 'a.py']"


async def test_subcalls_reach_the_host_and_return_handles(backend):
    single = await backend.execute("root", "repr(llm_query('what is this', context='src'))")
    batch = await backend.execute("root", "[r.text for r in llm_query_batched(['a', 'b'])]")

    assert "RLMResponse(id='query-1'" in single.value_repr
    assert batch.value_repr == "['answered:a', 'answered:b']"


async def test_commands_are_refused_by_name(backend):
    result = await backend.execute("root", "shell.run(['pytest'])")

    assert "no subprocess" in (result.error or "")
    assert "host or docker profile" in (result.error or "")


async def test_repository_writes_are_refused_by_name(backend):
    write = await backend.execute("root", "workspace.write('a.py', 'changed')")
    edit = await backend.execute("root", "workspace.edit('a.py', 'alpha', 'omega')")

    assert "read-only" in (write.error or "")
    assert "read-only" in (edit.error or "")


async def test_reads_still_work_because_they_cannot_change_anything(backend):
    result = await backend.execute("root", "workspace.read('a.py')")

    assert "alpha = 1" in result.value_repr


async def test_the_host_filesystem_and_subprocess_are_unreachable(backend):
    opened = await backend.execute("root", "open('/etc/passwd').read()")
    imported = await backend.execute("root", "import subprocess")

    assert "PermissionError" in (opened.error or "")
    assert "ModuleNotFoundError" in (imported.error or "")


async def test_a_completion_gate_refuses_rather_than_running_on_the_host(backend):
    """A gate that silently ran outside would verify the wrong machine."""
    result = await backend.shell("pytest -q")

    assert result.returncode == 127
    assert result.ok is False
    assert "no subprocess" in result.stderr


async def test_checkpoints_are_monty_snapshots_not_pickles(backend, monkeypatch):
    import pickle

    await backend.execute("root", "carried = 'state'")

    def refuse(*_args, **_kwargs):
        raise AssertionError("A Monty snapshot must never be unpickled by the host")

    monkeypatch.setattr(pickle, "loads", refuse)
    reference = await backend.checkpoint("root")

    assert reference.ok is True
    assert reference.size > 0
    assert reference.digest


async def test_root_and_children_get_separate_namespaces(backend):
    await backend.create_kernel("agent-1")
    await backend.execute("root", "only_in_root = 1")

    result = await backend.execute("agent-1", "only_in_root")

    assert "NameError" in (result.error or "")


async def test_the_profile_reports_what_it_is(backend):
    await backend.start()

    health = await backend.health()

    assert health.alive is True
    assert health.backend == "monty"
    assert "no shell, no writes" in health.detail
