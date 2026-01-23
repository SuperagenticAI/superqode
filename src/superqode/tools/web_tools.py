"""
Web Tools - Search and Fetch Web Content.

Provides web search and content fetching capabilities for agents:
- Web search with multiple provider support
- URL content fetching with summarization
- HTML to markdown conversion

Features:
- DuckDuckGo search (no API key required)
- Optional Tavily/SerpAPI integration
- Content extraction and summarization
- Configurable result limits
"""

from __future__ import annotations

import asyncio
import json
import re
import ssl
import urllib.request
import urllib.error
import urllib.parse
from html.parser import HTMLParser
from typing import Any, Dict, List, Optional
from dataclasses import dataclass

from .base import Tool, ToolResult, ToolContext


# ============================================================================
# HTML Processing Utilities
# ============================================================================


class HTMLToMarkdown(HTMLParser):
    """Convert HTML to Markdown format."""

    def __init__(self):
        super().__init__()
        self._output: List[str] = []
        self._skip_tags = {"script", "style", "head", "meta", "link", "noscript"}
        self._in_skip = False
        self._tag_stack: List[str] = []
        self._list_depth = 0
        self._in_code = False
        self._href = ""

    def handle_starttag(self, tag: str, attrs: List[tuple]):
        tag = tag.lower()
        self._tag_stack.append(tag)

        if tag in self._skip_tags:
            self._in_skip = True
            return

        attrs_dict = dict(attrs)

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            level = int(tag[1])
            self._output.append("\n" + "#" * level + " ")
        elif tag == "p":
            self._output.append("\n\n")
        elif tag == "br":
            self._output.append("\n")
        elif tag in ("strong", "b"):
            self._output.append("**")
        elif tag in ("em", "i"):
            self._output.append("*")
        elif tag == "a":
            self._href = attrs_dict.get("href", "")
            self._output.append("[")
        elif tag == "code":
            if self._in_code:
                return
            self._output.append("`")
            self._in_code = True
        elif tag == "pre":
            self._output.append("\n```\n")
            self._in_code = True
        elif tag == "ul":
            self._list_depth += 1
            self._output.append("\n")
        elif tag == "ol":
            self._list_depth += 1
            self._output.append("\n")
        elif tag == "li":
            indent = "  " * (self._list_depth - 1)
            self._output.append(f"{indent}- ")
        elif tag == "blockquote":
            self._output.append("\n> ")
        elif tag == "hr":
            self._output.append("\n---\n")

    def handle_endtag(self, tag: str):
        tag = tag.lower()

        if self._tag_stack and self._tag_stack[-1] == tag:
            self._tag_stack.pop()

        if tag in self._skip_tags:
            self._in_skip = False
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._output.append("\n")
        elif tag == "p":
            self._output.append("\n")
        elif tag in ("strong", "b"):
            self._output.append("**")
        elif tag in ("em", "i"):
            self._output.append("*")
        elif tag == "a":
            if self._href:
                self._output.append(f"]({self._href})")
            else:
                self._output.append("]")
            self._href = ""
        elif tag == "code":
            self._output.append("`")
            self._in_code = False
        elif tag == "pre":
            self._output.append("\n```\n")
            self._in_code = False
        elif tag == "ul" or tag == "ol":
            self._list_depth = max(0, self._list_depth - 1)
            self._output.append("\n")
        elif tag == "li":
            self._output.append("\n")

    def handle_data(self, data: str):
        if self._in_skip:
            return
        text = data.strip() if not self._in_code else data
        if text:
            self._output.append(text)

    def get_markdown(self) -> str:
        """Get the converted markdown."""
        result = "".join(self._output)
        # Clean up extra whitespace
        result = re.sub(r"\n{3,}", "\n\n", result)
        return result.strip()


class TextExtractor(HTMLParser):
    """Extract plain text from HTML."""

    def __init__(self):
        super().__init__()
        self._text: List[str] = []
        self._skip_tags = {"script", "style", "head", "meta", "link", "noscript"}
        self._in_skip = False

    def handle_starttag(self, tag: str, attrs: List[tuple]):
        if tag.lower() in self._skip_tags:
            self._in_skip = True

    def handle_endtag(self, tag: str):
        if tag.lower() in self._skip_tags:
            self._in_skip = False

    def handle_data(self, data: str):
        if not self._in_skip:
            text = data.strip()
            if text:
                self._text.append(text)

    def get_text(self) -> str:
        return "\n".join(self._text)


