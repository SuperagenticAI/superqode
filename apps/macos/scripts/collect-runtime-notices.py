"""Inventory bundled dependencies and copy their supplied license/notice texts.

This preserves upstream notices; it does not replace a redistribution review.
"""

import email
import hashlib
import json
from pathlib import Path
import shutil
import sys


def collect(runtime):
    target = runtime / "third-party-notices"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir()
    inventory = []
    for metadata in sorted(runtime.glob("python/lib/python*/site-packages/*.dist-info/METADATA")):
        dist = metadata.parent
        fields = email.message_from_bytes(metadata.read_bytes())
        name, version = fields.get("Name", dist.name), fields.get("Version", "unknown")
        destination = target / dist.name
        destination.mkdir()
        shutil.copy2(metadata, destination / "METADATA")
        notices = []
        for source in sorted(dist.rglob("*")):
            if (
                source.is_file()
                and not source.is_symlink()
                and source.name.lower().startswith(
                    ("license", "licence", "copying", "notice", "authors")
                )
            ):
                relative = source.relative_to(dist)
                output = destination / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, output)
                notices.append(str(relative))
        # Some wheels omit licenses that are present in their exact source
        # distribution. Preserve vendored texts from hash-checked locked sdists.
        normalized = name.lower().replace("_", "-").replace(".", "-")
        supplement = Path(__file__).resolve().parents[1] / "third-party" / f"{normalized}-{version}"
        if (supplement / "origin.json").exists():
            origin = json.loads((supplement / "origin.json").read_text())
            if origin["name"] != normalized or origin["version"] != version:
                raise ValueError(f"Notice version mismatch: {supplement}")
            for filename in origin["notices"]:
                if Path(filename).name != filename:
                    raise ValueError("Notice filenames must remain inside their supplement folder")
                if (
                    hashlib.sha256((supplement / filename).read_bytes()).hexdigest()
                    != origin["notice_sha256"][filename]
                ):
                    raise ValueError(f"Supplemental notice changed: {supplement / filename}")
                shutil.copy2(supplement / filename, destination / filename)
                notices.append(filename)
            shutil.copy2(supplement / "origin.json", destination / "source-origin.json")
        inventory.append(
            {
                "name": name,
                "version": version,
                "license_expression": fields.get("License-Expression"),
                "license_metadata": fields.get("License"),
                "notices": notices,
            }
        )
    # Python standalone supplies the interpreter and bundled library notices here.
    python_notices = []
    for source in sorted((runtime / "python").rglob("*")):
        if "site-packages" in source.parts:
            continue
        if (
            source.is_file()
            and not source.is_symlink()
            and source.name.lower().startswith(("license", "licence", "copying", "notice"))
        ):
            relative = source.relative_to(runtime / "python")
            output = target / "python" / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, output)
            python_notices.append(str(relative))
    report = {
        "distributions": inventory,
        "python_notices": python_notices,
        "review_required": [r["name"] for r in inventory if not r["notices"]],
    }
    (target / "inventory.json").write_text(json.dumps(report, indent=2) + "\n")
    # This runs after runtime security patches and before signing. Keep the
    # machine-readable package list aligned with the actual staged payload.
    packages = sorted(
        [{"name": row["name"], "version": row["version"]} for row in inventory],
        key=lambda row: row["name"].lower(),
    )
    (runtime / "python-dependencies.json").write_text(json.dumps(packages, indent=2) + "\n")
    print(
        f"Preserved notices for {len(inventory)} Python distributions; {len(report['review_required'])} need notice review"
    )
    return report


if __name__ == "__main__":
    collect(Path(sys.argv[1]).resolve())
