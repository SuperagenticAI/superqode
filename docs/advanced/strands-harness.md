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
Strands to the macOS backend and Connect workflow. Install the separate runtime
and run `superqode harness strands doctor` before connecting.

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

## Use from ACP, TUI, CLI and macOS

All four interfaces run the same Strands HarnessSpec through SuperQode's
HarnessKernel and governed tools. Install the separate runtime first. The TUI
shows streamed responses, one card per governed tool call, and reported token
usage; unavailable monetary cost remains unknown.

| Interface | Select Strands |
| --- | --- |
| CLI | `superqode harness run strands --provider ollama --model YOUR_INSTALLED_MODEL -p "Read README.md"` |
| TUI | `:harness switch strands`, or choose Strands in the Harness Hub; then choose your provider and model |
| macOS GUI | Connect, Harnesses, Open, Strands; choose your provider and model |
| ACP agent server | `superqode serve acp --harness strands --provider ollama --model YOUR_INSTALLED_MODEL` |

ACP clients can launch SuperQode with this configuration, substituting an
installed model identifier:

```json
{
  "agent_servers": {
    "SuperQode Strands": {
      "command": "superqode",
      "args": ["serve", "acp", "--harness", "strands", "--provider", "ollama", "--model", "YOUR_INSTALLED_MODEL"]
    }
  }
}
```

`SUPERQODE_ACP_HARNESS=strands` is the environment equivalent of `--harness`.
The existing `SUPERQODE_ACP_SPEC=template:strands` route also remains available.
Choose only one of `--harness`, `--spec` and `--dir`. The ACP route is SuperQode's
server backed by Strands; it preserves the same tool restrictions as the other
interfaces. Strands interactive approval/resume remains unsupported: `ask`
blocks execution. The raw upstream Strands CLI ACP server is not registered.

The TUI and GUI keep Strands visible with setup guidance when its separate
runtime is missing. This source branch must be included in a rebuilt app;
the previously published macOS application does not gain Strands automatically.

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

## Compatibility and limits

The Strands runtime pins Monty 0.0.23 in its separate environment. SuperQode's
optional Python REPL and RLM tools use Monty 1.x; do not install Strands into
that environment or downgrade core Monty to accommodate it. Installing the
Strands runtime does not add a Python REPL to the core preset.

For SuperQode's optional Monty tools, check availability with:

```bash
superqode providers monty check
superqode providers monty smoke
```

Durable program identity pins the worker hash. Checkpoints may require a fresh
run or reconciliation after a worker upgrade.

Provider errors distinguish authentication, permissions, missing models or
endpoints, configuration, connectivity and rate limits. Configure the selected
provider's credentials and model access; there is no silent provider fallback.
Automatic caching uses upstream provider detection; explicitly enabling caching
on an unsupported provider fails.

Use SuperQode's governed `serve acp --harness strands` endpoint for ACP. The
stock Strands CLI ACP server lacks the required client approval bridge and is
not registered as a supported coding connection.
