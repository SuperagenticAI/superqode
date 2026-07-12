"""Launch vendor CLI subscription logins from SuperQode.

When Codex or Grok has no local session, SuperQode can start the official CLI
login the same way users do outside the TUI:

* Codex  → ``codex login --device-auth``  (ChatGPT device code)
* Grok   → ``grok login --device-auth``   (X/SuperGrok device code)

Device-auth is used deliberately: it prints a URL + one-time code to stdout so
the SuperQode TUI can show them, open the browser when possible, and wait for
the CLI to finish writing ``~/.codex/auth.json`` / ``~/.grok/auth.json``.

SuperQode never implements the vendor OAuth itself and never copies tokens
during this flow — the vendor CLI owns the credential store.
"""

from __future__ import annotations

import asyncio
import os
import re
import shutil
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Optional


# URL in CLI output (device or authorize pages).
_URL_RE = re.compile(r"https?://[^\s<>\"']+")
# One-time codes like ``2KP1-NIB5S`` / ``MZQG-TVGG``.
_CODE_RE = re.compile(r"\b([A-Z0-9]{4,8}(?:-[A-Z0-9]{4,8})+)\b")

# How long SuperQode waits for the user to finish browser sign-in.
DEFAULT_LOGIN_TIMEOUT_SECONDS = 15 * 60

OnLine = Callable[[str], None]
OnLineAsync = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class SubscriptionLoginSpec:
    """Describes one vendor CLI subscription login."""

    id: str
    label: str
    binary: str
    # Relative path under $HOME (e.g. (".codex", "auth.json")). Resolved fresh
    # on every access so tests that patch $HOME — and the runtime home — agree.
    auth_subpath: tuple[str, ...]
    login_args: tuple[str, ...]
    install_hint: str
    success_hint: str
    env_key_fallbacks: tuple[str, ...] = ()
    # Optional override that returns the vendor auth file at call time. Used for
    # Grok so we defer to ``grok_cli_auth.GROK_AUTH_FILE`` (which tests patch),
    # keeping this module and the CLI-auth module pointing at one file.
    auth_path_getter: Optional[Callable[[], Path]] = None

    def current_auth_path(self) -> Path:
        """Resolve the vendor auth file *now* (never import-time frozen)."""
        if self.auth_path_getter is not None:
            try:
                return self.auth_path_getter()
            except Exception:  # noqa: BLE001 - fall back to the default location
                pass
        return Path.home().joinpath(*self.auth_subpath)


def _grok_auth_path() -> Path:
    from superqode.providers import grok_cli_auth

    return grok_cli_auth.GROK_AUTH_FILE


CODEX_LOGIN = SubscriptionLoginSpec(
    id="codex",
    label="Codex (ChatGPT)",
    binary="codex",
    auth_subpath=(".codex", "auth.json"),
    login_args=("login", "--device-auth"),
    install_hint="Install it:  npm i -g @openai/codex",
    success_hint="Codex login complete. Connecting…",
    env_key_fallbacks=("OPENAI_API_KEY", "CODEX_API_KEY"),
)

GROK_LOGIN = SubscriptionLoginSpec(
    id="grok",
    label="Grok (X / SuperGrok)",
    binary="grok",
    auth_subpath=(".grok", "auth.json"),
    login_args=("login", "--device-auth"),
    install_hint=(
        "Install it (macOS/Linux/WSL): curl -fsSL https://x.ai/cli/install.sh | bash\n"
        "Windows PowerShell:           irm https://x.ai/cli/install.ps1 | iex"
    ),
    success_hint="Grok login complete. Connecting…",
    env_key_fallbacks=("XAI_API_KEY",),
    auth_path_getter=_grok_auth_path,
)

_SPECS = {
    CODEX_LOGIN.id: CODEX_LOGIN,
    GROK_LOGIN.id: GROK_LOGIN,
}


