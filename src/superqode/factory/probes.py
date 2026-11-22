"""Bounded external Python probes; candidate code is never imported by the scorer."""

from __future__ import annotations

import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
import time
import math

from jsonschema import Draft202012Validator

from superqode.sandbox.local_sandbox import build_verification_argv
from .definition import obj, read_mapping, NAME

PROBE_SCHEMA = obj(
    {
        "format": {"const": "superqode.factory-probes/1"},
        "cases": {
            "type": "array",
            "minItems": 1,
            "maxItems": 64,
            "items": obj(
                {
                    "id": NAME,
                    "argv": {
                        "type": "array",
                        "minItems": 2,
                        "maxItems": 64,
                        "items": {"type": "string", "maxLength": 4096},
                    },
                    "stdin": {"type": "string", "maxLength": 16000},
                    "stdout": {"type": "string", "maxLength": 16000},
                    "stderr": {"type": "string", "maxLength": 16000},
                    "returncode": {"type": "integer", "minimum": 0, "maximum": 255},
                },
                ("id", "argv", "stdout"),
            ),
        },
    },
    ("format", "cases"),
)
OUTPUT_LIMIT = 64_000

# A private network namespace still permits loopback and Unix sockets. Install
# this filter inside Bubblewrap, before exec, so the evaluator cannot create
# sockets at all. libseccomp resolves syscall numbers for the host architecture;
# failure to load/install it stops the trusted launcher before candidate code.
LINUX_NETWORK_GUARD = """
import ctypes, errno
_sc = ctypes.CDLL('libseccomp.so.2')
_sc.seccomp_init.argtypes = [ctypes.c_uint32]
_sc.seccomp_init.restype = ctypes.c_void_p
_sc.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
_sc.seccomp_syscall_resolve_name.restype = ctypes.c_int
_sc.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
_sc.seccomp_load.argtypes = [ctypes.c_void_p]
_sc.seccomp_release.argtypes = [ctypes.c_void_p]
_sc.seccomp_release.restype = None
_ctx = _sc.seccomp_init(0x7fff0000)  # SCMP_ACT_ALLOW
if not _ctx:
    raise RuntimeError('Cannot initialize protected verification network filter')
try:
    for _name in (b'socket', b'socketpair', b'socketcall', b'io_uring_setup'):
        _nr = _sc.seccomp_syscall_resolve_name(_name)
        if _nr < 0:
            if _name == b'socketcall':  # Absent on modern native architectures.
                continue
            raise RuntimeError('Unsupported protected verification network syscall')
        if _sc.seccomp_rule_add(_ctx, 0x00050000 | errno.EPERM, _nr, 0) != 0:
            raise RuntimeError('Cannot configure protected verification network filter')
    if _sc.seccomp_load(_ctx) != 0:
        raise RuntimeError('Cannot install protected verification network filter')
finally:
    _sc.seccomp_release(_ctx)
"""


def parse_probes(text: str) -> dict:
    data = read_mapping(text)
    errors = list(Draft202012Validator(PROBE_SCHEMA).iter_errors(data))
    if errors:
        raise ValueError(f"Invalid protected probes: {errors[0].message}")
    ids = [row["id"] for row in data["cases"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Protected probe ids must be unique")
    for row in data["cases"]:
        if row["argv"][0] != "python" or any("\0" in arg for arg in row["argv"]):
            raise ValueError(
                "Protected probes currently require python argv without NUL characters"
            )
    return data


def run_python_probe(argv, *, candidate: Path, scratch: Path, stdin: str, deadline: float) -> dict:
    """Spawn under required OS isolation, draining bounded stdout/stderr concurrently."""
    # Set hard limits in a trusted launcher, avoiding preexec_fn in a threaded
    # engine. Candidate code receives neither evaluator code nor expectations.
    launcher = (
        "import json,os,resource,sys;"
        f"exec({LINUX_NETWORK_GUARD!r}) if sys.platform == 'linux' else None;"
        "resource.setrlimit(resource.RLIMIT_FSIZE,(16777216,16777216));"
        "resource.setrlimit(resource.RLIMIT_NOFILE,(64,64));"
        f"resource.setrlimit(resource.RLIMIT_CPU,({max(1, math.ceil(deadline - time.monotonic()))},)*2);"
        "os.execv(sys.executable,[sys.executable,'-S',*json.loads(sys.argv[1])])"
    )
    command = [sys.executable, "-S", "-c", launcher, json.dumps(argv[1:])]
    plan = build_verification_argv(command, candidate=candidate, scratch=scratch)
    if not plan.applied:
        return {"kind": "infrastructure_error", "backend": plan.backend, "detail": plan.reason}
    env = {
        "PYTHONNOUSERSITE": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTHONHASHSEED": "0",
        "PYTHONUTF8": "1",
        "TMPDIR": str(scratch),
        "LANG": "C.UTF-8",
    }
    started = time.monotonic()
    if started >= deadline:
        return {"kind": "timeout", "backend": plan.backend, "detail": "Verification budget expired"}
    child = None
    try:
        child = subprocess.Popen(
            [sys.executable, "-S", str(Path(__file__).with_name("probe_supervisor.py"))],
            cwd=candidate,
            env=env,
            start_new_session=True,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        request = {
            "argv": plan.argv,
            "cwd": str(candidate),
            "env": env,
            "stdin": stdin,
            "timeout": max(0.01, deadline - time.monotonic()),
            "backend": plan.backend,
        }
        child.stdin.write(json.dumps(request).encode() + b"\n")
        child.stdin.flush()  # Deliberately retain the parent-lifetime pipe.
        buffers = {"stdout": bytearray(), "stderr": bytearray()}
        with selectors.DefaultSelector() as selector:
            for name in buffers:
                stream = getattr(child, name)
                os.set_blocking(stream.fileno(), False)
                selector.register(stream, selectors.EVENT_READ, name)
            while selector.get_map():
                remaining = deadline + 5 - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Probe supervisor did not stop within its deadline")
                for key, _ in selector.select(min(remaining, 0.1)):
                    chunk = os.read(key.fd, 4096)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    buffers[key.data].extend(chunk)
                    if len(buffers[key.data]) > (1_000_000 if key.data == "stdout" else 8192):
                        raise ValueError("Probe supervisor output exceeded its bound")
        child.wait(timeout=1)
        if child.returncode:
            raise ValueError("Probe supervisor exited before returning evidence")
        return json.loads(buffers["stdout"])
    except (OSError, ValueError, TimeoutError, subprocess.TimeoutExpired) as exc:
        return {"kind": "infrastructure_error", "backend": plan.backend, "detail": str(exc)}
    finally:
        if child is not None:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
            child.wait(timeout=5)
            for stream in (child.stdin, child.stdout, child.stderr):
                if stream and not stream.closed:
                    stream.close()
