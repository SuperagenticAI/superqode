"""Theme colours must stay readable, and the brand must stay intact.

Two separate contracts, because a logo and a paragraph are not the same job:

* **Brand/display** colours (the SuperQode gradient) only ever render as large
  display text, so WCAG's 3.0:1 large-text threshold applies. These are the
  identity and must not be flattened for the sake of body-text rules.
* **Text** colours render prose, so primary and secondary text need 4.5:1, and
  decorative/tertiary text needs at least 3.0:1 to remain legible.

`muted` and `dim` previously measured 4.35:1 and 2.72:1, which is why this
exists: the drift was invisible until it was measured.
"""

from __future__ import annotations

import pytest

from superqode.app.constants import GRADIENT, RAINBOW


def brand_theme() -> dict[str, str]:
    """The SuperQode palette as defined, not the live (mutable) THEME dict.

    ``THEME`` is rewritten in place whenever a theme is applied, so reading it
    makes assertions depend on test order. The definition cannot drift.
    """
    from superqode import design_system as ds
    from superqode.app.theme_bridge import _palette_to_theme

    return _palette_to_theme(ds.get_theme("superqode").colors)


THEME = brand_theme()

#: WCAG 2.1 contrast minimums.
BODY_TEXT_MINIMUM = 4.5
LARGE_TEXT_MINIMUM = 3.0

#: Tokens that carry prose and must be comfortably readable.
READABLE_TEXT_TOKENS = ("text", "muted", "success", "error", "warning")

#: Tokens used for de-emphasised or decorative text (separators, hints).
DECORATIVE_TEXT_TOKENS = ("dim",)


