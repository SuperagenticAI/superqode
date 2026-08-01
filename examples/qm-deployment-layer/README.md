# SuperQode inside a QM agent computer

This directory is a copy-ready [QM deployment layer](https://github.com/yc-software/qm/blob/main/docs/deploy-directory.md). It implements the first integration boundary without coupling either codebase:

```text
QM conversation and durable computer
  -> QM execute tool and command policy
    -> superqode harness run
      -> SuperQode HarnessSpec, kernel, evidence, and run ledger
```

Copy `sandbox/tools/superqode` and `sandbox/skills/superqode-harness` into the matching paths in a QM deployment directory. The included executable is a small bootstrap pinned to SuperQode 0.2.67. Set `SUPERQODE_VERSION` to test another release, or replace the wrapper with a preinstalled `superqode` binary in your own pinned sandbox image.

Then run QM's normal checks:

```bash
npx qm check
npx qm sandbox build --dry-run
npx qm sandbox build
npx qm conformance
```

The descriptor requires approval for commands that can execute a coding harness and denies nested login and server commands. This matters because QM can approve the outer `superqode` invocation, but filesystem, shell, and network actions inside the run remain governed by the selected SuperQode HarnessSpec. Use a restrictive spec for untrusted requests.

Provider keys should be supplied through QM's deployment secret routing, not with `superqode auth`. For example, add the required provider variable such as `OPENAI_API_KEY` to `sandbox.secretEnv` in the deployment's `qm.config.jsonc`, then push it through QM's normal secret workflow.

The descriptor lists only the package hosts needed by its bootstrap. If a QM deployment enforces outbound hosts, add the selected model provider's API hostname to the deployment policy as well.

Example instruction to QM:

> Use the SuperQode harness at `harness.yaml` to inspect this repository, implement the smallest safe fix, and return the JSON run summary.

This layer is intentionally an in-computer CLI integration. The complementary cross-service design is A2A: expose the same HarnessSpec with `superqode serve a2a`, let QM expose its own A2A Agent Card, and exchange tasks by context rather than sharing Python or TypeScript internals.

## Independent TypeScript A2A check

`interop/a2a-client.mts` is a dependency-free Node TypeScript client. It discovers
the public Agent Card, selects A2A 1.0 HTTP+JSON, sends an authenticated task to
the advertised interface URL, and retrieves the resulting task. With Node 22:

```bash
node --experimental-strip-types interop/a2a-client.mts \
  https://super-agentic.ai \
  "$SUPERQODE_A2A_TOKEN" \
  "Run the QM and SuperQode interoperability check"
```

The SuperQode test suite runs this client against a real local HTTP server when
Node supports native TypeScript stripping. This provides an independent wire
test rather than validating only Python client and server code together.
