# Advanced: evaluate local starter models

This is an opt-in developer workflow, not part of newcomer setup. All shipped
starters are **catalog-verified**, not tested. No real model evaluation was run
on the build box. A catalog listing or a Fits estimate is not a quality result.

The registry is `src/superqode/local/data/starter_models.json`. Each entry names
its memory threshold, both engine tags and official catalog sources. Suggestions
still have to pass the existing weights, context, KV cache, buffers and headroom
fit calculation. The 80B starter is eligible only at 96 GB and above.

## What the evaluation does

`superqode local eval` sends real generation requests only to a literal loopback
Ollama or LM Studio endpoint. It runs five fixed tasks in separate new fixture
directories: edit a file, execute a test, repair a failing test, read/edit/test in
multiple steps, and submit a JSON tool call. It verifies actual tool results and
fixture contents, not a model's claim that it succeeded. Tests use a fixed Python
command, not a model-supplied shell command. Existing project files are not tools
in this suite. Fixture directories are retained and their location is printed.

**Read before consenting:** model-written Python executes with your user
permissions. The temporary fixture directory and restricted tool schemas are
not an OS sandbox. Python code can access files, credentials or the network via
its imports and can start processes. Use a disposable macOS account or an
appropriately isolated machine for untrusted models. `--allow-execution` is
explicit consent to this behavior. There is no automatic evaluation, download,
installation, promotion or results upload.

Each task has at most ten model turns and two invalid-tool corrective retries.
An invalid batch executes none of its tools. Results record pass/fail, valid,
invalid, repaired and text-emitted calls, correction counts, context, artifact
metadata, hardware, elapsed time and reported completion tokens. Tokens/sec
means reported completion tokens divided by request wall time, including prompt
processing, not pure decode throughput. Missing usage stays null. Ollama uses
native `/api/chat` with `num_ctx` per request. LM Studio uses OpenAI-compatible
chat completions, constrained by its REST v1 loaded context. Tool schemas count
in the shared request guard for both. The fit precheck uses the full loaded LM
Studio context, reported artifact size when present, and conservative f16 KV.

LM Studio requires the native REST v1 model listing (0.4 or newer). An endpoint
requiring an authentication token is not handled by this CLI. It reports that
failure; do not put credentials in the endpoint URL. Custom ports can be selected
with `--base-url http://127.0.0.1:PORT/v1`. Remote hosts, proxies and redirects are
not used.

## Run on your Mac

From a source checkout containing this change, with Python 3.12 installed
(Python 3.13 is also supported):

```bash
python3.12 -m venv .venv-local-eval
.venv-local-eval/bin/python -m pip install -e .
SQ="$PWD/.venv-local-eval/bin/superqode"
mkdir -p "$HOME/superqode-local-evals"
```

These commands install the checked-out source, not an older published engine.
They do not rebuild the macOS app. Rebuild its bundled engine separately when
checking the app's updated list.

### Ollama

Start Ollama using the existing Local AI controls, or your usual server process.
Do not start a second server on the same port. Downloading weights uses the
network and disk space. The example uses the smallest curated starter:

```bash
ollama pull qwen3.5:4b
"$SQ" local eval --engine ollama --registry-model qwen3.5:4b \
  --output "$HOME/superqode-local-evals/ollama-qwen35-4b.json" --allow-execution
```

Inspect the JSON and retained fixtures. Only after a complete passing run:

```bash
"$SQ" local promote "$HOME/superqode-local-evals/ollama-qwen35-4b.json"
"$SQ" local doctor --json
```

### LM Studio

Use an installed `lms` CLI (or its full path under `~/.lmstudio/bin`). Select a
small quantized artifact when downloading. The context value below comes from
the same hardware contract used by suggestions:

