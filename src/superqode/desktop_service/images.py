"""Private immutable image snapshots using the terminal's attachment validation."""

import base64
import hashlib
import uuid
from pathlib import Path


def stage_image(state: Path, path: str):
    from superqode.image_input import load_image, MAX_IMAGE_BYTES

    source = Path(path).expanduser().resolve(strict=True)
    if not source.is_file() or source.stat().st_size > MAX_IMAGE_BYTES:
        raise ValueError("Choose an image file smaller than 4 MB")
    image = load_image(source)
    raw = base64.b64decode(image.data)
    directory = state / "images"
    directory.mkdir(mode=0o700, exist_ok=True)
    if directory.is_symlink() or not directory.resolve().is_relative_to(state):
        raise ValueError("Image snapshots must stay inside desktop storage")
    identity = uuid.uuid4().hex
    suffix = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
    }[image.mime_type]
    target = directory / (identity + suffix)
    with target.open("xb") as output:
        import os

        os.fchmod(output.fileno(), 0o600)
        output.write(raw)
    return {
        "id": identity,
        "name": source.name,
        "path": str(target),
        "mime_type": image.mime_type,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "bytes": len(raw),
    }


def resolve_images(state, ids):
    from superqode.image_input import MAX_IMAGES

    if not isinstance(ids, list) or len(ids) > MAX_IMAGES:
        raise ValueError("Attach up to four images")
    result = []
    if any(not isinstance(identity, str) for identity in ids):
        raise ValueError("Choose a staged image")
    for identity in dict.fromkeys(ids):
        if (
            not isinstance(identity, str)
            or len(identity) != 32
            or any(c not in "0123456789abcdef" for c in identity)
        ):
            raise ValueError("Choose a staged image")
        files = list((state / "images").glob(identity + ".*"))
        if len(files) != 1 or files[0].is_symlink():
            raise ValueError("Image snapshot is missing; attach it again")
        target = files[0]
        from superqode.image_input import load_image

        image = load_image(target)
        raw = base64.b64decode(image.data)
        result.append(
            {"id": identity, "path": str(target), "sha256": hashlib.sha256(raw).hexdigest()}
        )
    return result


def load_snapshots(request):
    from superqode.image_input import load_image

    result = []
    for item in request.get("image_snapshots", []):
        target = Path(item["path"])
        image = load_image(target)
        if hashlib.sha256(base64.b64decode(image.data)).hexdigest() != item["sha256"]:
            raise ValueError("Image snapshot changed; attach it again")
        result.append(image)
    return tuple(result)
