"""Private interpreters and package environments for reviewed macOS ACP agents."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import platform
import shlex
import shutil
import sys
import tarfile
import tempfile

from superqode.agents.install_commands import InstallCommand

# SHA-256 values from the corresponding Node.js release SHASUMS256.txt.
_NODE = {
    "24.22.3": {
        "arm64": "ff6e17d4874b76d272212b908cc020d6e815fba5a6c7eaaa06add725840307fd",
        "x64": "977614af0504c81045e7fd85596dbca0e5f951b96681516dadafedcca8c447f7",
    },
    "22.23.5": {
        "arm64": "e7131995759b61a0170b646010d2ad35a5d37b4cb0d471f3e8317eac6f742f3d",
        "x64": "c53383238206b9ae4db23c5d8a63645e2e753bec8ab51a49cc81939aa64e9422",
    },
}
_PYTHON = ("3.13", "3.12")
# Direct package releases reviewed with these toolchain versions. npm writes
# package-lock.json and uv records the complete resolved Python environment.
_PACKAGE_VERSIONS = {
    "@earendil-works/pi-coding-agent": "1.5.2",
    "@qwen-code/qwen-code": "0.27.4",
    "cline": "3.0.74",
    "deepagents-code": "0.2.8",
    "fast-agent-mcp": "0.10.54",
    "hermes-agent[acp]": "0.19.0",
    "mistral-vibe": "3.1.2",
    "opencode-ai": "1.19.5",
    "pi-acp": "0.0.34",
}
_UV_VERSION = "0.13.8"
_UV = {
    "aarch64": "6b71028a6b904f2ae3340ef52e595512de807d06c0a20eaef2f692581b246558",
    "x86_64": "a04c2ffeac28b2003a2c13caf538ab425fcd7def3e4a41571f4a8fb370a66af3",
}
_SYSTEM_PATH = "/usr/bin:/bin:/usr/sbin:/sbin"
_INSTALL_ENV = {
    "HOME",
    "LANG",
    "LOGNAME",
    "TMPDIR",
    "USER",
    "ALL_PROXY",
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "NO_PROXY",
    "SSL_CERT_DIR",
    "SSL_CERT_FILE",
    "NODE_EXTRA_CA_CERTS",
}


def _app_root() -> Path | None:
    state = os.environ.get("SUPERQODE_STATE_DIR")
    if sys.platform == "darwin" and state and os.environ.get("SUPERQODE_APP") == "1":
        return Path(state).resolve() / "toolchains"
    return None


@dataclass(frozen=True)
class Toolchain:
    root: Path
    agent_dir: Path
    language: str
    versions: tuple[str, ...]
    packages: tuple[str, ...]
    executable: str

    @property
    def receipt_path(self) -> Path:
        return self.agent_dir / "current.json"

    def receipt(self) -> dict:
        try:
            data = json.loads(self.receipt_path.read_text())
            if (
                data["language"] == self.language
                and data["executable"] == self.executable
                and isinstance(data["generation"], str)
                and data["generation"].startswith("install-")
                and Path(data["generation"]).name == data["generation"]
                and isinstance(data["version"], str)
                and isinstance(data["selection"], str)
            ):
                return data
        except (OSError, ValueError, TypeError, KeyError):
            pass
        return {}

    def active(self) -> tuple[Path | None, dict]:
        receipt = self.receipt()
        if receipt:
            path = self.agent_dir / receipt["generation"] / self.executable
            if path.is_file() and os.access(path, os.X_OK):
                return path, receipt
        return None, {}

    def review(self, requested: str = "") -> dict:
        active = self.active()[1].get("selection")
        selection = requested or (active if active in self.versions else self.versions[0])
        if selection not in self.versions:
            raise ValueError(f"Choose a supported {self.language} version for this agent.")
        return {
            "language": self.language,
            "version": selection,
            "versions": list(self.versions),
            "packages": list(self.packages),
            "executable": self.executable,
        }


def for_agent(project: Path, identity: str, recipe: InstallCommand | None) -> Toolchain | None:
    root = _app_root()
    if (
        root is None
        or platform.machine() not in {"arm64", "x86_64"}
        or not recipe
        or not recipe.runnable
        or not recipe.managed
    ):
        return None
    if recipe.argv[:3] == ["npm", "install", "-g"]:
        language, versions, packages = "Node.js", tuple(_NODE), recipe.argv[3:]
    elif recipe.argv[:3] == ["uv", "tool", "install"]:
        versions = ("3.14",) if identity == "deepagents-code" else _PYTHON
        language, packages = "Python", recipe.argv[-1:]
    else:
        return None
    # Only packages with an app-owned entry point are pinned here. For example,
    # Junie's vendor installer writes a secondary binary and shim in the home folder.
    if not packages or any(package not in _PACKAGE_VERSIONS for package in packages):
        return None
    pin = "@" if language == "Node.js" else "=="
    pinned = tuple(f"{package}{pin}{_PACKAGE_VERSIONS[package]}" for package in packages)
    if identity == "deepagents-code":
        # deepagents-acp 0.0.13 imports the audio_block helper removed in ACP 1.0.
        pinned += ("agent-client-protocol==0.12.1",)
    project_id = hashlib.sha256(os.fsencode(project.resolve())).hexdigest()
    return Toolchain(
        root,
        root / "acp" / project_id / identity,
        language,
        versions,
        pinned,
        recipe.executable,
    )


def bind_launch(toolchain: Toolchain, argv: list[str]) -> tuple[list[str], dict]:
    launcher, receipt = toolchain.active()
    if launcher is None or not argv:
        return argv, {}
    arguments = argv[1:]
    if argv[0] == "uvx":
        # Bundled recipes declare the ACP entry point after the uvx options.
        arguments = argv[argv.index(toolchain.executable) + 1 :]
    return [str(launcher), *arguments], {
        "language": receipt["language"],
        "version": receipt["version"],
    }


def _install_archive(target: Path, url: str, sha256: str, member: str, executable: Path) -> Path:
    import urllib.request

    binary = target / executable
    if binary.is_file():
        return binary
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".download-", dir=target.parent) as stage:
        staging = Path(stage)
        archive = staging / "runtime.tar.gz"
        context = None
        try:
            import certifi
            import ssl

            context = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        with (
            urllib.request.urlopen(url, timeout=30, context=context) as response,
            archive.open("wb") as output,
        ):
            remaining = 64 * 1024 * 1024
            while chunk := response.read(1024 * 1024):
                remaining -= len(chunk)
                if remaining < 0:
                    raise ValueError("The runtime download exceeded its size limit.")
                output.write(chunk)
        with archive.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != sha256:
                raise ValueError("The runtime download failed its integrity check.")
        with tarfile.open(archive) as distribution:
            distribution.extractall(staging, filter="data")
        if not (staging / member / executable).is_file():
            raise ValueError("The runtime download did not include its executable.")
        try:
            (staging / member).rename(target)
        except OSError:
            if not binary.is_file():
                raise
    return binary


def _install_node(root: Path, version: str) -> Path:
    arch = {"arm64": "arm64", "x86_64": "x64"}[platform.machine()]
    name = f"node-v{version}-darwin-{arch}"
    return _install_archive(
        root / "node" / name,
        f"https://nodejs.org/dist/v{version}/{name}.tar.gz",
        _NODE[version][arch],
        name,
        Path("bin/node"),
    ).parent


def _install_uv(root: Path) -> Path:
    arch = {"arm64": "aarch64", "x86_64": "x86_64"}[platform.machine()]
    name = f"uv-{arch}-apple-darwin"
    return _install_archive(
        root / "uv" / f"{_UV_VERSION}-{arch}",
        f"https://github.com/astral-sh/uv/releases/download/{_UV_VERSION}/{name}.tar.gz",
        _UV[arch],
        name,
        Path("uv"),
    )


async def install(toolchain: Toolchain, review: dict, status) -> dict:
    """Publish a new launch command only after every dependency and entry point exists."""
    import asyncio

    from .configuration import run_install_command

    selection = review["version"]
    toolchain.agent_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    stage = Path(tempfile.mkdtemp(prefix="install-", dir=toolchain.agent_dir))
    env = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in _INSTALL_ENV or key.startswith("LC_")
    }
    env["PATH"] = _SYSTEM_PATH
    published = False
    try:
        if toolchain.language == "Node.js":
            status(f"Preparing SuperQode Node.js {selection}…")
            runtime = await asyncio.to_thread(_install_node, toolchain.root, selection)
            env["PATH"] = f"{runtime}:{_SYSTEM_PATH}"
            env["npm_config_cache"] = str(toolchain.root / "cache" / "npm")
            (stage / "package.json").write_text('{"private":true}\n')
            await run_install_command(
                [
                    str(runtime / "node"),
                    str(runtime / "npm"),
                    "install",
                    "--prefix",
                    str(stage),
                    "--userconfig",
                    str(stage / "user.npmrc"),
                    "--globalconfig",
                    str(stage / "global.npmrc"),
                    "--registry",
                    "https://registry.npmjs.org",
                    "--engine-strict",
                    "--no-audit",
                    "--no-fund",
                    *toolchain.packages,
                ],
                status,
                env=env,
                cwd=stage,
            )
            launch_bin = stage / "node_modules" / ".bin"
            version = selection
        else:
            status(f"Preparing SuperQode Python {selection}…")
            uv = str(await asyncio.to_thread(_install_uv, toolchain.root))
            env.update(
                UV_PYTHON_INSTALL_DIR=str(toolchain.root / "python"),
                UV_CACHE_DIR=str(toolchain.root / "cache" / "uv"),
                UV_PYTHON_PREFERENCE="only-managed",
                UV_NO_CONFIG="1",
            )
            await run_install_command(
                [uv, "python", "install", selection, "--no-bin"], status, env=env, cwd=stage
            )
            await run_install_command(
                [uv, "venv", "--python", selection, str(stage / "venv")], status, env=env, cwd=stage
            )
            launch_bin = stage / "venv" / "bin"
            python = str(launch_bin / "python")
            await run_install_command(
                [uv, "pip", "install", "--python", python, *toolchain.packages],
                status,
                env=env,
                cwd=stage,
            )
            await run_install_command(
                [uv, "pip", "check", "--python", python],
                status,
                env=env,
                cwd=stage,
            )
            frozen = []
            await run_install_command(
                [uv, "pip", "freeze", "--quiet", "--python", python],
                frozen.append,
                env=env,
                cwd=stage,
            )
            (stage / "requirements.txt").write_text("".join(frozen))
            version_output = []
            await run_install_command(
                [python, "-I", "-c", "import platform; print(platform.python_version())"],
                version_output.append,
                env=env,
                cwd=stage,
            )
            version = "".join(version_output).strip()
            runtime = launch_bin
        entry = launch_bin / toolchain.executable
        if not entry.is_file() or not os.access(entry, os.X_OK):
            raise ValueError(f"The installed packages did not provide {toolchain.executable}.")
        wrapper = stage / toolchain.executable
        prefix = str(launch_bin) if launch_bin == runtime else f"{launch_bin}:{runtime}"
        wrapper.write_text(
            "#!/bin/sh\n"
            "unset PYTHONPATH PYTHONHOME PYTHONUSERBASE VIRTUAL_ENV NODE_PATH NODE_OPTIONS\n"
            f"export PATH={shlex.quote(prefix)}${{PATH:+:$PATH}}:{_SYSTEM_PATH}\n"
            f'exec {shlex.quote(str(entry))} "$@"\n'
        )
        wrapper.chmod(0o700)
        receipt = {**review, "selection": selection, "version": version, "generation": stage.name}
        # The generation name is also part of the launch digest, so updates
        # require a fresh ACP probe. In-flight sessions keep their old path.
        pending = stage / "receipt.json"
        pending.write_text(json.dumps(receipt))
        os.replace(pending, toolchain.receipt_path)
        published = True
        return {"installed": True, "toolchain": receipt}
    finally:
        if not published:
            shutil.rmtree(stage)
