"""A disposable, dependency-free first Factory project, included in every install."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import yaml

from .definition import project_path
from .generation import check_generation_route
from .probes import run_python_probe
from .templates import factory_template

GOAL = "Fix total(values) in app.py so it adds every number, including negatives and empty lists."
APP = '''"""Add the numbers supplied as a JSON array on the command line."""
import json
import sys


def total(values):
    result = 0
    for value in values:
        result = value
    return result


if __name__ == "__main__":
    print(json.dumps(total(json.loads(sys.argv[1]))))
'''
PROBES = {
    "format": "superqode.factory-probes/1",
    "cases": [
        {"id": "multiple", "argv": ["python", "app.py", "[2,3]"], "stdout": "5\n"},
        {"id": "negative", "argv": ["python", "app.py", "[8,-3,1]"], "stdout": "6\n"},
        {"id": "empty", "argv": ["python", "app.py", "[]"], "stdout": "0\n"},
    ],
}


def create(destination, *, confirmed=False, model="ollama/qwen3-coder", allow_cloud=False):
    """Create only a new directory. No inference, model downloads or worker execution."""
    if confirmed is not True:
        raise ValueError("Confirm creation of a disposable demo with --confirm")
    if not isinstance(model, str) or not isinstance(allow_cloud, bool):
        raise ValueError("Choose a provider/model and explicit boolean cloud permission")
    from superqode.providers.model_specs import split_provider_model_ref
    from superqode.providers.dynamic import resolve_provider_def

    parsed = split_provider_model_ref(model)
    provider = resolve_provider_def(parsed.provider)
    if not provider or provider.harness_only or not parsed.model:
        raise ValueError("Choose a direct execution model as provider/model")
    definition = factory_template()
    if allow_cloud:
        definition["default_route"] = "best"
    try:
        check_generation_route(definition, parsed.provider, parsed.model)
    except ValueError:
        raise ValueError(
            "This sample keeps execution local. Choose a local model or explicitly use --allow-cloud."
        ) from None
    if any(word in parsed.model.lower() for word in ("embed", "rerank")):
        raise ValueError("Choose a chat or coding model for the sample")
    definition["metadata"]["name"] = "first-verified-run"
    definition["metadata"]["description"] = (
        "Disposable numeric CLI repair and protected verification."
    )
    definition["inference"]["harnesses"]["coder"]["model"] = model
    definition["data_context"]["files"]["acceptance"] = {
        "path": "protected/acceptance.json",
        "purpose": "evaluator",
    }
    definition["improvement"]["checks"]["regression"] = {
        "command": "python -m py_compile app.py",
        "files": [],
        "evaluator": "acceptance",
    }
    definition["governance"]["budget"].update(max_seconds=300, max_tool_calls=40)
    # Resolve existing parents, but refuse even dangling destination symlinks.
    destination = Path(destination).expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError("Choose a new demo directory; existing paths are never replaced")
    if not destination.parent.is_dir():
        raise ValueError("Choose an existing parent directory for the demo")
    destination = destination.parent.resolve() / destination.name
    destination.mkdir(mode=0o700)
    try:
        (destination / ".superqode").mkdir()
        (destination / "protected").mkdir()
        (destination / "app.py").write_text(APP)
        (destination / ".gitignore").write_text(
            ".superqode/workorders/\n.superqode/factory/\n.superqode/factory-studio/\n.superqode/factory-operations/\n__pycache__/\n"
        )
        (destination / "protected/acceptance.json").write_text(json.dumps(PROBES, indent=2) + "\n")
        (destination / ".superqode/factory.yaml").write_text(
            yaml.safe_dump(definition, sort_keys=False)
        )
        (destination / "README.md").write_text(
            "# Your first verified Factory run\n\n" + GOAL + "\n\n"
            "Run `sq factory demo check --execute` to reproduce the defect with isolated probes. "
            "This diagnostic supplies no release approval. Review the protected expectations, "
            "choose your execution model, then run `sq factory start`.\n\n"
            "A trial queues work; the worker needs explicit execution. Human gates, protected "
            "verification and release approval remain separate. This sample has no release signer. "
            "Model calls may cost money. You can delete this disposable folder after stopping its workers.\n"
        )
        git_environment = {
            key: value for key, value in os.environ.items() if not key.startswith("GIT_")
        }
        for arguments in (
            ["init", "-q", "--template="],
            [
                "add",
                "app.py",
                ".gitignore",
                "README.md",
                "protected/acceptance.json",
                ".superqode/factory.yaml",
            ],
            [
                "-c",
                "user.name=SuperQode Demo",
                "-c",
                "user.email=demo@superqode.invalid",
                "commit",
                "-qm",
                "First-run demo baseline",
            ],
        ):
            subprocess.run(
                ["git", "-c", "core.hooksPath=/dev/null", "-c", "commit.gpgsign=false", *arguments],
                cwd=destination,
                check=True,
                capture_output=True,
                timeout=30,
                env=git_environment,
            )
        folder = destination / ".superqode/factory-studio"
        folder.mkdir()
        (folder / "demo.json").write_text(
            json.dumps({"format": "superqode.factory-demo/1", "goal": GOAL})
        )
        from .authoring import parse

        parse(destination, (destination / ".superqode/factory.yaml").read_text())
    except subprocess.SubprocessError:
        shutil.rmtree(destination)
        raise ValueError(
            "Could not create the sample's Git baseline. Check Git and write access, then choose a new sample folder."
        ) from None
    except Exception:
        shutil.rmtree(destination)
        raise
    return {
        "project": str(destination),
        "goal": GOAL,
        "model": model,
        "cloud_allowed": allow_cloud,
        "model_calls": 0,
        "execution_started": False,
        "next_command": [
            "sq",
            "factory",
            "demo",
            "check",
            "--project",
            str(destination),
            "--execute",
        ],
    }


def check(root, *, execute=False):
    """Run the sample's built-in expectations under the protected OS sandbox."""
    if execute is not True:
        raise ValueError("Use --execute to run isolated demo probes; no models are called")
    root = Path(root).resolve()
    marker = project_path(root, ".superqode/factory-studio/demo.json")
    from .operations import read

    if json.loads(read(marker, 16000)).get("format") != "superqode.factory-demo/1":
        raise ValueError("Open a project created by factory demo create")
    program = read(project_path(root, "app.py"), 250000)
    rows = []
    with tempfile.TemporaryDirectory(prefix="superqode-demo-") as directory:
        candidate = Path(directory) / "candidate"
        candidate.mkdir()
        (candidate / "app.py").write_bytes(program)
        deadline = time.monotonic() + 30
        for case in PROBES["cases"]:
            scratch = Path(directory) / case["id"]
            scratch.mkdir()
            result = run_python_probe(
                case["argv"], candidate=candidate, scratch=scratch, stdin="", deadline=deadline
            )
            isolated = result.get("backend") not in {None, "none"}
            status = (
                "blocked"
                if result.get("kind") != "completed" or not isolated
                else "passed"
                if result.get("returncode") == 0 and result.get("stdout") == case["stdout"]
                else "failed"
            )
            rows.append({"id": case["id"], "status": status})
    status = (
        "blocked"
        if any(r["status"] == "blocked" for r in rows)
        else "failed"
        if any(r["status"] == "failed" for r in rows)
        else "passed"
    )
    return {
        "format": "superqode.factory-demo-check/1",
        "status": status,
        "cases": rows,
        "model_calls": 0,
        "release_authorized": False,
        "notice": "Diagnostic probe results only. Use a real Factory trial and protected verification to obtain SuperGauge evidence.",
    }
