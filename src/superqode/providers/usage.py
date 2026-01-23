"""
SuperQode Usage Tracking - Token and cost tracking.

Tracks token usage and estimated cost per session.

Features:
- Per-session token tracking
- Cost estimation
- Provider-specific pricing
- History storage

Usage:
    tracker = UsageTracker()
    tracker.set_provider("anthropic", "claude-sonnet-4")
    tracker.add_usage(1000, 500)  # input, output tokens
    print(tracker.get_summary())
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple


# ============================================================================
# DATA CLASSES
# ============================================================================


@dataclass
class UsageEntry:
    """A single usage entry."""

    timestamp: str
    input_tokens: int
    output_tokens: int
    cost: float
    model: str = ""

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class SessionUsage:
    """Usage for a single session."""

    session_id: str
    provider: str
    model: str
    started_at: str

    # Totals
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0.0

    # Messages
    message_count: int = 0
    tool_count: int = 0

    # History
    entries: List[UsageEntry] = field(default_factory=list)

    @property
    def total_tokens(self) -> int:
        return self.total_input_tokens + self.total_output_tokens

    def add_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cost: float = 0.0,
    ) -> None:
        """Add usage to session."""
        self.total_input_tokens += input_tokens
        self.total_output_tokens += output_tokens
        self.total_cost += cost
        self.message_count += 1

        self.entries.append(
            UsageEntry(
                timestamp=datetime.now().isoformat(),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cost=cost,
                model=self.model,
            )
        )

    def add_tool_call(self) -> None:
        """Record a tool call."""
        self.tool_count += 1


# ============================================================================
# USAGE TRACKER
# ============================================================================


class UsageTracker:
    """
    Tracks token usage and cost across sessions.
    """

    def __init__(self):
        self._current_session: Optional[SessionUsage] = None
        self._history: List[SessionUsage] = []
        self._config_path = Path.home() / ".superqode" / "usage.json"

        # Load history
        self._load_history()

    def _load_history(self) -> None:
        """Load usage history from file."""
        try:
            if self._config_path.exists():
                data = json.loads(self._config_path.read_text())
                # Only load summary, not full entries
                self._history = []
        except Exception:
            pass

    def _save_history(self) -> None:
        """Save usage history to file."""
        try:
            self._config_path.parent.mkdir(parents=True, exist_ok=True)

            # Save current session summary
            if self._current_session:
                data = {
                    "last_session": {
                        "provider": self._current_session.provider,
                        "model": self._current_session.model,
                        "total_tokens": self._current_session.total_tokens,
                        "total_cost": self._current_session.total_cost,
                        "messages": self._current_session.message_count,
                    },
                    "total_all_time": {
                        "tokens": sum(s.total_tokens for s in self._history)
                        + self._current_session.total_tokens,
                        "cost": sum(s.total_cost for s in self._history)
                        + self._current_session.total_cost,
                    },
                }
                self._config_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def start_session(
        self,
        provider: str,
        model: str,
        session_id: str = None,
    ) -> None:
        """Start a new usage session."""
        # Save previous session
        if self._current_session:
            self._history.append(self._current_session)

        self._current_session = SessionUsage(
            session_id=session_id or datetime.now().strftime("%Y%m%d_%H%M%S"),
            provider=provider,
            model=model,
            started_at=datetime.now().isoformat(),
        )

    def set_provider(self, provider: str, model: str) -> None:
        """Set or update the current provider/model."""
        if self._current_session:
            self._current_session.provider = provider
            self._current_session.model = model
        else:
            self.start_session(provider, model)

    def add_usage(
        self,
        input_tokens: int,
        output_tokens: int,
        cost: float = None,
    ) -> None:
        """Add token usage."""
        if not self._current_session:
            self.start_session("unknown", "unknown")

        # Calculate cost if not provided
        if cost is None:
            cost = self._estimate_cost(input_tokens, output_tokens)

        self._current_session.add_usage(input_tokens, output_tokens, cost)
        self._save_history()

    def add_tool_call(self) -> None:
        """Record a tool call."""
        if self._current_session:
            self._current_session.add_tool_call()

    def _estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost based on current provider/model."""
        if not self._current_session:
            return 0.0

        try:
            from superqode.providers.models import get_model_info

            info = get_model_info(self._current_session.provider, self._current_session.model)
            if info:
                return info.estimate_cost(input_tokens, output_tokens)
        except Exception:
            pass

        return 0.0

    def get_session_usage(self) -> Optional[SessionUsage]:
        """Get current session usage."""
        return self._current_session

    def get_summary(self) -> Dict[str, any]:
        """Get usage summary."""
        if not self._current_session:
            return {
                "connected": False,
                "provider": "",
                "model": "",
                "tokens": 0,
                "cost": 0.0,
                "messages": 0,
                "tools": 0,
            }

        s = self._current_session
        return {
            "connected": True,
            "provider": s.provider,
            "model": s.model,
            "tokens": s.total_tokens,
            "input_tokens": s.total_input_tokens,
            "output_tokens": s.total_output_tokens,
            "cost": s.total_cost,
            "messages": s.message_count,
            "tools": s.tool_count,
        }

    def get_display_text(self) -> str:
        """Get formatted display text for status bar."""
        if not self._current_session:
            return "Not connected"

        s = self._current_session

        # Format tokens
        if s.total_tokens >= 1000:
            tokens_str = f"{s.total_tokens / 1000:.1f}K"
        else:
            tokens_str = str(s.total_tokens)

        # Format cost
        if s.total_cost >= 0.01:
            cost_str = f"${s.total_cost:.2f}"
        elif s.total_cost > 0:
            cost_str = f"${s.total_cost:.4f}"
        else:
            cost_str = "Free"

        return f"{s.provider}/{s.model} | {tokens_str} tokens ({cost_str})"

    def get_compact_display(self) -> Tuple[str, str, str]:
        """Get compact display parts: (provider_model, tokens, cost)."""
        if not self._current_session:
            return ("", "", "")

        s = self._current_session

        # Provider/model (shortened)
        provider_model = f"{s.provider[:4]}/{s.model.split('-')[0]}"

        # Tokens
        if s.total_tokens >= 1000:
            tokens = f"{s.total_tokens // 1000}K"
        else:
            tokens = str(s.total_tokens)

        # Cost
        if s.total_cost >= 0.01:
            cost = f"${s.total_cost:.2f}"
        elif s.total_cost > 0:
            cost = f"${s.total_cost:.3f}"
        else:
            cost = ""

        return (provider_model, tokens, cost)

    def reset(self) -> None:
        """Reset current session."""
        if self._current_session:
            self._current_session.total_input_tokens = 0
            self._current_session.total_output_tokens = 0
            self._current_session.total_cost = 0.0
            self._current_session.message_count = 0
            self._current_session.tool_count = 0
            self._current_session.entries.clear()


# ============================================================================
# GLOBAL INSTANCE
# ============================================================================

_usage_tracker: Optional[UsageTracker] = None


def get_usage_tracker() -> UsageTracker:
    """Get the global usage tracker instance."""
    global _usage_tracker
    if _usage_tracker is None:
        _usage_tracker = UsageTracker()
    return _usage_tracker


# ============================================================================
# EXPORTS
# ============================================================================

__all__ = [
    "UsageEntry",
    "SessionUsage",
    "UsageTracker",
    "get_usage_tracker",
]
