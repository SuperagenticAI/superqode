"""Model catalog browsing over the full models.dev dataset.

Shared by the ``superqode models`` CLI and the TUI ``:models`` command so both
present the same data. Builds on :mod:`models_dev` (the cached catalog) and
:mod:`dynamic` (to mark curated/recommended providers).
"""

from __future__ import annotations

from typing import Iterable, List, Optional

from .dynamic import is_curated_provider
from .models import ModelCapability, ModelInfo
from .models_dev import get_models_dev

# Short capability labels for compact display.
_CAP_LABELS = {
    ModelCapability.TOOLS: "tools",
    ModelCapability.VISION: "vision",
    ModelCapability.REASONING: "reason",
    ModelCapability.CODE: "code",
    ModelCapability.LONG_CONTEXT: "long",
    ModelCapability.JSON_MODE: "json",
    ModelCapability.STREAMING: "stream",
}

# Capability filter aliases accepted on the command line.
_CAP_ALIASES = {
    "tools": ModelCapability.TOOLS,
    "tool": ModelCapability.TOOLS,
    "vision": ModelCapability.VISION,
    "image": ModelCapability.VISION,
    "reasoning": ModelCapability.REASONING,
    "reason": ModelCapability.REASONING,
    "code": ModelCapability.CODE,
    "coder": ModelCapability.CODE,
    "long": ModelCapability.LONG_CONTEXT,
    "long_context": ModelCapability.LONG_CONTEXT,
    "json": ModelCapability.JSON_MODE,
}


async def load_models_catalog(force: bool = False) -> List[ModelInfo]:
    """Load the full catalog (network-refresh if needed). Async."""
    client = get_models_dev()
    await client.ensure_loaded()
    if force:
        await client.refresh(force=True)
    return client.get_all_models()


def load_models_catalog_cached() -> List[ModelInfo]:
    """Load the catalog from the on-disk cache only (sync, no network)."""
    client = get_models_dev()
    client.ensure_cache_loaded()
    return client.get_all_models()


def caps_str(model: ModelInfo) -> str:
    """Compact capability list, e.g. ``tools,vision,reason``."""
    labels = [_CAP_LABELS[c] for c in model.capabilities if c in _CAP_LABELS]
    # Keep the meaningful ones up front; drop the near-universal "stream".
    labels = [label for label in labels if label != "stream"]
    return ",".join(labels)


def parse_capability(value: Optional[str]) -> Optional[ModelCapability]:
    """Map a CLI capability string to a :class:`ModelCapability`, or ``None``."""
    if not value:
        return None
    return _CAP_ALIASES.get(value.strip().lower())


def filter_models(
    models: Iterable[ModelInfo],
    *,
    search: Optional[str] = None,
    provider: Optional[str] = None,
    capability: Optional[ModelCapability] = None,
    free: bool = False,
    max_input_price: Optional[float] = None,
    curated_only: bool = False,
    sort: str = "provider",
    limit: Optional[int] = 50,
) -> List[ModelInfo]:
    """Filter + sort the catalog. Pure (operates on the provided iterable)."""
    q = (search or "").strip().lower()
    out: List[ModelInfo] = []
    for m in models:
        if provider and m.provider != provider:
            continue
        if capability and capability not in m.capabilities:
            continue
        if free and not (m.input_price == 0 and m.output_price == 0):
            continue
        if max_input_price is not None and m.input_price > max_input_price:
            continue
        if curated_only and not is_curated_provider(m.provider):
            continue
        if q and q not in m.id.lower() and q not in m.name.lower() and q not in m.provider.lower():
            continue
        out.append(m)

    if sort == "price":
        out.sort(key=lambda m: (m.input_price, m.provider, m.id))
    elif sort == "context":
        out.sort(key=lambda m: (-m.context_window, m.provider, m.id))
    else:  # provider (default): curated first, then alphabetical
        out.sort(key=lambda m: (not is_curated_provider(m.provider), m.provider, m.id))

    if limit is not None and limit > 0:
        out = out[:limit]
    return out


def _fmt_price(value: float) -> str:
    if value == 0:
        return "free"
    if value < 1:
        return f"{value:.2f}"
    return f"{value:.1f}"


def _fmt_ctx(ctx: int) -> str:
    if ctx >= 1_000_000:
        return f"{ctx // 1_000_000}M"
    if ctx >= 1000:
        return f"{ctx // 1000}k"
    return str(ctx)


def render_models_table(models: List[ModelInfo], *, total: Optional[int] = None) -> str:
    """Plain aligned table; ``*`` marks curated/recommended providers."""
    if not models:
        return "No models match." if total is None else "No models match the filter."

    rows = []
    for m in models:
        marker = "*" if is_curated_provider(m.provider) else " "
        rows.append(
            (
                f"{marker}{m.provider}",
                m.id,
                _fmt_ctx(m.context_window),
                f"{_fmt_price(m.input_price)}/{_fmt_price(m.output_price)}",
                caps_str(m),
            )
        )

    headers = ("PROVIDER", "MODEL", "CTX", "$IN/$OUT", "CAPS")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    # Cap the model column so very long ids don't blow up the line.
    widths[1] = min(widths[1], 48)

    def fmt_row(cells):
        return "  ".join(str(c)[: widths[i]].ljust(widths[i]) for i, c in enumerate(cells))

    lines = [fmt_row(headers), fmt_row(tuple("-" * w for w in widths))]
    lines.extend(fmt_row(r) for r in rows)
    shown = len(rows)
    footer = f"\n{shown} model(s)"
    if total is not None and total != shown:
        footer += f" of {total} matched (use --limit to see more)"
    footer += "   * = curated / recommended provider"
    lines.append(footer)
    return "\n".join(lines)


def render_providers_table() -> str:
    """List every known provider; ``*`` marks curated/recommended ones."""
    client = get_models_dev()
    client.ensure_cache_loaded()
    providers = client.get_providers()
    if not providers:
        return "No provider data (run `superqode models --refresh` once with network)."

    rows = []
    for pid in sorted(providers, key=lambda p: (not is_curated_provider(p), p)):
        info = providers[pid]
        marker = "*" if is_curated_provider(pid) else " "
        model_count = len(client.get_models_for_provider(pid))
        env = ", ".join(info.env_vars[:2]) if info.env_vars else "-"
        rows.append((f"{marker}{pid}", str(model_count), env))

    headers = ("PROVIDER", "MODELS", "API KEY ENV")
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    def fmt_row(cells):
        return "  ".join(str(c).ljust(widths[i]) for i, c in enumerate(cells))

    lines = [fmt_row(headers), fmt_row(tuple("-" * w for w in widths))]
    lines.extend(fmt_row(r) for r in rows)
    lines.append(f"\n{len(rows)} provider(s)   * = curated / recommended")
    return "\n".join(lines)


__all__ = [
    "load_models_catalog",
    "load_models_catalog_cached",
    "filter_models",
    "parse_capability",
    "caps_str",
    "render_models_table",
    "render_providers_table",
]
