"""Native review keeps revision evidence and changes only explicitly staged paths."""

import json
import subprocess

import pytest

from test_desktop_service import desktop  # noqa: F401


def git(root, *args):
    return subprocess.run(["git", "-C", str(root), *args], check=True, capture_output=True).stdout


def commit(root):
    git(
        root,
        "-c",
        "user.name=Local test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-qm",
        "Fixture",
    )


@pytest.fixture
def review(desktop):
    service, project, root = desktop
    commit(root)
    return service, project, root


def files(review, scope="uncommitted", **extra):
    service, project, _ = review
    return service.dispatch("review.list", {"project": project["id"], "scope": scope, **extra})


def detail(review, path="hello.txt", layer="unstaged", scope="uncommitted", **extra):
    service, project, _ = review
    listing = files(review, scope, **extra)
    item = next(row for row in listing["files"] if row["path"] == path and row["layer"] == layer)
    params = {"project": project["id"], "scope": scope, "file_id": item["id"], **extra}
    result = service.dispatch("review.diff", params)
    return result, {**params, "snapshot_id": result.get("snapshot_id")}


def test_uncommitted_keeps_staged_and_unstaged_versions_separate(review):
    _, _, root = review
    (root / "hello.txt").write_text("staged\n")
    git(root, "add", "hello.txt")
    (root / "hello.txt").write_text("unstaged\n")
    index_before = git(root, "ls-files", "--stage", "-z")
    staged, _ = detail(review, layer="staged")
    unstaged, _ = detail(review)
    assert staged["hunks"][0]["lines"][-1]["text"] == "staged"
    assert unstaged["hunks"][0]["lines"][0]["text"] == "staged"
    assert unstaged["hunks"][0]["lines"][-1]["text"] == "unstaged"
    assert git(root, "ls-files", "--stage", "-z") == index_before
    assert (root / "hello.txt").read_text() == "unstaged\n"


def test_index_only_change_is_visible_even_when_worktree_matches_head(review):
    _, _, root = review
    (root / "hello.txt").write_text("staged")
    git(root, "add", "hello.txt")
    (root / "hello.txt").write_text("hello")
    assert {row["layer"] for row in files(review)["files"]} == {"staged", "unstaged"}


def test_branch_is_committed_range_and_ignores_later_worktree_edits(review):
    service, _, root = review
    base = git(root, "rev-parse", "HEAD").decode().strip()
    (root / "hello.txt").write_text("committed\n")
    git(root, "add", "hello.txt")
    commit(root)
    (root / "hello.txt").write_text("later local edit\n")
    result, params = detail(review, layer="branch", scope="branch", base_ref=base)
    assert result["hunks"][0]["lines"][-1]["text"] == "committed"
    assert result["revisions"]["base"] == base
    (root / "hello.txt").write_text("another local edit\n")
    feedback = service.dispatch(
        "review.feedback", {**params, "hunk_id": 0, "start": 1, "end": 1, "comment": "Improve this"}
    )
    assert "Review feedback — Branch" in feedback["text"]
    with pytest.raises(ValueError, match="Only complete"):
        service.dispatch("review.stage", params)


@pytest.mark.parametrize("reference", ["--help", "main\nother", "", None])
def test_branch_requires_valid_reference(review, reference):
    with pytest.raises(ValueError, match="valid base"):
        files(review, "branch", base_ref=reference)


def test_feedback_contains_exact_old_and_new_line_numbers_and_revisions(review):
    service, _, root = review
    (root / "hello.txt").write_text("replacement\nsecond\n")
    result, params = detail(review)
    before = git(root, "ls-files", "--stage", "-z")
    feedback = service.dispatch(
        "review.feedback",
        {**params, "hunk_id": 0, "start": 0, "end": 1, "comment": "Please simplify"},
    )
    payload = feedback["anchor"]
    assert "old 1 / new – [-]" in feedback["text"]
    assert payload["snapshot_id"] == result["snapshot_id"]
    assert payload["lines"][0]["old_line"] == 1
    assert payload["lines"][0]["new_line"] is None
    assert payload["lines"][1]["new_line"] == 1
    assert payload["lines"][1]["old_line"] is None
    assert payload["comment"] == "Please simplify"
    assert git(root, "ls-files", "--stage", "-z") == before
    assert not service._all("SELECT id FROM jobs")


@pytest.mark.parametrize("method", ["review.stage", "review.feedback"])
def test_stale_worktree_review_cannot_stage_or_attach_feedback(review, method):
    service, _, root = review
    (root / "hello.txt").write_text("reviewed\n")
    _, params = detail(review)
    (root / "hello.txt").write_text("newer\n")
    index = git(root, "ls-files", "--stage", "-z")
    with pytest.raises(ValueError, match="revision changed"):
        service.dispatch(method, {**params, "hunk_id": 0, "start": 0, "end": 0, "comment": "Fix"})
    assert git(root, "ls-files", "--stage", "-z") == index
    assert not (root / ".git/index.lock").exists()


