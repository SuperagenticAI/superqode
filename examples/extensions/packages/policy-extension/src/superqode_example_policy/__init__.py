"""Independent policy-only extension fixture."""

from superqode import Extension

extension = Extension(
    "example-policy",
    name="Example Policy Extension",
    version="0.1.0",
    description="Denies git push and observes completed tools.",
)

extension.permission(
    tool="bash",
    argument="command",
    pattern="git push*",
    action="deny",
)


@extension.hook("after_tool_call", name="example-policy:audit")
def audit_completed_tool(_ctx, _name: str = "", _arguments=None, _result=None) -> None:
    """Reference observer hook; intentionally has no external side effects."""
