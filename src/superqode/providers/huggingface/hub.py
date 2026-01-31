"""HuggingFace Hub API client for model discovery and download.

This module provides access to the HuggingFace Hub API for:
- Searching models by name, task, library
- Getting model information (size, license, downloads)
- Listing GGUF files available for a model
- Downloading models for local use
"""

import asyncio
import json
import os
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen


# HuggingFace Hub API base URL
HF_API_BASE = "https://huggingface.co/api"


def discover_cached_models(cache_dirs: Optional[List[Path]] = None) -> List[Dict[str, Any]]:
    """Discover locally cached HuggingFace models.

    Returns:
        List of model info dicts with keys: id, path, modified
    """
    # Determine cache locations
    if cache_dirs is None:
        hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
        hf_home_path = Path(hf_home).expanduser()
        hf_hub_path = hf_home_path if hf_home_path.name == "hub" else hf_home_path / "hub"
        cache_dirs = [
            hf_hub_path,
            Path(os.path.expanduser("~/.cache/transformers")),
        ]

    models_by_id: Dict[str, Dict[str, Any]] = {}

    for cache_dir in cache_dirs:
        try:
            if not cache_dir.exists():
                continue
            for model_dir in cache_dir.glob("models--*"):
                if not model_dir.is_dir():
                    continue
                model_id = model_dir.name.replace("models--", "").replace("--", "/")
                try:
                    modified = datetime.fromtimestamp(model_dir.stat().st_mtime)
                except Exception:
                    modified = None
                existing = models_by_id.get(model_id)
                if existing:
                    # Keep the most recently modified entry
                    if modified and existing.get("modified") and modified <= existing["modified"]:
                        continue
                models_by_id[model_id] = {
                    "id": model_id,
                    "path": str(model_dir),
                    "modified": modified,
                }
        except Exception:
            continue

    # Sort newest first, then by id for stability (None modified goes last)
    models = list(models_by_id.values())
    def sort_key(m: Dict[str, Any]) -> tuple:
        modified = m.get("modified")
        ts = modified.timestamp() if modified else 0.0
        return (modified is None, -ts, m["id"])
    models.sort(key=sort_key)
    return models


@dataclass
class HFModel:
    """Represents a model from the HuggingFace Hub.

    Attributes:
        id: Model ID (e.g., "meta-llama/Llama-3.3-70B-Instruct")
        author: Model author/organization
        name: Model name without author prefix
        downloads: Total download count
        likes: Number of likes
        trending_score: Trending score (if available)
        library: Primary library (transformers, gguf, etc.)
        pipeline_tag: Task type (text-generation, etc.)
        tags: Model tags
        license: Model license
        gated: Whether model requires access approval
        private: Whether model is private
        created_at: Creation timestamp
        updated_at: Last update timestamp
        sha: Latest commit SHA
        siblings: List of files in the repo
    """

    id: str
    author: str = ""
    name: str = ""
    downloads: int = 0
    likes: int = 0
    trending_score: float = 0.0
    library: str = ""
    pipeline_tag: str = ""
    tags: List[str] = field(default_factory=list)
    license: str = ""
    gated: bool = False
    private: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    sha: str = ""
    siblings: List[Dict] = field(default_factory=list)

    @property
    def downloads_display(self) -> str:
        """Human-readable download count."""
        if self.downloads >= 1_000_000:
            return f"{self.downloads / 1_000_000:.1f}M"
        if self.downloads >= 1_000:
            return f"{self.downloads / 1_000:.1f}K"
        return str(self.downloads)

    @property
    def is_gguf(self) -> bool:
        """Check if model has GGUF files."""
        return "gguf" in self.library.lower() or any("gguf" in t.lower() for t in self.tags)

    @property
    def is_gated_llama(self) -> bool:
        """Check if this is a gated Llama model."""
        return self.gated and "llama" in self.id.lower()


@dataclass
class GGUFFile:
    """Represents a GGUF file available for download.

    Attributes:
        filename: Name of the GGUF file
        size_bytes: File size in bytes
        quantization: Detected quantization (Q4_K_M, Q8_0, etc.)
        url: Download URL
        sha: File SHA hash
    """

    filename: str
    size_bytes: int = 0
    quantization: str = "unknown"
    url: str = ""
    sha: str = ""

    @property
    def size_display(self) -> str:
        """Human-readable size."""
        if self.size_bytes == 0:
            return "unknown"
        gb = self.size_bytes / (1024**3)
        if gb >= 1:
            return f"{gb:.1f}GB"
        mb = self.size_bytes / (1024**2)
        return f"{mb:.0f}MB"


