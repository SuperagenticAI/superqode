"""Bounded image attachments shared by the composer and model transports."""

from __future__ import annotations

import base64
import re
import shlex
from dataclasses import dataclass
from pathlib import Path

MAX_IMAGE_BYTES = 4 * 1024 * 1024
MAX_IMAGES = 4
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


@dataclass(frozen=True)
class ImagePathReference:
    path: Path
    start: int
    end: int


# Terminal drops use quoted paths or shell-escaped spaces. Keep source spans so
# extracting attachments never flattens a multiline draft or rewrites prose.
_PATH_TOKEN = re.compile(
    r"""(?<!\S)(?:@?(?:"(?:\\.|[^"\\])*"|'[^']*')|(?:\\[^\r\n]|[^\s"'])+)(?=$|\s)"""
)


def parse_image_paths(text: str) -> list[ImagePathReference]:
    """Recognize explicit image paths and existing filenames, never commands."""
    from urllib.parse import unquote, urlparse

    lowered = text.lower()
    if not any(extension in lowered for extension in IMAGE_EXTENSIONS):
        return []
    stripped = text.strip()
    # Finder's plain-text clipboard may contain an unquoted path with spaces.
    if stripped.startswith(("/", "~/", "./", "../")):
        try:
            whole = Path(stripped).expanduser()
            is_image = whole.suffix.lower() in IMAGE_EXTENSIONS and whole.is_file()
        except (OSError, RuntimeError, ValueError):
            is_image = False
        if is_image:
            start = len(text) - len(text.lstrip())
            return [ImagePathReference(whole, start, start + len(stripped))]

    refs = []
    for match in _PATH_TOKEN.finditer(text):
        try:
            tokens = shlex.split(match.group(), posix=True)
        except ValueError:
            continue
        if len(tokens) != 1:
            continue
        value = tokens[0]
        explicit = value.startswith(("@", "/", "~/", "./", "../", "file://"))
        value = value.removeprefix("@")
        try:
            if value.startswith("file://"):
                uri = urlparse(value)
                if uri.netloc not in ("", "localhost"):
                    continue
                value = unquote(uri.path)
            path = Path(value)
            # Output often contains tilde markers. Only resolve home directories
            # for image candidates, never for arbitrary words in a pasted log.
            if path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            path = path.expanduser()
            is_image = explicit or path.is_file()
        except (OSError, RuntimeError, ValueError):
            is_image = False
        if is_image:
            refs.append(ImagePathReference(path, match.start(), match.end()))
    return refs


def strip_image_paths(text: str, refs: list[ImagePathReference]) -> str:
    chunks = []
    end = 0
    for ref in refs:
        chunks.append(text[end : ref.start])
        end = ref.end
    chunks.append(text[end:])
    return "".join(chunks).strip()


@dataclass(frozen=True)
class ImageAttachment:
    path: Path
    mime_type: str
    data: str

    def model_part(self) -> dict:
        return {
            "type": "image_url",
            "image_url": {"url": f"data:{self.mime_type};base64,{self.data}"},
        }

    def acp_part(self) -> dict:
        return {"type": "image", "mimeType": self.mime_type, "data": self.data}


def load_image(path: Path) -> ImageAttachment:
    """Validate format and size before encoding; never decode image bytes as text."""
    try:
        path = path.expanduser().resolve()
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"Cannot resolve image path: {path.name}") from exc
    if path.suffix.lower() not in IMAGE_EXTENSIONS:
        raise ValueError("Use a PNG, JPEG, GIF, or WebP image.")
    try:
        with path.open("rb") as stream:
            data = stream.read(MAX_IMAGE_BYTES + 1)
    except (OSError, ValueError) as exc:
        raise ValueError(f"Cannot read image: {path.name}") from exc
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Image exceeds 4 MB. Resize or crop it before attaching.")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif data.startswith(b"\xff\xd8\xff"):
        mime = "image/jpeg"
    elif data.startswith((b"GIF87a", b"GIF89a")):
        mime = "image/gif"
    elif data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        raise ValueError("File is not a recognized PNG, JPEG, GIF, or WebP image.")
    return ImageAttachment(path, mime, base64.b64encode(data).decode("ascii"))


def image_message(text: str, images: list[ImageAttachment]) -> str | list[dict]:
    if not images:
        return text
    return [{"type": "text", "text": text}, *(image.model_part() for image in images)]
