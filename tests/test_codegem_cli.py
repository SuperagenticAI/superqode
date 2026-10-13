"""Installed CodeGem helpers operate on the user's project without source scripts."""

import json
import sys

from superqode.codegem import download_cli, index_cli


def test_index_cli_queries_the_user_project(tmp_path, monkeypatch, capsys):
    calls = {}

    class Index:
        def __init__(self, root, config):
            calls.update(root=root, config=config)

        async def search(self, query, limit):
            calls.update(query=query, limit=limit)
            return [{"path": "src/auth.py"}]

    monkeypatch.setattr(index_cli, "CodeGemIndex", Index)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "superqode-codegem-index",
            str(tmp_path),
            "--provider",
            "sentence-transformers",
            "--scope",
            "src",
            "--query",
            "authentication",
        ],
    )
    index_cli.main()
    assert calls["root"] == tmp_path
    assert calls["config"]["provider"] == "sentence-transformers"
    assert calls["config"]["scope"] == ["src"]
    assert calls["query"] == "authentication"
    assert json.loads(capsys.readouterr().out) == [{"path": "src/auth.py"}]


def test_downloader_creates_ollama_modelfile(tmp_path, monkeypatch):
    def cached_download(spec, directory, workers):
        (directory / spec["file"]).write_bytes(b"test-model")

    monkeypatch.setattr(download_cli, "download", cached_download)
    monkeypatch.setattr(
        sys,
        "argv",
        ["superqode-codegem-download", "--directory", str(tmp_path), "--models", "coding"],
    )
    download_cli.main()
    model = tmp_path / download_cli.RELEASES["coding"]["file"]
    assert (tmp_path / "Modelfile").read_text() == (f'FROM "{model}"\nPARAMETER num_ctx 32768\n')
    assert json.loads((tmp_path / "manifest.json").read_text())["coding"]["sha256"]
