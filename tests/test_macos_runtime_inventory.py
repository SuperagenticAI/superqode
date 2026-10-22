import importlib.util
import json
from pathlib import Path


def test_inventory_is_refreshed_from_patched_runtime(tmp_path):
    script = Path(__file__).parents[1] / "apps/macos/scripts/collect-runtime-notices.py"
    spec = importlib.util.spec_from_file_location("runtime_notices", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    metadata = tmp_path / "python/lib/python3.13/site-packages/certifi-2026.10.19.dist-info"
    metadata.mkdir(parents=True)
    (metadata / "METADATA").write_text("Name: certifi\nVersion: 2026.10.19\n")
    (metadata / "LICENSE").write_text("Fixture license")
    (tmp_path / "python-dependencies.json").write_text('[{"name":"certifi","version":"old"}]')
    module.collect(tmp_path)
    assert json.loads((tmp_path / "python-dependencies.json").read_text()) == [
        {"name": "certifi", "version": "2026.10.19"}
    ]
