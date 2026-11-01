# AWS Strands harness

SuperQode can run the AWS Strands Python harness in a separate environment and
use it as a harness evaluation baseline or candidate. This is an initial
integration available on the feature branch, not a published app update.

The adapter uses `strands_harness.create_harness()`, its system prompt and its
context manager. SuperQode supplies the governed `read`, `write`, `edit` and
`bash` tools and records their execution. Strands' built-in shell, web tools,
skills, memory, delegation and programmatic caller are disabled. The built-in
environment/todo plugins are also disabled; provide project guidance through
SuperQode context or the primary agent instructions. Interactive
approval/resume, MCP, images, typed output and multi-agent workflows are not
implemented by this adapter. An `ask` permission blocks execution.

## Install the separate runtime

Use a SuperQode build containing this integration, from the feature branch or
its eventual package release:

```bash
superqode harness strands setup
superqode harness strands doctor
```

These commands are included in the Python package and do not require the source
checkout. The old `python scripts/setup-strands-runtime.py --install` helper is
retained for checkout compatibility.

This explicitly creates `~/.superqode/runtimes/strands` using uv and Python 3.12,
installs the Anthropic, OpenAI, Gemini, Ollama and LiteLLM provider extras, and checks the worker without calling a
model. It does not install Strands into SuperQode's Python environment. The
runtime pins Strands harness 0.3.3, SDK 1.63.0 and Monty 0.0.23. Transitive
requirements are resolved normally; this is not a bundled, hash-locked macOS
runtime. Selection does not trigger automatic installation.

For a custom isolated environment:

```bash
superqode harness strands setup --python /absolute/path/to/venv/bin/python
export SUPERQODE_STRANDS_PYTHON=/absolute/path/to/venv/bin/python
```

For the macOS app, use the default directory so the backend finds it when the
app is opened from Finder. Custom environment variables and terminal API-key
exports may not reach a Finder-launched app. The app must be rebuilt from this
branch to include the adapter; the currently published app is unchanged.

## Start with a read-only task

Use an installed Ollama chat model, substituting its actual identifier:

```bash
superqode harness run strands --provider ollama --model YOUR_INSTALLED_MODEL \
  --working-dir /path/to/project -p "Read README.md and summarize this project."
```

The preset disables writing and shell execution and does not advertise those
tools to the model. To change those settings,
generate an editable HarnessSpec:

```bash
superqode harness init my-strands -t strands
```

Enable only the capabilities you want under `execution_policy`. File tools
remain bounded to the project. Declared deny and ask rules, command allowlists,
SuperQode's permission manager and contextual tool policy are checked before
execution. A local worker is not an operating-system sandbox; enabling shell
execution grants commands the host user's privileges.

In the TUI, select **Strands** from the harness picker or use
`:harness switch strands`, then select your model. The shared catalog exposes
Strands to the macOS backend and Connect workflow. See the [release validation report](strands-release-validation.md) for the
locally verified native UI and packaging scope.

Supported provider identifiers are `bedrock`, `anthropic`, `openai`, `google`,
`ollama` and `litellm`. Choose an explicit model; there is no silent fallback to
the AWS harness's default model. Anthropic/OpenAI/Google use provider API keys;
Bedrock uses the AWS SDK credential workflow and model/region access. Existing
keys are resolved through SuperQode's common credential resolver: environment
or app-injected credentials take precedence over saved local auth. Only the
selected provider's variables and required OS/proxy/TLS settings are forwarded
to the worker; unrelated tokens such as `GITHUB_TOKEN` are excluded. Credentials
are not written to the spec. AWS uses its existing profile/SSO credential chain.
LiteLLM proxy connections use `LITELLM_API_KEY` and `LITELLM_BASE_URL`.
There is no Strands subscription/OAuth login. API and Bedrock charges apply.

## Configure bounded runs

Example runtime section:

```yaml
runtime:
  backend: strands
  config:
    effort: auto
    context_manager: auto
    caching: auto
    max_turns: 20
    total_tokens: 100000
    output_tokens: 32000
    timeout_seconds: 300
    wall_timeout_seconds: 3600
    session: true
```

Unsupported configuration fields fail instead of being silently ignored.
Token limits are SDK limits checked at turn boundaries, not a hard currency cap.
`timeout_seconds` bounds active awaited worker/tool execution. Event consumer or
UI processing time is excluded from that budget. A separate `wall_timeout_seconds`
deadline (3600 seconds by default, configurable up to 3600) includes consumer
processing time and reaps the worker even if the UI stops consuming events. It
does not cancel the UI task. Active host tools are cancelled at either deadline.
The adapter rejects incomplete, limited or malformed terminal results. Unknown
cost stays unknown. Token counts and resolved package versions are recorded.

Sessions are separated by project, full HarnessSpec, selected model and
SuperQode session id. Changes to any of those start a different Strands session.
Use `session: false` for benchmark specs and fresh worktrees for coding trials.
Memory and skill auto-discovery stay disabled in both coding and evaluation.

## Evaluate and optimise

Strands runs through the same HarnessKernel evaluation path as other backends:

