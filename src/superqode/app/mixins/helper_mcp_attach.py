"""MCP resource resolution and prompt/image attachment staging."""

from __future__ import annotations
import asyncio
from pathlib import Path
from typing import Optional
from superqode.app.widgets import (
    ConversationLog,
)


class HelperMcpAttachMixin:
    """MCP resource resolution and prompt/image attachment staging."""

    @staticmethod
    def _parse_mcp_resource_ref(ref: str) -> tuple[str, str] | None:
        if not ref.startswith("mcp://"):
            return None
        body = ref[len("mcp://") :]
        if "/" not in body:
            return None
        server_id, uri = body.split("/", 1)
        if not server_id or not uri:
            return None
        return server_id, uri

    @staticmethod
    def _extract_mcp_refs_from_text(text: str) -> tuple[str, list[str]]:
        """Remove inline MCP refs from prompt text and return them separately."""
        if "mcp://" not in text:
            return text.strip(), []
        from superqode.app_main import SuperQodeApp

        parts = text.split()
        refs: list[str] = []
        kept: list[str] = []
        for part in parts:
            stripped = part.strip()
            if stripped.startswith("mcp://") and SuperQodeApp._parse_mcp_resource_ref(stripped):
                refs.append(stripped)
            else:
                kept.append(part)
        return " ".join(kept).strip(), refs

    @staticmethod
    def _truncate_mcp_content(text: str, remaining_chars: int) -> tuple[str, bool]:
        if len(text) <= remaining_chars:
            return text, False
        return text[: max(0, remaining_chars)].rstrip(), True

    async def _resolve_mcp_attachment_context(self, log: ConversationLog | None = None) -> str:
        """Read staged MCP resource refs into bounded prompt context."""
        refs = list(dict.fromkeys(getattr(self, "_current_mcp_refs", []) or []))
        if not refs:
            return ""
        try:
            from superqode.mcp.integration import get_mcp_manager

            manager = await get_mcp_manager()
        except Exception as exc:
            if log is not None:
                log.add_error(f"Could not initialize MCP manager for resource context: {exc}")
            return ""

        blocks: list[str] = []
        total_chars = 0
        max_resources = 5
        max_total_chars = 30000
        loaded = 0
        skipped = 0
        for ref in refs[:max_resources]:
            parsed = self._parse_mcp_resource_ref(ref)
            if parsed is None:
                skipped += 1
                continue
            server_id, uri = parsed
            try:
                content = await manager.read_resource(server_id, uri)
            except Exception as exc:
                skipped += 1
                blocks.append(
                    f'<mcp-resource server="{server_id}" uri="{uri}" error="{str(exc)}"></mcp-resource>'
                )
                continue
            if content is None:
                skipped += 1
                blocks.append(
                    f'<mcp-resource server="{server_id}" uri="{uri}" error="not found"></mcp-resource>'
                )
                continue
            text = getattr(content, "text", None)
            mime_type = getattr(content, "mime_type", None) or ""
            if not text:
                skipped += 1
                blob = getattr(content, "blob", None)
                reason = "binary content" if blob else "empty content"
                blocks.append(
                    f'<mcp-resource server="{server_id}" uri="{uri}" mime_type="{mime_type}" skipped="{reason}"></mcp-resource>'
                )
                continue
            remaining = max_total_chars - total_chars
            if remaining <= 0:
                skipped += 1
                break
            clipped, truncated = self._truncate_mcp_content(text, remaining)
            total_chars += len(clipped)
            truncated_attr = ' truncated="true"' if truncated else ""
            blocks.append(
                f'<mcp-resource server="{server_id}" uri="{uri}" mime_type="{mime_type}"{truncated_attr}>\n'
                f"{clipped}\n"
                "</mcp-resource>"
            )
            loaded += 1
            if truncated:
                break
        self._current_mcp_refs = []
        if log is not None and (loaded or skipped):
            message = f"Including {loaded} MCP resource(s)"
            if skipped:
                message += f"; {skipped} skipped or unavailable"
            log.add_info(message + ".")
        if not blocks:
            return ""
        return "<mcp-resources>\n" + "\n\n".join(blocks) + "\n</mcp-resources>"

    def _resolve_mcp_attachment_context_sync(self, log: ConversationLog | None = None) -> str:
        """Synchronous wrapper for thread-based agent runners."""
        try:
            return asyncio.run(self._resolve_mcp_attachment_context(log))
        except RuntimeError:
            # If a loop is already active in this thread, skip rather than deadlock.
            if log is not None:
                log.add_error("Could not resolve MCP resources from this runner.")
            return ""

    @staticmethod
    def _configured_mcp_server_ids() -> list[str]:
        try:
            from superqode.mcp.config import load_mcp_config

            servers = load_mcp_config(Path.cwd() / ".superqode" / "mcp.json")
            return list(servers.keys())
        except Exception:
            return []

    def _sync_attachment_prefill(self) -> None:
        refs = getattr(self, "_attached_refs", [])
        images = getattr(self, "_staged_images", {})
        self._staged_images = {ref: image for ref, image in images.items() if ref in refs}
        text_refs = [ref for ref in refs if ref not in self._staged_images]
        prefill = " ".join(dict.fromkeys(text_refs)) + " " if text_refs else ""
        try:
            from superqode.app.inputs import SelectionAwareInput

            draft = self.query_one("#prompt-input", SelectionAwareInput).value
        except Exception:
            draft = ""
        previous = getattr(self, "_attachment_prefill", "")
        if previous and draft.startswith(previous):
            draft = draft[len(previous) :]
        self._attachment_prefill = prefill
        self._set_prompt_prefill(prefill + draft)
        self._refresh_attachment_bar()

    def _refresh_attachment_bar(self) -> None:
        from rich.text import Text
        from rich.style import Style
        from textual.widgets import Static
        from superqode.app.constants import THEME

        try:
            panel = self.query_one("#attachment-bar", Static)
        except Exception:
            return
        refs = getattr(self, "_attached_refs", [])
        line = Text("◈ Attachments  ", style=THEME["purple"])
        for index, ref in enumerate(refs, 1):
            label = Path(ref.lstrip("@")).name
            if len(label) > 24:
                label = label[:21] + "…"
            line.append(f"{index}. {label} ×", style=THEME["text"])
            line.stylize(
                Style(meta={"@click": f"app.remove_attachment({index})"}),
                len(line) - len(f"{index}. {label} ×"),
            )
            line.append("  ")
        panel.update(line)
        panel.set_class(bool(refs), "visible")

    def _prepare_image_input(self, log: ConversationLog) -> list | None:
        """Snapshot images for this turn, keeping the draft intact on failure."""
        from superqode.image_input import load_image

        staged = getattr(self, "_staged_images", {})
        if not staged:
            return []
        if getattr(self, "is_busy", False):
            log.add_error("Wait for the current run to finish before sending images.")
            return None
        pure = getattr(self, "_pure_mode", None)
        if pure is not None and pure.session.connected:
            if not getattr(self, "_chat_mode", False) and (
                getattr(pure, "_harness_spec", None) is not None
                or not getattr(pure, "_agent", None)
            ):
                log.add_error(
                    "Image input is available in direct Chat, built-in coding, and image-capable ACP agents. Your attachments are still staged."
                )
                return None
            if not self._model_supports_vision(pure.session.model):
                log.add_error(
                    "The selected model does not support images. Choose a vision model; your attachments are still staged."
                )
                return None
        try:
            return [load_image(image.path) for image in staged.values()]
        except ValueError as exc:
            log.add_error(str(exc))
            return None

    def _consume_image_input(self, images: list) -> None:
        self._current_images = images
        staged = getattr(self, "_staged_images", {})
        self._attached_refs = [
            ref for ref in getattr(self, "_attached_refs", []) if ref not in staged
        ]
        self._staged_images = {}
        self._refresh_attachment_bar()

    def _restore_image_input(self, images: list) -> None:
        if not images:
            return
        for image in images:
            try:
                ref = "@" + str(image.path.relative_to(Path.cwd()))
            except ValueError:
                ref = "@" + str(image.path)
            self._staged_images[ref] = image
            if ref not in self._attached_refs:
                self._attached_refs.append(ref)
        self._refresh_attachment_bar()
        self._set_prompt_prefill(getattr(self, "_last_user_message", ""))

    def _is_image_path(self, value: str) -> bool:
        """True if value looks like a path to a readable image file."""
        try:
            path = Path(value.strip().strip("'\"")).expanduser()
            return path.suffix.lower() in self._IMAGE_EXTENSIONS and path.is_file()
        except Exception:
            return False

    def _stage_pasted_images(self, text: str) -> bool:
        """Handle a path-only terminal drop before TextArea inserts it."""
        from superqode.image_input import parse_image_paths, strip_image_paths

        refs = parse_image_paths(text)
        if not refs or strip_image_paths(text, refs):
            return False
        log = self.query_one("#log", ConversationLog)
        for ref in refs:
            if not self._stage_image_attachment(ref.path, log, source="pasted path"):
                return False
        return True

    def _grab_clipboard_image(self) -> Optional[Path]:
        """Best-effort capture of an image on the system clipboard to a temp PNG.

        Tries macOS ``pngpaste`` first, then an AppleScript fallback, then
        Pillow's ImageGrab (cross-platform). Returns the saved path or None.
        """
        import shutil
        import subprocess
        import sys
        import tempfile

        target_dir = Path.cwd() / ".superqode" / "pasted"
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            target_dir = Path(tempfile.gettempdir())
        from uuid import uuid4

        out = target_dir / f"clipboard-{uuid4().hex}.png"

        if shutil.which("pngpaste"):
            try:
                result = subprocess.run(["pngpaste", str(out)], capture_output=True, timeout=10)
                if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
                    return out
            except Exception:
                pass

        if sys.platform == "darwin":
            script = (
                "set theData to the clipboard as «class PNGf»\n"
                f'set theFile to open for access POSIX file "{out}" with write permission\n'
                "write theData to theFile\nclose access theFile"
            )
            try:
                result = subprocess.run(
                    ["osascript", "-e", script], capture_output=True, timeout=10
                )
                if result.returncode == 0 and out.exists() and out.stat().st_size > 0:
                    return out
            except Exception:
                pass

        try:
            from PIL import ImageGrab  # type: ignore

            image = ImageGrab.grabclipboard()
            if image is not None and hasattr(image, "save"):
                image.save(out, "PNG")
                if out.exists() and out.stat().st_size > 0:
                    return out
        except Exception:
            pass
        return None

    def _stage_image_attachment(
        self, path: Path, log: ConversationLog, *, source: str = ""
    ) -> bool:
        """Stage an image file for the next prompt and inform the user."""
        from superqode.image_input import MAX_IMAGES, load_image

        if getattr(self, "is_busy", False):
            log.add_info("Wait for the current run to finish before attaching an image.")
            return False
        try:
            image = load_image(path)
        except ValueError as exc:
            log.add_error(str(exc))
            return False
        path = image.path
        try:
            ref = "@" + str(path.relative_to(Path.cwd()))
        except ValueError:
            ref = "@" + str(path)
        if not hasattr(self, "_attached_refs"):
            self._attached_refs = []
        if not hasattr(self, "_staged_images"):
            self._staged_images = {}
        if ref not in self._staged_images and len(self._staged_images) >= MAX_IMAGES:
            log.add_error(
                f"Attach up to {MAX_IMAGES} images per prompt. Remove one with :attach remove <number>."
            )
            return False
        self._staged_images[ref] = image
        self._attached_refs.append(ref)
        self._attached_refs = list(dict.fromkeys(self._attached_refs))
        self._sync_attachment_prefill()
        label = f" ({source})" if source else ""
        log.add_success(f"🖼  Attached image{label}: {path.name}")
        model = getattr(self, "current_model", "") or ""
        if model and not self._model_supports_vision(model):
            log.add_info(
                "Note: the active model may not support images. Connect a vision model to use it."
            )
        return True

    async def _add_mcp_server_config(
        self,
        manager,
        server_id: str,
        target: str,
    ) -> tuple[bool, str]:
        """Persist and register an MCP server config."""
        from superqode.mcp.config import load_mcp_config, save_mcp_config

        config = self._mcp_server_config_from_target(server_id, target)
        servers = load_mcp_config()
        if server_id in servers:
            return False, f"MCP server already exists: {server_id}"
        servers[server_id] = config
        save_mcp_config(servers)
        manager.add_server(config)
        return True, f"Saved MCP server {server_id}."

    @staticmethod
    def _resolve_mcp_resource_ref(manager, target: str):
        """Resolve a user-facing MCP resource reference to a resource object."""
        target = target.strip()
        resources = list(manager.list_all_resources())
        if not target:
            return None
        if target.isdigit():
            index = int(target) - 1
            return resources[index] if 0 <= index < len(resources) else None
        if target.startswith("mcp://"):
            target = target[len("mcp://") :]
        server_hint = ""
        resource_hint = target
        if "/" in target:
            server_hint, resource_hint = target.split("/", 1)

        matches = []
        lowered = resource_hint.lower()
        for resource in resources:
            if server_hint and resource.server_id.lower() != server_hint.lower():
                continue
            candidates = [
                resource.uri,
                resource.name,
                f"{resource.server_id}/{resource.uri}",
                f"{resource.server_id}/{resource.name}",
            ]
            if any(candidate and candidate.lower() == lowered for candidate in candidates):
                matches.append(resource)
                continue
            if any(candidate and candidate.lower().startswith(lowered) for candidate in candidates):
                matches.append(resource)
        return matches[0] if len(matches) == 1 else None
