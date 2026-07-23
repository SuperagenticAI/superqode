#!/usr/bin/env python3
"""Build and exercise real Extensible Core Python packages in a temporary venv.

The outer mode builds SuperQode plus independent tool, policy, skill, broken,
and tool-upgrade wheels. It validates discovery, execution, policy, skills,
disable-before-import, failure isolation, upgrade, and uninstall across fresh
processes. The repository's development environment is not modified.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "examples" / "extensions" / "packages"


def _run(command: list[str], *, env: dict[str, str] | None = None) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, env=env, check=True)


def _wheel(dist: Path, project_name: str, version: str) -> Path:
    normalized = project_name.replace("-", "_")
    matches = sorted(dist.glob(f"{normalized}-{version}-*.whl"))
    if len(matches) != 1:
        raise RuntimeError(f"expected one wheel for {project_name} {version}, found: {matches}")
    return matches[0]


def _venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def run_lifecycle() -> None:
    uv = shutil.which("uv")
    if not uv:
        raise RuntimeError("uv is required to run the extension package lifecycle check")

    with tempfile.TemporaryDirectory(prefix="superqode-extension-packages-") as temporary:
        temp = Path(temporary)
        dist = temp / "dist"
        dist.mkdir()
        _run([uv, "build", "--wheel", "--out-dir", str(dist), str(ROOT)])
        package_dirs = (
            "tool-extension",
            "policy-extension",
            "skill-extension",
            "broken-extension",
            "tool-extension-v2",
        )
        for package_dir in package_dirs:
            _run(
                [
                    uv,
                    "build",
                    "--wheel",
                    "--out-dir",
                    str(dist),
                    str(PACKAGES / package_dir),
                ]
            )

        tool_v1 = _wheel(dist, "superqode-example-tool-extension", "0.1.0")
        tool_v2 = _wheel(dist, "superqode-example-tool-extension", "0.2.0")
        policy = _wheel(dist, "superqode-example-policy-extension", "0.1.0")
        skill = _wheel(dist, "superqode-example-skill-extension", "0.1.0")
        broken = _wheel(dist, "superqode-example-broken-extension", "0.1.0")
        superqode = _wheel(dist, "superqode", "0.2.33")

        venv = temp / "venv"
        _run([uv, "venv", str(venv)])
        python = _venv_python(venv)
        _run([uv, "pip", "install", "--python", str(python), str(superqode)])
        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                str(tool_v1),
                str(policy),
                str(skill),
                str(broken),
            ]
        )

        workspace = temp / "workspace"
        workspace.mkdir()
        env = os.environ.copy()
        env["SUPERQODE_TRUST_STORE"] = str(temp / "trust.json")
        installed_command = [
            str(python),
            str(Path(__file__).resolve()),
            "--installed",
            "--workspace",
            str(workspace),
        ]
        _run(
            [
                *installed_command,
                "--expect-tool-version",
                "0.1.0",
                "--check-broken-isolation",
            ],
            env=env,
        )

        _run(
            [
                uv,
                "pip",
                "install",
                "--python",
                str(python),
                "--no-deps",
                "--upgrade",
                str(tool_v2),
            ]
        )
        _run([*installed_command, "--expect-tool-version", "0.2.0"], env=env)

        _run(
            [
                uv,
                "pip",
                "uninstall",
                "--python",
                str(python),
                "superqode-example-tool-extension",
            ]
        )
        _run([*installed_command, "--expect-tool-missing"], env=env)

    print("Extension package lifecycle check passed.")


async def _check_installed(
    workspace: Path,
    expect_tool_version: str,
    *,
    expect_tool_missing: bool = False,
    check_broken_isolation: bool = False,
) -> None:
    from superqode.agent.hooks import LifecycleContext
    from superqode.extensions import ExtensionContext, load_extension_runtime
    from superqode.plugins import disable_plugin, enable_plugin
    from superqode.tools.base import ToolContext, ToolRegistry

    # The broken fixture raises from its module body. If disabling it by entry
    # point name produces no error, discovery skipped it before import.
    disable_plugin("broken-probe", workspace)
    runtime = load_extension_runtime(workspace)
    loaded = {extension.id: extension for extension in runtime.extensions}
    expected_ids = {"example-policy", "example-skill"}
    if not expect_tool_missing:
        expected_ids.add("example-tool")
    if not expected_ids.issubset(loaded):
        raise AssertionError(
            f"missing extension entry points: {sorted(expected_ids - loaded.keys())}; "
            f"errors={runtime.errors}; skipped={runtime.skipped}"
        )
    if runtime.errors:
        raise AssertionError(f"extension activation errors: {runtime.errors}")
    if "broken-probe: disabled" not in runtime.skipped:
        raise AssertionError(f"broken entry point was not skipped before import: {runtime.skipped}")
    if expect_tool_missing and "example-tool" in loaded:
        raise AssertionError("uninstalled tool extension still loaded")
    if not expect_tool_missing and loaded["example-tool"].version != expect_tool_version:
        raise AssertionError(
            f"tool extension version {loaded['example-tool'].version}; "
            f"expected {expect_tool_version}"
        )

    if expect_tool_missing:
        try:
            importlib.metadata.version("superqode-example-tool-extension")
        except importlib.metadata.PackageNotFoundError:
            pass
        else:
            raise AssertionError("tool distribution metadata survived uninstall")
    else:
        distribution_version = importlib.metadata.version("superqode-example-tool-extension")
        if distribution_version != expect_tool_version:
            raise AssertionError(
                f"installed distribution version {distribution_version}; "
                f"expected {expect_tool_version}"
            )

    registry = ToolRegistry.core()
    if [tool.name for tool in registry.list()] != ["read", "write", "edit", "bash"]:
        raise AssertionError("Core no longer has the exact four-tool default")
    runtime.apply_tools(registry)
    line_count = registry.get("example_line_count")
    skill_tool = registry.get("skill")
    if skill_tool is None:
        raise AssertionError("packaged-skill adapter was not registered")
    if expect_tool_missing and line_count is not None:
        raise AssertionError("uninstalled tool remained in the registry")
    if not expect_tool_missing and line_count is None:
        raise AssertionError("installed tool was not registered")

    if line_count is not None:
        tool_result = await line_count.execute(
            {"text": "one two\nthree"},
            ToolContext(session_id="package-check", working_directory=workspace),
        )
        tool_payload = json.loads(tool_result.output)
        if tool_payload["extension_version"] != expect_tool_version:
            raise AssertionError(f"tool implementation did not upgrade: {tool_payload}")
        if expect_tool_version == "0.2.0" and tool_payload.get("words") != 3:
            raise AssertionError(f"version-two tool behavior is missing: {tool_payload}")

    lifecycle = LifecycleContext(
        session_id="package-check",
        provider="test",
        model="model",
        working_directory=workspace,
    )
    hooks = runtime.build_hooks()
    denied = await hooks.fire_decision(
        "permission_request",
        lifecycle,
        "bash",
        {"command": "git push origin main"},
    )
    if not denied.denied:
        raise AssertionError("installed policy extension did not deny git push")
    if "example-policy:audit" not in hooks.list_hooks("after_tool_call"):
        raise AssertionError("installed policy observer hook was not registered")

    skill_result = await skill_tool.execute(
        {"action": "invoke", "name": "packaged_review", "context": "review this diff"},
        ToolContext(session_id="package-check", working_directory=workspace),
    )
    if not skill_result.success or "Report concrete findings" not in skill_result.output:
        raise AssertionError(f"packaged skill was not usable: {skill_result}")

    if not expect_tool_missing:
        disable_plugin("example-tool", workspace)
        disabled_runtime = load_extension_runtime(workspace)
        if any(extension.id == "example-tool" for extension in disabled_runtime.extensions):
            raise AssertionError("disabled Python entry-point extension still loaded")
        if "example-tool: disabled" not in disabled_runtime.skipped:
            raise AssertionError(f"disabled extension was not reported: {disabled_runtime.skipped}")
        enable_plugin("example-tool", workspace)
        reenabled_runtime = load_extension_runtime(workspace)
        if not any(extension.id == "example-tool" for extension in reenabled_runtime.extensions):
            raise AssertionError("re-enabled Python entry-point extension did not load")

    if check_broken_isolation:
        enable_plugin("broken-probe", workspace)
        broken_runtime = load_extension_runtime(workspace)
        if not any(error.extension_id == "broken-probe" for error in broken_runtime.errors):
            raise AssertionError(
                f"broken extension did not report its load error: {broken_runtime.errors}"
            )
        if not expected_ids.issubset({item.id for item in broken_runtime.extensions}):
            raise AssertionError("broken extension prevented healthy extensions from loading")
        disable_plugin("broken-probe", workspace)

    context = ExtensionContext(root=workspace, harness_id="core")
    print(
        json.dumps(
            {
                "extensions": sorted(expected_ids),
                "tool_version": None if expect_tool_missing else expect_tool_version,
                "tool_names": [tool.name for tool in registry.list()],
                "policy_denied": denied.denied,
                "skill_loaded": skill_result.success,
                "context_chars": len(runtime.context_text(context)),
                "disable_reenable": not expect_tool_missing,
                "disabled_before_import": True,
                "broken_isolated": check_broken_isolation,
                "tool_uninstalled": expect_tool_missing,
            },
            sort_keys=True,
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--installed", action="store_true")
    parser.add_argument("--workspace", type=Path)
    parser.add_argument("--expect-tool-version", default="0.1.0")
    parser.add_argument("--expect-tool-missing", action="store_true")
    parser.add_argument("--check-broken-isolation", action="store_true")
    args = parser.parse_args()
    if args.installed:
        if args.workspace is None:
            parser.error("--workspace is required with --installed")
        asyncio.run(
            _check_installed(
                args.workspace.resolve(),
                args.expect_tool_version,
                expect_tool_missing=args.expect_tool_missing,
                check_broken_isolation=args.check_broken_isolation,
            )
        )
        return
    run_lifecycle()


if __name__ == "__main__":
    main()
