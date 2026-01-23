"""
Network Tools - HTTP/Web Operations.

Provides tools for fetching content from URLs, making API requests,
and working with web resources.

Features:
- Fetch HTML/JSON/text from URLs
- Configurable timeouts and size limits
- HTML to text extraction
- JSON response parsing
"""

import asyncio
import json
import ssl
import urllib.request
import urllib.error
from pathlib import Path
from typing import Any, Dict, Optional
from html.parser import HTMLParser
import re

from .base import Tool, ToolResult, ToolContext


class HTMLTextExtractor(HTMLParser):
    """Extract text content from HTML."""

    def __init__(self):
        super().__init__()
        self._text = []
        self._skip_tags = {"script", "style", "head", "meta", "link"}
        self._current_tag = None
        self._in_skip = False

    def handle_starttag(self, tag, attrs):
        self._current_tag = tag.lower()
        if self._current_tag in self._skip_tags:
            self._in_skip = True

    def handle_endtag(self, tag):
        if tag.lower() in self._skip_tags:
            self._in_skip = False
        self._current_tag = None

    def handle_data(self, data):
        if not self._in_skip:
            text = data.strip()
            if text:
                self._text.append(text)

    def get_text(self) -> str:
        return "\n".join(self._text)


class FetchTool(Tool):
    """
    Fetch content from URLs.

    Supports:
    - HTML pages (with text extraction)
    - JSON APIs
    - Plain text
    - Raw content

    Security:
    - Configurable size limits
    - Timeout protection
    - No file:// URLs
    """

    DEFAULT_TIMEOUT = 30
    MAX_SIZE = 1024 * 1024  # 1MB default limit
    USER_AGENT = "SuperQode/1.0 (AI Coding Assistant)"

    @property
    def name(self) -> str:
        return "fetch"

    @property
    def description(self) -> str:
        return "Fetch content from a URL. Supports HTML (extracts text), JSON, and plain text."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch (http or https)"},
                "format": {
                    "type": "string",
                    "enum": ["auto", "text", "json", "html", "raw"],
                    "description": "Response format: auto (detect), text (extract from HTML), json, html (raw HTML), raw (bytes as text)",
                },
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 30)"},
                "headers": {"type": "object", "description": "Additional HTTP headers to send"},
                "max_size": {
                    "type": "integer",
                    "description": "Maximum response size in bytes (default: 1MB)",
                },
            },
            "required": ["url"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        url = args.get("url", "")
        format_type = args.get("format", "auto")
        timeout = args.get("timeout", self.DEFAULT_TIMEOUT)
        headers = args.get("headers", {})
        max_size = args.get("max_size", self.MAX_SIZE)

        # Validate URL
        if not url:
            return ToolResult(success=False, output="", error="URL is required")

        if not url.startswith(("http://", "https://")):
            return ToolResult(
                success=False, output="", error="Only http:// and https:// URLs are supported"
            )

        try:
            # Run fetch in executor to not block
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(
                    None, lambda: self._sync_fetch(url, headers, timeout, max_size)
                ),
                timeout=timeout + 5,  # Extra buffer for executor
            )

            if result.get("error"):
                return ToolResult(success=False, output="", error=result["error"])

            content = result["content"]
            content_type = result.get("content_type", "")

            # Process based on format
            output = self._process_content(content, content_type, format_type)

            return ToolResult(
                success=True,
                output=output,
                metadata={
                    "url": url,
                    "content_type": content_type,
                    "size": len(content),
                    "format": format_type,
                },
            )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False, output="", error=f"Request timed out after {timeout} seconds"
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Fetch error: {str(e)}")

    def _sync_fetch(
        self, url: str, headers: Dict[str, str], timeout: int, max_size: int
    ) -> Dict[str, Any]:
        """Synchronous fetch implementation."""
        try:
            # Build request
            req = urllib.request.Request(url)
            req.add_header("User-Agent", self.USER_AGENT)

            for key, value in headers.items():
                req.add_header(key, value)

            # Create SSL context
            ctx = ssl.create_default_context()

            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
                content_type = response.headers.get("Content-Type", "")

                # Read with size limit
                content = response.read(max_size)

                # Check if truncated
                extra = response.read(1)
                if extra:
                    content += b"\n\n[Content truncated at " + str(max_size).encode() + b" bytes]"

                # Decode
                charset = self._get_charset(content_type)
                try:
                    text = content.decode(charset, errors="replace")
                except (UnicodeDecodeError, LookupError):
                    text = content.decode("utf-8", errors="replace")

                return {"content": text, "content_type": content_type}

        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.reason}"}
        except urllib.error.URLError as e:
            return {"error": f"URL Error: {str(e.reason)}"}
        except Exception as e:
            return {"error": str(e)}

    def _get_charset(self, content_type: str) -> str:
        """Extract charset from Content-Type header."""
        if not content_type:
            return "utf-8"

        # Look for charset=
        match = re.search(r"charset=([^\s;]+)", content_type, re.I)
        if match:
            return match.group(1).strip("\"'")

        return "utf-8"

    def _process_content(self, content: str, content_type: str, format_type: str) -> str:
        """Process content based on format type."""
        # Auto-detect format
        if format_type == "auto":
            if "application/json" in content_type:
                format_type = "json"
            elif "text/html" in content_type:
                format_type = "text"  # Extract text from HTML
            else:
                format_type = "raw"

        if format_type == "json":
            try:
                data = json.loads(content)
                return json.dumps(data, indent=2)
            except json.JSONDecodeError:
                return content

        elif format_type == "text":
            # Extract text from HTML
            try:
                parser = HTMLTextExtractor()
                parser.feed(content)
                text = parser.get_text()
                return text if text else content
            except Exception:
                return content

        elif format_type == "html":
            return content

        else:  # raw
            return content


