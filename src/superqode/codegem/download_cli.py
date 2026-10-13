"""Download pinned, checksum-verified Gemma artifacts with resumable ranges."""

import argparse
import concurrent.futures
import hashlib
import json
import os
import shutil
import time
import urllib.request
from pathlib import Path

RELEASES = {
    "coding": {
        "repo": "google/gemma-4-26B-A4B-it-qat-q4_0-gguf",
        "revision": "d1c082be9cf3c8a514acf63b8761f4b41935842e",
        "file": "gemma-4-26B_q4_0-it.gguf",
        "bytes": 14439363584,
        "sha256": "3eca3b8f6d7baf218a7dd6bba5fb59a56ee25fe2d567b6f5f589b4f697eca51d",
    },
    "embedding": {
        "repo": "ggml-org/embeddinggemma-2-GGUF",
        "revision": "bfcd298762cc34d0357ece5ebdd31791a3a374d8",
        "file": "embeddinggemma-2-BF16.gguf",
        "bytes": 557950176,
        "sha256": "68bae29d62fb8c7d23e98d21fd4662753ddd636e6b62b8a70dfe059a9844f216",
    },
    "embedding-v1": {
        "repo": "ggml-org/embeddinggemma-300M-GGUF",
        "revision": "0f741b5a6585bd53aeb15cd1372c56f2a0f65e12",
        "file": "embeddinggemma-300M-Q8_0.gguf",
        "bytes": 333590944,
        "sha256": "b5ce9d77a3fc4b3b39ccb5643c36777911cc4eb46a66962eadfa3f5f60490d63",
    },
}


def digest(path):
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def download(spec, directory, workers):
    target = directory / spec["file"]
    if target.exists() and digest(target) == spec["sha256"]:
        print(f"Verified cached {target}", flush=True)
        return
    # Allow room for temporary ranges and the assembled artifact.
    if shutil.disk_usage(directory).free < spec["bytes"] * 2 + 2_000_000_000:
        raise RuntimeError("Insufficient free disk space for a safe parallel download")
    parts = directory / (spec["file"] + ".ranges")
    parts.mkdir(exist_ok=True)
    block = 256 * 1024 * 1024
    url = f"https://huggingface.co/{spec['repo']}/resolve/{spec['revision']}/{spec['file']}?download=true"

    def fetch(index):
        start = index * block
        end = min(spec["bytes"], start + block) - 1
        part = parts / str(index)
        if part.exists() and part.stat().st_size == end - start + 1:
            return index
        for attempt in range(4):
            try:
                req = urllib.request.Request(
                    url + f"&range={index}", headers={"Range": f"bytes={start}-{end}"}
                )
                with urllib.request.urlopen(req, timeout=60) as response, part.open("wb") as handle:
                    if (
                        response.status != 206
                        or response.headers.get("Content-Range")
                        != f"bytes {start}-{end}/{spec['bytes']}"
                    ):
                        raise RuntimeError("Download server did not honor the requested byte range")
                    shutil.copyfileobj(response, handle, length=1024 * 1024)
                if part.stat().st_size != end - start + 1:
                    raise RuntimeError("Incomplete model range")
                return index
            except Exception:
                if attempt == 3:
                    raise
                time.sleep(2**attempt)

    count = (spec["bytes"] + block - 1) // block
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
        for complete, _ in enumerate(
            concurrent.futures.as_completed([pool.submit(fetch, i) for i in range(count)]), 1
        ):
            # result() ensures a failed download never silently becomes a model.
            _.result()
            print(f"{spec['file']}: {complete}/{count} ranges complete", flush=True)
    temporary = target.with_suffix(target.suffix + ".part")
    with temporary.open("wb") as output:
        for index in range(count):
            with (parts / str(index)).open("rb") as source:
                shutil.copyfileobj(source, output, length=1024 * 1024)
    if digest(temporary) != spec["sha256"]:
        raise RuntimeError("Model SHA-256 mismatch; artifact was not activated")
    temporary.replace(target)
    shutil.rmtree(parts)
    print(f"Downloaded and SHA-256 verified {target}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, default=Path(".superqode/models/codegem"))
    parser.add_argument(
        "--models", nargs="+", choices=tuple(RELEASES), default=["coding", "embedding"]
    )
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    for name in args.models:
        download(RELEASES[name], args.directory, max(1, min(args.workers, 16)))
    (args.directory / "manifest.json").write_text(json.dumps(RELEASES, indent=2) + "\n")
    if "coding" in args.models:
        model = (args.directory / RELEASES["coding"]["file"]).resolve()
        (args.directory / "Modelfile").write_text(
            f'FROM "{model}"\nPARAMETER num_ctx 32768\n', encoding="utf-8"
        )


if __name__ == "__main__":
    main()
