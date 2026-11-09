"""Bounded LM Studio v1 operations on the app's fixed loopback server."""

import json
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "http://127.0.0.1:1234/api/v1"


def request(path, payload=None, *, timeout=30):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path, data=body, headers={"Content-Type": "application/json"}
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
    return [
        row
        for row in request("/models").get("models", [])
        if isinstance(row, dict) and row.get("type") in {"llm", "decision"}
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
