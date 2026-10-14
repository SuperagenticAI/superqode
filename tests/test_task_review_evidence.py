from superqode.app.task_review import task_review


def check(command="pytest -q", exit_code=0):
    return {
        "name": "bash",
        "command": command,
        "status": "success",
        "metadata": {"exit_code": exit_code},
    }


def test_missing_exit_is_unverified():
    assert task_review({}, [check(exit_code=None)]).title == "Unverified"


def test_failure_remains_visible_after_later_success():
    assert task_review({}, [check(exit_code=1), check()]).title == "Checks failed"


def test_post_check_edit_invalidates_evidence():
    result = task_review({}, [check(), {"name": "write", "status": "success"}])
    assert result.title == "Unverified"
    assert "Outdated" in result.summary


def test_rerun_after_edit_records_check():
    assert (
        task_review({}, [{"name": "edit", "status": "success"}, check()]).title == "Checks recorded"
    )


def test_shell_masked_exit_is_unverified():
    assert task_review({}, [check("pytest || true")]).title == "Unverified"


def test_remaining_work_is_not_completed():
    assert task_review({"remaining_work": "Add integration test"}, [check()]).title == "Unverified"
