"""Independent packaged-skill extension fixture."""

from pathlib import Path

from superqode import Extension

extension = Extension(
    "example-skill",
    name="Example Skill Extension",
    version="0.1.0",
    description="Adds one Markdown review skill to Core.",
)
extension.skill(Path(__file__).with_name("SKILL.md"))
