import importlib.util
import json
from pathlib import Path
import plistlib


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


def test_framework_build_inputs_are_pruned_and_nested_code_is_signed_first(tmp_path, monkeypatch):
    script = Path(__file__).parents[1] / "apps/macos/scripts/sign-bundle.py"
    spec = importlib.util.spec_from_file_location("bundle_signing", script)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    app = tmp_path / "SuperQode.app"
    framework = app / "Contents/Resources/runtime/python/Frameworks/Tcl.framework"
    runtime_python = app / "Contents/Resources/runtime/python"
    python_resources = runtime_python / "Resources"
    python_resources.mkdir(parents=True)
    (python_resources / "Info.plist").write_bytes(
        plistlib.dumps({"CFBundleExecutable": "Python", "CFBundlePackageType": "FMWK"})
    )
    python_library = runtime_python / "Python"
    python_library.write_bytes(b"\xcf\xfa\xed\xfeMach-O Python framework fixture")
    version = framework / "Versions/8.6"
    resources = version / "Resources"
    resources.mkdir(parents=True)
    (resources / "Info.plist").write_bytes(plistlib.dumps({"CFBundleExecutable": "Tcl"}))
    (framework / "Versions/Current").symlink_to("8.6", target_is_directory=True)
    (framework / "Resources").symlink_to("Versions/Current/Resources", target_is_directory=True)
    (framework / "Tcl").symlink_to("Versions/Current/Tcl")
    archive = version / "libtclstub8.6.a"
    archive.write_bytes(b"!<arch>\nstatic development archive")
    archive_link = framework / "libtclstub8.6.a"
    archive_link.symlink_to("Versions/Current/libtclstub8.6.a")
    config = version / "tclConfig.sh"
    config.write_text("# Tcl extension linker flags\n")
    config.chmod(0o755)
    config_link = framework / "tclConfig.sh"
    config_link.symlink_to("Versions/Current/tclConfig.sh")
    executable = version / "Tcl"
    executable.write_bytes(b"\xcf\xfa\xed\xfeMach-O framework fixture")
    library = version / "libnested.dylib"
    library.write_bytes(b"\xcf\xfa\xed\xfeMach-O nested library fixture")
    notice = resources / "license.terms"
    notice.write_text("Tcl license fixture")
    unrelated = app / "Contents/Resources/project.a"
    unrelated.write_bytes(b"unrelated resource")
    app_executable = app / "Contents/MacOS/SuperQode"
    app_executable.parent.mkdir(parents=True)
    app_executable.write_bytes(b"\xcf\xfa\xed\xfeMach-O app fixture")
    (app / "Contents/Info.plist").write_bytes(
        plistlib.dumps(
            {"CFBundleIdentifier": "dev.superqode.fixture", "CFBundleExecutable": "SuperQode"}
        )
    )
    calls = []

    def codesign(command, *, check):
        assert check
        assert command[0] == "codesign"
        if "--sign" in command:
            assert not archive.exists()
            assert not archive_link.is_symlink()
            assert not config.exists()
            assert not config_link.is_symlink()
        calls.append(command)

    monkeypatch.setattr(module.subprocess, "run", codesign)
    module.sign(app, "-")
    signed_paths = [command[-1] for command in calls if "--sign" in command]
    assert signed_paths == [str(library), str(framework), str(runtime_python), str(app)]
    verified_paths = [command[-1] for command in calls if "--verify" in command]
    assert str(executable) not in verified_paths
    assert str(app_executable) not in verified_paths
    assert {str(library), str(framework), str(runtime_python), str(app)} <= set(verified_paths)
    assert any(command[-1] == str(app) and "--deep" in command for command in calls)
    assert executable.exists()
    assert notice.read_text() == "Tcl license fixture"
    assert unrelated.read_bytes() == b"unrelated resource"
