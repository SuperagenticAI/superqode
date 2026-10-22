"""Record the exact packaged sources, independently of the checkout's dirty state."""

import hashlib
import ast
import json
from pathlib import Path
import subprocess
import sys

app = Path(__file__).resolve().parents[1]
root = app.parents[1]
payload = Path(sys.argv[1])
manifest = json.loads((payload / "manifest.json").read_text())


def digest_tree(folder, suffix):
    digest = hashlib.sha256()
    for path in sorted(folder.rglob("*" + suffix)):
        digest.update(str(path.relative_to(folder)).encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


manifest.update(
    {
        "source": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "engine_source_tree_sha256": digest_tree(payload / "backend/superqode", ".py"),
        "native_source_tree_sha256": digest_tree(app / "Sources", ".swift"),
        "lock_sha256": hashlib.sha256((root / "uv.lock").read_bytes()).hexdigest(),
        "runtime_requirements_sha256": hashlib.sha256(
            (app / "runtime-requirements.txt").read_bytes()
        ).hexdigest(),
        "presentation": "SwiftUI/AppKit",
        "engine": next(
            ast.literal_eval(node.value)
            for node in ast.parse((payload / "backend/superqode/__init__.py").read_text()).body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(target, ast.Name) and target.id == "__version__"
                for target in node.targets
            )
        ),
    }
)
manifest.pop("source_tree_sha256", None)
(payload / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
