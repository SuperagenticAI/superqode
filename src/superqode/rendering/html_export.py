"""Export a conversation transcript to a standalone HTML file.

Dependency-free: turns the ConversationLog message record
``[(role, text, agent), ...]`` into a self-contained, styled HTML document that
keeps SuperQode's dark/quantum look. Lightweight markdown is supported (fenced
code blocks, headings, bold/inline code, bullet lists) — enough for clean,
shareable transcripts without pulling in a markdown dependency.
"""

from __future__ import annotations

import html
import re
from datetime import datetime

_ROLE_META = {
    "user": ("you", "#22d3ee"),
    "agent": ("agent", "#a855f7"),
    "assistant": ("agent", "#a855f7"),
    "system": ("system", "#71717a"),
    "error": ("error", "#f43f5e"),
    "success": ("done", "#22c55e"),
    "info": ("info", "#71717a"),
    "shell": ("shell", "#fbbf24"),
}

_INLINE_CODE = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")


def _inline(text: str) -> str:
    """Escape a line and apply inline markdown (code, bold)."""
    escaped = html.escape(text)
    escaped = _INLINE_CODE.sub(r"<code>\1</code>", escaped)
    escaped = _BOLD.sub(r"<strong>\1</strong>", escaped)
    return escaped


def _render_markdown(text: str) -> str:
    """Convert a small, safe subset of markdown to HTML."""
    lines = text.split("\n")
    out: list[str] = []
    in_code = False
    code_buf: list[str] = []
    in_list = False

    def _close_list() -> None:
        nonlocal in_list
        if in_list:
            out.append("</ul>")
            in_list = False

    for line in lines:
        fence = line.strip().startswith("```")
        if fence:
            if in_code:
                out.append(f"<pre><code>{html.escape(chr(10).join(code_buf))}</code></pre>")
                code_buf = []
                in_code = False
            else:
                _close_list()
                in_code = True
            continue
        if in_code:
            code_buf.append(line)
            continue

        stripped = line.strip()
        if not stripped:
            _close_list()
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            _close_list()
            level = len(heading.group(1))
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        bullet = re.match(r"^[-*]\s+(.*)$", stripped)
        if bullet:
            if not in_list:
                out.append("<ul>")
                in_list = True
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            continue

        _close_list()
        out.append(f"<p>{_inline(stripped)}</p>")

    if in_code:  # unterminated fence — still show the content
        out.append(f"<pre><code>{html.escape(chr(10).join(code_buf))}</code></pre>")
    _close_list()
    return "\n".join(out)


_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  body {{ background:#000; color:#e4e4e7; font-family:-apple-system,BlinkMacSystemFont,
    "Segoe UI",Roboto,sans-serif; margin:0; padding:2rem; line-height:1.5; }}
  .wrap {{ max-width:880px; margin:0 auto; }}
  header {{ border-bottom:1px solid #27272a; padding-bottom:1rem; margin-bottom:1.5rem; }}
  h1.title {{ font-size:1.4rem; margin:0; color:#a855f7; }}
  .meta {{ color:#71717a; font-size:.85rem; margin-top:.25rem; }}
  .msg {{ margin:0 0 1.25rem; padding:.75rem 1rem; background:#0a0a0a;
    border:1px solid #1a1a1a; border-radius:8px; }}
  .msg .role {{ font-weight:700; font-size:.8rem; text-transform:uppercase;
    letter-spacing:.05em; margin-bottom:.4rem; }}
  .msg pre {{ background:#050505; border:1px solid #27272a; border-radius:6px;
    padding:.75rem; overflow-x:auto; }}
  .msg code {{ background:#1a1a1a; padding:.1rem .3rem; border-radius:4px;
    font-size:.9em; }}
  .msg pre code {{ background:none; padding:0; }}
  .msg h1,.msg h2,.msg h3 {{ color:#d4d4d8; }}
  .msg p {{ margin:.4rem 0; }}
  footer {{ color:#52525b; font-size:.8rem; margin-top:2rem; text-align:center; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1 class="title">{title}</h1>
  <div class="meta">{meta}</div>
</header>
{body}
<footer>Exported from SuperQode</footer>
</div>
</body>
</html>
"""


def render_transcript_html(
    messages: list[tuple[str, str, str]],
    *,
    title: str = "SuperQode Transcript",
) -> str:
    """Render a list of ``(role, text, agent)`` messages to an HTML document."""
    blocks: list[str] = []
    for role, text, agent in messages:
        if role in ("info",):  # skip transient UI chatter
            continue
        label, color = _ROLE_META.get(role, (role or "msg", "#a1a1aa"))
        if role in ("agent", "assistant") and agent:
            label = agent
        if role in ("agent", "assistant", "system", "error"):
            content = _render_markdown(str(text))
        else:
            content = f"<pre>{html.escape(str(text))}</pre>"
        blocks.append(
            f'<div class="msg"><div class="role" style="color:{color}">'
            f"{html.escape(label)}</div>{content}</div>"
        )

    meta = datetime.now().strftime("%Y-%m-%d %H:%M")
    body = "\n".join(blocks) if blocks else '<p class="meta">Empty transcript.</p>'
    return _TEMPLATE.format(title=html.escape(title), meta=meta, body=body)
