# Bring Your Own Harness

A harness is a single YAML file that defines how a coding agent behaves: which model route it uses, which tools it can call, whether it can write files or run shell commands, how memory is restored, and how it asks for approval. The file lives in the repository, can be reviewed in code review, and can be checked into version control.

This guide shows how to create a harness, inspect the resolved policy, customize it, measure it, and run it against the selected model route.

## Why This Matters

Many coding agents ship with a fixed harness. The model route, tool loop, memory, context strategy, approvals, search, workflow, and optimization assumptions are controlled by the product.

SuperQode makes those settings explicit in a project file. Teams can review the harness, run evals against it, and update it as model routes, repositories, and workflows change.

With Open Models and local models, these settings have a direct effect on reliability. The harness records the model, context size, prompt shape, tool format, memory behavior, and local permissions:

- Local execution can avoid recurring API usage for agent loops that resend repository context.
- A committed harness gives teams a repeatable configuration for coding runs.
- If a local model is unreliable with native tool calls, the harness can switch it to prompt tool-call format.
- A read-only reviewer harness can deny write and shell access at the policy layer.

SuperQode's shipped templates are starting points. Review the generated harness before giving broad write or shell access, then adjust model policy, memory, permissions, search, and workflow settings for the repository.

## Step 1: Get A Harness

You almost never need to write a harness from scratch. You have three ways to get one, from easiest to most manual.

### Option A: The wizard (recommended)

The wizard asks a few plain questions and writes the file for you. No YAML editing required to get started.

Use the TUI path when you want to create and immediately use your first harness:

```bash
cd your-project
superqode
```

Inside the TUI:

```text
:connect local
:harness wizard
```

Then answer the prompts:

| Prompt | First-run answer |
| --- | --- |
| Harness name | Press Enter for `my-harness`, or type a project name such as `repo-coder` |
| Starting point | Press Enter for `qwen-coding`, or choose another template |
| Provider | Press Enter for the template default, or type `ollama`, `lmstudio`, `mlx`, `ds4`, `openai`, or `anthropic` |
| Model | Press Enter for the template model, or type the exact model tag you connected |
| Tools | Press Enter for full coding tools |
| Permissions | Press Enter for balanced approvals |
| Tool-call format | Press Enter for auto |
| Workflow | Press Enter for a single-agent workflow |
| Output file | Press Enter for `harness.yaml`; if it already exists, SuperQode suggests `harness-2.yaml`, `harness-3.yaml`, and so on |
| Load this harness now? | Press Enter or type `yes` |

When the wizard finishes, SuperQode writes the harness file, loads it, and the TUI starts using that policy for future messages. Try a small first prompt:

```text
Read README.md and summarize this project.
```

Check what is loaded anytime:

```text
:harness status
:harness doctor
```

Use the CLI path when you want the same builder outside the TUI:

```bash
superqode harness wizard
```

You can also provide the answers up front with flags:

```text
:harness wizard my-coder --starter qwen-coding --output harness.yaml --load
```

Either way, the builder records the name, starting point (model family), provider/model, file and shell permissions, approval style, tool-call format, and optional multi-agent workflow. Then it writes `harness.yaml` and explains what it built in plain English.

For a first CLI run after the wizard:

```bash
superqode harness explain --spec harness.yaml
superqode harness doctor --spec harness.yaml
superqode harness run --spec harness.yaml --prompt "Read README.md and summarize this project."
```

### Option B: Start from a model-family template

SuperQode ships templates with researched starter defaults per model family.
Pick the one closest to your model and edit from there:

```bash
superqode harness init my-coder -t qwen-coding
```

| Template | Starting point |
| --- | --- |
| `qwen-coding` | Qwen Coder (low temperature, native tools, long agentic sessions) |
| `glm-coding` | GLM 4.x/5.x (strong agentic coder, native tools) |
| `glm52-coding` | GLM-5.2 via Z.AI general API (long horizon, native tools) |
| `gemma4-coding` | Gemma 4 local (strict-JSON tool calls, MLX) |
| `ds4-coding` | DeepSeek/DS4 (compact-JSON tool calls) |
| `ds4-fast-local` | DS4 fast local iteration starter |
| `coding` | Any model (generic full coding agent) |
| `no-tool` | Model-only reasoning/review, no tools |

List them anytime with `superqode harness list-templates`.

### Option C: Let the doctor generate it for your hardware

```bash
superqode local init --repo .
```

That detects your machine, picks a trusted model when one is available, and generates `superqode.local.yaml` using the same harness format.

### Option D: Migrate what you already have

If your repo already has `AGENTS.md`, `CLAUDE.md`, `.agents/skills`, role
prompts, or an older harness, start with a dry-run plan:

```bash
superqode local migrate --repo . --model MiniMaxAI/MiniMax-M1
```

The migrator does not rewrite your files. It shows what exists, which model
pack matches, which prompts or skills need local-model cleanup, and which smoke
and explain commands to run next.

Then create a model pack you own:

```bash
:local build --repo . --model MiniMaxAI/MiniMax-M1 --pack minimax-m1
superqode local pack init --model MiniMaxAI/MiniMax-M1 --dry-run
superqode local pack init --model MiniMaxAI/MiniMax-M1
superqode local init --repo . --pack minimax-m1 --skip-smoke
```

