"""Bounded LM Studio v1 operations on the app's fixed loopback server."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request


def base_url(*, openai=False):
    """Use the same app-owned loopback port for model listing and operations.

    Resolve SPECS per call so a configured port is not captured at import time.
    Shell provider hosts never redirect the desktop's local model operations.
    """
    from .servers import SPECS

    prefix = "/v1" if openai else "/api/v1"
    return f"http://127.0.0.1:{SPECS['lmstudio'].default_port}{prefix}"


def request(path, payload=None, *, timeout=30, openai=False):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        base_url(openai=openai) + path, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return json.loads(response.read(2_000_000))
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise ValueError(
                "LM Studio REST v1 is unavailable. Update LM Studio and lms to a version supporting /api/v1/models, then retry."
            ) from exc
        if exc.code in {401, 403}:
            raise ValueError(
                "LM Studio rejected local API access. Review its API authentication configuration in LM Studio."
            ) from exc
        raise


def models():
    """Prefer native metadata; older compatible servers expose model IDs only."""
    try:
        payload = request("/models")
    except ValueError as exc:
        # Only missing native API capability permits a compatibility fallback.
        # Authentication errors must not be retried through another endpoint.
        if not isinstance(exc.__cause__, urllib.error.HTTPError) or exc.__cause__.code != 404:
            raise
        payload = {}
    native = payload.get("models") if isinstance(payload, dict) else None
    if isinstance(native, list):
        return [
            row
            for row in native
            if isinstance(row, dict) and row.get("type") in {"llm", "decision"}
        ]
    compatible = request("/models", openai=True)
    return [
        {"key": row["id"], "type": "llm", "loaded_instances": []}
        for row in compatible.get("data", [])
        if isinstance(row, dict) and isinstance(row.get("id"), str) and 0 < len(row["id"]) <= 4096
    ]


def load(model, context):
    return request(
        "/models/load",
        {
            "model": model,
            "context_length": context,
            "flash_attention": True,
            "echo_load_config": True,
        },
        timeout=600,
    )


def download(model, emit):
    status = request("/models/download", {"model": model})
    # The server owns its transfer. Cancellation of our observer does not
    # claim to cancel an LM Studio download; the UI explains this explicitly.
    deadline = time.monotonic() + 24 * 3600
    while True:
        emit(
            "progress",
            {
                "status": status.get("status", "unknown"),
                "completed": status.get("downloaded_bytes", 0),
                "total": status.get("total_size_bytes"),
                "unit": "B",
                "label": "LM Studio · " + status.get("status", "unknown"),
                "bytes_per_second": status.get("bytes_per_second"),
            },
        )
        state = status.get("status")
        if state in {"completed", "already_downloaded"}:
            return status
        if state in {"failed", "paused"}:
            raise ValueError(
                "LM Studio download " + state + ". Inspect it in LM Studio before retrying."
            )
        job = status.get("job_id")
        if state != "downloading" or not isinstance(job, str) or time.monotonic() >= deadline:
            raise ValueError("LM Studio returned no active download. Check its download manager.")
        time.sleep(1)
        status = request("/models/download/status/" + urllib.parse.quote(job, safe=""))