# ============================================================================
# Web Search Tool
# ============================================================================


@dataclass
class SearchResult:
    """A search result."""

    title: str
    url: str
    snippet: str


class WebSearchTool(Tool):
    """
    Search the web for information.

    Uses DuckDuckGo by default (no API key required).
    Can be configured to use Tavily or SerpAPI with API keys.

    Features:
    - Multiple search providers
    - Configurable result count
    - Search type options (fast, deep)
    """

    USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    DEFAULT_TIMEOUT = 15
    MAX_RESULTS = 10

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return """Search the web and return relevant results.

Returns a list of search results with titles, URLs, and snippets.
Useful for finding documentation, examples, recent information, etc."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"},
                "num_results": {
                    "type": "integer",
                    "description": "Number of results to return (default: 5, max: 10)",
                },
                "search_type": {
                    "type": "string",
                    "enum": ["auto", "fast", "deep"],
                    "description": "Search type: fast (quick results), deep (more comprehensive)",
                },
            },
            "required": ["query"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        query = args.get("query", "")
        num_results = min(args.get("num_results", 5), self.MAX_RESULTS)
        search_type = args.get("search_type", "auto")

        if not query:
            return ToolResult(success=False, output="", error="Search query is required")

        try:
            # Try DuckDuckGo first (no API key needed)
            results = await self._search_duckduckgo(query, num_results)

            if not results:
                return ToolResult(
                    success=True,
                    output=f"No results found for: {query}",
                    metadata={"query": query, "count": 0},
                )

            # Format results
            output_lines = [f"Search results for: {query}\n"]

            for i, result in enumerate(results, 1):
                output_lines.append(f"{i}. {result.title}")
                output_lines.append(f"   URL: {result.url}")
                if result.snippet:
                    # Truncate long snippets
                    snippet = (
                        result.snippet[:200] + "..."
                        if len(result.snippet) > 200
                        else result.snippet
                    )
                    output_lines.append(f"   {snippet}")
                output_lines.append("")

            return ToolResult(
                success=True,
                output="\n".join(output_lines),
                metadata={"query": query, "count": len(results), "search_type": search_type},
            )

        except Exception as e:
            return ToolResult(success=False, output="", error=f"Search failed: {str(e)}")

    async def _search_duckduckgo(self, query: str, num_results: int) -> List[SearchResult]:
        """Search using DuckDuckGo HTML."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, lambda: self._sync_search_duckduckgo(query, num_results)
        )

    def _sync_search_duckduckgo(self, query: str, num_results: int) -> List[SearchResult]:
        """Synchronous DuckDuckGo search implementation."""
        try:
            # Use DuckDuckGo HTML search
            encoded_query = urllib.parse.quote_plus(query)
            url = f"https://html.duckduckgo.com/html/?q={encoded_query}"

            req = urllib.request.Request(url)
            req.add_header("User-Agent", self.USER_AGENT)

            ctx = ssl.create_default_context()

            with urllib.request.urlopen(req, timeout=self.DEFAULT_TIMEOUT, context=ctx) as response:
                html = response.read().decode("utf-8", errors="replace")

            # Parse results
            results = self._parse_ddg_results(html, num_results)
            return results

        except Exception as e:
            # Fallback to instant answer API
            try:
                return self._search_ddg_instant(query, num_results)
            except Exception:
                raise e

    def _parse_ddg_results(self, html: str, num_results: int) -> List[SearchResult]:
        """Parse DuckDuckGo HTML results."""
        results = []

        # Find result blocks
        result_pattern = re.compile(
            r'<a[^>]*class="result__a"[^>]*href="([^"]*)"[^>]*>([^<]*)</a>', re.DOTALL
        )

        snippet_pattern = re.compile(r'<a[^>]*class="result__snippet"[^>]*>([^<]*)</a>', re.DOTALL)

        # Find all result links
        link_matches = result_pattern.findall(html)
        snippet_matches = snippet_pattern.findall(html)

        for i, (url, title) in enumerate(link_matches[:num_results]):
            # Clean URL (DuckDuckGo uses redirect URLs)
            if "uddg=" in url:
                try:
                    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
                    url = parsed.get("uddg", [url])[0]
                except Exception:
                    pass

            # Get snippet if available
            snippet = snippet_matches[i] if i < len(snippet_matches) else ""

            # Clean HTML entities
            title = self._clean_html_entities(title)
            snippet = self._clean_html_entities(snippet)

            results.append(SearchResult(title=title.strip(), url=url, snippet=snippet.strip()))

        return results

    def _search_ddg_instant(self, query: str, num_results: int) -> List[SearchResult]:
        """Search using DuckDuckGo instant answer API."""
        encoded_query = urllib.parse.quote_plus(query)
        url = f"https://api.duckduckgo.com/?q={encoded_query}&format=json&no_redirect=1"

        req = urllib.request.Request(url)
        req.add_header("User-Agent", self.USER_AGENT)

        ctx = ssl.create_default_context()

        with urllib.request.urlopen(req, timeout=self.DEFAULT_TIMEOUT, context=ctx) as response:
            data = json.loads(response.read().decode("utf-8"))

        results = []

        # Abstract result
        if data.get("AbstractURL") and data.get("AbstractText"):
            results.append(
                SearchResult(
                    title=data.get("Heading", query),
                    url=data["AbstractURL"],
                    snippet=data["AbstractText"][:200],
                )
            )

        # Related topics
        for topic in data.get("RelatedTopics", [])[: num_results - len(results)]:
            if isinstance(topic, dict) and topic.get("FirstURL"):
                results.append(
                    SearchResult(
                        title=topic.get("Text", "")[:100],
                        url=topic["FirstURL"],
                        snippet=topic.get("Text", "")[:200],
                    )
                )

        return results

    def _clean_html_entities(self, text: str) -> str:
        """Clean HTML entities from text."""
        import html

        return html.unescape(text)