All paths produce the same kind of file. Whichever you use, the next steps are identical.

!!! note "Starter packs are not certification"
    The Gemma, Qwen, GLM, MiniMax, DS4, Devstral, and gpt-oss packs are default
    starting points for model families. They have not been live-certified
    against every checkpoint, quantization, serving engine, hardware tier, and
    repository. Run smoke checks, explain the harness, and adapt the pack for
    your own project before giving broad write or shell access.

## Step 2: Inspect The Resolved Policy

This command reads the resolved policy used by the runtime and returns a human-readable summary:

```bash
superqode harness explain --spec harness.yaml --provider ollama --model qwen3-coder
```

Example output:

```text
Harness: my-coder

'my-coder' is a coding harness: it gives the model read_file, write_file,
edit_file, grep, bash, and more to work in your repository, under the
permission rules below.

Model
  - Primary model: ollama/qwen3-coder.
  - Temperature 0.1 (lower is more deterministic, better for code).
  - Parallel tool calls are OFF (one tool at a time, safer for local models).

Permissions
  - Reading files and searching the repo: allowed.
  - Writing/editing files: allowed.
  - Running shell commands: allowed.
  - Network access: blocked (offline by default).
  - Approval profile 'balanced': auto-approves safe reads/searches but asks
    before writes and shell commands.

Workflow
  - Single agent handles the whole task.
```

If you ever wonder "what can this agent actually do to my repo?", run `explain` and read the answer.

## Step 3: Edit It

The harness file is plain YAML. Here are the fields you will touch most often.

### Choose the model

```yaml
model_policy:
  primary: ollama/qwen3-coder
  temperature: 0.1
  context_window: 16384
```

### Control what the agent can do

```yaml
execution_policy:
  allow_read: true      # read and search files
  allow_write: true     # create and edit files
  allow_shell: true     # run shell commands
  allow_network: false  # reach the internet
  approval_profile: balanced  # ask before writes and shell
```

Set `allow_write: false` and `allow_shell: false` to get a safe read-only reviewer that can look at your code but can never change it or run commands.

### Help weak local models call tools reliably

Small local models often produce malformed native tool calls. Switch them to prompt format, where tools are described in the prompt and parsed from text:

```yaml
model_policy:
  primary: ollama/gemma4
  tool_call_format: prompt
```

After this, `explain` will report: "Tool calls use PROMPT format... because this model has weak or unreliable native tool support."

### Block specific commands

```yaml
execution_policy:
  permission_rules:
    - tool: bash
      pattern: "rm *"
      action: deny
```

## Step 4: Verify Your Changes

Two commands confirm an edit did what you meant.

See the fully resolved policy as structured data:

```bash
superqode harness compile --spec harness.yaml
```

Compare two harnesses to see exactly what changed:

```bash
superqode harness diff harness.yaml locked.yaml
```

Catch mistakes before you run:

```bash
superqode harness validate harness.yaml
```

## Step 5: Run It

Interactive TUI:

```bash
superqode --harness harness.yaml
```

One-shot headless task:

```bash
superqode harness run --spec harness.yaml \
  --provider ollama --model qwen3-coder \
  -p "Read README.md and summarize this project."
```

The agent now behaves exactly as `explain` described. If your harness blocks shell commands, the model cannot run them even if it tries.

## Runtime behavior

Nothing here is cosmetic. When you load a harness, SuperQode turns your YAML into real runtime rules:

1. `execution_policy.allow_write` / `allow_shell` / `allow_network` become hard permission rules. A blocked tool group is denied at the permission layer, before the tool ever runs.
2. `model_policy` sets the actual temperature, tool-call format, iteration limit, history limit, and whether parallel tool calls are allowed.
3. `agents[].tools` filters the tool registry, so the model only ever sees the tools you listed.
4. `workflow` decides whether one agent handles the task or it flows through planner, implementer, and reviewer roles.
5. `context` controls which instruction files load, where sessions are stored, and when the conversation compacts.

You can prove this to yourself: set `allow_shell: false`, run `harness explain`, and you will see "Running shell commands: BLOCKED". Run a task that asks the model to use the shell, and the permission layer refuses it.

## A Read-Only Reviewer Example

```yaml
version: 1
name: local-reviewer
flavor: coding
runtime:
  backend: builtin
model_policy:
  primary: ollama/qwen3-coder
  temperature: 0.1
  tool_call_format: prompt
execution_policy:
  sandbox: local
  approval_profile: balanced
  allow_read: true
  allow_write: false
  allow_shell: false
  allow_network: false
agents:
  - id: reviewer
    role: review
    tools:
      - read_file
      - grep
      - glob
      - repo_search
```

Run `superqode harness explain --spec local-reviewer.yaml` and the Permissions section will confirm writes and shell are blocked. This harness can read and analyze your repository but can never modify it.

## Next Steps

- [Harness System](../advanced/harness-system.md): the full field-by-field reference.
- [Configuration vs Harness](../concepts/configuration-vs-harness.md): how `harness.yaml` differs from `superqode.yaml`.
- [Local Models](../providers/local.md): get a local server and model running first.
- [Local Agentic Coding](../local-agentic-coding.md): the local-first positioning and workflow.
