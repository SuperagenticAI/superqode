"""Tools contributed by the manifest-guard example."""

from collections import Counter

from superqode.tools.base import Tool, ToolContext, ToolResult


class ProjectSummaryTool(Tool):
    read_only = True

    @property
    def name(self) -> str:
        return "project_summary"

    @property
    def description(self) -> str:
        return "Summarize project file types without reading file contents."

    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, args: dict, ctx: ToolContext) -> ToolResult:
        counts = Counter(
            path.suffix.lower() or "[no extension]"
            for path in ctx.working_directory.rglob("*")
            if path.is_file() and ".git" not in path.parts
        )
        lines = [f"{suffix}: {count}" for suffix, count in counts.most_common(20)]
        return ToolResult(success=True, output="\n".join(lines) or "No project files found.")
