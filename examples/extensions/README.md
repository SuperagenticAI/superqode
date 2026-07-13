# SuperQode extension examples

These examples exercise the same extension runtime used by the native `core`
harness. Core keeps its four default tools until an extension is explicitly
installed and enabled.

## Manifest plugin

`manifest-guard/` is a project-local plugin. Install and trust it from a test
project:

```bash
superqode trust yes
superqode plugins add /path/to/superqode/examples/extensions/manifest-guard
superqode plugins doctor
superqode --harness core
```

It contributes one read-only tool, a bounded context file, an audit hook, and a
declarative rule that denies `git push` through the native permission hook.

## Python package

`python-package/` demonstrates the public decorator API and the
`superqode.extensions` Python entry-point group:

```bash
uv pip install -e /path/to/superqode/examples/extensions/python-package
superqode --harness core
```

It contributes a typed function tool, a slash command, a lifecycle hook and a
small context source. Remove the package to remove the extension.

## Independent package conformance fixtures

`packages/` contains separate tool, policy and skill distributions plus a
version-two upgrade fixture. Run their complete build/install/execute/disable/
re-enable/upgrade lifecycle in a temporary environment:

```bash
uv run python scripts/check_extension_packages.py
```

This check never installs the fixture packages into SuperQode's development
environment.
