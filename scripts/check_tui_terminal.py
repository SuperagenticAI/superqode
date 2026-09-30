"""Offline real-PTY input/rendering smoke check (Unix), not an SSH emulator.

Exercises bracketed paste, newline encodings, resizing, Escape and copy-command
routing. Clipboard backends are captured; verify native/remote clipboard behavior
with the live-terminal checklist in docs/advanced/tui.md.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path
import select
import signal
import struct
import subprocess
import sys
import tempfile
from time import monotonic


def child(state_path: Path):
    from superqode.app_main import SuperQodeApp, SelectionAwareInput
    from superqode.app.widgets import ConversationLog
    from superqode.history import HistoryManager

    class TerminalProbe(SuperQodeApp):
        def __init__(self):
            super().__init__()
            self._history_manager = HistoryManager(history_file=Path.cwd() / "history.jsonl")
            self.copies = []
            for name in (
                "_start_models_dev_refresh",
                "_start_acp_registry_refresh",
                "_report_catalog_freshness",
                "_run_startup_connect",
                "_prewarm_litellm",
            ):
                setattr(self, name, lambda *a, **k: None)

        def on_mount(self):
            super().on_mount()
            self._last_response = "copy fixture\nexact code"
            self.query_one("#log", ConversationLog).add_assistant(self._last_response)
            self.set_interval(0.05, self.record)

        def _copy_text_to_clipboard(self, text):
            copied = super()._copy_text_to_clipboard(text)
            self.copies.append(text)
            return copied

        def _os_clipboard_copy(self, text):
            return False  # Emit OSC 52 without changing the host clipboard.

        def record(self):
            from textual.css.query import NoMatches

            try:
                prompt = self.query_one("#prompt-input", SelectionAwareInput)
            except NoMatches:
                return
            state = {
                "text": prompt.value,
                "cursor": prompt.cursor_position,
                "focused": getattr(self.focused, "id", None),
                "screen": type(self.screen).__name__,
                "size": [self.size.width, self.size.height],
                "copies": self.copies,
            }
            temporary = state_path.with_suffix(".tmp")
            temporary.write_text(json.dumps(state), encoding="utf-8")
            os.replace(temporary, state_path)

    TerminalProbe().run()


def probe(term: str, size: tuple[int, int]):
    import fcntl
    import pty
    import termios

    checks = []
    output_bytes = 0
    with tempfile.TemporaryDirectory(prefix="superqode-pty-") as directory:
        root = Path(directory)
        state_path = root / "state.json"
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", size[1], size[0], 0, 0))
        env = {**os.environ, "TERM": term, "HOME": directory, "SUPERQODE_VIM_MODE": "0"}
        env.pop("SUPERQODE_CONNECT", None)
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--child", str(state_path)],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=root,
            env=env,
            start_new_session=True,
        )
        os.close(slave)
        transcript = bytearray()

        def wait_for(name, predicate, timeout=8):
            nonlocal output_bytes
            deadline = monotonic() + timeout
            state = {}
            while monotonic() < deadline:
                ready, _, _ = select.select([master], [], [], 0.05)
                if ready:
                    try:
                        data = os.read(master, 65536)
                    except OSError:
                        data = b""
                    output_bytes += len(data)
                    transcript.extend(data)
                    del transcript[:-16000]
                if process.poll() is not None:
                    raise RuntimeError(
                        f"{name}: TUI exited {process.returncode}: {transcript[-3000:]!r}"
                    )
                if state_path.exists():
                    state = json.loads(state_path.read_text())
                    if predicate(state):
                        checks.append(name)
                        return state
            raise RuntimeError(f"{term} {size}: {name} timed out; last state {state}")

        def send(data):
            os.write(master, data)

        try:
            wait_for(
                "startup and rendering",
                lambda s: s["focused"] == "prompt-input" and s["size"] == list(size),
            )
            send(b"\x1b[200~first\n  second\x1b[201~")
            wait_for(
                "bracketed multiline paste remains unsent", lambda s: s["text"] == "first\n  second"
            )
            send(b"\x0a")
            wait_for("Ctrl+J newline", lambda s: s["text"] == "first\n  second\n")
            send(b"\x1b[13;2u")
            wait_for("CSI-u Shift+Enter newline", lambda s: s["text"] == "first\n  second\n\n")
            send(b"\x1b[13;3u")
            wait_for("CSI-u Alt+Enter newline", lambda s: s["text"] == "first\n  second\n\n\n")
            send(b"\x15")
            wait_for("clear multiline input", lambda s: s["text"] == "")
            send(b":copy response")
            wait_for("copy command input", lambda s: s["text"] == ":copy response")
            send(b"\r")
            wait_for(
                "copy command routes exact response",
                lambda s: s["copies"] == ["copy fixture\nexact code"] and s["text"] == "",
            )
            encoded = base64.b64encode(b"copy fixture\nexact code")
            wait_for(
                "OSC 52 clipboard escape emitted",
                lambda s: b"\x1b]52;" in transcript and encoded in transcript,
            )
            send(b"keep this draft")
            wait_for("typing", lambda s: s["text"] == "keep this draft")
            send(b"\x0b")
            wait_for("command palette keyboard focus", lambda s: s["focused"] != "prompt-input")
            send(b"\x1b")
            wait_for(
                "Escape restores draft and focus",
                lambda s: s["focused"] == "prompt-input" and s["text"] == "keep this draft",
            )
            resized = [size[0] + 10, size[1] + 5]
            fcntl.ioctl(
                master, termios.TIOCSWINSZ, struct.pack("HHHH", resized[1], resized[0], 0, 0)
            )
            os.kill(process.pid, signal.SIGWINCH)
            wait_for(
                "resize preserves draft",
                lambda s: s["size"] == resized and s["text"] == "keep this draft",
            )
            send(b"\x15")
            wait_for("clear before context command", lambda s: s["text"] == "")
            send(b":context next")
            wait_for("context command input", lambda s: s["text"] == ":context next")
            send(b"\r")
            wait_for("context panel opens", lambda s: s["screen"] == "ContextPreviewScreen")
            send(b"\x1b")
            wait_for(
                "panel Escape restores prompt focus",
                lambda s: s["focused"] == "prompt-input" and s["screen"] != "ContextPreviewScreen",
            )
            return {
                "term": term,
                "size": list(size),
                "checks": checks,
                "rendered_bytes": output_bytes,
            }
        finally:
            process.terminate()
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            os.close(master)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--child", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return 0
    if os.name != "posix":
        parser.error("PTY checks require Unix; use the live-terminal checklist on Windows.")
    report = {
        "kind": "real PTY, offline",
        "clipboard": "command routing and OSC 52 emission; native backend disabled",
        "results": [],
        "failures": [],
    }
    for term, size in (("xterm-256color", (80, 24)), ("screen-256color", (120, 40))):
        try:
            report["results"].append(probe(term, size))
        except (OSError, RuntimeError, ValueError) as exc:
            report["failures"].append(str(exc))
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
