"""Install and check the isolated Strands environment without model calls."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

BASE_VARIABLES = {
    "PATH",
    "HOME",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "SYSTEMROOT",
    "WINDIR",
    "COMSPEC",
    "PATHEXT",
    "TMPDIR",
    "TEMP",
    "TMP",
    "LANG",
    "LANGUAGE",
    "LC_ALL",
    "LC_CTYPE",
    "TZ",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "NO_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
    "no_proxy",
    "SSL_CERT_FILE",
    "SSL_CERT_DIR",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
}
PACKAGES = (
    "strands-harness[anthropic,openai,gemini,ollama,litellm]==0.3.3",
    "strands-agents==1.63.0",
    # Keep the patched client compatible with the fixed locking library.
    # Later LiteLLM releases currently constrain filelock below its fixes.
    "litellm==1.103.1",
    "filelock==4.2.1",
)


def default_python() -> Path:
    return (
        Path(
            os.environ.get("SUPERQODE_STRANDS_PYTHON")
            or Path.home()
            / ".superqode/runtimes/strands"
            / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        )
        .expanduser()
        .absolute()
    )


def setup_runtime(interpreter: Path | None = None, *, install: bool = False) -> dict:
    target = (interpreter or default_python()).expanduser().absolute()
    if install:
        uv = shutil.which("uv")
        if not uv:
            raise ValueError("Install uv first, then run `superqode harness strands setup`.")
        if target.parent.parent.resolve() == Path(sys.prefix).resolve():
            raise ValueError("Choose a separate environment, not this Python interpreter")
        if target.exists() and not (target.parent.parent / "pyvenv.cfg").is_file():
            raise ValueError("Choose an isolated virtual environment, not a system interpreter")
        if not target.exists():
            subprocess.run([uv, "venv", "--python", "3.12", str(target.parent.parent)], check=True)
        subprocess.run([uv, "pip", "install", "--python", str(target), *PACKAGES], check=True)
    if not target.is_file():
        raise ValueError("Strands runtime not found. Run `superqode harness strands setup`.")
    worker = Path(__file__).with_name("backends") / "strands_worker.py"
    try:
        result = subprocess.run(
            [str(target), "-I", str(worker), "--check"],
            capture_output=True,
            text=True,
            timeout=30,
            env={name: value for name, value in os.environ.items() if name in BASE_VARIABLES},
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ValueError(
            "Strands runtime could not be checked. Run `superqode harness strands setup`."
        ) from exc
    try:
        packet = json.loads(result.stdout)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Strands runtime returned an invalid setup response. Run `superqode harness strands setup`."
        ) from exc
    if not isinstance(packet, dict) or result.returncode or packet.get("type") != "ready":
        # The worker emits categorical diagnostics, never provider response bodies.
        raise ValueError(
            "Strands runtime setup check failed. Run `superqode harness strands setup`."
        )
    return packet["versions"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--python", type=Path)
    args = parser.parse_args()
    try:
        versions = setup_runtime(args.python, install=args.install)
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f"Strands setup failed: {exc}\n")
    print("Strands runtime ready: " + json.dumps(versions, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
