"""Launch the installed ACP worker without installing anything at startup."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import sys

from . import SETUP_HINT, installed, runtime_python, state_dir


def worker_environment() -> dict[str, str]:
    from superqode.harness.strands_setup import BASE_VARIABLES
    from superqode.providers.credentials import provider_api_key
    from superqode.providers.registry import PROVIDERS

    names = BASE_VARIABLES | {
        "OPENAI_API_KEY",
        "OPENAI_BASE_URL",
        "OPENAI_API_BASE",
        "OPENAI_ORG_ID",
        "OPENAI_PROJECT_ID",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_BASE_URL",
        "GOOGLE_API_KEY",
        "GEMINI_API_KEY",
        "SUPERQODE_PYDANTIC_CODER_MODEL",
    }
    environment = {name: value for name, value in os.environ.items() if name in names}
    for provider, variables in (
        ("openai", ("OPENAI_API_KEY",)),
        ("anthropic", ("ANTHROPIC_API_KEY",)),
        ("google", ("GOOGLE_API_KEY", "GEMINI_API_KEY")),
    ):
        definition = PROVIDERS.get(provider)
        if definition and (key := provider_api_key(definition)):
            for variable in variables:
                environment[variable] = key
    if "OPENAI_BASE_URL" not in environment and environment.get("OPENAI_API_BASE"):
        environment["OPENAI_BASE_URL"] = environment["OPENAI_API_BASE"]
    return environment


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", help="Default provider:model; may also be selected over ACP")
    args = parser.parse_args(argv)
    if not installed():
        print("Pydantic Coder runtime is missing or needs updating. " + SETUP_HINT, file=sys.stderr)
        return 1
    argv = [
        str(runtime_python()),
        "-I",
        "-u",
        str(Path(__file__).with_name("worker.py")),
        "--state-dir",
        str(state_dir() / "pydantic-coder"),
    ]
    if args.model:
        argv.extend(["--model", args.model])
    os.execve(argv[0], argv, worker_environment())


if __name__ == "__main__":
    raise SystemExit(main())
