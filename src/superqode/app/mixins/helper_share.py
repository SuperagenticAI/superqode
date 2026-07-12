"""Session-share id resolution and artifact import."""

from __future__ import annotations
import shlex
import time
from pathlib import Path


class HelperShareMixin:
    """Session-share id resolution and artifact import."""

    def _resolve_export_target(self, args: str) -> tuple[str, Path]:
        """Resolve ``:export [format] [path]`` into a format and output path."""
        format_aliases = {
            "html": "html",
            "htm": "html",
            "markdown": "markdown",
            "md": "markdown",
            "json": "json",
        }
        suffix_by_format = {
            "html": ".html",
            "markdown": ".md",
            "json": ".json",
        }
        tokens = shlex.split((args or "").strip()) if (args or "").strip() else []
        export_format = "html"
        path_arg = ""
        if tokens and tokens[0].lower() in format_aliases:
            export_format = format_aliases[tokens[0].lower()]
            path_arg = " ".join(tokens[1:]).strip()
        elif tokens:
            path_arg = " ".join(tokens).strip()
            suffix_format = {
                ".html": "html",
                ".htm": "html",
                ".md": "markdown",
                ".markdown": "markdown",
                ".json": "json",
            }.get(Path(path_arg).suffix.lower())
            if suffix_format:
                export_format = suffix_format

        suffix = suffix_by_format[export_format]
        if path_arg:
            out_path = Path(path_arg).expanduser()
            if out_path.suffix.lower() not in {
                ".html",
                ".htm",
                ".md",
                ".markdown",
                ".json",
            }:
                out_path = out_path.with_suffix(suffix)
            return export_format, out_path

        stamp = time.strftime("%Y%m%d-%H%M%S")
        return export_format, Path(".superqode") / "exports" / f"transcript-{stamp}{suffix}"
    def _resolve_share_session_id(self, value: str = "") -> str:
        from superqode.headless import resolve_session_id

        requested = (value or "").strip()
        if requested:
            return resolve_session_id(requested, ".superqode/sessions")
        current_id = self._current_session_id()
        if not current_id:
            raise ValueError("No active session. Use :sessions to choose one.")
        return resolve_session_id(current_id, ".superqode/sessions")
    @staticmethod
    def _parse_share_session_and_path(tokens: list[str]) -> tuple[str, str]:
        if not tokens:
            return "", ""
        if len(tokens) == 1:
            token = tokens[0]
            suffix = Path(token).suffix
            if suffix or "/" in token or token.startswith("."):
                return "", token
            return token, ""
        return tokens[0], tokens[1]
    def _import_share_artifact(self, path: Path, new_session_id: str = "") -> str:
        from superqode.session.share_artifacts import import_share_artifact

        return import_share_artifact(
            path,
            new_session_id=new_session_id,
            storage_dir=".superqode/sessions",
        )
