# Independently installable extension packages

These packages are the Extensible Core conformance fixtures. Each package owns
one capability and is discovered through the `superqode.extensions` Python
entry-point group.

- `tool-extension/` contributes a typed, read-only tool.
- `policy-extension/` contributes a declarative denial rule and audit hook.
- `skill-extension/` contributes a packaged Markdown skill.
- `tool-extension-v2/` is the upgrade fixture for `tool-extension/`; it has the
  same distribution, entry-point and extension identifiers at version `0.2.0`.
- `broken-extension/` deliberately fails during import so the lifecycle check
  can prove disable-before-import and per-extension failure isolation.

Run the real package lifecycle check from the repository root:

```bash
uv run python scripts/check_extension_packages.py
```

The checker builds wheels into a temporary directory and uses ephemeral `uv`
environments. It does not install the fixtures into SuperQode's development
environment.