# ============================================================================
# Web Fetch Tool (Enhanced)
# ============================================================================


class WebFetchTool(Tool):
    """
    Fetch and analyze web content.

    Features:
    - HTML to markdown conversion
    - Text extraction
    - Optional summarization
    - Configurable output format
    """

    USER_AGENT = "SuperQode/1.0 (AI Coding Assistant)"
    DEFAULT_TIMEOUT = 30
    MAX_SIZE = 2 * 1024 * 1024  # 2MB

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return """Fetch content from a URL and optionally process it.

Supports:
- HTML pages (converts to markdown or extracts text)
- JSON APIs (formatted output)
- Plain text content

Useful for reading documentation, API responses, web pages, etc."""

    @property
    def parameters(self) -> Dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "URL to fetch (http or https)"},
                "format": {
                    "type": "string",
                    "enum": ["auto", "markdown", "text", "json", "raw"],
                    "description": "Output format: markdown (HTML to MD), text (plain text), json, raw",
                },
                "extract_main": {
                    "type": "boolean",
                    "description": "Try to extract main content only (skip navigation, ads)",
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum content length in characters (default: 50000)",
                },
                "selector": {
                    "type": "string",
                    "description": "CSS-like selector to extract specific content (e.g., 'article', 'main')",
                },
            },
            "required": ["url"],
        }

    async def execute(self, args: Dict[str, Any], ctx: ToolContext) -> ToolResult:
        url = args.get("url", "")
        format_type = args.get("format", "auto")
        extract_main = args.get("extract_main", True)
        max_length = args.get("max_length", 50000)
        selector = args.get("selector", "")

        if not url:
            return ToolResult(success=False, output="", error="URL is required")

        if not url.startswith(("http://", "https://")):
            return ToolResult(
                success=False, output="", error="Only http:// and https:// URLs are supported"
            )

        try:
            loop = asyncio.get_event_loop()
            result = await asyncio.wait_for(
                loop.run_in_executor(None, lambda: self._sync_fetch(url)),
                timeout=self.DEFAULT_TIMEOUT + 5,
            )

            if result.get("error"):
                return ToolResult(success=False, output="", error=result["error"])

            content = result["content"]
            content_type = result.get("content_type", "")

            # Process content based on format
            output = self._process_content(
                content, content_type, format_type, extract_main, selector
            )

            # Truncate if needed
            if len(output) > max_length:
                output = output[:max_length] + f"\n\n[Content truncated at {max_length} characters]"

            return ToolResult(
                success=True,
                output=output,
                metadata={
                    "url": url,
                    "content_type": content_type,
                    "original_size": len(content),
                    "output_size": len(output),
                    "format": format_type,
                },
            )

        except asyncio.TimeoutError:
            return ToolResult(
                success=False,
                output="",
                error=f"Request timed out after {self.DEFAULT_TIMEOUT} seconds",
            )
        except Exception as e:
            return ToolResult(success=False, output="", error=f"Fetch error: {str(e)}")

    def _sync_fetch(self, url: str) -> Dict[str, Any]:
        """Synchronous fetch implementation."""
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", self.USER_AGENT)
            req.add_header(
                "Accept", "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"
            )

            ctx = ssl.create_default_context()

            with urllib.request.urlopen(req, timeout=self.DEFAULT_TIMEOUT, context=ctx) as response:
                content_type = response.headers.get("Content-Type", "")

                # Read with size limit
                content = response.read(self.MAX_SIZE)

                # Check for truncation
                extra = response.read(1)
                truncated = bool(extra)

                # Decode
                charset = self._get_charset(content_type)
                try:
                    text = content.decode(charset, errors="replace")
                except (UnicodeDecodeError, LookupError):
                    text = content.decode("utf-8", errors="replace")

                if truncated:
                    text += f"\n\n[Content truncated at {self.MAX_SIZE} bytes]"

                return {"content": text, "content_type": content_type, "truncated": truncated}

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

        match = re.search(r"charset=([^\s;]+)", content_type, re.I)
        if match:
            return match.group(1).strip("\"'")

        return "utf-8"

    def _process_content(
        self, content: str, content_type: str, format_type: str, extract_main: bool, selector: str
    ) -> str:
        """Process content based on format type."""
        # Auto-detect format
        if format_type == "auto":
            if "application/json" in content_type:
                format_type = "json"
            elif "text/html" in content_type:
                format_type = "markdown"
            else:
                format_type = "raw"

        if format_type == "json":
            try:
                data = json.loads(content)
                return json.dumps(data, indent=2)
            except json.JSONDecodeError:
                return content

        elif format_type == "markdown":
            # Convert HTML to Markdown
            try:
                # Optionally extract main content first
                if extract_main:
                    content = self._extract_main_content(content, selector)

                parser = HTMLToMarkdown()
                parser.feed(content)
                return parser.get_markdown()
            except Exception:
                return content

        elif format_type == "text":
            # Extract plain text
            try:
                parser = TextExtractor()
                parser.feed(content)
                return parser.get_text()
            except Exception:
                return content

        else:  # raw
            return content

    def _extract_main_content(self, html: str, selector: str) -> str:
        """Extract main content from HTML."""
        # Simple extraction based on common patterns
        # Priority: article, main, .content, .post, #content, body

        patterns = [
            (r"<article[^>]*>(.*?)</article>", "article"),
            (r"<main[^>]*>(.*?)</main>", "main"),
            (r'<div[^>]*class="[^"]*content[^"]*"[^>]*>(.*?)</div>', ".content"),
            (r'<div[^>]*id="content"[^>]*>(.*?)</div>', "#content"),
        ]

        if selector:
            # Custom selector (simplified)
            if selector.startswith("."):
                class_name = selector[1:]
                patterns.insert(
                    0, (rf'<[^>]*class="[^"]*{class_name}[^"]*"[^>]*>(.*?)</\w+>', selector)
                )
            elif selector.startswith("#"):
                id_name = selector[1:]
                patterns.insert(0, (rf'<[^>]*id="{id_name}"[^>]*>(.*?)</\w+>', selector))
            else:
                patterns.insert(0, (rf"<{selector}[^>]*>(.*?)</{selector}>", selector))

        for pattern, name in patterns:
            match = re.search(pattern, html, re.DOTALL | re.IGNORECASE)
            if match:
                return match.group(1)

        # Return original if no main content found
        return html
