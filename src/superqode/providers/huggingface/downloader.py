"""Model download and conversion utilities for HuggingFace models.

This module provides utilities for downloading models from HuggingFace Hub
and preparing them for local use with Ollama or transformers.
"""

import asyncio
import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from urllib.request import Request, urlopen


@dataclass
class DownloadProgress:
    """Progress information for model downloads.

    Attributes:
        filename: File being downloaded
        total_bytes: Total size in bytes
        downloaded_bytes: Bytes downloaded so far
        speed_mbps: Download speed in MB/s
        eta_seconds: Estimated time remaining
        completed: Whether download is complete
        error: Error message if failed
    """

    filename: str = ""
    total_bytes: int = 0
    downloaded_bytes: int = 0
    speed_mbps: float = 0.0
    eta_seconds: float = 0.0
    completed: bool = False
    error: str = ""

    @property
    def progress_percent(self) -> float:
        """Get download progress as percentage."""
        if self.total_bytes == 0:
            return 0.0
        return (self.downloaded_bytes / self.total_bytes) * 100

    @property
    def size_display(self) -> str:
        """Human-readable total size."""
        gb = self.total_bytes / (1024**3)
        if gb >= 1:
            return f"{gb:.1f}GB"
        mb = self.total_bytes / (1024**2)
        return f"{mb:.0f}MB"


@dataclass
class DownloadResult:
    """Result of a model download.

    Attributes:
        success: Whether download succeeded
        path: Path to downloaded file(s)
        model_id: HuggingFace model ID
        quantization: Quantization level (for GGUF)
        ollama_model_name: Name to use in Ollama (if applicable)
        error: Error message if failed
    """

    success: bool
    path: Path = None
    model_id: str = ""
    quantization: str = ""
    ollama_model_name: str = ""
    error: str = ""


