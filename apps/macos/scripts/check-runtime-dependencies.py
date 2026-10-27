"""Check the distributions visible to the actual bundled Python, including overlays."""

from importlib import metadata
import json

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version


def check(distributions=None):
    # importlib follows sys.path and uv's overlay .pth files. Prefix-only scans
    # can misleadingly report that zero packages were checked in an overlay.
    active = {}
    for dist in metadata.distributions() if distributions is None else distributions:
        name = canonicalize_name(dist.metadata["Name"])
        active.setdefault(name, dist)
    if not active:
        return {"packages": 0, "requirements": 0, "errors": ["No runtime distributions found"]}
    extras = {name: set() for name in active}
    pending = list(active)
    checked = set()
    errors = set()
    while pending:
        name = pending.pop()
        dist = active[name]
        for raw in dist.requires or []:
            requirement = Requirement(raw)
            if requirement.marker and not any(
                requirement.marker.evaluate({"extra": extra}) for extra in ["", *extras[name]]
            ):
                continue
            checked.add((name, raw))
            dependency = canonicalize_name(requirement.name)
            found = active.get(dependency)
            if found is None:
                errors.add(f"{name}: missing {dependency}")
                continue
            if requirement.specifier and not requirement.specifier.contains(
                Version(found.version), prereleases=True
            ):
                errors.add(
                    f"{name}: {dependency} {found.version} does not satisfy {requirement.specifier}"
                )
            added = set(requirement.extras) - extras[dependency]
            if added:
                extras[dependency].update(added)
                pending.append(dependency)
    return {"packages": len(active), "requirements": len(checked), "errors": sorted(errors)}


if __name__ == "__main__":
    report = check()
    print(json.dumps(report, indent=2))
    raise SystemExit(bool(report["errors"]))
