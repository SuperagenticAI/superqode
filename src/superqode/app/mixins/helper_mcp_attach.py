"""MCP resource resolution and prompt/image attachment staging."""

from __future__ import annotations
import asyncio
import time
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
        if not getattr(self, "_attached_refs", None):
            self._set_prompt_prefill("")
            return
        prefill = " ".join(dict.fromkeys(self._attached_refs)) + " "
        self._set_prompt_prefill(prefill)

    def _is_image_path(self, value: str) -> bool:
        """True if value looks like a path to a readable image file."""
        try:
            path = Path(value.strip().strip("'\"")).expanduser()
            return path.suffix.lower() in self._IMAGE_EXTENSIONS and path.is_file()
        except Exception:
            return False

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
        out = target_dir / f"clipboard-{int(time.time())}.png"

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
        try:
            ref = "@" + str(path.relative_to(Path.cwd()))
        except ValueError:
            ref = "@" + str(path)
        if not hasattr(self, "_attached_refs"):
            self._attached_refs = []
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
