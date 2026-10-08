"""Discover capabilities from the selected executable, never from a version guess."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from superqode.herdr import child_env


@dataclass
class CodexCapabilities:
    methods: dict[str, dict[str, Any]] = field(default_factory=dict)
    schemas: dict[str, dict[str, Any]] = field(default_factory=dict)
    error: str = ""
    version: str = ""

    @property
    def verified(self):
        return bool(self.methods)

    def supports(self, method, field=None):
        schema = self.methods.get(method)
        return schema is not None and (field is None or field in schema.get("properties", {}))

    def require(self, method, field=None):
        if not self.supports(method, field):
            raise RuntimeError(
                f"Installed Codex CLI does not advertise {method}"
                + (f".{field}" if field else "")
                + ". Update Codex or choose a supported control."
            )

    def validate(self, method, params):
        if self.supports(method):
            from jsonschema import Draft7Validator

            schema = self.methods[method]
            definitions = {
                **self.schemas.get("ClientRequest", {}).get("definitions", {}),
                **schema.get("definitions", {}),
            }
            Draft7Validator({**schema, "definitions": definitions}).validate(params)


_CACHE: dict[tuple, CodexCapabilities] = {}


def probe_capabilities(binary: str) -> CodexCapabilities:
    """Generate once per binary revision, away from both repositories and CODEX_HOME."""
    try:
        path = Path(binary).resolve()
        stat = path.stat()
        key = (str(path), stat.st_mtime_ns, stat.st_size)
        if key in _CACHE:
            return _CACHE[key]
        with tempfile.TemporaryDirectory(prefix="superqode-codex-schema-") as directory:
            result = subprocess.run(
                [
                    binary,
                    "app-server",
                    "generate-json-schema",
                    "--experimental",
                    "--out",
                    directory,
                ],
                capture_output=True,
                timeout=20,
                env=child_env(),
            )
            if result.returncode:
                return CodexCapabilities(
                    error="Schema generation failed; experimental controls disabled"
                )
            root = Path(directory)
            schemas = {p.stem: json.loads(p.read_text()) for p in root.rglob("*.json")}
            request = schemas["ClientRequest"]
            definitions = request.get("definitions", {})
            methods = {}
            for variant in request.get("oneOf", []):
                props = variant.get("properties", {})
                ref = props.get("params", {}).get("$ref", "").split("/")[-1]
                for method in props.get("method", {}).get("enum", []):
                    methods[method] = schemas.get(ref, definitions.get(ref, {}))
            version = subprocess.run(
                [binary, "--version"], capture_output=True, timeout=3, env=child_env()
            )
            import re

            match = re.search(r"\d+\.\d+\.\d+", version.stdout.decode(errors="replace"))
            capabilities = CodexCapabilities(
                methods=methods, schemas=schemas, version=match.group() if match else ""
            )
            if capabilities.verified:
                _CACHE[key] = capabilities
            return capabilities
    except (OSError, ValueError, KeyError, subprocess.SubprocessError):
        return CodexCapabilities(error="Schema unavailable; experimental controls disabled")