def test_staging_review_preserves_other_staged_and_unstaged_edits(review):
    service, _, root = review
    (root / "other.txt").write_text("other staged")
    git(root, "add", "other.txt")
    (root / "other.txt").write_text("other unstaged")
    other_index = git(root, "show", ":other.txt")
    (root / "hello.txt").write_text("reviewed\n")
    _, params = detail(review)
    service.dispatch("review.stage", params)
    assert git(root, "show", ":hello.txt") == b"reviewed\n"
    assert git(root, "show", ":other.txt") == other_index
    assert (root / "other.txt").read_text() == "other unstaged"


def test_stale_index_review_preserves_newer_staged_edits(review):
    service, _, root = review
    (root / "hello.txt").write_text("reviewed\n")
    _, params = detail(review)
    (root / "hello.txt").write_text("new staged\n")
    git(root, "add", "hello.txt")
    (root / "hello.txt").write_text("reviewed\n")
    with pytest.raises(ValueError, match="revision changed"):
        service.dispatch("review.stage", params)
    assert git(root, "show", ":hello.txt") == b"new staged\n"


def test_tracked_deletion_can_be_reviewed_and_staged(review):
    service, _, root = review
    (root / "hello.txt").unlink()
    result, params = detail(review)
    assert result["change"] == "D"
    assert result["hunks"][0]["lines"][0]["kind"] == "delete"
    service.dispatch("review.stage", params)
    assert git(root, "ls-files", "hello.txt") == b""
    assert not (root / "hello.txt").exists()


def test_untracked_special_path_stages_only_literal_file(review):
    service, _, root = review
    name = "space [x]*,file.txt"
    (root / name).write_text("new file\n")
    (root / "space x-other.txt").write_text("leave alone")
    _, params = detail(review, path=name, layer="untracked")
    service.dispatch("review.stage", params)
    assert name.encode() in git(root, "ls-files", "-z").split(b"\0")
    assert b"space x-other.txt" not in git(root, "ls-files", "-z").split(b"\0")


def test_busy_index_is_not_removed_or_changed(review):
    service, _, root = review
    (root / "hello.txt").write_text("reviewed")
    _, params = detail(review)
    lock = root / ".git/index.lock"
    lock.write_text("owned elsewhere")
    with pytest.raises(ValueError, match="index is busy"):
        service.dispatch("review.stage", params)
    assert lock.read_text() == "owned elsewhere"


@pytest.mark.parametrize("status", ["running", "queued", "needs_approval", "cancelling"])
def test_staging_is_blocked_while_project_work_is_active(review, status):
    service, project, root = review
    (root / "hello.txt").write_text("reviewed")
    _, params = detail(review)
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("active", project["id"], "task", "Active", status, "{}", None, 1, 1),
    )
    with pytest.raises(ValueError, match="Finish or stop"):
        service.dispatch("review.stage", params)


def test_sensitive_paths_are_excluded_and_symlink_content_is_not_read(review, tmp_path):
    _, _, root = review
    (root / ".env").write_text("secret")
    (root / ".aws").mkdir()
    (root / ".aws/credentials").write_text("secret")
    outside = tmp_path / "outside"
    outside.write_text("outside secret")
    (root / "link").symlink_to(outside)
    listing = files(review)
    assert listing["excluded_count"] == 2
    assert {row["path"] for row in listing["files"]} == {"link"}
    result, _ = detail(review, path="link", layer="untracked")
    assert result["hunks"] == []
    assert not result["can_stage"]
    assert "outside secret" not in json.dumps(result)


@pytest.mark.parametrize(
    "content",
    [b"binary\0data", b"\xff\xfe", b"x" * 1_000_001],
    ids=["binary", "non-utf8", "oversized"],
)
def test_unsupported_content_is_explicit_and_cannot_be_staged(review, content):
    service, _, root = review
    (root / "hello.txt").write_bytes(content)
    result, params = detail(review)
    assert result["issue"]
    assert not result["can_stage"]
    with pytest.raises(ValueError):
        service.dispatch("review.stage", params)


def test_unborn_repository_and_empty_untracked_file(desktop):
    service, _, root = desktop
    (root / "empty.txt").write_text("")
    staged, _ = detail(desktop, layer="staged")
    assert staged["change"] == "A"
    assert staged["revisions"] == {}
    result, params = detail(desktop, path="empty.txt", layer="untracked")
    assert result["can_stage"] and not result["hunks"]
    service.dispatch("review.stage", params)
    assert git(root, "show", ":empty.txt") == b""


def test_turn_uses_sealed_after_state_not_current_worktree(review):
    from superqode.desktop_service.checkpoints import begin_task, finish_task

    service, project, root = review
    capture = begin_task(root, "Selected turn")
    (root / "hello.txt").write_text("turn result\n")
    finish_task(capture)
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("turn", project["id"], "task", "Turn", "completed", "{}", "{}", 1, 1),
    )
    service.append("turn", {"type": "checkpoint", "data": {"id": capture[2], "phase": "baseline"}})
    (root / "hello.txt").write_text("later unrelated changes\n")
    result, _ = detail(review, layer="turn", scope="turn", job="turn")
    assert result["hunks"][0]["lines"][-1]["text"] == "turn result"
    assert "concurrent edits" in result["label"]
    assert not result["can_stage"]


