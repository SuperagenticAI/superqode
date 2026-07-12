"""Mixin classes for :class:`superqode.app_main.SuperQodeApp`.

The TUI application was historically one ~34k-line ``SuperQodeApp(App)`` class.
To keep behavior identical while making the code navigable, cohesive groups of
methods live here as ``*Mixin`` classes that ``SuperQodeApp`` inherits.

Rules (see the refactor plan):
- Methods are moved verbatim — same name, signature, and body. ``self`` semantics
  are unchanged because the mixins are combined back into one class via
  ``class SuperQodeApp(*Mixins, App)`` (mixins first so they win over ``App``).
- Class-level state (``CSS``, ``BINDINGS``, ``reactive`` descriptors, ``_*`` defaults)
  and Textual ``App`` lifecycle overrides (``compose``/``on_mount``/…) stay on the
  concrete ``SuperQodeApp`` class, not in mixins.
"""
