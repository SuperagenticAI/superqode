"""Stdlib-only watchdog for a protected probe and its controller lifetime.

Executed as a script with -S; never imports candidate or application modules.
"""

import json
import os
import selectors
import signal
import subprocess
import sys
import threading
import time


def supervise(request):
    started = time.monotonic()
    deadline = started + request["timeout"]
    stdin = request["stdin"]
    child = subprocess.Popen(
        request["argv"],
        cwd=request["cwd"],
        env=request["env"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    output = {"stdout": bytearray(), "stderr": bytearray()}
    pending = memoryview(stdin.encode())
    kind, detail = "completed", ""
    try:
        with selectors.DefaultSelector() as selector:
            for name in output:
                stream = getattr(child, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            if pending:
                os.set_blocking(child.stdin.fileno(), False)
                selector.register(child.stdin, selectors.EVENT_WRITE, "stdin")
            else:
                child.stdin.close()
            while selector.get_map():
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    kind, detail = "timeout", "Verification budget expired"
                    break
                for key, _ in selector.select(min(remaining, 0.1)):
                    if key.data == "stdin":
                        try:
                            pending = pending[os.write(key.fd, pending) :]
                        except BrokenPipeError:
                            pending = memoryview(b"")
                        if not pending:
                            selector.unregister(key.fileobj)
                            key.fileobj.close()
                        continue
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffer = output[key.data]
                    if len(buffer) + len(chunk) > 64_000:
                        buffer.extend(chunk[: 64_000 - len(buffer)])
                        kind, detail = "output_limit", "Probe exceeded its output limit"
                        break
                    buffer.extend(chunk)
                if kind != "completed":
                    break
            if kind == "completed":
                try:
                    child.wait(timeout=max(0.01, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    kind, detail = "timeout", "Verification budget expired"
    finally:
        # The OS backend disallows descendants or owns their PID namespace.
        # Parent loss additionally kills this entire supervisor process group.
        if child.poll() is None:
            try:
                child.kill()
            except ProcessLookupError:
                pass
        child.wait(timeout=5)
        for stream in (child.stdin, child.stdout, child.stderr):
            if stream and not stream.closed:
                stream.close()
    try:
        stdout = bytes(output["stdout"]).decode("utf-8")
        stderr = bytes(output["stderr"]).decode("utf-8")
    except UnicodeDecodeError:
        kind, detail = "invalid_utf8", "Probe output must be UTF-8"
        stdout = bytes(output["stdout"]).decode("utf-8", errors="replace")
        stderr = bytes(output["stderr"]).decode("utf-8", errors="replace")
    return {
        "kind": kind,
        "detail": detail,
        "backend": request["backend"],
        "returncode": child.returncode,
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_ms": int((time.monotonic() - started) * 1000),
    }


def main():
    request = json.loads(sys.stdin.buffer.readline(1_000_001))
    done = threading.Event()

    def parent_lifetime():
        # The controller keeps this pipe open until the result is collected.
        while os.read(sys.stdin.fileno(), 1):
            pass
        if not done.is_set():
            os.killpg(os.getpgrp(), signal.SIGKILL)

    threading.Thread(target=parent_lifetime, daemon=True).start()
    try:
        result = supervise(request)
    except Exception as exc:
        result = {"kind": "infrastructure_error", "detail": str(exc), "backend": request["backend"]}
    done.set()
    print(json.dumps(result), flush=True)


if __name__ == "__main__":
    main()
