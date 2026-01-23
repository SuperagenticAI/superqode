"""
Enhanced Permission System - Rule-Based Access Control.

Provides granular control over what operations agents can perform:
- File access patterns with wildcards
- Tool-specific permissions
- Directory-scoped rules
- Allow/Deny/Ask actions
- Optimized for SuperQode's multi-agent QE workflow
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple
import hashlib


class PermissionAction(Enum):
    """Action to take when permission rule matches."""

    ALLOW = "allow"  # Automatically allow
    DENY = "deny"  # Automatically deny
    ASK = "ask"  # Ask user for permission
    ALLOW_SESSION = "allow_session"  # Allow for this session only


class PermissionScope(Enum):
    """Scope of the permission rule."""

    FILE_READ = "file_read"
    FILE_WRITE = "file_write"
    FILE_DELETE = "file_delete"
    DIRECTORY_CREATE = "directory_create"
    DIRECTORY_DELETE = "directory_delete"
    SHELL_EXECUTE = "shell_execute"
    NETWORK_ACCESS = "network_access"
    TOOL_CALL = "tool_call"


@dataclass
class PermissionRule:
    """A single permission rule.

    Rules are matched in order of specificity:
    1. Exact path matches
    2. Glob patterns
    3. Directory prefixes
    4. Default rules
    """

    pattern: str  # Glob pattern or exact path
    scope: PermissionScope  # What operation this applies to
    action: PermissionAction  # What to do when matched
    priority: int = 0  # Higher = checked first
    reason: str = ""  # Explanation for the rule
    expires_at: Optional[datetime] = None  # Optional expiration
    created_by: str = ""  # Who created this rule

    @property
    def is_expired(self) -> bool:
        """Check if rule has expired."""
        if self.expires_at is None:
            return False
        return datetime.now() > self.expires_at

    def matches(self, path: str, scope: PermissionScope) -> bool:
        """Check if this rule matches the given path and scope."""
        if self.scope != scope:
            return False

        if self.is_expired:
            return False

        # Exact match
        if self.pattern == path:
            return True

        # Glob pattern
        if fnmatch.fnmatch(path, self.pattern):
            return True

        # Directory prefix (pattern ends with /**)
        if self.pattern.endswith("/**"):
            prefix = self.pattern[:-3]
            if path.startswith(prefix):
                return True

        return False

    def to_dict(self) -> dict:
        return {
            "pattern": self.pattern,
            "scope": self.scope.value,
            "action": self.action.value,
            "priority": self.priority,
            "reason": self.reason,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
            "created_by": self.created_by,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PermissionRule":
        return cls(
            pattern=data["pattern"],
            scope=PermissionScope(data["scope"]),
            action=PermissionAction(data["action"]),
            priority=data.get("priority", 0),
            reason=data.get("reason", ""),
            expires_at=datetime.fromisoformat(data["expires_at"])
            if data.get("expires_at")
            else None,
            created_by=data.get("created_by", ""),
        )


@dataclass
class PermissionRequest:
    """A request for permission."""

    id: str
    scope: PermissionScope
    path: str
    tool_name: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    agent_name: str = ""
    timestamp: datetime = field(default_factory=datetime.now)
    context: str = ""  # Why this permission is needed

    @property
    def display_name(self) -> str:
        """Get human-readable name for the request."""
        if self.tool_name:
            return f"{self.tool_name}: {self.path}"
        return f"{self.scope.value}: {self.path}"


@dataclass
class PermissionDecision:
    """A recorded permission decision."""

    request_id: str
    action: PermissionAction
    decided_by: str  # "user", "rule:pattern", "default"
    timestamp: datetime = field(default_factory=datetime.now)
    rule_pattern: Optional[str] = None


class PermissionManager:
    """
    Manages permission rules and decisions.

    Provides rule-based access control with wildcard support,
    session-scoped permissions, and decision history.

    Usage:
        manager = PermissionManager()

        # Add rules
        manager.add_rule(PermissionRule(
            pattern="src/**",
            scope=PermissionScope.FILE_WRITE,
            action=PermissionAction.ALLOW,
        ))
        manager.add_rule(PermissionRule(
            pattern=".env*",
            scope=PermissionScope.FILE_READ,
            action=PermissionAction.DENY,
            reason="Sensitive environment files",
        ))

        # Check permission
        result = manager.check_permission(
            PermissionRequest(
                id="req-1",
                scope=PermissionScope.FILE_WRITE,
                path="src/main.py",
            )
        )

        if result.action == PermissionAction.ASK:
            # Ask user and record decision
            manager.record_decision(...)
    """

    # Default rules (lowest priority)
    DEFAULT_RULES = [
        # Deny sensitive files by default
        PermissionRule(
            "**/.env*", PermissionScope.FILE_READ, PermissionAction.DENY, -100, "Environment files"
        ),
        PermissionRule(
            "**/*.pem", PermissionScope.FILE_READ, PermissionAction.DENY, -100, "Private keys"
        ),
        PermissionRule(
            "**/*.key", PermissionScope.FILE_READ, PermissionAction.DENY, -100, "Private keys"
        ),
        PermissionRule(
            "**/credentials*", PermissionScope.FILE_READ, PermissionAction.DENY, -100, "Credentials"
        ),
        PermissionRule(
            "**/secrets*", PermissionScope.FILE_READ, PermissionAction.DENY, -100, "Secrets"
        ),
        # Deny dangerous directories
        PermissionRule(
            "**/.git/**", PermissionScope.FILE_WRITE, PermissionAction.DENY, -100, "Git internals"
        ),
        PermissionRule(
            "**/node_modules/**",
            PermissionScope.FILE_WRITE,
            PermissionAction.DENY,
            -100,
            "Dependencies",
        ),
        # Allow reading most source files
        PermissionRule(
            "**/*.py", PermissionScope.FILE_READ, PermissionAction.ALLOW, -50, "Python source"
        ),
        PermissionRule(
            "**/*.js", PermissionScope.FILE_READ, PermissionAction.ALLOW, -50, "JavaScript source"
        ),
        PermissionRule(
            "**/*.ts", PermissionScope.FILE_READ, PermissionAction.ALLOW, -50, "TypeScript source"
        ),
        PermissionRule(
            "**/*.go", PermissionScope.FILE_READ, PermissionAction.ALLOW, -50, "Go source"
        ),
        PermissionRule(
            "**/*.rs", PermissionScope.FILE_READ, PermissionAction.ALLOW, -50, "Rust source"
        ),
        # Default to ask for everything else
        PermissionRule(
            "**", PermissionScope.FILE_WRITE, PermissionAction.ASK, -1000, "Default write"
        ),
        PermissionRule(
            "**", PermissionScope.FILE_DELETE, PermissionAction.ASK, -1000, "Default delete"
        ),
        PermissionRule(
            "**", PermissionScope.SHELL_EXECUTE, PermissionAction.ASK, -1000, "Default shell"
        ),
    ]

    def __init__(
        self,
        rules_file: Optional[Path] = None,
        include_defaults: bool = True,
    ):
        self._rules: List[PermissionRule] = []
        self._session_rules: List[PermissionRule] = []  # Session-only rules
        self._decisions: List[PermissionDecision] = []
        self._rules_file = rules_file

        # Load default rules
        if include_defaults:
            self._rules.extend(self.DEFAULT_RULES)

        # Load saved rules
        if rules_file and rules_file.exists():
            self._load_rules()

    def add_rule(
        self,
        rule: PermissionRule,
        session_only: bool = False,
    ) -> None:
        """Add a permission rule.

        Args:
            rule: The rule to add
            session_only: If True, rule is cleared at session end
        """
        if session_only:
            self._session_rules.append(rule)
        else:
            self._rules.append(rule)

        # Sort by priority (highest first)
        self._rules.sort(key=lambda r: r.priority, reverse=True)
        self._session_rules.sort(key=lambda r: r.priority, reverse=True)

    def remove_rule(self, pattern: str, scope: PermissionScope) -> bool:
        """Remove a rule by pattern and scope."""
        for rules_list in [self._rules, self._session_rules]:
            for rule in rules_list[:]:
                if rule.pattern == pattern and rule.scope == scope:
                    rules_list.remove(rule)
                    return True
        return False

    def check_permission(self, request: PermissionRequest) -> PermissionDecision:
        """
        Check if a permission request should be allowed.

        Returns a decision based on matching rules.
        """
        # Check session rules first (highest priority)
        for rule in self._session_rules:
            if rule.matches(request.path, request.scope):
                return PermissionDecision(
                    request_id=request.id,
                    action=rule.action,
                    decided_by=f"session_rule:{rule.pattern}",
                    rule_pattern=rule.pattern,
                )

        # Check persistent rules
        for rule in self._rules:
            if rule.matches(request.path, request.scope):
                return PermissionDecision(
                    request_id=request.id,
                    action=rule.action,
                    decided_by=f"rule:{rule.pattern}",
                    rule_pattern=rule.pattern,
                )

        # Default: ask
        return PermissionDecision(
            request_id=request.id,
            action=PermissionAction.ASK,
            decided_by="default",
        )

    def record_decision(
        self,
        request: PermissionRequest,
        action: PermissionAction,
        create_rule: bool = False,
        rule_scope: str = "exact",  # "exact", "directory", "extension"
    ) -> None:
        """
        Record a permission decision (from user).

        Args:
            request: The original request
            action: The action taken
            create_rule: If True, create a rule for future requests
            rule_scope: How broad to make the rule
        """
        decision = PermissionDecision(
            request_id=request.id,
            action=action,
            decided_by="user",
        )
        self._decisions.append(decision)

        # Create rule for future requests if requested
        if create_rule and action in (PermissionAction.ALLOW, PermissionAction.DENY):
            pattern = self._create_pattern(request.path, rule_scope)

            rule = PermissionRule(
                pattern=pattern,
                scope=request.scope,
                action=action,
                priority=100,  # User rules have high priority
                created_by="user",
            )

            # Session-scoped for ALLOW_SESSION
            session_only = action == PermissionAction.ALLOW_SESSION
            self.add_rule(rule, session_only=session_only)

    def _create_pattern(self, path: str, scope: str) -> str:
        """Create a pattern from a path based on scope."""
        if scope == "exact":
            return path
        elif scope == "directory":
            # Match all files in the same directory
            dir_path = str(Path(path).parent)
            return f"{dir_path}/**"
        elif scope == "extension":
            # Match all files with same extension
            ext = Path(path).suffix
            return f"**/*{ext}"
        else:
            return path

    def allow_all(
        self,
        pattern: str,
        scope: PermissionScope,
        session_only: bool = True,
    ) -> None:
        """Add an allow-all rule for a pattern."""
        self.add_rule(
            PermissionRule(
                pattern=pattern,
                scope=scope,
                action=PermissionAction.ALLOW,
                priority=200,  # High priority
                created_by="user",
            ),
            session_only=session_only,
        )

    def deny_all(
        self,
        pattern: str,
        scope: PermissionScope,
        session_only: bool = False,
    ) -> None:
        """Add a deny-all rule for a pattern."""
        self.add_rule(
            PermissionRule(
                pattern=pattern,
                scope=scope,
                action=PermissionAction.DENY,
                priority=200,  # High priority
                created_by="user",
            ),
            session_only=session_only,
        )

    def clear_session_rules(self) -> None:
        """Clear all session-only rules."""
        self._session_rules.clear()

    def get_rules(self, include_session: bool = True) -> List[PermissionRule]:
        """Get all rules."""
        rules = list(self._rules)
        if include_session:
            rules.extend(self._session_rules)
        rules.sort(key=lambda r: r.priority, reverse=True)
        return rules

    def get_decisions(self, limit: int = 100) -> List[PermissionDecision]:
        """Get recent decisions."""
        return self._decisions[-limit:]

    def _load_rules(self) -> None:
        """Load rules from file."""
        if not self._rules_file or not self._rules_file.exists():
            return

        try:
            data = json.loads(self._rules_file.read_text())
            for rule_data in data.get("rules", []):
                rule = PermissionRule.from_dict(rule_data)
                if not rule.is_expired:
                    self._rules.append(rule)

            self._rules.sort(key=lambda r: r.priority, reverse=True)
        except (json.JSONDecodeError, KeyError):
            pass

    def save_rules(self) -> None:
        """Save rules to file."""
        if not self._rules_file:
            return

        # Only save non-default, non-session rules
        user_rules = [r for r in self._rules if r.created_by == "user" and not r.is_expired]

        data = {
            "rules": [r.to_dict() for r in user_rules],
        }

        self._rules_file.parent.mkdir(parents=True, exist_ok=True)
        self._rules_file.write_text(json.dumps(data, indent=2))


def create_permission_request(
    scope: PermissionScope,
    path: str,
    tool_name: Optional[str] = None,
    tool_args: Optional[Dict[str, Any]] = None,
    agent_name: str = "",
    context: str = "",
) -> PermissionRequest:
    """Convenience function to create a permission request."""
    request_id = hashlib.sha256(
        f"{scope.value}:{path}:{datetime.now().isoformat()}".encode()
    ).hexdigest()[:12]

    return PermissionRequest(
        id=f"req-{request_id}",
        scope=scope,
        path=path,
        tool_name=tool_name,
        tool_args=tool_args,
        agent_name=agent_name,
        context=context,
    )
