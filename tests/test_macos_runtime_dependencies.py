import importlib.util
from pathlib import Path
from types import SimpleNamespace


def checker():
    path = Path(__file__).parents[1] / "apps/macos/scripts/check-runtime-dependencies.py"
    spec = importlib.util.spec_from_file_location("runtime_check", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.check


def dist(name, version="1.0", requires=None):
    return SimpleNamespace(metadata={"Name": name}, version=version, requires=requires or [])


def test_empty_scan_cannot_claim_compatibility():
    assert checker()([])["errors"]


def test_overlay_order_and_transitive_extra_requirements():
    report = checker()(
        [
            dist("app", requires=["client[auth]>=1"]),
            dist("client", "1.1", ['keylib>=2; extra == "auth"']),
            dist("client", "1.0"),  # Shadowed base copy must not override the overlay.
            dist("keylib", "2.1"),
        ]
    )
    assert report == {"packages": 3, "requirements": 2, "errors": []}


def test_incompatible_overlay_and_missing_dependencies_are_reported():
    report = checker()([dist("app", requires=["sdk<2", "absent>=1"]), dist("sdk", "2.0")])
    assert len(report["errors"]) == 2
