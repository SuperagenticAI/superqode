"""Build an isolated, relocatable Python payload without copying user state."""

from __future__ import annotations

import json
import ast
import hashlib
from pathlib import Path
import shutil
import subprocess

APP = Path(__file__).resolve().parents[1]
ROOT = APP.parents[1]
TARGET = APP / "runtime"
PYTHON = APP / ".build-venv/bin/python"


def main():
    if not PYTHON.exists():
        raise RuntimeError(
            "Create the locked build environment first: UV_PROJECT_ENVIRONMENT=apps/macos/.build-venv uv sync --frozen --no-dev --no-editable --python 3.13"
        )
    manifest = json.loads(
        subprocess.check_output(
            [
                str(PYTHON),
                "-c",
                "import sys,sysconfig,json;print(json.dumps({'base':sys.base_prefix,'site':sysconfig.get_path('purelib'),'version':f'{sys.version_info.major}.{sys.version_info.minor}'}))",
            ],
            text=True,
        )
    )
    if TARGET.exists():
        shutil.rmtree(TARGET)
    TARGET.mkdir()
    shutil.copytree(
        manifest["base"],
        TARGET / "python",
        symlinks=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    site = TARGET / "python/lib" / f"python{manifest['version']}" / "site-packages"
    site.mkdir(parents=True, exist_ok=True)
    shutil.copytree(
        manifest["site"],
        site,
        dirs_exist_ok=True,
        symlinks=False,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "__editable__*", "_superqode*"),
    )
    if (site / "superqode").exists():
        shutil.rmtree(site / "superqode")
    backend = TARGET / "backend"
    shutil.copytree(
        ROOT / "src/superqode",
        backend / "superqode",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copy2(ROOT / "LICENSE", TARGET / "LICENSE-superqode")
    shutil.copy2(ROOT / "NOTICE", TARGET / "NOTICE-superqode")
    (TARGET / "manifest.json").write_text(
        json.dumps(
            {
                "python": manifest["version"],
                "engine": next(
                    ast.literal_eval(node.value)
                    for node in ast.parse((backend / "superqode/__init__.py").read_text()).body
                    if isinstance(node, ast.Assign)
                    and any(
                        isinstance(target, ast.Name) and target.id == "__version__"
                        for target in node.targets
                    )
                ),
                "source": subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
                "source_tree_sha256": hashlib.sha256(
                    b"".join(p.read_bytes() for p in sorted((backend / "superqode").rglob("*.py")))
                ).hexdigest(),
                "lock_sha256": hashlib.sha256((ROOT / "uv.lock").read_bytes()).hexdigest(),
            },
            indent=2,
        )
    )
    executable = TARGET / "python/bin/python3"
    # Match the engine-pluggable API used by the repository's bounded experiments.
    requirement = (
        "gepa @ git+https://github.com/gepa-ai/gepa.git@f919db0a622e2e9f9204779b81fe00cc1b2d808f"
    )
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(executable),
            "--target",
            str(site),
            "--no-deps",
            requirement,
        ],
        check=True,
    )
    output = subprocess.check_output(
        [str(executable), "-c", "import sys,ssl,sqlite3;print(sys.prefix)"], text=True
    )
    print("Runtime built:", output.strip())
    cli = TARGET / "python/bin/superqode"
    cli.write_text(
        '#!/bin/sh\nSQ_BIN="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"\nPYTHONDONTWRITEBYTECODE=1 PYTHONPATH="$SQ_BIN/../../backend" LITELLM_LOCAL_MODEL_COST_MAP=True exec "$SQ_BIN/python3" -m superqode.main "$@"\n'
    )
    cli.chmod(0o755)
    # Patch the standalone interpreter's pip and the app's fsspec without
    # changing optional engine extras that are not bundled in this app.
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(executable),
            "--target",
            str(site),
            "--no-deps",
            "--require-hashes",
            "--requirement",
            str(APP / "runtime-requirements.txt"),
        ],
        check=True,
    )
    subprocess.run([str(executable), "-m", "pip", "check"], check=True)
    inventory = subprocess.check_output(
        [
            str(executable),
            "-c",
            "import importlib.metadata as m,json;print(json.dumps(sorted([{'name':d.metadata['Name'],'version':d.version} for d in m.distributions()],key=lambda x:x['name'].lower()),indent=2))",
        ],
        text=True,
    )
    (TARGET / "python-dependencies.json").write_text(inventory)
    subprocess.run(
        [
            str(executable),
            "-c",
            "from gepa.optimize_anything import OptimizeAnythingConfig, optimize_best_of;print('Omni API verified')",
        ],
        check=True,
    )


if __name__ == "__main__":
    main()