```bash
superqode harness eval --spec baseline.yaml --variant candidate.yaml \
  --tasks tasks.yaml --provider ollama --model YOUR_INSTALLED_MODEL \
  --working-dir /path/to/fixture --split held-out --live --json
```

`--live` executes the selected endpoint; paid providers can incur charges.
Keep tool privileges, fixture contents and model settings comparable. Reuse the
existing supported graders and held-out adoption checks. The adapter does not
import Strands Evals scores or authorize automatic adoption of external reports.
It makes bounded Strands runtime settings available to the existing experiment
flow; it adds no dedicated Strands optimiser or native tuning workflow.

## Monty versions and upgrade options

Monty is already used in SuperQode:

| Use | Behaviour | Source |
| --- | --- | --- |
| `python_repl` | Fresh, bounded Python snippet; no direct filesystem/network/environment or third-party imports | `tools/monty_tool.py` |
| Optional tool composition | With `SUPERQODE_RLM_TOOLS=1`, explicit host calls retain SuperQode policy; parallel calls are restricted | `tools/composition.py` |
| Recoverable programs | Sequential host-tool calls with durable checkpoints, bounded calls and replay validation | `tools/monty_program.py`, `harness/pipy_program.py`, `workorders/programs.py` |
| Native RLM Monty kernel | Resident Python state with selected read-only host capabilities; no direct subprocess or file-writing access | `rlm/kernel_monty.py` |
| Strands upstream caller | Upstream programmatic tool caller depends on Monty 0.0.23 | Disabled in this adapter; dependency stays in its own environment |

The core preset has only four tools, so installing Monty does not add a Python
REPL to that preset. Broader tool profiles expose `python_repl` when a compatible
Monty 1.x package is available. Incompatible 0.x installs are now excluded from
that tool's discovery. Check it with:

```bash
superqode providers monty check
superqode providers monty smoke
```

SuperQode's lock currently selects Monty 1.0.0; its optional requirement allows
1.x. The latest registry release observed on 31 October 2026 is **1.4.0**.
Separate runs of 34 REPL/checkpoint tests and 13 native RLM kernel tests passed
on both versions. This is
initial compatibility evidence, not permission to restore checkpoints under a
new worker binary: durable program identity pins the worker hash, and old
checkpoints may require a fresh run or reconciliation after an upgrade.

Recommended options:

1. Keep core Monty 1.0.0 and the separate Strands runtime for the initial test.
2. Trial core Monty 1.4.0 in a separate environment, including the native RLM
   kernel, before updating the lock and revalidating macOS packaging.
3. Revisit a shared environment if upstream Strands supports Monty 1.x. Disabling
   its caller does not remove the current unconditional 0.0.23 dependency.

Do not downgrade core Monty to accommodate Strands. This branch changes neither
the core dependency range nor the lock.

## Validation and boundaries

The 1 November review identified timeout ownership, saved-key forwarding,
installation guidance, environment filtering and packaging issues in the initial
implementation. The review follow-up passed 246 selected backend, connection,
desktop and Monty tests, including six actual-worker tests against local fixtures
(no paid model calls). Ruff format/check passed for the changed Python files;
`python scripts/check_public_docs_style.py` and the documentation build passed.
A built wheel was installed in a fresh environment and its packaged setup/doctor
commands were exercised outside the checkout. These checks do not validate a
native macOS build or live provider credentials.

Provider errors now distinguish
authentication, permissions, missing models/endpoints, configuration, connectivity
and rate limits without returning raw provider response bodies.

The original Monty checks ran separately against 1.0.0 and 1.4.0: each passed
34 REPL/recovery tests and 13 RLM kernel tests. These are not Strands compatibility
claims for Monty 1.x; the Strands runtime remains isolated on 0.0.23.

The integration has deterministic subprocess tests for policy denial, scoped
file access, command filtering, incomplete results, usage, timeout and cancellation.
Opt-in tests exercise the actual pinned Strands SDK against a local Ollama HTTP
fixture, including governed file reads, saved credentials, provider errors, session
restoration and the shared evaluation/adoption path. From a development checkout,
install the test dependencies with `uv sync --frozen --extra dev`, then run:

```bash
SUPERQODE_TEST_STRANDS_PYTHON=/absolute/path/to/strands/bin/python \
  .venv/bin/python -m pytest -q tests/test_strands_backend.py \
  tests/test_strands_setup.py tests/test_strands_runtime_integration.py
```

These tests make no paid model calls and prove no real-model quality improvement.
The tests also cover the OpenAI Responses API, shared endpoint configuration and
the desktop job process with the default preset. The native macOS CI workflow
runs these SDK tests and a packaged-app Strands smoke test without paid accounts.
Automatic caching uses upstream provider detection; explicitly enabling caching
on an unsupported provider still fails.

Real AWS/API-key inference and Developer ID signed/notarized distribution require
separate release validation. See the [release validation report](strands-release-validation.md)
for evidence from the local Mac review. The raw Strands CLI ACP route is not registered as a supported
coding connection by this implementation, because its stock server lacks the
required client approval bridge. See the [source investigation](strands-harness-research.md).
