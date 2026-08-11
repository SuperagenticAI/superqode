"""Contract tests for context held as data.

The point of a context object is that a model can measure and narrow a corpus
before deciding how to read it, and that a chunk it queries can be traced back
to the file it came from.
"""

from __future__ import annotations

import asyncio

import pytest

from superqode.rlm.context import ContextChunk, ContextPolicy, RLMContext
from superqode.rlm.kernel import PersistentPythonKernel


def _repo(root, files: dict[str, str]):
    for name, content in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def test_a_repository_becomes_a_measurable_corpus(tmp_path):
    _repo(tmp_path, {"a.py": "value = 1\n", "pkg/b.py": "value = 2\n", "notes.md": "hello\n"})

    context = RLMContext(tmp_path)

    assert context.files() == ["a.py", "notes.md", "pkg/b.py"]
    assert len(context) == sum(len(text) for text in ("value = 1\n", "value = 2\n", "hello\n"))
    assert context.profile == "repository"
    assert "files=3" in repr(context)


def test_measuring_the_corpus_does_not_read_it(tmp_path, monkeypatch):
    """`len` is what a model calls before deciding how to approach a repo."""
    _repo(tmp_path, {"a.py": "x" * 5000})
    context = RLMContext(tmp_path)
    context.files()

    def explode(*_args, **_kwargs):
        raise AssertionError("len(context) must not read file contents")

    monkeypatch.setattr("pathlib.Path.read_bytes", explode)

    assert len(context) == 5000


