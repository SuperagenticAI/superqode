"""Rule-based approval policy for the ``permission_request`` hook seam.

When a tool needs approval (the :class:`PermissionManager` returns ASK), the
agent loop fires the ``permission_request`` decision hook. This module turns a
harness's declarative :class:`PermissionRuleSpec` list into a handler for that
seam, so teams can encode *which* tool calls auto-approve, auto-deny, or still
prompt - the OpenCode ``pattern -> action`` model.

Evaluation is first-match-wins in declared order:

* ``allow`` -> auto-approve (the loop skips the human prompt)
* ``deny``  -> block with a policy message
* ``ask``   -> abstain, so the existing prompt/pause flow runs
* no rule matches -> abstain

Because this is a normal ``permission_request`` handler, it composes with any
other declared hooks under the registry's deny-precedence: a deny from *either*
this policy or a custom hook wins.
"""

from __future__ import annotations

import fnmatch
from typing import Any, Callable, Iterable, Optional

from ..agent.hooks import ALLOW, DENY, HookDecision
from .spec import PermissionRuleSpec


def _argument_values(rule: PermissionRuleSpec, arguments: dict[str, Any]) -> list[str]:
    """Values a rule's ``pattern`` should be tested against for ``arguments``."""
    if rule.argument:
        if rule.argument not in arguments:
            return []
        return [str(arguments.get(rule.argument, ""))]
    return [str(value) for value in arguments.values()]


def rule_matches(rule: PermissionRuleSpec, tool: str, arguments: dict[str, Any]) -> bool:
    """True if ``rule`` applies to a call to ``tool`` with ``arguments``."""
    if not fnmatch.fnmatch(tool, rule.tool or "*"):
        return False
    pattern = rule.pattern or "*"
    if pattern == "*" and not rule.argument:
        return True
    values = _argument_values(rule, arguments)
    if not values:
        # An argument-scoped rule against an absent argument does not match;
        # a value-scoped rule with no arguments only matches the catch-all.
        return pattern == "*" and rule.argument == ""
    return any(fnmatch.fnmatch(value, pattern) for value in values)


def evaluate_permission_rules(
    rules: Iterable[PermissionRuleSpec],
    tool: str,
    arguments: dict[str, Any],
) -> Optional[PermissionRuleSpec]:
    """Return the first rule that matches the call, or ``None``."""
    for rule in rules:
        if rule_matches(rule, tool, arguments):
            return rule
    return None


def build_permission_handler(
    rules: Iterable[PermissionRuleSpec],
) -> Callable[..., Optional[HookDecision]]:
    """Build a ``permission_request`` handler from ``rules``.

    The handler returns a :class:`HookDecision` for ``allow``/``deny`` matches
    and ``None`` (abstain) for ``ask`` or no match, letting the normal
    prompt/pause flow take over.
    """
    ruleset = tuple(rules)

    def handler(ctx: Any, name: str = "", arguments: Any = None, *_a: Any) -> Optional[HookDecision]:
        args = arguments if isinstance(arguments, dict) else {}
        rule = evaluate_permission_rules(ruleset, name, args)
        if rule is None:
            return None
        action = (rule.action or "ask").strip().lower()
        if action == "allow":
            return HookDecision(action=ALLOW, reason=f"permission rule: {rule.tool}->allow")
        if action == "deny":
            return HookDecision(
                action=DENY,
                message=f"Tool '{name}' denied by harness permission policy.",
                reason=f"permission rule: {rule.tool}->deny",
            )
        # "ask" (or anything unrecognized) -> abstain to the prompt flow.
        return None

    handler.__name__ = "harness_permission_policy"
    return handler


__all__ = [
    "build_permission_handler",
    "evaluate_permission_rules",
    "rule_matches",
]
