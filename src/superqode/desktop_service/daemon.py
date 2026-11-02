"""Opt-in local desktop engine, authenticated over a private Unix socket.

The UI talks to a disposable stdio bridge. Disconnecting that bridge never
replays a request or shuts down the engine. Explicit shutdown retains the
existing service's cancellation, worker reaping and writer-lease contract.
"""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import signal
import socket
import stat
import subprocess
import sys
import threading
import time
import uuid

from .service import DesktopService, MAX_TEXT, private_root

PROTOCOL = 1


def build_id():
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.glob("*.py")):
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def socket_path(root):
    direct = root / "engine.sock"
    if len(os.fsencode(direct)) < 100:
        return direct
    directory = private_root(
        Path("/private/tmp" if sys.platform == "darwin" else "/tmp")
        / f"superqode-engine-{os.getuid()}"
    )
    return directory / (hashlib.sha256(os.fsencode(root)).hexdigest()[:24] + ".sock")


def token(root, *, create=False):
    path = root / "engine.token"
    if create:
        try:
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(secrets.token_hex(32))
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(descriptor) as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError("Background engine token must be a private file owned by this user")
        value = stream.read(65)
        if len(value) != 64:
            raise ValueError("Background engine token is invalid")
        return value


def connect(root, *, timeout=2, management=False):
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stream = None
    client.settimeout(timeout)
    try:
        client.connect(str(socket_path(root)))
        stream = client.makefile("rwb", buffering=0)
        client.sendall(
            (
                json.dumps(
                    {
                        "token": token(root),
                        "protocol": PROTOCOL,
                        "build": build_id(),
                        "management": management,
                    }
                )
                + "\n"
            ).encode()
        )
        response = json.loads(stream.readline(4096))
        if response.get("error"):
            raise ValueError(response["error"])
        if response.get("protocol") != PROTOCOL:
            raise ValueError(
                "Background engine protocol changed. Stop the old engine before reconnecting."
            )
        client.settimeout(None)
        return client, stream, response
    except BaseException:
        if stream is not None:
            stream.close()
        client.close()
        raise


class BackgroundEngine:
    def __init__(self, root):
        self.service = DesktopService(root)
        self.root = self.service.root
        self.instance = uuid.uuid4().hex
        self.started = time.time()
        self.build = build_id()
        self.secret = token(self.root, create=True)
        self.stopping = threading.Event()
        self.clients = set()
        self.lock = threading.Lock()

    def status(self):
        with self.lock:
            count = len(self.clients)
        return {
            "mode": "background",
            "instance": self.instance,
            "pid": os.getpid(),
            "started": self.started,
            "clients": count,
            "protocol": PROTOCOL,
            "active_jobs": sum(
                row["status"] in {"queued", "running", "needs_approval", "cancelling"}
                for row in self.service.job_summaries()
            ),
            "continuity": "Work survives UI disconnect; engine or Mac loss interrupts work without automatic replay.",
        }

    def dispatch(self, method, params):
        if method == "engine.status":
            return self.status()
        if method == "engine.shutdown":
            if params.get("instance") != self.instance:
                raise ValueError("Engine changed. Refresh its status before stopping it.")
            if self.status()["active_jobs"] and params.get("cancel_active") is not True:
                raise ValueError(
                    "Active work remains. Explicitly choose Stop engine and active work."
                )
            return {"stopping": True}
        if self.stopping.is_set():
            raise ValueError("Background engine is shutting down")
        return self.service.dispatch(method, params)

    def client(self, client, pool):
        client.settimeout(5)
        stream = client.makefile("rwb", buffering=0)
        write_lock = threading.Lock()
        alive = threading.Event()
        management = False
        alive.set()

        def write(value):
            with write_lock:
                if alive.is_set():
                    try:
                        client.sendall((json.dumps(value, default=str) + "\n").encode())
                    except OSError:
                        alive.clear()

        def handle(request):
            try:
                if not isinstance(request, dict) or not isinstance(request.get("params", {}), dict):
                    raise ValueError("Invalid desktop request")
                if management and request.get("method") not in {"engine.status", "engine.shutdown"}:
                    raise ValueError(
                        "Recovery connection only supports inspecting or stopping the engine"
                    )
                result = self.dispatch(request["method"], request.get("params", {}))
                write({"id": request.get("id"), "result": result})
                if request["method"] == "engine.shutdown":
                    self.stopping.set()
            except Exception as exc:
                write(
                    {
                        "id": request.get("id") if isinstance(request, dict) else None,
                        "error": str(exc)[:2000],
                    }
                )

        try:
            auth = json.loads(stream.readline(4096))
            if not isinstance(auth, dict) or not hmac.compare_digest(
                str(auth.get("token", "")).encode("utf-8", errors="replace"), self.secret.encode()
            ):
                write({"error": "Background engine authentication failed"})
                return
            management = auth.get("management") is True
            if auth.get("protocol") != PROTOCOL or (
                not management and auth.get("build") != self.build
            ):
                write(
                    {
                        "error": "A different engine build is still running. Finish work and stop that engine before opening this build."
                    }
                )
                return
            write({"protocol": PROTOCOL, "instance": self.instance})
            client.settimeout(None)
            while not self.stopping.is_set():
                raw = stream.readline(MAX_TEXT + 1)
                if not raw or len(raw) > MAX_TEXT:
                    break
                try:
                    request = json.loads(raw)
                except ValueError:
                    break
                if isinstance(request, dict) and request.get("method") == "engine.shutdown":
                    handle(request)
                else:
                    pool.submit(handle, request)
        except (OSError, ValueError):
            pass
        finally:
            alive.clear()
            with self.lock:
                self.clients.discard(client)
            stream.close()
            client.close()

    def serve(self):
        path = socket_path(self.root)
        server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        handlers = []
        try:
            # The DesktopService engine lease is already held. A second engine
            # cannot unlink this listener or mark running work interrupted.
            path.unlink(missing_ok=True)
            server.bind(str(path))
            os.chmod(path, 0o600)
            server.listen(8)
            server.settimeout(0.3)
            with ThreadPoolExecutor(max_workers=6) as pool:
                while not self.stopping.is_set():
                    try:
                        client, _ = server.accept()
                    except socket.timeout:
                        continue
                    with self.lock:
                        if len(self.clients) >= 8:
                            client.close()
                            continue
                        self.clients.add(client)
                    thread = threading.Thread(target=self.client, args=(client, pool), daemon=True)
                    handlers = [thread for thread in handlers if thread.is_alive()]
                    handlers.append(thread)
                    thread.start()
                with self.lock:
                    for client in list(self.clients):
                        try:
                            client.shutdown(socket.SHUT_RD)
                        except OSError:
                            pass
                for thread in handlers:
                    thread.join(timeout=6)
        finally:
            server.close()
            path.unlink(missing_ok=True)
            self.service.close()


