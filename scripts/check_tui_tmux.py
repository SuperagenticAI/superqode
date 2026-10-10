"""Run SuperQode inside a real tmux server behind a scripted outer terminal.

The outer terminal is a PTY owned by this script. It answers colour queries
that reach it (directly or through tmux DCS passthrough), and records what
tmux forwards: OSC 11 queries, DEC mode 2031, OSC 52 clipboard writes.
Offline and local only; not part of CI.

    python scripts/check_tui_tmux.py [--output report.json]
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
from pathlib import Path
import pty
import re
import select
import shlex
import shutil
import struct
import subprocess
import sys
import tempfile
import termios
from time import monotonic, sleep

SCRIPT = Path(__file__).resolve().with_name("check_tui_terminal.py")
OSC11_QUERY = b"\x1b]11;?"
LIGHT_REPLY = b"\x1b]11;rgb:fafa/fafa/fafa\x1b\\"


def run_case(passthrough: bool, size=(100, 30), extra_env=None, answer=True) -> dict:
    checks, notes = [], {}
    with tempfile.TemporaryDirectory(prefix="sq-tmux-") as directory:
        root = Path(directory)
        state_path = root / "state.json"
        socket = f"sqprobe{os.getpid()}{int(passthrough)}"
        conf = root / "tmux.conf"
        conf.write_text(
            "set -g default-terminal tmux-256color\n"
            f"set -g allow-passthrough {'on' if passthrough else 'off'}\n"
            "set -g set-clipboard on\n"
            "set -as terminal-features ',xterm-256color:clipboard'\n"
            "set -g escape-time 10\n"
            "set -g status off\n"
        )
        env = {
            **{k: v for k, v in os.environ.items() if k not in {"NO_COLOR", "TMUX"}},
            "TERM": "xterm-256color",
            "HOME": directory,
            "SUPERQODE_VIM_MODE": "0",
            **(extra_env or {}),
        }
        inner = (
            f"cd {directory} && HOME={directory} SUPERQODE_VIM_MODE=0 "
            + " ".join(f"{k}={shlex.quote(v)}" for k, v in (extra_env or {}).items())
            + f" {sys.executable} {SCRIPT} --child {state_path}"
        )
        master, slave = pty.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", size[1], size[0], 0, 0))
        process = subprocess.Popen(
            [
                "tmux",
                "-L",
                socket,
                "-f",
                str(conf),
                "new-session",
                "-x",
                str(size[0]),
                "-y",
                str(size[1]),
                inner,
            ],
            stdin=slave,
            stdout=slave,
            stderr=slave,
            cwd=root,
            env=env,
            start_new_session=True,
        )
        os.close(slave)
        seen = bytearray()
        replied = 0

        def pump(seconds=0.05):
            nonlocal replied
            ready, _, _ = select.select([master], [], [], seconds)
            if ready:
                try:
                    data = os.read(master, 65536)
                except OSError:
                    data = b""
                seen.extend(data)
                # Answer every OSC 11 query that reaches the outer terminal.
                count = seen.count(OSC11_QUERY)
                while answer and replied < count:
                    os.write(master, LIGHT_REPLY)
                    replied += 1

        def state():
            try:
                return json.loads(state_path.read_text())
            except (OSError, ValueError):
                return {}

        def wait_for(name, predicate, timeout=10):
            deadline = monotonic() + timeout
            while monotonic() < deadline:
                pump()
                current = state()
                if current and predicate(current):
                    checks.append(name)
                    return current
            raise RuntimeError(f"{name} timed out; last state {state()}")

        def send(data):
            os.write(master, data)

        try:
            wait_for("startup inside tmux", lambda s: s.get("focused") == "prompt-input")
            sleep(1.0)
            for _ in range(40):
                pump()
            current = state()
            notes["outer_saw_osc11_query"] = OSC11_QUERY in seen
            notes["outer_saw_2031_enable"] = b"\x1b[?2031h" in seen
            notes["terminal_palette"] = current.get("terminal_palette")
            notes["appearance"] = current.get("appearance")
            notes["detection_source"] = current.get("detection_source")
            notes["app_scheme_notifications"] = current.get("scheme_notifications")
            # Gallery: F6 opens it in the probe app; arrow focuses the list.
            send(b"\x1b[17~")
            wait_for("gallery opens (F6 through tmux)", lambda s: s["screen"] == "ThemePicker")
            send(b"\x1b[B")
            sleep(0.3)
            send(b"f")
            sleep(0.5)
            config = Path(directory) / ".superqode" / "config.json"
            try:
                favorites = json.loads(config.read_text())["appearance"]["favorite_themes"]
            except (OSError, ValueError, KeyError):
                favorites = []
            if favorites:
                checks.append("f toggles a favorite")
            else:
                notes["favorite_failure"] = "no favorite saved"
            send(b"w")
            wait_for("w shows workspace", lambda s: s["workspace_preview"])
            send(b"w")
            wait_for("w returns to gallery", lambda s: not s["workspace_preview"])
            send(b"\x1bOS")  # F4 in SS3 form, as some terminals send it
            wait_for("F4 (SS3) shows workspace", lambda s: s["workspace_preview"])
            send(b"\x1b[14~")  # F4 in CSI form
            wait_for("F4 (CSI) returns to gallery", lambda s: not s["workspace_preview"])
            send(b"\x1b")
            wait_for("Escape closes gallery", lambda s: s["screen"] != "ThemePicker")
            # Clipboard through tmux.
            send(b":copy response")
            wait_for("copy command typed", lambda s: s["text"] == ":copy response")
            seen_before = len(seen)
            send(b"\r")
            wait_for("copy routed", lambda s: s["copies"])
            deadline = monotonic() + 5
            while monotonic() < deadline and b"\x1b]52;" not in seen[seen_before:]:
                pump()
            notes["outer_saw_osc52"] = b"\x1b]52;" in seen[seen_before:]
            # Resize the outer terminal; tmux resizes the pane.
            new = (size[0] - 20, size[1] - 6)
            fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", new[1], new[0], 0, 0))
            os.killpg(process.pid, 28)  # SIGWINCH to the tmux client
            wait_for("resize reaches app", lambda s: s["size"] == list(new))
            return {
                "passthrough": passthrough,
                "checks": checks,
                "notes": notes,
                "env": extra_env or {},
                "outer_answers_osc11": answer,
            }
        finally:
            subprocess.run(["tmux", "-L", socket, "kill-server"], capture_output=True)
            try:
                process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                process.kill()
            os.close(master)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not shutil.which("tmux"):
        parser.error("tmux is not installed")
    tmux = subprocess.run(["tmux", "-V"], capture_output=True, text=True).stdout.strip()
    report = {"tmux": tmux, "results": [], "failures": []}
    cases = [
        (True, None, True),
        (False, None, True),
        (False, {"COLORFGBG": "0;15"}, False),
        (True, {"COLORFGBG": "15;0"}, False),
    ]
    for passthrough, extra, answer in cases:
        try:
            report["results"].append(run_case(passthrough, extra_env=extra, answer=answer))
        except (OSError, RuntimeError, ValueError) as exc:
            report["failures"].append(f"passthrough={passthrough} env={extra}: {exc}")
    text = json.dumps(report, indent=2)
    if args.output:
        args.output.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 1 if report["failures"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