@dataclass
class LoginResult:
    """Outcome of an interactive subscription login attempt."""

    ok: bool
    reason: str = ""
    auth_path: Optional[Path] = None
    opened_browser: bool = False
    lines: list[str] = field(default_factory=list)
    returncode: Optional[int] = None


def get_login_spec(product: str) -> SubscriptionLoginSpec:
    key = (product or "").strip().lower()
    if key not in _SPECS:
        raise KeyError(f"Unknown subscription login product: {product}")
    return _SPECS[key]


def binary_path(spec: SubscriptionLoginSpec) -> Optional[str]:
    return shutil.which(spec.binary)


def has_env_key(spec: SubscriptionLoginSpec) -> bool:
    return any(os.environ.get(name) for name in spec.env_key_fallbacks)


def has_local_login(spec: SubscriptionLoginSpec, *, path: Optional[Path] = None) -> bool:
    """True when the vendor auth file exists (and is non-empty)."""
    auth = path or spec.current_auth_path()
    try:
        return auth.is_file() and auth.stat().st_size > 0
    except OSError:
        return False


def login_ready(spec: SubscriptionLoginSpec, *, path: Optional[Path] = None) -> bool:
    """True when SuperQode can use the product without launching login."""
    return has_local_login(spec, path=path) or has_env_key(spec)


def login_command(spec: SubscriptionLoginSpec) -> list[str]:
    binary = binary_path(spec)
    if not binary:
        raise FileNotFoundError(f"{spec.binary} not found on PATH")
    return [binary, *spec.login_args]


def extract_urls(text: str) -> list[str]:
    return _URL_RE.findall(text or "")


def extract_device_codes(text: str) -> list[str]:
    """Pull device codes from CLI output, skipping long URL path noise."""
    codes: list[str] = []
    for match in _CODE_RE.finditer(text or ""):
        code = match.group(1)
        # Avoid grabbing URL path segments that look code-like.
        start = match.start(1)
        if start > 0 and text[start - 1] in "/?&=#":
            continue
        if code not in codes:
            codes.append(code)
    return codes


def prefer_open_browser() -> bool:
    """Whether SuperQode should try to open the system browser."""
    if os.environ.get("SUPERQODE_NO_BROWSER", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }:
        return False
    # SSH / pure headless: leave the URL for the user to copy.
    if os.environ.get("SSH_CONNECTION") or os.environ.get("SSH_TTY"):
        # Still open if a local display exists (X11/macOS forwarding rare but ok).
        if not (
            os.environ.get("DISPLAY")
            or os.environ.get("WAYLAND_DISPLAY")
            or os.uname().sysname == "Darwin"
        ):
            return False
    return True


def open_login_url(url: str) -> bool:
    """Best-effort browser open; returns True when webbrowser reports success."""
    if not url or not prefer_open_browser():
        return False
    try:
        return bool(webbrowser.open(url))
    except Exception:  # noqa: BLE001 - never fail the login flow on browser open
        return False


