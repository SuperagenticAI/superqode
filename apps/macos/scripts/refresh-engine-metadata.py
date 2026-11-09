"""Replace stale engine metadata in a staged app runtime, never the base payload."""

import ast
from pathlib import Path
import shutil
import sys
import tomllib


def refresh(payload, project):
    payload = Path(payload).resolve()
    package = payload / "backend/superqode"
    version = next(
        ast.literal_eval(node.value)
        for node in ast.parse((package / "__init__.py").read_text()).body
        if isinstance(node, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "__version__" for t in node.targets)
    )
    config = tomllib.loads(Path(project).read_text())["project"]
    if version != config["version"]:
        raise ValueError("Packaged engine version disagrees with pyproject.toml")
    stale = [p for p in payload.rglob("*.dist-info") if p.name.lower().startswith("superqode-")]
    for path in stale:
        if path.is_symlink() or not path.resolve().is_relative_to(payload):
            raise ValueError("Engine metadata must be inside the staged runtime")
    for path in stale:
        shutil.rmtree(path)
    info = payload / "backend" / f"superqode-{version}.dist-info"
    info.mkdir()
    metadata = [
        "Metadata-Version: 2.3",
        "Name: superqode",
        f"Version: {version}",
        "Summary: " + config.get("description", "SuperQode engine"),
    ]
    metadata += ["Requires-Dist: " + requirement for requirement in config.get("dependencies", [])]
    (info / "METADATA").write_text("\n".join(metadata) + "\n")
    (info / "entry_points.txt").write_text(
        "[console_scripts]\n"
        + "".join(f"{name} = {target}\n" for name, target in config.get("scripts", {}).items())
    )
    (info / "INSTALLER").write_text("superqode-app-bundler\n")
    (info / "RECORD").write_text("")
    return version


if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3]
    print("Packaged engine metadata: " + refresh(sys.argv[1], root / "pyproject.toml"))