def test_binary_and_ignored_files_stay_out(tmp_path):
    _repo(tmp_path, {"a.py": "ok\n"})
    (tmp_path / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (tmp_path / "data.bin").write_bytes(b"\x00\x01\x02binary")

    context = RLMContext(tmp_path)

    assert context.files() == ["a.py"]


def test_read_cannot_bypass_context_include_or_exclude_policy(tmp_path):
    _repo(tmp_path, {"visible.py": "ok\n", "secret.env": "token\n"})
    context = RLMContext(tmp_path, policy=ContextPolicy(exclude=("*.env",)))

    assert context.read("visible.py") == "ok\n"
    with pytest.raises(ValueError, match="outside the configured RLM context"):
        context.read("secret.env")


def test_a_view_can_be_narrowed_without_disturbing_the_original(tmp_path):
    _repo(tmp_path, {"src/a.py": "one\n", "src/b.py": "two\n", "docs/c.md": "three\n"})
    context = RLMContext(tmp_path)

    python_only = context.select("src/*.py")

    assert python_only.files() == ["src/a.py", "src/b.py"]
    assert python_only.profile == "explicit"
    assert len(context.files()) == 3


def test_chunks_remember_where_they_came_from(tmp_path):
    _repo(tmp_path, {"a.py": "a" * 250, "b.py": "b" * 100})

    chunks = RLMContext(tmp_path).chunk(size=100)

    assert [chunk.path for chunk in chunks] == ["a.py", "a.py", "a.py", "b.py"]
    assert [chunk.index for chunk in chunks] == [0, 1, 2, 0]
    assert (chunks[1].start, chunks[1].end) == (100, 200)
    assert len(chunks[2]) == 50
    assert isinstance(chunks[0], ContextChunk)
    assert chunks[0].labelled().startswith("# a.py (chars 0-100)")


def test_chunks_can_overlap_so_a_boundary_does_not_split_meaning(tmp_path):
    _repo(tmp_path, {"a.py": "0123456789"})

    chunks = RLMContext(tmp_path).chunk(size=6, overlap=2)

    assert [chunk.text for chunk in chunks] == ["012345", "456789", "89"]


def test_a_chunk_shows_a_preview_rather_than_its_contents(tmp_path):
    _repo(tmp_path, {"a.py": "z" * 4000})

    chunk = RLMContext(tmp_path).chunk(size=4000)[0]

    assert len(repr(chunk)) < 160
    assert "chars=4000" in repr(chunk)


def test_search_reports_path_and_line(tmp_path):
    _repo(tmp_path, {"a.py": "alpha\nbeta\n", "b.py": "beta\n"})

    matches = RLMContext(tmp_path).search("beta")

    assert matches == ["a.py:2:beta", "b.py:1:beta"]


def test_search_is_bounded(tmp_path):
    _repo(tmp_path, {"a.py": "match\n" * 500})

    assert len(RLMContext(tmp_path).search("match", limit=10)) == 10


def test_a_large_file_is_truncated_and_the_fact_is_reported(tmp_path):
    _repo(tmp_path, {"big.py": "x" * 5000})
    context = RLMContext(tmp_path, policy=ContextPolicy(max_file_bytes=1000))

    text = context.read("big.py")

    assert len(text) == 1000
    assert context.stats()["truncated"] == ["big.py"]


def test_the_file_count_is_bounded(tmp_path):
    _repo(tmp_path, {f"file{index}.py": "x" for index in range(20)})

    context = RLMContext(tmp_path, policy=ContextPolicy(max_files=5))

    assert len(context.files()) == 5


def test_a_path_outside_the_root_is_refused(tmp_path):
    _repo(tmp_path, {"a.py": "ok"})

    with pytest.raises(ValueError, match="escapes context root"):
        RLMContext(tmp_path).read("../secrets.txt")


def test_a_document_context_needs_no_repository(tmp_path):
    context = RLMContext(tmp_path, document="line one\nline two\n")

    assert context.profile == "document"
    assert len(context) == 18
    assert context.text() == "line one\nline two\n"
    assert context.search("two") == ["<document>:2:line two"]
    assert [chunk.path for chunk in context.chunk(size=5)] == ["<document>"] * 4


def test_the_policy_reads_runtime_config():
    policy = ContextPolicy.from_config(
        {"context_max_files": 10, "context_include": ["src/**"], "context_exclude": ["**/gen.py"]}
    )

    assert policy.max_files == 10
    assert policy.include == ("src/**",)
    assert policy.exclude == ("**/gen.py",)


async def test_the_kernel_namespace_exposes_context(tmp_path):
    _repo(tmp_path, {"a.py": "value = 1\n"})
    kernel = PersistentPythonKernel(tmp_path)

    listed = await kernel.execute("context.files()")
    size = await kernel.execute("len(context)")

    assert listed.value_repr == "['a.py']"
    assert size.value_repr == "10"


async def test_context_is_not_checkpointed(tmp_path):
    """It is a host-owned view of the repository, not user state."""
    _repo(tmp_path, {"a.py": "ok\n"})
    kernel = PersistentPythonKernel(tmp_path, checkpoint_path=tmp_path / "state.pkl")

    await kernel.execute("kept = 1")
    saved = kernel.checkpoint()

    assert saved["saved"] == ["kept"]
    assert "context" not in saved["skipped"]


async def test_chunking_then_querying_is_the_intended_shape(tmp_path):
    """The pattern the harness exists for: chunk the corpus, query the chunks."""
    from superqode.pipy.messages import AssistantMessage, TextContent
    from superqode.pipy.provider_events import AssistantDoneEvent
    from superqode.pipy.stream import Model
    from superqode.rlm.subcalls import SubcallExecutor

    _repo(tmp_path, {"a.py": "alpha\n" * 200, "b.py": "beta\n" * 200})

    def stream_fn(model, context, options):
        async def events():
            prompt = context.messages[0].text
            answer = "alpha" if "alpha" in prompt else "beta"
            yield AssistantDoneEvent(
                reason="stop",
                message=AssistantMessage(content=[TextContent(text=answer)]),
            )

        return events()

    kernel = PersistentPythonKernel(tmp_path)
    kernel.subcalls.bind(
        SubcallExecutor(model=Model(id="fake", provider="fake"), stream_fn=stream_fn),
        asyncio.get_running_loop(),
    )

    result = await kernel.execute(
        "chunks = context.chunk(size=600)\n"
        "answers = llm_query_batched([c.labelled() for c in chunks])\n"
        "sorted({a.text for a in answers})"
    )

    assert result.error is None
    assert result.value_repr == "['alpha', 'beta']"
