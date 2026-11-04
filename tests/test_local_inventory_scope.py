from pathlib import Path

from superqode.local import inventory


def test_inventory_does_not_stat_linked_files_or_walk_linked_folders(tmp_path, monkeypatch):
    cache = tmp_path / "models--publisher--model"
    cache.mkdir()
    (cache / "weights.bin").write_bytes(b"1234")
    protected = tmp_path / "Documents"
    protected.mkdir()
    secret = protected / "private.bin"
    secret.write_bytes(b"private")
    (cache / "outside.bin").symlink_to(secret)
    (cache / "outside-folder").symlink_to(protected, target_is_directory=True)
    stat = Path.stat

    def guarded_stat(path, *args, **kwargs):
        assert path != secret, "Inventory accessed a protected file"
        assert "outside-folder" not in path.parts or (
            path == cache / "outside-folder" and kwargs.get("follow_symlinks") is False
        ), "Inventory followed a protected directory"
        assert path != cache / "outside.bin" or kwargs.get("follow_symlinks") is False
        return stat(path, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", guarded_stat)
    assert inventory._dir_size_gb(cache) == 0.0


def test_hf_inventory_rejects_linked_model_and_snapshot_directories(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    protected = tmp_path / "Music"
    protected.mkdir()
    (protected / "model.safetensors").write_bytes(b"private")
    (cache / "models--linked--model").symlink_to(protected, target_is_directory=True)
    model = cache / "models--safe--model"
    model.mkdir()
    (model / "snapshots").symlink_to(protected, target_is_directory=True)
    monkeypatch.setattr(inventory, "_hf_cache_root", lambda: cache)
    iterdir = Path.iterdir

    def guarded_iterdir(path):
        assert path not in {protected, model / "snapshots", cache / "models--linked--model"}
        return iterdir(path)

    monkeypatch.setattr(Path, "iterdir", guarded_iterdir)
    assert inventory.list_hf_models() == []


def test_internal_hf_blob_links_are_not_double_counted(tmp_path):
    blob = tmp_path / "blobs" / "weight"
    blob.parent.mkdir()
    with blob.open("wb") as stream:
        stream.truncate(256 * 1024**2)
    snapshot = tmp_path / "snapshots" / "revision"
    snapshot.mkdir(parents=True)
    (snapshot / "model.safetensors").symlink_to(blob)
    assert inventory._dir_size_gb(tmp_path) == round(256 / 1024, 1)
