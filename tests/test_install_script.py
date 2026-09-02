from __future__ import annotations

import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install" / "install.sh"
HOSTED_INSTALLER = ROOT / "docs" / "install.sh"
WRAPPER = ROOT / "scripts" / "install.sh"

pytestmark = pytest.mark.skipif(shutil.which("sh") is None, reason="POSIX sh is required")


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)


def _fake_tool_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    command_bin = tmp_path / "commands"
    tool_bin = tmp_path / "tools"
    command_bin.mkdir()
    tool_bin.mkdir()
    uv_log = tmp_path / "uv.log"

    _write_executable(
        command_bin / "uv",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "$1" = "tool" ] && [ "$2" = "install" ]; then
    exit 0
fi
if [ "$1" = "tool" ] && [ "$2" = "dir" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
    exit 0
fi
exit 2
""",
    )
    _write_executable(tool_bin / "superqode", "#!/bin/sh\nprintf '%s\\n' 'superqode 0.test'\n")
    _write_executable(tool_bin / "sq", "#!/bin/sh\nprintf '%s\\n' 'sq 0.test'\n")

    env = {
        **os.environ,
        "HOME": str(tmp_path / "home"),
        "PATH": os.pathsep.join((str(command_bin), os.environ.get("PATH", ""))),
        "FAKE_UV_LOG": str(uv_log),
        "FAKE_TOOL_BIN": str(tool_bin),
    }
    return env, uv_log


def test_installer_is_valid_posix_shell_and_hosted_copy_stays_exact():
    for path in (INSTALLER, HOSTED_INSTALLER, WRAPPER):
        result = subprocess.run(
            ["sh", "-n", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0, result.stderr

    assert HOSTED_INSTALLER.read_bytes() == INSTALLER.read_bytes()


def test_installer_uses_isolated_uv_tool_install_and_verifies_both_commands(tmp_path: Path):
    env, uv_log = _fake_tool_environment(tmp_path)

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "superqode 0.test" in result.stdout
    assert "sq 0.test" in result.stdout
    assert "SuperQode is installed. Run: superqode" in result.stdout
    uv_calls = uv_log.read_text(encoding="utf-8")
    assert ("tool install --no-config --upgrade --force --with litellm<1.92 superqode") in uv_calls
    assert "tool dir --bin --no-config" in uv_calls


def test_installer_supports_explicit_extras_and_version_pin(tmp_path: Path):
    env, uv_log = _fake_tool_environment(tmp_path)
    env["SUPERQODE_EXTRAS"] = "tau,vendor-sdks"
    env["SUPERQODE_VERSION"] = "0.2.37"

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert (
        "tool install --no-config --upgrade --force "
        "--with litellm<1.92 "
        "superqode[tau,vendor-sdks]==0.2.37"
    ) in uv_log.read_text(encoding="utf-8")


def test_installer_rejects_malformed_options_before_running_uv(tmp_path: Path):
    env, uv_log = _fake_tool_environment(tmp_path)
    env["SUPERQODE_EXTRAS"] = "tau;unexpected"

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 1
    assert "SUPERQODE_EXTRAS may contain only" in result.stderr
    assert not uv_log.exists()


def test_installer_bootstraps_uv_when_it_is_missing(tmp_path: Path):
    command_bin = tmp_path / "commands"
    tool_bin = tmp_path / "tools"
    home_dir = tmp_path / "home"
    command_bin.mkdir()
    tool_bin.mkdir()
    uv_log = tmp_path / "uv.log"
    uv_template = tmp_path / "uv-template"
    bootstrap = tmp_path / "uv-bootstrap.sh"

    _write_executable(
        uv_template,
        """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "$1" = "tool" ] && [ "$2" = "install" ]; then exit 0; fi
