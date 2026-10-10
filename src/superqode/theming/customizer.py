"""Editable colors become a portable native theme, with live contrast checks."""

from __future__ import annotations

from copy import deepcopy

from superqode import design_system as ds
from superqode.theming import (
    blend,
    contrast,
    luminance,
    native_document,
    palette_tokens,
    resolve_colors,
    theme_from_document,
)


def customize_theme(
    base: ds.Theme, name: str, *, accent: str, background: str, surface: str, text: str
) -> tuple[ds.Theme, float, float]:
    colors = resolve_colors(
        {"accent": accent, "bg": background, "surface": surface, "text": text}, {}, base.appearance
    )
    accent, background, surface, text = (colors[key] for key in ("accent", "bg", "surface", "text"))
    # native_document exposes the source token/extension dictionaries. A live
    # editor must own a copy, including when its base is a bundled palette.
    document = deepcopy(native_document(base))
    document.update(
        name=name,
        description=f"Customized from {base.name}",
        appearance="light" if luminance(background) > 0.5 else "dark",
    )
    document["colors"].update(
        {
            **{
                key: accent
                for key in (
                    "primary",
                    "primary_dark",
                    "primary_bright",
                    "primary_light",
                    "primary_glow",
                    "border_focus",
                )
            },
            **{key: text for key in ("text_primary", "text_secondary")},
            "text_muted": blend(text, background, 0.25),
            "text_dim": blend(text, background, 0.4),
            "bg_void": background,
            "bg_surface": surface,
            "bg_elevated": blend(surface, text, 0.03),
            "bg_hover": blend(surface, text, 0.07),
            "bg_active": blend(surface, text, 0.12),
            "code_bg": surface,
        }
    )
    tokens = document["tokens"]
    tokens.update(
        purple=accent,
        border_active=accent,
        bg=background,
        surface=surface,
        surface2=document["colors"]["bg_elevated"],
        hover=document["colors"]["bg_hover"],
        active=document["colors"]["bg_active"],
        user_bg=background,
        custom_bg=surface,
        code_bg=surface,
        tool_pending_bg=surface,
        tool_success_bg=surface,
        tool_error_bg=surface,
        selected_bg=document["colors"]["bg_active"],
        search_bg=document["colors"]["bg_active"],
        export_bg=background,
        export_card_bg=surface,
        export_info_bg=surface,
    )
    for key in (
        "text",
        "user_text",
        "custom_text",
        "custom_label",
        "tool_title",
        "tool_output",
        "md_heading",
        "md_code_block",
        "selected_text",
        "search_text",
    ):
        tokens[key] = text
    tokens.update(muted=document["colors"]["text_muted"], dim=document["colors"]["text_dim"])
    theme = theme_from_document(document)
    palette = palette_tokens(theme)
    backgrounds = [palette[key] for key in ("bg", "surface", "surface2")]
    requested = min(contrast(text, background) for background in backgrounds)
    rendered = min(contrast(palette["text"], background) for background in backgrounds)
    return theme, requested, rendered
