import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

import pytest

from superqode.desktop_service.daemon import connect, socket_path


class Client:
    def __init__(self, root):
        self.socket, self.stream, self.hello = connect(root)
        self.sequence = 0

    def call(self, method, params=None):
        self.sequence += 1
        self.socket.sendall(
            (
                json.dumps({"id": self.sequence, "method": method, "params": params or {}}) + "\n"
            ).encode()
        )
        row = json.loads(self.stream.readline())
        assert row["id"] == self.sequence
        if "error" in row:
            raise ValueError(row["error"])
        return row["result"]

    def close(self):
        try:
            self.socket.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.stream.close()
        self.socket.close()


@pytest.fixture
def background(tmp_path):
    state = tmp_path / "background-state"
    with (tmp_path / "engine.log").open("w") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "superqode.desktop_service.daemon",
                "--serve",
                "--state",
                str(state),
            ],
            stdout=log,
            stderr=log,
            env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
        )
    try:
        for _ in range(100):
            if process.poll() is not None:
                pytest.fail((tmp_path / "engine.log").read_text())
            try:
                client = Client(state)
                client.close()
                break
            except (OSError, ValueError):
                time.sleep(0.05)
        else:
            pytest.fail("Background engine never became ready")
        yield state, process
    finally:
        if process.poll() is None:
            try:
                client = Client(state)
                status = client.call("engine.status")
                client.call(
                    "engine.shutdown", {"instance": status["instance"], "cancel_active": True}
                )
                client.close()
            except (OSError, ValueError):
                process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def test_work_survives_ui_disconnect_and_reconnect_without_duplicate_execution(
    background, tmp_path
):
    state, process = background
    project = tmp_path / "project"
    project.mkdir()
    (project / "check.py").write_text(
        "import time\nfrom pathlib import Path\ntime.sleep(1)\nwith Path('count.txt').open('a') as f: f.write('once\\n')\nprint('finished after UI disconnect')\n"
    )
    first = Client(state)
    before = first.call("engine.status")
    opened = first.call("projects.open", {"path": str(project)})
    started = first.call(
        "checks.start",
        {
            "project": opened["id"],
            "command": f"{sys.executable} check.py",
            "command_id": "durable-check",
        },
    )
    first.close()
    second = Client(state)
    assert second.call("engine.status")["instance"] == before["instance"]
    assert second.call("engine.status")["pid"] == process.pid
    retry = second.call(
        "checks.start",
        {
            "project": opened["id"],
            "command": f"{sys.executable} check.py",
            "command_id": "durable-check",
        },
    )
    assert retry == started
    for _ in range(120):
        job = second.call("jobs.get", started)
        if job["status"] not in {"running", "queued"}:
            break
        time.sleep(0.05)
    assert job["status"] == "completed", job
    assert (project / "count.txt").read_text() == "once\n"
    assert any("finished after UI disconnect" in json.dumps(row) for row in job["events"])
    second.close()
    assert process.poll() is None


def test_authentication_and_socket_permissions(background):
    state, _ = background
    assert (state / "engine.token").stat().st_mode & 0o777 == 0o600
    assert socket_path(state).stat().st_mode & 0o777 == 0o600
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(socket_path(state)))
    client.sendall(b'{"token":"wrong","protocol":1}\n')
    assert "authentication failed" in client.recv(4096).decode()
    client.close()


def test_second_engine_cannot_interrupt_owner_and_shutdown_requires_current_instance(background):
    state, process = background
    client = Client(state)
    status = client.call("engine.status")
    other = subprocess.run(
        [
            sys.executable,
            "-m",
            "superqode.desktop_service.daemon",
            "--serve",
            "--state",
            str(state),
        ],
        capture_output=True,
        timeout=10,
    )
    assert other.returncode != 0
    assert client.call("engine.status")["instance"] == status["instance"]
    assert process.poll() is None
    with pytest.raises(ValueError, match="Engine changed"):
        client.call("engine.shutdown", {"instance": "stale"})
    assert client.call("hello")["protocol"] == 1
    client.close()


def test_build_mismatch_is_actionable_and_does_not_stop_existing_work(background):
    from superqode.desktop_service.daemon import token

    state, process = background
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.connect(str(socket_path(state)))
    client.sendall(
        (json.dumps({"token": token(state), "protocol": 1, "build": "old"}) + "\n").encode()
    )
    assert "different engine build" in client.recv(4096).decode()
    client.close()
    assert process.poll() is None


def test_management_connection_cannot_execute_work(background):
    state, _ = background
    client, stream, _ = connect(state, management=True)
    try:
        client.sendall(b'{"id":1,"method":"engine.status","params":{}}\n')
        assert json.loads(stream.readline())["result"]["mode"] == "background"
        client.sendall(b'{"id":2,"method":"projects.open","params":{"path":"/tmp"}}\n')
        assert "only supports" in json.loads(stream.readline())["error"]
    finally:
        stream.close()
        client.close()


def test_real_stdio_bridge_disconnect_keeps_daemon_alive(tmp_path):
    state = tmp_path / "bridge-state"
    process = subprocess.Popen(
        [sys.executable, "-m", "superqode.desktop_service.daemon", "--state", str(state)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env={**os.environ, "PYTHONPATH": str(Path(__file__).resolve().parents[1] / "src")},
    )
    try:
        process.stdin.write(b'{"id":1,"method":"engine.status","params":{}}\n')
        process.stdin.flush()
        status = json.loads(process.stdout.readline())["result"]
        assert status["mode"] == "background"
        process.stdin.close()
        assert process.wait(timeout=8) == 0
        client = Client(state)
        assert client.call("engine.status")["instance"] == status["instance"]
        client.call("engine.shutdown", {"instance": status["instance"]})
        client.close()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()
        try:
            client = Client(state)
            current = client.call("engine.status")
            client.call("engine.shutdown", {"instance": current["instance"], "cancel_active": True})
            client.close()
        except (OSError, ValueError):
            pass
