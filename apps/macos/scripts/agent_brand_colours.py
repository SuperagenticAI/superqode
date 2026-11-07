"""Official brand colours for bundled ACP registry glyphs.

Only marks whose official logo is coloured are listed. The registry paths are
kept as they are; only their fills change. Every other glyph stays a monochrome
template so it follows light and dark appearances.
"""

import re

# Colours come from each owner's own site or brand page, cross-checked with
# simple-icons where it lists the mark.
SOURCES = {
    "antigravity-acp": (
        "official full-color icon",
        "https://antigravity.google/assets/image/brand/antigravity-icon__full-color.png",
    ),
    "claude-acp": ("#D97757", "https://claude.ai (simple-icons Claude, Claude Code)"),
    "cortex-code": ("#29B5E8", "https://www.snowflake.com/brand-guidelines/"),
    "gemini": (
        "#3186FF, #08B962, #F94543, #FABC12",
        "https://gemini.google.com (current Gemini spark)",
    ),
    "junie": ("#48E054", "https://www.jetbrains.com/junie/"),
    "mistral-vibe": ("#FFAF01, #FF8204, #FA500F, #E61300, #C4001D", "https://mistral.ai/brand"),
    "qwen-code": ("#6950EF", "https://qwen.ai (simple-icons QWen)"),
}

# The registry glyph is monochrome. These identities keep a separate official
# full-colour file in the asset catalog, so a registry import must not replace it.
PRESERVE_COLOUR_ASSETS = {"antigravity-acp"}

SOLID = {
    "claude-acp": "#D97757",
    "cortex-code": "#29B5E8",
    "junie": "#48E054",
    "qwen-code": "#6950EF",
}

# Mistral's pixel M is striped by row, top to bottom, as on mistral.ai/brand.
MISTRAL_ROWS = [
    (5.3, "#FFAF01"),
    (8.8, "#FF8204"),
    (12.2, "#FA500F"),
    (15.7, "#E61300"),
    (19.1, "#C4001D"),
]

GEMINI_DEFS = (
    "<defs>"
    '<linearGradient id="g0" gradientUnits="userSpaceOnUse" x1="7" y1="15.5" x2="11" y2="12">'
    '<stop stop-color="#08B962"/><stop offset="1" stop-color="#08B962" stop-opacity="0"/></linearGradient>'
    '<linearGradient id="g1" gradientUnits="userSpaceOnUse" x1="8" y1="5.5" x2="11.5" y2="11">'
    '<stop stop-color="#F94543"/><stop offset="1" stop-color="#F94543" stop-opacity="0"/></linearGradient>'
    '<linearGradient id="g2" gradientUnits="userSpaceOnUse" x1="3.5" y1="13.5" x2="17.5" y2="12">'
    '<stop stop-color="#FABC12"/><stop offset=".46" stop-color="#FABC12" stop-opacity="0"/></linearGradient>'
    "</defs>"
)


def _mistral(content: str) -> str:
    def row(match: re.Match) -> str:
        top = float(match.group(2))
        colour = min(MISTRAL_ROWS, key=lambda item: abs(item[0] - top))[1]
        return match.group(1) + match.group(2) + match.group(3).replace("#000000", colour)

    return re.sub(r'(<path d="M[\d.]+ )([\d.]+)(H[^"]*"[^>]*>)', row, content)


def _gemini(content: str) -> str:
    path = re.search(r'<path fill="#000000" d="([^"]+)"\s*/>', content)
    if not path:
        raise ValueError("Unexpected Gemini glyph")
    d = path.group(1)
    layers = "".join(
        f'<path fill="{fill}" d="{d}"/>' for fill in ("#3186FF", "url(#g0)", "url(#g1)", "url(#g2)")
    )
    return content.replace(path.group(0), GEMINI_DEFS + layers)


def coloured(identity: str):
    """Return a recolour function for a brand-coloured glyph, or None."""
    if identity in SOLID:
        return lambda content: content.replace("#000000", SOLID[identity])
    return {"mistral-vibe": _mistral, "gemini": _gemini}.get(identity)
