"""Independent tool-only extension fixture."""

from superqode import Extension

EXTENSION_VERSION = "0.1.0"

extension = Extension(
    "example-tool",
    name="Example Tool Extension",
    version=EXTENSION_VERSION,
    description="Adds one typed, read-only tool to Core.",
)


@extension.tool(description="Count lines and characters in supplied text.", read_only=True)
def example_line_count(text: str) -> dict[str, int | str]:
    return {
        "lines": len(text.splitlines()),
        "characters": len(text),
        "extension_version": EXTENSION_VERSION,
    }
