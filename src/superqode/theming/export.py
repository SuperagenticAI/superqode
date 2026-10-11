"""Explicit interoperable palette export; no silent loss of native roles."""

from __future__ import annotations

from superqode.theming import BUILTINS, PI_MAP, native_document, palette_tokens

PI_SCHEMA_URL = "https://raw.githubusercontent.com/earendil-works/pi/main/packages/coding-agent/schemas/theme.schema.json"


def export_name(theme):
    """Built-in names are reserved on import; export a reusable copy instead."""
    return f"{theme.name}-copy" if theme.name in {*BUILTINS, "system", "auto"} else theme.name


def native_export_document(theme):
    return {**native_document(theme), "name": export_name(theme), "tokens": palette_tokens(theme)}


def pi_document(theme):
    """Export only recognized Pi properties using the effective readable colors."""
    tokens = palette_tokens(theme)
    return {
        "$schema": PI_SCHEMA_URL,
        "name": export_name(theme),
        "appearance": theme.appearance,
        "colors": {key: tokens[role] for key, role in PI_MAP.items()},
        "export": {
            "pageBg": tokens["export_bg"],
            "cardBg": tokens["export_card_bg"],
            "infoBg": tokens["export_info_bg"],
        },
    }


def pi_compatibility(theme):
    """Report what Pi cannot represent, without mislabelling it as invalid JSON."""
    from superqode.theming import theme_from_document

    theme_from_document(pi_document(theme))
    return {
        "valid": True,
        "format": "pi",
        "exported_name": export_name(theme),
        "mapped_roles": len(PI_MAP),
        "omitted_extension_colors": sorted(theme.extensions),
        "notes": [
            "Exports effective readable colors; source variables are flattened.",
            "SuperQode palette fields and extension colors have no exact Pi equivalent.",
        ],
    }
