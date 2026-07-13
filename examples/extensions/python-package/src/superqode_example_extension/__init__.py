"""Reference Python-package extension for the SuperQode Core harness."""

from superqode import Extension, ExtensionContext

extension = Extension(
    "python-package-example",
    name="Python Package Example",
    version="0.1.0",
    description="Typed tools, commands, hooks and context from a Python package.",
)


@extension.tool(description="Count whitespace-separated words in text.", read_only=True)
def word_count(text: str) -> dict[str, int]:
    return {"words": len(text.split()), "characters": len(text)}


@extension.command("extension-info", description="Show this extension's active project.")
def extension_info(_args: str, context: ExtensionContext) -> str:
    return f"Python Package Example is active for {context.root}"


@extension.before_tool
def observe_tool(_ctx, _name: str = "", _arguments=None) -> None:
    """Reference observer hook; real packages can audit or return a decision."""


@extension.context
def project_context(context: ExtensionContext) -> str:
    return f"The active extension workspace is `{context.root}`."