class DownloadTool(Tool):
    """
    Download a file from a URL.

    Saves the file to the specified path.
    """

    DEFAULT_TIMEOUT = 60
    MAX_SIZE = 50 * 1024 * 1024  # 50MB limit
    USER_AGENT = "SuperQode/1.0 (AI Coding Assistant)"

    @property
    def name(self) -> str:
        return "download"

    @property
    def description(self) -> str:
        return "Download a file from a URL and save it to a path."

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to download from"},
                "path": {"type": "string", "description": "Path to save the file"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default: 60)"},
            },
            "required": ["url", "path"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        url = args.get("url", "")
        path = args.get("path", "")
        timeout = args.get("timeout", self.DEFAULT_TIMEOUT)

        if not url or not path:
            return ToolResult(success=False, output="", error="Both url and path are required")

        if not url.startswith(("http://", "https://")):
            return ToolResult(
                success=False, output="", error="Only http:// and https:// URLs are supported"
            )

        file_path = Path(path)
        if not file_path.is_absolute():
            file_path = ctx.working_directory / file_path

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._sync_download(url, file_path, timeout)),
                timeout=timeout + 5,
            )

            if result.get("error"):
                return ToolResult(success=False, output="", error=result["error"])

            return ToolResult(
                success=True,
                output=f"Downloaded {result['size']} bytes to {path}",
                metadata={"url": url, "path": str(file_path), "size": result["size"]},
            )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False, output="", error=f"Download timed out after {timeout} seconds"
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Download error: {str(e)}")

    def _sync_download(self, url: str, file_path: Path, timeout: int) -> Dict[str, Any]:
        """Synchronous download implementation."""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", self.USER_AGENT)

            ctx = ssl.create_default_context()

            file_path.parent.mkdir(parents=True, exist_ok=True)

            with urllib.request.urlopen(req, timeout=timeout, context=ctx) as response:
                with open(file_path, "wb") as f:
                    total = 0
                    while True:
                        chunk = response.read(8192)
                        if not chunk:
                            break

                        total += len(chunk)
                        if total > self.MAX_SIZE:
                            return {"error": f"File exceeds maximum size of {self.MAX_SIZE} bytes"}

                        f.write(chunk)

                return {"size": total}

        except urllib.error.HTTPError as e:
            return {"error": f"HTTP {e.code}: {e.reason}"}
        except urllib.error.URLError as e:
            return {"error": f"URL Error: {str(e.reason)}"}
        except Exception as e:
            return {"error": str(e)}
