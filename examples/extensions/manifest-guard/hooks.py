"""Lifecycle hooks contributed by the manifest-guard example."""

import logging

logger = logging.getLogger("manifest_guard")


def audit_tool(ctx, name: str = "", arguments=None, result=None) -> None:
    """Record bounded tool outcome metadata without storing tool arguments."""
    logger.info(
        "session=%s iteration=%s tool=%s success=%s",
        ctx.session_id,
        ctx.iteration,
        name,
        getattr(result, "success", None),
    )