class HFDownloader:
    """Download and convert HuggingFace models for local use.

    Supports:
    - Downloading GGUF files for Ollama/llama.cpp
    - Downloading safetensors for transformers
    - Creating Ollama Modelfiles for downloaded GGUFs
    - Progress tracking with callbacks

    Environment:
        HF_TOKEN: For private/gated models
        HF_HOME: Cache directory (default: ~/.cache/huggingface)
    """

    def __init__(self, token: Optional[str] = None, cache_dir: Optional[Path] = None):
        """Initialize the downloader.

        Args:
            token: HF token for authentication.
            cache_dir: Cache directory for downloads.
        """
        self._token = (
            token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        )

        if cache_dir:
            self._cache_dir = cache_dir
        else:
            hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
            self._cache_dir = Path(hf_home) / "superqode"

        # Ensure cache dir exists
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def cache_dir(self) -> Path:
        """Get the cache directory."""
        return self._cache_dir

    async def download_gguf(
        self,
        model_id: str,
        quantization: str = "Q4_K_M",
        output_dir: Optional[Path] = None,
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    ) -> DownloadResult:
        """Download a GGUF file from HuggingFace Hub.

        Args:
            model_id: HuggingFace model ID (e.g., "TheBloke/Llama-2-7B-GGUF")
            quantization: Desired quantization level (Q4_K_M, Q8_0, etc.)
            output_dir: Output directory (defaults to cache)
            progress_callback: Callback for progress updates

        Returns:
            DownloadResult with download info.
        """
        from superqode.providers.huggingface.hub import get_hf_hub

        hub = get_hf_hub()

        # Find GGUF files for this model
        gguf_files = await hub.list_gguf_files(model_id)

        if not gguf_files:
            return DownloadResult(
                success=False, model_id=model_id, error=f"No GGUF files found for {model_id}"
            )

        # Find file matching requested quantization
        target_file = None
        quant_upper = quantization.upper()

        for f in gguf_files:
            if f.quantization.upper() == quant_upper:
                target_file = f
                break

        # If exact match not found, use first available
        if not target_file:
            target_file = gguf_files[0]
            quantization = target_file.quantization

        # Set output directory
        out_dir = output_dir or self._cache_dir / "gguf"
        out_dir.mkdir(parents=True, exist_ok=True)

        output_path = out_dir / target_file.filename

        # Check if already downloaded
        if output_path.exists() and output_path.stat().st_size == target_file.size_bytes:
            return DownloadResult(
                success=True,
                path=output_path,
                model_id=model_id,
                quantization=quantization,
            )

        # Download the file
        loop = asyncio.get_event_loop()

        try:
            await loop.run_in_executor(
                None,
                lambda: self._download_file(
                    target_file.url,
                    output_path,
                    target_file.size_bytes,
                    target_file.filename,
                    progress_callback,
                ),
            )

            return DownloadResult(
                success=True,
                path=output_path,
                model_id=model_id,
                quantization=quantization,
            )

        except Exception as e:
            return DownloadResult(success=False, model_id=model_id, error=str(e))

    def _download_file(
        self,
        url: str,
        output_path: Path,
        total_size: int,
        filename: str,
        progress_callback: Optional[Callable[[DownloadProgress], None]],
    ) -> None:
        """Download a file with progress tracking."""
        import time

        headers = {}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        request = Request(url, headers=headers)

        chunk_size = 8192
        downloaded = 0
        start_time = time.time()
        last_update = start_time

        with urlopen(request, timeout=300) as response:
            with open(output_path, "wb") as f:
                while True:
                    chunk = response.read(chunk_size)
                    if not chunk:
                        break

                    f.write(chunk)
                    downloaded += len(chunk)

                    # Update progress every 0.5 seconds
                    current_time = time.time()
                    if progress_callback and (current_time - last_update) >= 0.5:
                        elapsed = current_time - start_time
                        speed = (downloaded / (1024**2)) / elapsed if elapsed > 0 else 0
                        remaining = total_size - downloaded
                        eta = remaining / (downloaded / elapsed) if downloaded > 0 else 0

                        progress_callback(
                            DownloadProgress(
                                filename=filename,
                                total_bytes=total_size,
                                downloaded_bytes=downloaded,
                                speed_mbps=speed,
                                eta_seconds=eta,
                            )
                        )
                        last_update = current_time

        # Final progress update
        if progress_callback:
            progress_callback(
                DownloadProgress(
                    filename=filename,
                    total_bytes=total_size,
                    downloaded_bytes=total_size,
                    completed=True,
                )
            )

    async def download_for_ollama(
        self,
        model_id: str,
        quantization: str = "Q4_K_M",
        progress_callback: Optional[Callable[[DownloadProgress], None]] = None,
    ) -> DownloadResult:
        """Download GGUF and create Ollama Modelfile.

        Downloads the GGUF file and creates a Modelfile that can be used
        with `ollama create` to register the model.

        Args:
            model_id: HuggingFace model ID with GGUF files
            quantization: Desired quantization
            progress_callback: Progress callback

        Returns:
            DownloadResult with ollama_model_name set
        """
        # Download the GGUF
        result = await self.download_gguf(
            model_id, quantization, progress_callback=progress_callback
        )

        if not result.success:
            return result

        # Create Modelfile
        modelfile_path = result.path.parent / f"{result.path.stem}.Modelfile"

        # Generate Ollama model name
        model_name = model_id.split("/")[-1].lower()
        model_name = model_name.replace("-gguf", "").replace("_gguf", "")
        model_name = f"hf-{model_name}-{quantization.lower()}"

        # Create Modelfile content
        modelfile_content = f"""# Modelfile for {model_id}
# Created by SuperQode HF Downloader

FROM {result.path}

# Default parameters - adjust as needed
PARAMETER temperature 0.7
PARAMETER top_p 0.9
PARAMETER num_ctx 4096
"""

        with open(modelfile_path, "w") as f:
            f.write(modelfile_content)

        result.ollama_model_name = model_name

        return result

    async def register_with_ollama(
        self, gguf_path: Path, model_name: str, parameters: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Register a downloaded GGUF with Ollama.

        Creates a Modelfile and runs `ollama create` to register the model.

        Args:
            gguf_path: Path to GGUF file
            model_name: Name to register in Ollama
            parameters: Optional parameters for Modelfile

        Returns:
            True if registration succeeded
        """
        # Create Modelfile
        modelfile_content = f"FROM {gguf_path}\n"

        if parameters:
            for key, value in parameters.items():
                modelfile_content += f"PARAMETER {key} {value}\n"
        else:
            modelfile_content += "PARAMETER temperature 0.7\n"
            modelfile_content += "PARAMETER num_ctx 4096\n"

        modelfile_path = gguf_path.parent / f"{model_name}.Modelfile"

        with open(modelfile_path, "w") as f:
            f.write(modelfile_content)

        # Run ollama create
        try:
            result = subprocess.run(
                ["ollama", "create", model_name, "-f", str(modelfile_path)],
                capture_output=True,
                text=True,
                timeout=300,
            )

            return result.returncode == 0

        except FileNotFoundError:
            # Ollama not installed
            return False
        except subprocess.TimeoutExpired:
            return False
        except Exception:
            return False

    async def download_for_transformers(
        self, model_id: str, progress_callback: Optional[Callable[[DownloadProgress], None]] = None
    ) -> DownloadResult:
        """Download a model for use with transformers.

        This uses huggingface_hub's snapshot_download if available,
        otherwise falls back to manual download.

        Args:
            model_id: HuggingFace model ID
            progress_callback: Progress callback

        Returns:
            DownloadResult with path to model directory
        """
        try:
            from huggingface_hub import snapshot_download

            loop = asyncio.get_event_loop()

            def do_download():
                return snapshot_download(
                    model_id,
                    token=self._token,
                    cache_dir=str(self._cache_dir / "transformers"),
                )

            path = await loop.run_in_executor(None, do_download)

            return DownloadResult(
                success=True,
                path=Path(path),
                model_id=model_id,
            )

        except ImportError:
            return DownloadResult(
                success=False,
                model_id=model_id,
                error="huggingface_hub not installed. Run: pip install huggingface-hub",
            )
        except Exception as e:
            return DownloadResult(success=False, model_id=model_id, error=str(e))

    def list_cached_models(self) -> List[Dict[str, Any]]:
        """List all cached downloaded models.

        Returns:
            List of dicts with cached model info.
        """
        cached = []

        # Check GGUF cache
        gguf_dir = self._cache_dir / "gguf"
        if gguf_dir.exists():
            for f in gguf_dir.glob("*.gguf"):
                cached.append(
                    {
                        "type": "gguf",
                        "filename": f.name,
                        "path": str(f),
                        "size_bytes": f.stat().st_size,
                        "size_display": self._format_size(f.stat().st_size),
                    }
                )

        # Check transformers cache
        tf_dir = self._cache_dir / "transformers"
        if tf_dir.exists():
            for d in tf_dir.iterdir():
                if d.is_dir():
                    # Calculate total size
                    total_size = sum(f.stat().st_size for f in d.rglob("*") if f.is_file())
                    cached.append(
                        {
                            "type": "transformers",
                            "model_id": d.name,
                            "path": str(d),
                            "size_bytes": total_size,
                            "size_display": self._format_size(total_size),
                        }
                    )

        return cached

    def _format_size(self, size_bytes: int) -> str:
        """Format size in human-readable format."""
        gb = size_bytes / (1024**3)
        if gb >= 1:
            return f"{gb:.1f}GB"
        mb = size_bytes / (1024**2)
        return f"{mb:.0f}MB"


# Singleton instance
_downloader_instance: Optional[HFDownloader] = None


def get_hf_downloader() -> HFDownloader:
    """Get the global HF downloader instance.

    Returns:
        HFDownloader instance.
    """
    global _downloader_instance
    if _downloader_instance is None:
        _downloader_instance = HFDownloader()
    return _downloader_instance
