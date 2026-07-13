"""Version-two upgrade fixture for the independent tool extension."""

from superqode import Extension

EXTENSION_VERSION = "0.2.0"

extension = Extension(
    "example-tool",
    name="Example Tool Extension",
    version=EXTENSION_VERSION,
    description="Upgraded typed tool with word accounting.",
)


@extension.tool(description="Count lines, words and characters in supplied text.", read_only=True)
def example_line_count(text: str) -> dict[str, int | str]:
    return {
        "lines": len(text.splitlines()),
        "words": len(text.split()),
        "characters": len(text),
        "extension_version": EXTENSION_VERSION,
    }
