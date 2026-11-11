"""Platform-aware, reviewable setup for optional Mac inference engines."""

import hashlib
import json
import os
import platform
import shlex
import shutil
import subprocess

from .runtimes import validate


def plan(profile):
    spec = validate(profile)
    brew = shutil.which("brew")
    steps = []
    guidance = "Install and start the vendor's local API server, then enter its loopback URL and check models."
    if spec.template in {"vllm-metal", "omlx"}:
        guidance = "Requires Apple Silicon. Review the official guide, install the runtime, then use its memory-tier/model recipe to start the server. Installation downloads packages, not model weights, and does not start a server."
        if platform.system() == "Darwin" and platform.machine() == "arm64" and brew:
            if spec.template == "vllm-metal":
                steps = [
                    [
                        brew,
                        "tap",
                        "vllm-project/vllm-metal",
                        "https://github.com/vllm-project/vllm-metal",
                    ],
                    [brew, "install", "vllm-project/vllm-metal/vllm-metal"],
                ]
            else:
                steps = [
                    [brew, "tap", "jundot/omlx", "https://github.com/jundot/omlx"],
                    [brew, "install", "jundot/omlx/omlx"],
                ]
        elif not brew:
            guidance += " Install Homebrew first from https://brew.sh, or use the vendor installer."
    value = {
        "runtime": spec.id,
        "name": spec.name,
        "automatic": bool(steps),
        "steps": steps,
        "commands": [shlex.join(s) for s in steps],
        "docs_url": spec.docs_url,
        "guidance": guidance,
    }
    value["digest"] = hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()
    return value


def run(reviewed, emit):
    # The service constructs argv from fixed recipes after digest review.
    allowed = {
        "PATH",
        "HOME",
        "TMPDIR",
        "LANG",
        "LC_ALL",
        "USER",
        "LOGNAME",
        "SHELL",
        "HOMEBREW_PREFIX",
        "HOMEBREW_CACHE",
    }
    environment = {k: v for k, v in os.environ.items() if k in allowed}
    environment.update(
        HOMEBREW_NO_AUTO_UPDATE="1", HOMEBREW_NO_INSTALL_CLEANUP="1", NONINTERACTIVE="1"
    )
    for index, step in enumerate(reviewed["steps"]):
        emit(
            "stage",
            {
                "message": f"Installing {reviewed['name']}: step {index + 1} of {len(reviewed['steps'])}"
            },
        )
        with subprocess.Popen(
            step, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, env=environment
        ) as child:
            for line in child.stdout:
                emit("output", {"text": line[:4000]})
            if child.wait():
                raise ValueError(
                    "Runtime installation did not finish. Inspect the output and official setup guide; a partial Homebrew install can be retried."
                )
    emit(
        "result",
        {
            "status": "completed",
            "message": "Runtime installed. Follow the vendor model recipe to start its loopback server, then check models.",
        },
    )