@pytest.mark.parametrize("selection", [(False, 1), (-1, 1), (1, 0), (0, 999)])
def test_feedback_rejects_invalid_ranges(review, selection):
    service, _, root = review
    (root / "hello.txt").write_text("new\n")
    _, params = detail(review)
    with pytest.raises(ValueError, match="contiguous"):
        service.dispatch(
            "review.feedback",
            {**params, "hunk_id": 0, "start": selection[0], "end": selection[1], "comment": "Fix"},
        )


def test_mode_only_change_is_visible_and_can_be_staged(review):
    service, _, root = review
    (root / "hello.txt").chmod(0o755)
    result, params = detail(review)
    assert result["hunks"] == []
    assert result["base_mode"] == "100644"
    assert result["target_mode"] == "100755"
    service.dispatch("review.stage", params)
    assert git(root, "ls-files", "--stage", "hello.txt").startswith(b"100755")


def test_stage_uses_normal_git_text_normalization(review):
    service, _, root = review
    (root / ".gitattributes").write_text("*.txt text eol=lf\n")
    (root / "hello.txt").write_bytes(b"reviewed\r\ntext\r\n")
    _, params = detail(review)
    service.dispatch("review.stage", params)
    assert git(root, "show", ":hello.txt") == b"reviewed\ntext\n"
    assert (root / "hello.txt").read_bytes() == b"reviewed\r\ntext\r\n"
    assert b".gitattributes" not in git(root, "ls-files", "-z").split(b"\0")


def test_large_preview_cannot_authorize_staging_or_comments(review):
    service, _, root = review
    (root / "hello.txt").write_text("".join(f"line {index}\n" for index in range(6000)))
    result, params = detail(review)
    assert result["truncated"]
    assert not result["can_stage"]
    with pytest.raises(ValueError, match="complete"):
        service.dispatch(
            "review.feedback", {**params, "hunk_id": 0, "start": 0, "end": 0, "comment": "Fix"}
        )
    with pytest.raises(ValueError, match="complete"):
        service.dispatch("review.stage", params)


def test_list_limit_is_explicit(review):
    _, _, root = review
    for index in range(502):
        (root / f"new-{index}.txt").write_text("new")
    listing = files(review)
    assert len(listing["files"]) == 500
    assert listing["truncated"]


def test_staging_failure_releases_lock_and_preserves_real_index(review, monkeypatch):
    from superqode.desktop_service import review as module

    service, _, root = review
    (root / "hello.txt").write_text("reviewed")
    _, params = detail(review)
    original = git(root, "ls-files", "--stage", "-z")
    run = module._git

    def fail_update(root, *args, **kwargs):
        if args[0] == "update-index":
            raise ValueError("Injected index failure")
        return run(root, *args, **kwargs)

    monkeypatch.setattr(module, "_git", fail_update)
    with pytest.raises(ValueError, match="Injected index failure"):
        service.dispatch("review.stage", params)
    assert git(root, "ls-files", "--stage", "-z") == original
    assert not (root / ".git/index.lock").exists()
    assert not list((root / ".git").glob(".superqode-review-*"))


def test_cancelled_job_writer_still_blocks_staging(review):
    service, project, root = review
    (root / "hello.txt").write_text("reviewed")
    _, params = detail(review)
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("writer", project["id"], "task", "Writer", "cancelled", "{}", None, 1, 1),
    )
    service.processes["writer"] = object()
    try:
        with pytest.raises(ValueError, match="Finish or stop"):
            service.dispatch("review.stage", params)
    finally:
        service.processes.pop("writer")


def test_missing_checkpoint_does_not_fall_back_to_worktree(review):
    service, project, _ = review
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("turn", project["id"], "task", "Turn", "completed", "{}", None, 1, 1),
    )
    with pytest.raises(ValueError, match="no local checkpoint"):
        files(review, "turn", job="turn")


def test_turn_cannot_reference_foreign_project(review, tmp_path):
    service, _, _ = review
    foreign_root = tmp_path / "foreign"
    foreign_root.mkdir()
    foreign = service.open_project(str(foreign_root))
    service._write(
        "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?)",
        ("foreign", foreign["id"], "task", "Foreign", "completed", "{}", None, 1, 1),
    )
    with pytest.raises(ValueError, match="this project"):
        files(review, "turn", job="foreign")


def test_staging_in_linked_worktree_uses_its_own_index(review, tmp_path):
    service, _, root = review
    linked = tmp_path / "linked"
    git(root, "worktree", "add", "--detach", str(linked), "HEAD")
    project = service.open_project(str(linked))
    (linked / "hello.txt").write_text("linked change\n")
    original_index = git(root, "ls-files", "--stage", "-z")
    _, params = detail((service, project, linked))
    service.dispatch("review.stage", params)
    assert git(linked, "show", ":hello.txt") == b"linked change\n"
    assert git(root, "ls-files", "--stage", "-z") == original_index
    assert (root / "hello.txt").read_text() == "hello"
