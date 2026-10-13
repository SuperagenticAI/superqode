# CodeGem: Google model research and implementation evidence

Research date: 13 October 2026. Scope: Gemini and Gemma coding tasks only.

CodeGem is a native Python harness with six tools and Google-specific provider
behavior. It shares SuperQode's durable PiPy loop, file tools, session tree and
event translation instead of introducing a second implementation of those
mechanisms. It is not a claim of benchmark leadership or an exact reproduction
of a private Google product.

## What is available to inspect

Gemma has published weights, reference model code and inference documentation.
The inspected [DeepMind transformer source](https://github.com/google-deepmind/gemma/blob/main/gemma/gm/nn/_transformer.py)
builds configurable attention blocks, selects local/global positional settings,
uses an RMS normalization layer, and supports an attention KV cache. Its
[configuration](https://github.com/google-deepmind/gemma/blob/main/gemma/gm/nn/_config.py)
separates query-head and KV-head counts, attention types and sliding-window
size. These architectural details support an inference: long context size and
memory cost must be treated as deployment properties, not as permission to send
the entire repository to every small local model. They do not prove a particular
coding prompt is optimal.

Gemini's public [technical report](https://arxiv.org/abs/2312.11805) describes the
model family. Its full training implementation and deployed model weights are
not available here. We therefore inspect its documented API behavior and the
public coding client, rather than claim access to the proprietary model source.

Google has an open coding agent: [Gemini CLI](https://github.com/google-gemini/gemini-cli).
The inspected [chat implementation](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/core/geminiChat.ts)
contains response validation, stable tool IDs, conversation recording and
bounded retry machinery. The inspected [prompt snippets](https://github.com/google-gemini/gemini-cli/blob/main/packages/core/src/prompts/snippets.ts)
provide public evidence for coding-task instructions. CodeGem uses independently
written, shorter instructions; it does not copy Gemini CLI's runtime or prompts.

## Gemini wire behavior matters more than a generic system prompt

Google's [thought-signature documentation](https://ai.google.dev/gemini-api/docs/generate-content/thought-signatures)
requires preserving opaque signatures and their association with response parts.
A generic text/tool transcript can discard information that the next signed
tool turn needs. CodeGem stores the exact native model Content alongside its
ordinary text/tool projections. Resume reconstructs requests from that original
Content, preserving order and signatures. Function responses echo native call
IDs when the model supplied them, and batches return their results together.
No fabricated signature or signature-validation bypass is used.
Interrupted batches receive explicit unknown-outcome error responses without
automatically replaying uncertain writes. Truncated calls are excluded from
provider replay because their tools never executed.

The [Gemini 3 guide](https://ai.google.dev/gemini-api/docs/generate-content/gemini-3)
recommends the temperature-1 default. CodeGem retains it, enables high thinking
for known Gemini 3 identities, and gives cloud responses a larger output budget
than local Gemma. Unknown future generations accept a model ID without guessing
new thinking parameters. Native `thinking_config` can explicitly select a
documented configuration. Live cloud quality and latency remain unmeasured
because no API key was supplied.

## Gemma generations and serving templates differ

Google's [prompt-formatting guide](https://ai.google.dev/gemma/docs/core/prompt-structure)
distinguishes generation-specific formatting. CodeGem folds system instructions
into the user conversation for older Gemma profiles and uses the system role for
Gemma 4. The server, not CodeGem, owns tokenization and the actual chat template.
An incompatible server template cannot be fixed by a harness name alone.

The [Gemma function-calling guide](https://ai.google.dev/gemma/docs/capabilities/function-calling)
shows Gemma 4's tool declaration, call and response tokens, typed tool schemas,
and application-side execution. CodeGem uses a named six-tool registry and
validates arguments before execution. It delegates that token grammar to a
compatible Ollama server rather than trying to parse special tokens with regex
or execute generated prose. Servers without advertised tool capability use a
strict JSON envelope as a compatibility path.

The [Gemma thinking guide](https://ai.google.dev/gemma/docs/capabilities/thinking)
documents thinking-template differences even between Gemma 4 sizes, including
an empty thought channel for selected models when thinking is off. CodeGem
passes supported thinking controls to the server and retains returned thinking
separately from final text. This reinforces the need to validate the actual
serving stack for each release.

The [Ollama tool protocol](https://docs.ollama.com/capabilities/tool-calling)
returns results using the tool role and tool_name, with assistant tool_calls in
history. CodeGem follows this native protocol and probes `/api/show` before
choosing tool mode. Native capability is preferred; JSON mode remains an
explicit override and a fallback for older models.

## What CodeGem adopts from Antigravity

Antigravity's [agent overview](https://www.antigravity.google/docs/agent/),
[planning command](https://www.antigravity.google/docs/plan/), and
[artifact overview](https://antigravity.google/docs/artifacts)
document a workflow involving codebase analysis, plans, code changes and
reviewable results. Those observable ideas inform CodeGem's inspect, plan,
implement, verify instructions and its existing SuperQode event presentation.

An exact Python replica of Antigravity is not possible from this evidence.
Its private scheduling, prompts, model routing and server logic were not
inspected, and its implementation language is not established by these sources.
The six-tool requirement also excludes its browser integrations and wider
artifact/agent machinery. CodeGem intentionally implements a smaller coding
workflow in the host application's native UI.

## Local experiments

The installed local model is `gemma4:12b-mlx`. The server reports
`gemma4_unified`, approximately 13 billion parameters, NVFP4 weights, a
131,072-token model context limit, and completion/tools/thinking capabilities.
Trials explicitly use a 32,768-token serving budget. This is an operational
budget, not a revised claim about the model architecture.

`scripts/validate_codegem.py` runs two temporary projects: a mean-function repair
with two pytest cases, and a slug-function creation with one pytest case.
Independent pytest execution scores actual files. Together, the trajectories
exercise all six tools. Tests are checked for preservation, not rewritten to
make an apparent success. The final runner also checks protected tests after
each tool result, catching a model that changes and later restores a test.

Early native pilots with thinking on and off produced passing final artifacts.
The no-thinking repair pilot temporarily rewrote a test and restored it; that
trajectory is not a clean instruction-following pass. The thinking pilot passed
both cases with no observed test-file writes, taking 15 and 11 tool calls. A
temperature-0.2 pilot also passed both final artifact checks with 10 and 16 tool
calls. These are small smoke trials, not a held-out repository benchmark.

The trials exposed repeated Python indentation errors in model-generated
arguments, unnecessary rereads, and running pytest files directly as scripts.
The harness surfaces these errors for correction. Bash now uses SuperQode's
Python environment, and the prompt explicitly requests the proper pytest
runner, protected-test preservation and short Python checks. Lower temperature
alone did not remove these problems, so native Gemma 4 defaults remain
temperature 1 with thinking when supported.

Forced JSON mode with thinking enabled timed out on the repair trial before any
tool call. This is evidence against forcing that path on this local serving
stack; it does not establish that JSON mode fails on every Gemma deployment.
Failed experiments are retained in the validation evidence alongside successes.
Native mode remains the local default selected by capabilities.

The final native run, with the strengthened prompt and per-tool protected-test
audit, passed both repair and creation tasks: 32.37 and 52.74 seconds respectively,
with no protected-test changes. A subsequent creation run after adding explicit
Python syntax-recovery guidance also passed in 47.82 seconds. Generated Python
still needed multiple corrections; this remains a model-quality limitation.
The JSON creation trial also failed to produce a valid JSON envelope.
The [machine-readable validation record](codegem-validation-2026-10-13.json)
preserves outcomes, token counts and tool counts, including failed trials.

Elapsed-time comparisons are not statistically meaningful: the pilots used
different prompt revisions and some shared the local server concurrently.
Model-generated tool errors are distinct from provider failures and final
artifact correctness. No claim is made that two tasks measure overall coding
quality, outperform Pi, or predict an unreleased Gemini model's behavior.

## Acceptance checks and remaining limits

Automated checks cover exact six-tool discovery, supported families, actual file
and subprocess effects, process timeout/cancellation and background cleanup,
bounded output, native signed-content serialization, tool-result pairing, native
and JSON provider contracts, permission denials, loop limits, protocol discovery,
kernel execution and persistence across fresh backend instances. Existing PiPy,
harness catalog, policy, examples and Hub tests are included in regression checks.

The implementation uses turn-buffered provider calls. There is no network token
streaming, browser automation, model delegation, hosted Gemma transport,
OpenAI-compatible local endpoint support, or OS sandbox. Gemini currently uses
the GenerateContent API-key path; Vertex identity/OAuth and newer alternative
API contracts are not implemented. New releases require capability/documentation
review and repeatable trials before being described as validated.

The next quality evidence should be several held-out real-repository fixes per
Gemma size, matched-task comparison against PiPy/Gemini CLI, and Gemini cloud
trials with a key. Extend the acceptance corpus without changing protected
tests, record failures and token budgets, and promote family defaults only when
the data support them.
