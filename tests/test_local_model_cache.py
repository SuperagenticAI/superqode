from superqode.local import workbench


def test_transfer_size_counts_only_missing_pinned_cache_files(monkeypatch, tmp_path):
    import huggingface_hub

    cached = tmp_path / "cached.gguf"
    cached.write_bytes(b"x" * 100)
    seen = []

    def lookup(repo, filename, *, revision):
        seen.append((repo, filename, revision))
        return str(cached) if filename == "one.gguf" else None

    monkeypatch.setattr(huggingface_hub, "try_to_load_from_cache", lookup)
    files = [{"name": "one.gguf", "bytes": 100}, {"name": "two.gguf", "bytes": 90}]
    assert workbench.transfer_bytes("publisher/model", "a" * 40, files) == 90
    assert all(row[2] == "a" * 40 for row in seen)
    cached.write_bytes(b"partial")
    assert workbench.transfer_bytes("publisher/model", "a" * 40, files) == 190
    assert (
        workbench.transfer_bytes(
            "publisher/model", "a" * 40, [{"name": "unknown.gguf", "bytes": None}]
        )
        is None
    )