def ensure_connection(root):
    try:
        return connect(root)
    except (ConnectionError, FileNotFoundError, socket.timeout, OSError):
        pass
    log_path = root / "background-engine.log"
    if log_path.exists() and log_path.stat().st_size > 2_000_000:
        log_path.replace(root / "background-engine.previous.log")
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
    with os.fdopen(descriptor, "ab") as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-u",
                "-m",
                "superqode.desktop_service.daemon",
                "--serve",
                "--state",
                str(root),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
            start_new_session=True,
        )
    deadline = time.monotonic() + 12
    while time.monotonic() < deadline:
        process.poll()
        try:
            return connect(root)
        except (ConnectionError, FileNotFoundError, socket.timeout, OSError):
            time.sleep(0.1)
    raise ValueError(
        "Background engine did not start. Inspect its local log; another engine may still own this state directory."
    )


def bridge(root, *, management=False):
    client, stream, _ = connect(root, management=True) if management else ensure_connection(root)

    def send():
        try:
            while raw := sys.stdin.buffer.readline(MAX_TEXT + 1):
                if len(raw) > MAX_TEXT:
                    break
                client.sendall(raw)
        finally:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass

    threading.Thread(target=send, daemon=True).start()
    try:
        while raw := stream.readline(16 * 1024 * 1024 + 1):
            if len(raw) > 16 * 1024 * 1024:
                raise ValueError("Background response exceeded the local protocol limit")
            sys.stdout.buffer.write(raw)
            sys.stdout.buffer.flush()
    except OSError:
        pass  # Disconnect ends the bridge; requests are never replayed.
    finally:
        stream.close()
        client.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--state", required=True)
    parser.add_argument("--serve", action="store_true")
    parser.add_argument("--manage", action="store_true")
    args = parser.parse_args()
    root = private_root(args.state)
    if args.serve:
        engine = BackgroundEngine(root)
        for name in (signal.SIGINT, signal.SIGTERM):
            signal.signal(name, lambda *_: engine.stopping.set())
        engine.serve()
    else:
        bridge(root, management=args.manage)


if __name__ == "__main__":
    main()
