"""Validated shortcut overrides for app, composer, and modal widget scopes."""

from __future__ import annotations

import json
import weakref
from pathlib import Path


class Keymap:
    def __init__(self, path: Path):
        self.scopes = {}
        self.warnings = []
        self._applied = weakref.WeakSet()
        try:
            data = json.loads(path.read_text()) if path.exists() else {}
            if not isinstance(data, dict):
                raise ValueError("Expected an object of shortcut overrides")
            # Preserve the original flat action-to-key format.
            self.scopes = (
                {"app": data} if all(isinstance(value, str) for value in data.values()) else data
            )
        except (OSError, ValueError) as exc:
            self.warnings.append(f"Keybindings could not be loaded: {exc}")

    def apply(self, node, *, scope=None):
        if node in self._applied:
            return
        self._applied.add(node)
        scope = scope or type(node).__name__
        overrides = self.scopes.get(scope, {})
        if not isinstance(overrides, dict):
            self.warnings.append(f"{scope}: expected action-to-key mappings")
            return
        bindings = node._bindings.key_to_bindings
        known = {binding.action: binding for items in bindings.values() for binding in items}
        for action, key in overrides.items():
            if action not in known or not isinstance(key, str) or not key.strip():
                self.warnings.append(f"{scope}: unknown action or empty shortcut: {action}")
                continue
            key = key.strip()
            # Binding actions come from the widget's own declarations. Config
            # cannot inject Python expressions or arbitrary action parameters.
            original = known[action]
            conflicts = [
                binding.action
                for candidate in key.split(",")
                for binding in bindings.get(candidate.strip(), [])
                if binding.action != action
            ]
            if conflicts:
                self.warnings.append(f"{scope}: {key} also binds {', '.join(conflicts)}")
                continue
            for previous in list(bindings):
                bindings[previous] = [
                    binding for binding in bindings[previous] if binding.action != action
                ]
                if not bindings[previous]:
                    del bindings[previous]
            node._bindings.bind(
                key, action, original.description, show=original.show, priority=original.priority
            )

    @staticmethod
    def inventory(app):
        rows = []
        nodes = [("app", app)]
        if app.screen_stack:
            screen = app.screen
            nodes += [(type(node).__name__, node) for node in [screen, *screen.walk_children()]]
        seen = set()
        for scope, node in nodes:
            for items in node._bindings.key_to_bindings.values():
                for binding in items:
                    row = (scope, binding.key, binding.action, binding.description)
                    if row not in seen:
                        rows.append(row)
                        seen.add(row)
        return rows