async def run_subscription_login(
    product: str,
    *,
    on_line: Optional[OnLine] = None,
    timeout: float = DEFAULT_LOGIN_TIMEOUT_SECONDS,
    auth_path: Optional[Path] = None,
    open_browser: Optional[bool] = None,
    poll_interval: float = 0.5,
    force: bool = False,
) -> LoginResult:
    """Run the vendor CLI device-auth login and wait for success.

    Streams CLI stdout/stderr lines via ``on_line``. Opens the first sign-in
    URL in the system browser when allowed. Succeeds when the auth file appears
    or the CLI exits zero after writing credentials.

    When ``force`` is True (e.g. an expired session file still on disk), the
    existing auth file is ignored and the CLI login is always launched.
    """
    try:
        spec = get_login_spec(product)
    except KeyError as exc:
        return LoginResult(ok=False, reason=str(exc))

    target_auth = auth_path or spec.current_auth_path()
    if not force and has_local_login(spec, path=target_auth):
        return LoginResult(
            ok=True,
            reason="already signed in",
            auth_path=target_auth,
        )

    if binary_path(spec) is None:
        return LoginResult(
            ok=False,
            reason=f"{spec.label} CLI is not installed. {spec.install_hint}",
        )

    try:
        cmd = login_command(spec)
    except FileNotFoundError as exc:
        return LoginResult(ok=False, reason=str(exc))

    should_open = prefer_open_browser() if open_browser is None else bool(open_browser)
    opened_browser = False
    lines: list[str] = []
    seen_urls: set[str] = set()

    def _emit(line: str) -> None:
        nonlocal opened_browser
        text = line.rstrip("\n")
        if not text:
            return
        lines.append(text)
        if on_line is not None:
            try:
                on_line(text)
            except Exception:  # noqa: BLE001
                pass
        if should_open and not opened_browser:
            for url in extract_urls(text):
                if url in seen_urls:
                    continue
                seen_urls.add(url)
                lowered = url.lower()
                if any(
                    token in lowered
                    for token in ("device", "authorize", "auth.", "login", "oauth", "codex")
                ):
                    if open_login_url(url):
                        opened_browser = True
                        break

    process: Optional[asyncio.subprocess.Process] = None
    try:
        process = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            stdin=asyncio.subprocess.DEVNULL,
        )
    except OSError as exc:
        return LoginResult(ok=False, reason=f"Could not start {spec.binary}: {exc}")

    assert process.stdout is not None
    buffer = ""

    async def _read_stdout() -> None:
        nonlocal buffer
        while True:
            chunk = await process.stdout.read(256)
            if not chunk:
                break
            buffer += chunk.decode(errors="replace")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                _emit(line)

    reader = asyncio.create_task(_read_stdout())
    deadline = asyncio.get_running_loop().time() + max(5.0, float(timeout))
    returncode: Optional[int] = None
    timed_out = False

    try:
        while True:
            if has_local_login(spec, path=target_auth):
                # Credentials landed; stop the CLI if it is still waiting.
                if process.returncode is None:
                    process.terminate()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2.0)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
                returncode = process.returncode
                break

            if process.returncode is not None:
                returncode = process.returncode
                break

            if asyncio.get_running_loop().time() >= deadline:
                timed_out = True
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
                returncode = process.returncode
                break

            try:
                await asyncio.wait_for(asyncio.shield(reader), timeout=poll_interval)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                raise
    finally:
        if not reader.done():
            try:
                await asyncio.wait_for(reader, timeout=1.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                reader.cancel()
        if buffer.strip():
            _emit(buffer)
            buffer = ""

    if has_local_login(spec, path=target_auth):
        return LoginResult(
            ok=True,
            reason="signed in",
            auth_path=target_auth,
            opened_browser=opened_browser,
            lines=lines,
            returncode=returncode,
        )

    if timed_out:
        return LoginResult(
            ok=False,
            reason=(
                f"{spec.label} login timed out after {int(timeout)}s. "
                f"Run `{spec.binary} {' '.join(spec.login_args)}` in a terminal and retry."
            ),
            opened_browser=opened_browser,
            lines=lines,
            returncode=returncode,
        )

    detail = ""
    for line in reversed(lines):
        if line.strip():
            detail = line.strip()
            break
    reason = (
        f"{spec.label} login did not complete"
        + (f" (exit {returncode})" if returncode not in (None, 0) else "")
        + (f": {detail}" if detail else ".")
    )
    return LoginResult(
        ok=False,
        reason=reason,
        opened_browser=opened_browser,
        lines=lines,
        returncode=returncode,
    )


__all__ = [
    "CODEX_LOGIN",
    "GROK_LOGIN",
    "DEFAULT_LOGIN_TIMEOUT_SECONDS",
    "LoginResult",
    "SubscriptionLoginSpec",
    "binary_path",
    "extract_device_codes",
    "extract_urls",
    "get_login_spec",
    "has_env_key",
    "has_local_login",
    "login_command",
    "login_ready",
    "open_login_url",
    "prefer_open_browser",
    "run_subscription_login",
]
