"""
Large Output Handling for Agent Responses.

Saves large outputs to files when they exceed a size threshold,
preventing token limit issues and improving readability.
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class OutputConfig:
    """Configuration for large output handling."""

    max_output_size: int = 50000  # chars
    save_to_file_threshold: int = 10000  # chars
    output_dir: str = ".superqode/outputs"


class LargeOutputHandler:
    """Handles large outputs by saving to files."""

    def __init__(self, config: Optional[OutputConfig] = None, workspace: str = "."):
        self.config = config or OutputConfig()
        self.workspace = Path(workspace)
        self._output_dir = self.workspace / self.config.output_dir
        self._output_dir.mkdir(parents=True, exist_ok=True)

    def should_save_to_file(self, output: str) -> bool:
        """Check if output should be saved to file."""
        return len(output) > self.config.save_to_file_threshold

    def save_output(self, output: str, prefix: str = "output") -> str:
        """Save output to file and return file path."""
        import uuid
        from datetime import datetime

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        filename = f"{prefix}_{timestamp}_{unique_id}.txt"

        output_path = self._output_dir / filename
        output_path.write_text(output, encoding="utf-8")

        return str(output_path.relative_to(self.workspace))

    def handle_output(self, output: str) -> tuple[str, Optional[str]]:
        """Process output, saving to file if too large.
        
        Returns:
            tuple of (display_message, file_path or None)
        """
        if not self.should_save_to_file(output):
            return output, None

        file_path = self.save_output(output)
        display = (
            f"Output too large to display ({len(output)} chars).\n"
            f"Saved to: {file_path}\n"
            f"\n--- Output Preview (first 500 chars) ---\n"
            f"{output[:500]}\n"
            f"--- End Preview ---"
        )

        return display, file_path

    def read_saved_output(self, file_path: str) -> Optional[str]:
        """Read a previously saved output file."""
        try:
            path = self.workspace / file_path
            if path.exists():
                return path.read_text(encoding="utf-8")
        except Exception:
            pass
        return None

    def list_outputs(self) -> list[dict]:
        """List all saved output files."""
        outputs = []
        if self._output_dir.exists():
            for f in sorted(self._output_dir.iterdir()):
                if f.is_file():
                    stat = f.stat()
                    outputs.append({
                        "name": f.name,
                        "path": str(f.relative_to(self.workspace)),
                        "size": stat.st_size,
                        "modified": stat.st_mtime,
                    })
        return outputs

    def clear_old_outputs(self, max_age_days: int = 7) -> int:
        """Clear output files older than max_age_days."""
        import time

        if not self._output_dir.exists():
            return 0

        cutoff = time.time() - (max_age_days * 86400)
        removed = 0

        for f in self._output_dir.iterdir():
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink()
                removed += 1

        return removed


def create_output_handler(
    max_size: int = 50000,
    workspace: str = ".",
) -> LargeOutputHandler:
    """Create a large output handler."""
    config = OutputConfig(max_output_size=max_size)
    return LargeOutputHandler(config=config, workspace=workspace)