```bash
lms daemon up
lms get qwen/qwen3.5-4b
CTX=$(.venv-local-eval/bin/python -c 'from superqode.local.context_contract import choose_contract; print(choose_contract("qwen/qwen3.5-4b", provider="lmstudio").context)')
lms load qwen/qwen3.5-4b --context-length "$CTX" --identifier superqode-eval-qwen35-4b
lms server start
"$SQ" local eval --engine lmstudio --registry-model qwen3.5:4b \
  --model superqode-eval-qwen35-4b \
  --output "$HOME/superqode-local-evals/lmstudio-qwen35-4b.json" --allow-execution
"$SQ" local promote "$HOME/superqode-local-evals/lmstudio-qwen35-4b.json"
```

A runtime alias is allowed only when the native listing maps it to the exact
curated catalog key. Unknown mappings are blocked before generation or promotion.
Do not rename an unrelated artifact to bypass this check. If your installed key
is different, inspect `lms ls` and `/api/v1/models`; leave it catalog-verified
until the mapping is reviewed. Existing report files are never overwritten;
choose a new output filename for a rerun. These commands are examples to run on
the Mac, not evidence that either model passed here.

## Promotion and scope

`superqode local promote REPORT.json` explicitly imports a passing run produced
by `superqode local eval`. The `"$SQ"` examples above invoke those same commands
from the checked-out engine, rather than an older installed executable.

Promotion imports the complete report into `~/.superqode/local-model-evals.json`.
It does not edit the shipped registry, global harness config or anyone else's
results. Nothing is uploaded. Failed, partial, no-tool, simulated, unknown-identity
or non-Mac evidence cannot promote a starter. The overlay is user-controlled
local evidence, not a signed attestation or a security boundary.

Suggestions prefer only fitting tested entries for the same engine and current
memory tier. A result from a larger Mac or a shorter context cannot promote a
lower-memory or larger-context recommendation. Without applicable evidence the
existing catalog-verified choices remain. Installed models and saved setups
remain usable. Reopen or refresh Local AI to read newly imported evidence; the
existing description says when a suggested tag has a local five-task run.

A passing five-task run concerns the recorded runtime tag, artifact/quantization,
Mac and context. It does not certify every artifact behind a catalog key, other
harnesses, future model revisions or arbitrary repositories. Retain the artifact
metadata when interpreting a Tested result, and rerun after changing any of
those conditions. The app's newcomer layout and connection choices are unchanged.

## Native small-model reliability

Ollama and LM Studio models at most 9B, or using an effective context at most
8192 tokens, automatically use a lean native profile. Unknown-size aliases use
the context threshold. The base prompt is minimal, custom/project instructions
remain, and only core file, shell, search, permission and context helpers are
advertised. Broad MCP discovery, delegation and other large tool catalogs are
not available in lean mode. Deferred core helpers remain usable. Schema prose
is shortened without dropping types, required fields or constraints. Other
providers and external harnesses do not inherit this native profile.

The native engine repairs fenced JSON, trailing commas outside strings, Python
single-quoted literals, explicit text calls and unambiguous argument aliases.
It does not guess values or ambiguous names. Invalid batches receive short
corrective feedback, with at most two retries per user run in streaming and
non-streaming execution. A third invalid batch stops without executing it.
Existing permission checks still apply to repaired calls.

Aggregate counters contain no prompts, model names or project paths. They stay
in `~/.superqode/local-reliability.json`, appear in `local doctor --json` under
`local_reliability`, and are exposed by the existing `get_context_remaining`
status tool along with the lean-mode indicator. There is no telemetry transport.

Official LM Studio references:

- [Native model listing and loaded context](https://lmstudio.ai/docs/developer/rest/list)
- [Load flags and custom identifiers](https://lmstudio.ai/docs/cli/load)
- [Devstral Small 2 catalog](https://lmstudio.ai/models/mistralai/devstral-small-2-2512)
- [Qwen3-Coder-Next catalog](https://lmstudio.ai/models/qwen/qwen3-coder-next)
