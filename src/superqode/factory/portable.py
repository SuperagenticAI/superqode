"""Plain-file Factory exports for headless operation and explicit platform adaptation."""

import hashlib
import io
from pathlib import Path
from uuid import uuid4
import zipfile

from superqode import __version__
from .definition import load_factory
from .snapshot import canonical, resolve_factory
from .operations import ownership, path, write
from .maintenance import execution
from .versioning import _safe_text, source_name

FORMAT = "superqode.factory-portable/1"


def _hash(raw):
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def _engine():
    hasher = hashlib.sha256()
    for file in sorted(Path(__file__).parent.glob("*.py")):
        hasher.update(file.name.encode() + b"\0" + file.read_bytes() + b"\0")
    return {"version": __version__, "factory_module_sha256": hasher.hexdigest()}


def preview(root):
    snapshot = resolve_factory(load_factory(root=root))
    sources = snapshot.payload["sources"]
    for name, value in sources.items():
        source_name(name)
        _safe_text(name, value["text"])
    return {
        "format": FORMAT,
        "name": snapshot.payload["definition"]["metadata"]["name"],
        "snapshot_digest": snapshot.digest,
        "files": sorted(sources),
        "source_bytes": sum(len(value["text"].encode()) for value in sources.values()),
        "engine": _engine(),
        "requires_desktop_app": False,
        "runtime": "SuperQode CLI on a supported macOS or Linux host",
        "external_platforms": {"adapter_required": True, "execution_verified": False},
        "application_included": False,
        "credential_stores_included": False,
        "run_history_included": False,
        "execution_started": False,
    }


def create(root, *, expected):
    root = Path(root).resolve()
    with ownership(root), execution(root, require_enabled=False):
        review = preview(root)
        if not expected or expected != review["snapshot_digest"]:
            raise ValueError("Factory sources changed; refresh the export review")
        snapshot = resolve_factory(load_factory(root=root))
        if snapshot.digest != expected:
            raise ValueError("Factory sources changed during export")
        entries = {
            "factory/" + name: value["text"].encode()
            for name, value in snapshot.payload["sources"].items()
        }
        entries["resolved-snapshot.json"] = canonical(snapshot.to_dict()).encode()
        entries["README.md"] = (
            "# Take your Factory with you\n\n"
            "The macOS app is an authoring client; it does not need to stay open.\n\n"
            "## Run on your own host\n\n"
            "1. Restore or clone the application separately. Do not extract this package over a live checkout.\n"
            "2. Review the plain files under factory/ and copy them to the application root, preserving their paths. "
            "The .superqode directory is hidden in some file browsers.\n"
            "3. Install the reviewed SuperQode engine build matching manifest.json and its dependencies. "
            "An engine version number alone does not prove identical source; use the Factory module fingerprint "
            "and your approved build provenance. This archive contains configuration, not an engine installer.\n"
            "4. Configure model providers, environment bindings, credentials and protected isolation on the target.\n"
            "5. Validate without execution:\n\n"
            "```sh\nsq factory validate --project /path/to/application\n"
            "sq factory operations check --project /path/to/application --probe\n```\n\n"
            "Use the CLI, MCP or a customer-managed worker to prepare new target-local runs. "
            "Model calls, gates, protected acceptance and release approval remain explicit. "
            "No queue, approval, runtime session or historical result is reactivated by copying these files.\n\n"
            "## Use another platform\n\n"
            "Factory definitions and referenced components are editable text. resolved-snapshot.json also "
            "records the resolved harnesses and source digests. A different platform needs an adapter for "
            "its workflow, tool, model, evaluator and permission contracts. "
            "Conversion and execution on other vendors have not been verified. Do not remove human gates, "
            "protected checks, budget limits or release policy merely to make a conversion load.\n\n"
            "## Contents and privacy\n\n"
            "Only declared Factory sources and the pinned snapshot are included. These may contain private "
            "context, skills and protected evaluator code; review before sharing. The application checkout, "
            "runtime binaries, provider credentials, model weights and run history are not a backup scope "
            "of this package. Secret environment references require new bindings on the target.\n"
        ).encode()
        manifest = {
            **review,
            "entries": {
                name: {"bytes": len(raw), "sha256": _hash(raw)}
                for name, raw in sorted(entries.items())
            },
            "release_authorized": False,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.writestr("manifest.json", canonical(manifest))
            for name, raw in sorted(entries.items()):
                archive.writestr(name, raw)
        if resolve_factory(load_factory(root=root)).digest != expected:
            raise ValueError("Factory sources changed during export")
        raw = buffer.getvalue()
        identity = "export_" + uuid4().hex
        destination = path(root, "exports/" + identity + ".zip")
        write(destination, raw)
        return {
            "id": identity,
            "path": str(destination),
            "sha256": _hash(raw),
            "bytes": len(raw),
            "manifest": manifest,
            "execution_started": False,
            "release_authorized": False,
        }
