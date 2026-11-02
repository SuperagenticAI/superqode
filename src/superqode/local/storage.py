"""Shared model-cache preference. Changing the location never moves/deletes weights."""

from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import tempfile


def _file():
    return Path.home() / ".superqode" / "local-model-storage.json"


def cache_override():
    try:
        value = json.loads(_file().read_text()).get("hf_cache")
        return str(_validate(value)) if value else None
    except (OSError, ValueError, TypeError, AttributeError):
        return None


def cache_directory():
    from huggingface_hub.constants import HF_HUB_CACHE

    default = os.environ.get("HF_HUB_CACHE") or (
        str(Path(os.environ["HF_HOME"]).expanduser() / "hub")
        if os.environ.get("HF_HOME")
        else HF_HUB_CACHE
    )
    return Path(cache_override() or default).expanduser()


def _validate(value):
    if not isinstance(value, str) or not value.strip() or len(value) > 4096:
        raise ValueError("Choose an absolute Hugging Face cache directory")
    if any(ord(char) < 32 for char in value):
        raise ValueError("The cache path contains control characters")
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("Choose an absolute Hugging Face cache directory")
    path = path.resolve()
    if path == Path(path.anchor) or any(part.lower().endswith(".app") for part in path.parts):
        raise ValueError("Choose a model directory outside application bundles")
    if path.exists() and not path.is_dir():
        raise ValueError("The cache location is a file; choose a directory")
    return path


def free_bytes(path):
    path = Path(path)
    while not path.exists() and path != path.parent:
        path = path.parent
    return shutil.disk_usage(path).free


def status():
    path = cache_directory()
    return {
        "hf_cache": str(path),
        "custom": cache_override() is not None,
        "free_bytes": free_bytes(path),
        "note": "Applies to new SuperQode Hub downloads in the app, CLI and TUI. Existing weights and LM Studio links stay in their current locations. Ollama and LM Studio keep their own storage settings.",
    }


def save(value):
    path = _validate(value) if value else None
    if path:
        ancestor = path
        while not ancestor.exists():
            ancestor = ancestor.parent
        if not ancestor.is_dir() or not os.access(ancestor, os.W_OK | os.X_OK):
            raise ValueError("This cache directory is not writable; choose another location")
    destination = _file()
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    descriptor, temporary = tempfile.mkstemp(dir=destination.parent, prefix=".model-storage-")
    try:
        with os.fdopen(descriptor, "w") as output:
            json.dump({"hf_cache": str(path) if path else None}, output)
            output.write("\n")
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)
    return status()
