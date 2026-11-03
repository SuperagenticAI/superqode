"""DS4 native setup: reviewed configuration, owned lifecycle and honest models."""

import io
import json
from pathlib import Path
import shlex
import sys

import pytest

from superqode.desktop_service import local_models
from superqode.local import servers, workbench
from test_desktop_service import desktop  # noqa: F401


@pytest.fixture
def ds4_files(tmp_path):
    binary = tmp_path / "custom runtime" / "ds4-server"
    binary.parent.mkdir()
    binary.write_text("#!/bin/sh\nexit 0\n")
    binary.chmod(0o755)
    weights = tmp_path / "DeepSeek V4 Flash.gguf"
    weights.write_bytes(b"GGUF-fixture")
    return {
        "action": "serve",
        "engine": "ds4",
        "binary": str(binary),
        "model": str(weights),
        "context": 32768,
        "kv_cache": "auto",
        "kv_disk_dir": str(tmp_path / "kv cache"),
        "kv_disk_space_mb": 4096,
    }


def test_review_reuses_weights_and_remembers_configuration_without_starting(
    desktop, ds4_files, monkeypatch
):
    service, _, _ = desktop
    monkeypatch.setattr(
        servers.ServerManager, "start", lambda *a, **k: pytest.fail("review started a server")
    )
    plan = service.dispatch("local.models.prepare", ds4_files)
    argv = shlex.split(plan["command"])
    assert argv[0] == ds4_files["binary"]
    assert argv[argv.index("-m") + 1] == ds4_files["model"]
    assert argv[argv.index("--host") + 1] == "127.0.0.1"
    assert argv[argv.index("--ctx") + 1] == "32768"
    assert argv[argv.index("--kv-disk-dir") + 1] == ds4_files["kv_disk_dir"]
    assert argv[argv.index("--kv-disk-space-mb") + 1] == "4096"
    assert not Path(ds4_files["kv_disk_dir"]).exists()
    config = service.dispatch("local.models.ds4", {})
    assert all(config[k] == ds4_files[k] for k in config)
    assert not service.dispatch("local.models.jobs", {})


@pytest.mark.parametrize(
    "replacement",
    [
        {"binary": "/missing/ds4-server"},
        {"binary": "bad\npath"},
        {"model": "/missing/model.gguf"},
        {"kv_disk_dir": ""},
        {"kv_disk_space_mb": -1},
        {"kv_disk_space_mb": True},
        {"kv_disk_space_mb": 1048577},
        {"kv_cache": "q8_0"},
        {"context": 0},
    ],
)
def test_invalid_ds4_configuration_is_rejected_before_execution(tmp_path, ds4_files, replacement):
    with pytest.raises(ValueError):
        workbench.prepare({**ds4_files, **replacement}, tmp_path / "registry")


def test_unavailable_explicit_binary_does_not_fall_back_to_another_install(tmp_path, monkeypatch):
    monkeypatch.setattr(servers.shutil, "which", lambda name: "/other/ds4-server")
    manager = servers.ServerManager(tmp_path, ds4_binary=tmp_path / "missing")
    assert manager._ds4_binary() is None


def test_ds4_models_remain_local_and_exclude_alias_for_an_unloaded_shape(monkeypatch):
    import urllib.request

    payload = {
        "data": [
            {"id": "deepseek-v4-flash", "name": "DeepSeek V4 Flash"},
            {"id": "deepseek-v4-pro", "name": "DeepSeek V4 Flash"},
            {"id": "deepseek-chat", "name": "DeepSeek V4 Flash"},
        ]
    }
    urls = []

    def open_fixture(url, **kwargs):
        urls.append(url)
        return io.BytesIO(json.dumps(payload).encode())

    monkeypatch.setattr(urllib.request, "urlopen", open_fixture)
    monkeypatch.setenv("DS4_HOST", "https://unrelated.invalid/v1")
    route = local_models.available("ds4")
    assert urls == ["http://127.0.0.1:8000/v1/models"]
    assert route["provider"] == "ds4"
    assert route["models"] == ["deepseek-v4-flash", "deepseek-chat"]


def test_reviewed_ds4_configuration_reaches_the_owned_process(tmp_path, ds4_files, monkeypatch):
    import socket

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    monkeypatch.setattr(servers.SPECS["ds4"], "default_port", port)
    marker = tmp_path / "actual-argv.json"
    binary = Path(ds4_files["binary"])
    binary.write_text(f"""#!{sys.executable}
import json,sys
from pathlib import Path
from http.server import BaseHTTPRequestHandler,HTTPServer
Path({str(marker)!r}).write_text(json.dumps(sys.argv[1:]))
class H(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_GET(self):
  self.send_response(200);self.end_headers();self.wfile.write(b'{{"data":[{{"id":"deepseek-v4-flash","name":"DeepSeek V4 Flash"}}]}}')
HTTPServer(('127.0.0.1',int(sys.argv[sys.argv.index('--port')+1])),H).serve_forever()
""")
    registry = tmp_path / "registry"
    plan = workbench.prepare(ds4_files, registry)
    manager = servers.ServerManager(registry)
    try:
        result = workbench.run(plan, registry, lambda *a: None, owner_job="ds4-native-fixture")
        assert result["ready"] and not result["server"]["adopted"]
        args = json.loads(marker.read_text())
        for flag, value in [
            ("--ctx", "32768"),
            ("-m", ds4_files["model"]),
            ("--kv-disk-dir", ds4_files["kv_disk_dir"]),
            ("--kv-disk-space-mb", "4096"),
        ]:
            assert args[args.index(flag) + 1] == value
        assert manager._load("ds4").owner_job == "ds4-native-fixture"
    finally:
        manager.stop("ds4")
