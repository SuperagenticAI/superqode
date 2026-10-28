# HOL Guard command-inspection extension (experimental)

This independent SuperQode extension applies a conservative **command classification gate** to the native `core` harness's `bash` tool. It uses SuperQode's existing `before_tool` extension hook. It is opt-in and has not been approved or released by SuperQode's maintainers.

## Install in a test environment

Use Python 3.12 or 3.13, and keep the environment disposable:

```bash
uv pip install -e ./examples/extensions/packages/hol-guard-extension
hol-guard command test 'printf hello' --json
superqode --harness core
```

Install HOL Guard separately from its [official repository](https://github.com/hashgraph-online/hol-guard) and verify that `hol-guard` is on the same process PATH. An absolute trusted binary may be selected with `HOL_GUARD_BIN`. No Guard Cloud account is required for this inspection example. Removing the Python package removes the extension.

## Precisely what it does

Before SuperQode executes a `bash` tool call, the extension passes the **original command string** as a positional argument to `hol-guard command test --json -- <command>`. The invocation inspects the command; it never executes it. The extension allows execution only when the returned JSON has both `minimum_action: "allow"` and `classification.explicitly_benign: true`, without a contradictory stop signal.

Unknown/review/block classifications, multiple verdicts, diagnostic text mixed with a verdict, malformed JSON, a missing binary, subprocess errors and timeouts are denied. The CLI's stdout must contain exactly one JSON object; any non-JSON prefix or suffix is treated as non-authoritative. Other SuperQode tools are unaffected; this does not guard arbitrary tool calls, MCP operations or other harnesses.

**This is not HOL Guard's authoritative runtime policy decision.** The `command test` surface reports `policy_evaluation: "not_run"`. The extension does not perform Guard's native approval flow, apply its runtime policy, record native execution receipts, or provide complete command-interception coverage. Classification-only allow is insufficient to establish authorization for a real production system. For native Guard policy enforcement, use a supported harness listed in [HOL Guard's harness matrix](https://github.com/hashgraph-online/hol-guard/blob/main/docs/guard/harness-support.md).

## Verify

From the SuperQode repository root, with its development dependencies installed:

```bash
uv run pytest -q tests/test_hol_guard_extension.py
```

The tests exercise the adapter decision mapping, original command arguments, malformed/contradictory verdicts and subprocess failures using synthetic runner outputs. They do not prove that a live SuperQode session or an installed HOL Guard runtime blocked a command. Before relying on this outside a disposable test project, reproduce a genuine allowed command and a blocked command with an observable, harmless sentinel, and inspect the source and current SuperQode hook semantics.

The extension is HOL-authored; no SuperQode maintainer approval, merge, package release or third-party adoption is implied by the open pull request.
