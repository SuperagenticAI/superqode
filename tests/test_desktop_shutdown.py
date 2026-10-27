import sqlite3
import threading

import pytest

from superqode.desktop_service.service import DesktopService


def test_close_releases_database_and_is_idempotent(tmp_path):
    service = DesktopService(tmp_path / "state")
    service.close()
    service.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        service.db.execute("SELECT 1")


def test_close_waits_for_final_writes_after_process_removal(tmp_path):
    service = DesktopService(tmp_path / "state")
    entered = threading.Event()
    release = threading.Event()
    written = threading.Event()
    failures = []

    def final_write():
        entered.set()
        release.wait(timeout=3)
        try:
            service._write("INSERT INTO settings VALUES(?,?)", ("final", "true"))
            written.set()
        except Exception as error:
            failures.append(error)

    service._background(final_write)
    assert entered.wait(timeout=2)
    closer = threading.Thread(target=service.close)
    closer.start()
    try:
        assert closer.is_alive()
        assert service.db.execute("SELECT 1").fetchone()[0] == 1
    finally:
        release.set()
        closer.join(timeout=5)
    assert not closer.is_alive()
    assert written.is_set()
    assert not failures
    with sqlite3.connect(service.root / "desktop.sqlite") as connection:
        assert (
            connection.execute("SELECT value FROM settings WHERE key='final'").fetchone()[0]
            == "true"
        )
    connection.close()


def test_closing_engine_cannot_start_more_work(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service = DesktopService(tmp_path / "state")
    opened = service.open_project(str(project))
    service.close()
    with pytest.raises(ValueError, match="shutting down"):
        service.start(opened["id"], "check", {})