if [ "$1" = "tool" ] && [ "$2" = "dir" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
    exit 0
fi
exit 2
""",
    )
    bootstrap.write_text(
        """#!/bin/sh
mkdir -p "$HOME/.local/bin"
cp "$FAKE_UV_TEMPLATE" "$HOME/.local/bin/uv"
chmod +x "$HOME/.local/bin/uv"
""",
        encoding="utf-8",
    )
    _write_executable(
        command_bin / "curl",
        '#!/bin/sh\nprintf \'%s\\n\' "$*" >> "$FAKE_CURL_LOG"\ncat "$FAKE_BOOTSTRAP"\n',
    )
    _write_executable(tool_bin / "superqode", "#!/bin/sh\nprintf '%s\\n' 'superqode 0.test'\n")
    _write_executable(tool_bin / "sq", "#!/bin/sh\nprintf '%s\\n' 'sq 0.test'\n")
    curl_log = tmp_path / "curl.log"
    env = {
        **os.environ,
        "HOME": str(home_dir),
        "PATH": os.pathsep.join((str(command_bin), "/usr/bin", "/bin")),
        "FAKE_BOOTSTRAP": str(bootstrap),
        "FAKE_CURL_LOG": str(curl_log),
        "FAKE_TOOL_BIN": str(tool_bin),
        "FAKE_UV_LOG": str(uv_log),
        "FAKE_UV_TEMPLATE": str(uv_template),
        "SUPERQODE_UV_INSTALLER_URL": "https://example.test/uv-install.sh",
    }

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "official Astral uv installer will run now" in result.stdout
    assert "-LsSf https://example.test/uv-install.sh" in curl_log.read_text(encoding="utf-8")
    assert (home_dir / ".local/bin/uv").is_file()


NOISY_UV = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "$1" = "tool" ] && [ "$2" = "install" ]; then
    echo "Resolved 247 packages in 1.02s"
    echo "Prepared 118 packages in 2.31s"
    echo "Installed 247 packages in 0.88s"
    i=0
    while [ $i -lt 60 ]; do
        echo " + noisy-transitive-dependency-$i==1.2.3"
        i=$((i+1))
    done
    exit 0
fi
if [ "$1" = "tool" ] && [ "$2" = "dir" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
    exit 0
fi
exit 2
"""

FAILING_UV = """#!/bin/sh
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "$1" = "tool" ] && [ "$2" = "install" ]; then
    echo "Resolved 247 packages in 1.02s"
    echo "error: numpy==2.9.9 has no source distribution" >&2
    exit 2
fi
if [ "$1" = "tool" ] && [ "$2" = "dir" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
    exit 0
fi
exit 2
"""


def _run_installer(tmp_path: Path, uv_body: str, **extra_env: str):
    env, uv_log = _fake_tool_environment(tmp_path)
    env.update(extra_env)
    _write_executable(tmp_path / "commands" / "uv", uv_body)
    result = subprocess.run(
        ["sh", str(INSTALLER)],
        cwd=tmp_path,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )
    return result, uv_log


def test_installer_hides_the_dependency_wall(tmp_path: Path):
    """Several hundred resolved packages scrolling past reads like a failure.

    The install still has to report that it worked, so the completion lines
    stay while the package manager's own output is held back.
    """
    result, _ = _run_installer(tmp_path, NOISY_UV)

    assert result.returncode == 0, result.stderr
    assert "noisy-transitive-dependency-40" not in result.stdout
    assert "Resolved 247 packages" not in result.stdout
    assert "SuperQode is installed. Run: superqode" in result.stdout
    assert "superqode 0.test" in result.stdout


def test_installer_shows_the_captured_output_when_a_step_fails(tmp_path: Path):
    """Hiding output must not turn a real failure into a silent one."""
    result, _ = _run_installer(tmp_path, FAILING_UV)

    assert result.returncode == 1
    assert "numpy==2.9.9 has no source distribution" in result.stderr
    assert "Error: installing SuperQode failed." in result.stderr


def test_installer_streams_everything_when_verbose_is_requested(tmp_path: Path):
    result, _ = _run_installer(tmp_path, NOISY_UV, SUPERQODE_INSTALL_VERBOSE="1")

    assert result.returncode == 0, result.stderr
    assert "noisy-transitive-dependency-40" in result.stdout
    assert "SuperQode is installed. Run: superqode" in result.stdout


def test_installer_emits_no_escape_sequences_when_output_is_not_a_terminal(tmp_path: Path):
    """Captured output lands in CI logs and pipes, where ANSI is noise."""
    result, _ = _run_installer(tmp_path, NOISY_UV)

    assert "\033" not in result.stdout
    assert "\x1b" not in result.stdout


def test_installer_never_says_python_or_pypi_to_the_user(tmp_path: Path):
    """The audience includes people who avoid Python tooling on sight.

    What the installer prints is about SuperQode; the packaging detail stays
    in the script's own header comment, where someone auditing a piped shell
    script can still find it.
    """
    result, _ = _run_installer(tmp_path, NOISY_UV)

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "Python" not in combined
    assert "python" not in combined
    assert "PyPI" not in combined


def test_installer_names_the_version_and_extras_it_is_installing(tmp_path: Path):
    """Dropping the raw package spec must not hide what was asked for."""
    result, _ = _run_installer(
        tmp_path,
        NOISY_UV,
        SUPERQODE_EXTRAS="tau,vendor-sdks",
        SUPERQODE_VERSION="0.2.68",
    )

    assert result.returncode == 0, result.stderr
    assert "Installing SuperQode 0.2.68 with extras: tau,vendor-sdks" in result.stdout


def _run_installer_on_a_terminal(tmp_path: Path, uv_body: str, timeout: float = 25.0) -> str:
    """Drive the installer through a pty so the animated path actually runs."""
    import pty
    import select

    env, _ = _fake_tool_environment(tmp_path)
    env.update(TERM="xterm-256color", COLORTERM="truecolor", LANG="en_US.UTF-8", COLUMNS="90")
    _write_executable(tmp_path / "commands" / "uv", uv_body)

    pid, fd = pty.fork()
    if pid == 0:  # pragma: no cover - replaced by exec in the child
        os.chdir(tmp_path)
        os.execve("/bin/sh", ["sh", str(INSTALLER)], env)
    chunks: list[bytes] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        readable, _, _ = select.select([fd], [], [], 0.2)
        if not readable:
            continue
        try:
            chunk = os.read(fd, 65536)
        except OSError:
            break
        if not chunk:
            break
        chunks.append(chunk)
    os.waitpid(pid, 0)
    return b"".join(chunks).decode("utf-8", "replace")


@pytest.mark.skipif(not hasattr(os, "fork"), reason="pty requires fork")
def test_installer_paints_the_brand_on_a_real_terminal(tmp_path: Path):
    """The animated path only runs on a tty, so nothing else exercises it."""
    output = _run_installer_on_a_terminal(tmp_path, NOISY_UV)

    # Banner: the mark from the logo, the name, and the positioning line.
    assert "SuperQode" in output
    assert "the harness interoperability layer for coding agents." in output
    assert "Agent to Agent communication over ACP, A2A and UHP" in output

    # The wordmark closes the install.
    assert "███████╗██╗" in output

    # Colours are sampled from assets/superqode-logo.png. If the artwork is
    # re-exported, these are the values to re-sample.
    for stop in (
        "38;2;121;32;232",
        "38;2;172;28;207",
        "38;2;218;22;153",
        "38;2;254;24;86",
        "38;2;254;107;5",
        "38;2;255;163;0",
    ):
        assert stop in output, f"missing logo gradient stop {stop}"

    # Still quiet about the packaging, even with the full presentation on.
    assert "noisy-transitive-dependency-40" not in output
    assert "Python" not in output
    assert "PyPI" not in output
