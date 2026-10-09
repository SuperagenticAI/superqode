"""Pinned, offline palette catalog. Browsing never installs or runs code."""

from __future__ import annotations

from functools import lru_cache
import json
from pathlib import Path

from superqode import design_system as ds
from superqode.theming import ThemeError, load_theme_file, native_document

LIBRARY = Path(__file__).parents[1] / "data" / "theme-library"


@lru_cache(maxsize=1)
def catalog() -> dict:
    return json.loads((LIBRARY / "catalog.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=128)
def library_theme(name: str) -> ds.Theme:
    if name not in catalog()["themes"]:
        raise ThemeError(f"Unknown catalog theme: {name}. Browse with :theme browse")
    return load_theme_file(LIBRARY / f"{name}.json")


def theme_rows(query: str = "", *, installed_only: bool = False) -> list[dict]:
    """Cheap discovery metadata; load only the palette being previewed."""
    collection = catalog()
    names = list(ds.THEMES)
    if not installed_only:
        names.extend(name for name in collection["themes"] if name not in ds.THEMES)
    rows = []
    for name in names:
        theme = ds.THEMES.get(name)
        source = (
            (theme.source if theme.source in {"built-in", "bundled"} else "custom")
            if theme
            else collection["collection"]
        )
        row = {
            "name": name,
            "description": theme.description if theme else name.replace("-", " ").title(),
            "appearance": theme.appearance if theme else "dark",
            "source": source,
            "installed": theme is not None,
        }
        if name in collection["themes"]:
            row.update(
                collection=collection["collection"],
                version=collection["version"],
                license=collection["license"],
                url=f"{collection['repository']}/blob/{collection['revision']}/themes/{name}.json",
            )
        if not query or query.casefold().strip() in " ".join(map(str, row.values())).casefold():
            rows.append(row)
    return rows


def install_theme(name: str) -> str:
    """Install a known palette without overwriting user edits or changing selection."""
    from superqode.app.theme_bridge import import_theme

    if name in ds.THEMES:
        existing = ds.THEMES[name]
        if name in catalog()["themes"] and any(
            native_document(existing)[key] != native_document(library_theme(name))[key]
            for key in ("appearance", "colors", "tokens", "extensions")
        ):
            raise ThemeError(
                f"{name!r} is already installed with different colors; your theme was retained"
            )
        return name
    library_theme(name)  # Check the slug and validate before touching user files.
    return import_theme(LIBRARY / f"{name}.json")
