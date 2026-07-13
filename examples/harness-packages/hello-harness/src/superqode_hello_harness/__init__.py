"""Smallest useful independently installed SuperQode harness."""


async def run(message, session):
    """Return a deterministic response while demonstrating session access."""
    return f"hello from {session.harness_id}: {message.content}"