class HuggingFaceHub:
    """HuggingFace Hub API client.

    Provides access to the HF Hub for model discovery and download.

    Environment:
        HF_TOKEN: HuggingFace token for private/gated models
        HF_HOME: Cache directory (default: ~/.cache/huggingface)
    """

    def __init__(self, token: Optional[str] = None, cache_dir: Optional[Path] = None):
        """Initialize the HF Hub client.

        Args:
            token: HF token for authentication. Falls back to HF_TOKEN env var.
            cache_dir: Cache directory. Falls back to HF_HOME or ~/.cache/huggingface.
        """
        self._token = (
            token or os.environ.get("HF_TOKEN") or os.environ.get("HUGGING_FACE_HUB_TOKEN")
        )

        if cache_dir:
            self._cache_dir = cache_dir
        else:
            hf_home = os.environ.get("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
            self._cache_dir = Path(hf_home)

    @property
    def token(self) -> Optional[str]:
        """Get the HF token."""
        return self._token

    @property
    def cache_dir(self) -> Path:
        """Get the cache directory."""
        return self._cache_dir

    @property
    def is_authenticated(self) -> bool:
        """Check if we have authentication."""
        return self._token is not None and len(self._token) > 0

    def _request(self, endpoint: str, params: Optional[Dict] = None, timeout: float = 30.0) -> Any:
        """Make a request to the HF Hub API.

        Args:
            endpoint: API endpoint (e.g., "/models")
            params: Query parameters
            timeout: Request timeout

        Returns:
            JSON response.
        """
        url = f"{HF_API_BASE}{endpoint}"

        if params:
            url = f"{url}?{urlencode(params)}"

        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"

        request = Request(url, headers=headers)

        with urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))

    async def _async_request(
        self, endpoint: str, params: Optional[Dict] = None, timeout: float = 30.0
    ) -> Any:
        """Async wrapper for _request."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, lambda: self._request(endpoint, params, timeout))

    async def search_models(
        self,
        query: str = "",
        task: str = "text-generation",
        library: Optional[str] = None,
        sort: str = "downloads",
        direction: str = "-1",
        limit: int = 20,
    ) -> List[HFModel]:
        """Search for models on HF Hub.

        Args:
            query: Search query (model name, author, etc.)
            task: Task/pipeline type (text-generation, text2text-generation)
            library: Filter by library (transformers, gguf, etc.)
            sort: Sort field (downloads, likes, trending_score, created_at)
            direction: Sort direction (-1 for descending, 1 for ascending)
            limit: Maximum results to return

        Returns:
            List of HFModel objects.
        """
        params = {
            "limit": str(limit),
            "sort": sort,
            "direction": direction,
            "full": "true",  # Include all fields
        }

        if query:
            params["search"] = query

        if task:
            params["pipeline_tag"] = task

        if library:
            params["library"] = library

        try:
            response = await self._async_request("/models", params)
            return [self._parse_model(m) for m in response]
        except Exception:
            return []

    async def get_trending(self, limit: int = 20) -> List[HFModel]:
        """Get trending text-generation models.

        Args:
            limit: Maximum results.

        Returns:
            List of trending HFModel objects.
        """
        return await self.search_models(task="text-generation", sort="trending_score", limit=limit)

    async def get_popular_coding(self, limit: int = 20) -> List[HFModel]:
        """Get popular coding/code models.

        Args:
            limit: Maximum results.

        Returns:
            List of popular coding HFModel objects.
        """
        # Search for code-related models
        models = []

        # Try different code-related queries
        for query in ["coder", "code", "starcoder"]:
            results = await self.search_models(
                query=query, task="text-generation", sort="downloads", limit=limit
            )
            for m in results:
                if m.id not in [existing.id for existing in models]:
                    models.append(m)

            if len(models) >= limit:
                break

        return models[:limit]

    async def get_model_info(self, model_id: str) -> Optional[HFModel]:
        """Get detailed information about a model.

        Args:
            model_id: Full model ID (e.g., "meta-llama/Llama-3.3-70B-Instruct")

        Returns:
            HFModel with detailed info, or None if not found.
        """
        try:
            # URL encode the model ID (handles slashes)
            encoded_id = quote(model_id, safe="")
            response = await self._async_request(f"/models/{encoded_id}")
            return self._parse_model(response, full=True)
        except HTTPError as e:
            if e.code == 404:
                return None
            raise
        except Exception:
            return None

    async def list_gguf_files(self, model_id: str) -> List[GGUFFile]:
        """List GGUF files available for a model.

        Args:
            model_id: Full model ID.

        Returns:
            List of GGUFFile objects available for download.
        """
        model = await self.get_model_info(model_id)
        if not model:
            return []

        gguf_files = []
        for sibling in model.siblings:
            filename = sibling.get("rfilename", "")
            if filename.lower().endswith(".gguf"):
                size = sibling.get("size", 0)
                sha = sibling.get("sha", "")

                # Detect quantization from filename
                quant = self._detect_quantization(filename)

                # Build download URL
                url = f"https://huggingface.co/{model_id}/resolve/main/{filename}"

                gguf_files.append(
                    GGUFFile(
                        filename=filename,
                        size_bytes=size,
                        quantization=quant,
                        url=url,
                        sha=sha,
                    )
                )

        # Sort by quantization quality (higher quality first)
        quant_order = [
            "F32",
            "F16",
            "BF16",
            "Q8_0",
            "Q6_K",
            "Q5_K_M",
            "Q5_K_S",
            "Q4_K_M",
            "Q4_K_S",
            "Q4_0",
            "Q3_K_M",
            "Q3_K_S",
            "Q2_K",
        ]

        def sort_key(f: GGUFFile) -> int:
            try:
                return quant_order.index(f.quantization)
            except ValueError:
                return 999

        gguf_files.sort(key=sort_key)

        return gguf_files

    async def search_gguf_models(self, query: str = "", limit: int = 20) -> List[HFModel]:
        """Search specifically for GGUF models.

        Args:
            query: Search query.
            limit: Maximum results.

        Returns:
            List of HFModel objects with GGUF files.
        """
        return await self.search_models(
            query=query, task="text-generation", library="gguf", limit=limit
        )

    async def check_access(self, model_id: str) -> Dict[str, Any]:
        """Check if user has access to a gated model.

        Args:
            model_id: Model ID to check.

        Returns:
            Dict with access status info.
        """
        if not self.is_authenticated:
            return {
                "has_access": False,
                "reason": "Not authenticated. Set HF_TOKEN environment variable.",
                "gated": True,
            }

        model = await self.get_model_info(model_id)
        if not model:
            return {
                "has_access": False,
                "reason": "Model not found",
                "gated": False,
            }

        if not model.gated:
            return {
                "has_access": True,
                "reason": "Model is not gated",
                "gated": False,
            }

        # Try to access a file to check permissions
        try:
            # Try to get repo info with credentials
            encoded_id = quote(model_id, safe="")
            await self._async_request(f"/models/{encoded_id}/tree/main")
            return {
                "has_access": True,
                "reason": "Access granted",
                "gated": True,
            }
        except HTTPError as e:
            if e.code == 403:
                return {
                    "has_access": False,
                    "reason": "Access denied. Request access at https://huggingface.co/" + model_id,
                    "gated": True,
                }
            raise

    def _parse_model(self, data: Dict[str, Any], full: bool = False) -> HFModel:
        """Parse model data from API response."""
        model_id = data.get("id", data.get("modelId", ""))

        # Split author and name
        author = ""
        name = model_id
        if "/" in model_id:
            author, name = model_id.split("/", 1)

        # Parse timestamps
        created_at = None
        updated_at = None
        if "createdAt" in data:
            try:
                created_at = datetime.fromisoformat(data["createdAt"].replace("Z", "+00:00"))
            except Exception:
                pass
        if "lastModified" in data:
            try:
                updated_at = datetime.fromisoformat(data["lastModified"].replace("Z", "+00:00"))
            except Exception:
                pass

        # Get library
        library = ""
        if "library_name" in data:
            library = data["library_name"]
        elif "tags" in data:
            # Check tags for library info
            for tag in data.get("tags", []):
                if tag in ("transformers", "gguf", "pytorch", "tensorflow", "jax"):
                    library = tag
                    break

        return HFModel(
            id=model_id,
            author=author,
            name=name,
            downloads=data.get("downloads", 0),
            likes=data.get("likes", 0),
            trending_score=data.get("trendingScore", 0.0),
            library=library,
            pipeline_tag=data.get("pipeline_tag", ""),
            tags=data.get("tags", []),
            license=self._extract_license(data),
            gated=data.get("gated", False) or data.get("gated", "") == "auto",
            private=data.get("private", False),
            created_at=created_at,
            updated_at=updated_at,
            sha=data.get("sha", ""),
            siblings=data.get("siblings", []) if full else [],
        )

    def _extract_license(self, data: Dict[str, Any]) -> str:
        """Extract license from model data."""
        # Check card_data first
        card_data = data.get("cardData", {})
        if "license" in card_data:
            return card_data["license"]

        # Check tags for license
        for tag in data.get("tags", []):
            if tag.startswith("license:"):
                return tag.split(":", 1)[1]

        return ""

    def _detect_quantization(self, filename: str) -> str:
        """Detect quantization from GGUF filename."""
        filename_upper = filename.upper()

        # Common quantization patterns
        quants = [
            "Q8_0",
            "Q6_K",
            "Q5_K_M",
            "Q5_K_S",
            "Q4_K_M",
            "Q4_K_S",
            "Q4_0",
            "Q3_K_M",
            "Q3_K_S",
            "Q2_K",
            "IQ4_XS",
            "IQ3_XS",
            "IQ2_XS",
            "F32",
            "F16",
            "BF16",
        ]

        for quant in quants:
            if quant in filename_upper or quant.replace("_", "-") in filename_upper:
                return quant

        return "unknown"


# Singleton instance
_hub_instance: Optional[HuggingFaceHub] = None


def get_hf_hub() -> HuggingFaceHub:
    """Get the global HuggingFace Hub client instance.

    Returns:
        HuggingFaceHub client instance.
    """
    global _hub_instance
    if _hub_instance is None:
        _hub_instance = HuggingFaceHub()
    return _hub_instance