def relative_luminance(color: str) -> float:
    """WCAG relative luminance for a ``#rrggbb`` colour."""
    value = color.lstrip("#")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def linearize(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    red, green, blue = (linearize(channel) for channel in channels)
    return 0.2126 * red + 0.7152 * green + 0.0722 * blue


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two colours."""
    first, second = relative_luminance(foreground), relative_luminance(background)
    lighter, darker = max(first, second), min(first, second)
    return (lighter + 0.05) / (darker + 0.05)


class TestContrastMath:
    def test_known_ratios(self):
        """Guard the calculation itself, so a bad formula cannot pass the suite."""
        assert contrast_ratio("#ffffff", "#000000") == pytest.approx(21.0, abs=0.01)
        assert contrast_ratio("#000000", "#000000") == pytest.approx(1.0, abs=0.01)


class TestTextRemainsReadable:
    @pytest.mark.parametrize("token", READABLE_TEXT_TOKENS)
    def test_prose_tokens_meet_body_text_contrast(self, token):
        ratio = contrast_ratio(THEME[token], THEME["bg"])

        assert ratio >= BODY_TEXT_MINIMUM, (
            f"THEME[{token!r}] = {THEME[token]} is {ratio:.2f}:1 on {THEME['bg']}, "
            f"below the {BODY_TEXT_MINIMUM}:1 needed for body text"
        )

    @pytest.mark.parametrize("token", DECORATIVE_TEXT_TOKENS)
    def test_decorative_tokens_stay_legible(self, token):
        ratio = contrast_ratio(THEME[token], THEME["bg"])

        assert ratio >= LARGE_TEXT_MINIMUM, (
            f"THEME[{token!r}] = {THEME[token]} is {ratio:.2f}:1, "
            "too faint to read even as secondary text"
        )

    def test_the_text_hierarchy_is_ordered(self):
        """Primary must outrank secondary, which must outrank decorative."""
        primary = contrast_ratio(THEME["text"], THEME["bg"])
        secondary = contrast_ratio(THEME["muted"], THEME["bg"])
        decorative = contrast_ratio(THEME["dim"], THEME["bg"])

        assert primary > secondary > decorative


class TestBrandIsPreserved:
    """The gradient is the identity. It must not be diluted by contrast work."""

    #: The signature purple-to-orange gradient, asserted verbatim.
    EXPECTED_GRADIENT = (
        "#7c3aed",
        "#b794f6",
        "#c084fc",
        "#ec4899",
        "#f97316",
        "#fb923c",
    )

    def test_the_signature_gradient_is_unchanged(self):
        assert tuple(GRADIENT) == self.EXPECTED_GRADIENT

    @pytest.mark.parametrize("color", EXPECTED_GRADIENT)
    def test_every_gradient_stop_is_visible_as_display_text(self, color):
        ratio = contrast_ratio(color, THEME["bg"])

        assert ratio >= LARGE_TEXT_MINIMUM, (
            f"brand colour {color} is {ratio:.2f}:1, invisible even as a logo"
        )

    def test_the_ui_accent_is_a_brand_colour(self):
        """The interface should look like the logo, not merely sit beside it."""
        assert THEME["purple"] in GRADIENT
        assert contrast_ratio(THEME["purple"], THEME["bg"]) >= BODY_TEXT_MINIMUM

    def test_accent_colours_are_not_greyed_out(self):
        """A regression that turned brand hues to grey would pass contrast."""
        for token in ("purple", "pink", "cyan"):
            value = THEME[token].lstrip("#")
            red, green, blue = (int(value[i : i + 2], 16) for i in (0, 2, 4))
            assert max(red, green, blue) - min(red, green, blue) > 40, (
                f"THEME[{token!r}] has lost its saturation"
            )


class TestPaletteHygiene:
    def test_rainbow_stops_are_display_safe(self):
        faint = [
            color for color in RAINBOW if contrast_ratio(color, THEME["bg"]) < LARGE_TEXT_MINIMUM
        ]

        assert faint == []

    def test_no_theme_colour_is_invisible(self):
        """Nothing in the palette should be effectively unreadable."""
        invisible = {
            token: value
            for token, value in THEME.items()
            if value.startswith("#")
            and token not in {"bg", "surface", "surface2", "border", "border_active", "code_bg"}
            and token != "user_prompt_bg"
            and contrast_ratio(value, THEME["bg"]) < LARGE_TEXT_MINIMUM
        }

        assert invisible == {}


class TestEveryThemeIsReadable:
    """The bridge maps a design-system palette onto THEME for every theme.

    The default SuperQode theme is the product's own identity and is held to
    the full contract. The ported themes (Tokyo Night, Monokai, Gruvbox) carry
    their upstream authors' palettes, which are genuinely low-contrast; that is
    recorded here rather than silently shipped, so the gap is a known trade-off
    instead of an accident.
    """

    #: Themes whose upstream palette does not meet the contract. Shrinking this
    #: set is an improvement; growing it silently is a regression.
    KNOWN_LOW_CONTRAST = {"tokyonight", "monokai", "gruvbox"}

    def _ratios(self, name):
        from superqode import design_system as ds
        from superqode.app.theme_bridge import _palette_to_theme

        mapped = _palette_to_theme(ds.get_theme(name).colors)
        background = mapped["bg"]
        return {
            token: contrast_ratio(mapped[token], background) for token in ("text", "muted", "dim")
        }

    def test_the_brand_theme_meets_the_full_contract(self):
        ratios = self._ratios("superqode")

        assert ratios["text"] >= BODY_TEXT_MINIMUM
        assert ratios["muted"] >= BODY_TEXT_MINIMUM
        assert ratios["dim"] >= LARGE_TEXT_MINIMUM

    def test_primary_text_is_readable_in_every_theme(self):
        """No theme, ported or not, may render its main text unreadably."""
        from superqode.app.theme_bridge import theme_names

        failures = {
            name: round(self._ratios(name)["text"], 2)
            for name in theme_names()
            if self._ratios(name)["text"] < BODY_TEXT_MINIMUM
        }

        assert failures == {}

    def test_the_low_contrast_set_has_not_grown(self):
        from superqode.app.theme_bridge import theme_names

        failing = {
            name
            for name in theme_names()
            if self._ratios(name)["muted"] < BODY_TEXT_MINIMUM
            or self._ratios(name)["dim"] < LARGE_TEXT_MINIMUM
        }

        assert failing <= self.KNOWN_LOW_CONTRAST, (
            f"new low-contrast themes: {sorted(failing - self.KNOWN_LOW_CONTRAST)}"
        )
