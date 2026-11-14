# SystemOne decision providers

SystemOne evaluates typed questions alongside your coding model. Choose
TypeSafe Jev, Google Gemini Decision, or OpenAI Decisions. The coding model
continues to write code; the decision provider returns probabilities, choices
and rubric scores. Connecting an ordinary OpenAI or Gemini chat model does not
select a SystemOne decision engine.

| Provider | Supported model IDs | Credential | Official setup |
| --- | --- | --- | --- |
| TypeSafe | `jev-1.13.0`, `jev-1.14.0` | `TYPESAFE_API_KEY` | [TypeSafe models](https://docs.typesafe.ai/models) |
| Google | `gemini-decision-1` | `GEMINI_API_KEY` | [Google Decisions API](https://aistudio.google.com/docs/decisions-api) |
| OpenAI | `gpt-6-luna` | `OPENAI_API_KEY` | [OpenAI Decisions API](https://developers.openai.com/api/docs/guides/decisions) |

These are API connections with separate usage billing and account/model access
requirements. Do not use a coding-agent subscription token in place of an API
key. No extra vendor SDK installation is needed for these adapters.

Cloud decisions send bounded evidence to the selected provider, even when the
coding model is local. Redaction does not make a cloud request local. Airplane
mode skips live decisions; provider failures retain the existing permission
policy, complete tool catalogue, or original context as appropriate.

## macOS

Open a project, choose **New thread → SystemOne**, then:

1. Select the decision engine and its supported model.
2. Enter an API key. You can explicitly reuse a saved provider API key, load a
   saved decision key, or keep the new key only for this session. Remembering
   uses this Mac's Keychain; keys are not written into the harness file.
3. Optionally use **Test decision**. This explicit action sends a small synthetic
   request containing yes/no, choice and score questions and can incur API
   charges. It checks connectivity and answer formats, not quality.
4. Choose **Connect and choose coding model**. This saves a separate project
   harness with a pinned decision provider/model, then opens coding-model setup.

Opening the page or saving settings makes no inference call. A saved harness
does not change other threads. Remembered decision keys restore silently when
Keychain permits; **Load saved decision key** lets you request access explicitly.

New profiles start in shadow mode. Advanced exposes an acknowledgement that
you reviewed this specific model/policy on representative held-out examples,
followed by an enforcement toggle. This acknowledgement is not a quality
certification. Model/provider changes reset the controls.

## Terminal UI

Use the provider menu or a direct connection:

```text
:connect systemone-models
:connect systemone-google
:connect systemone-openai
```

Set the corresponding API key in the shell that launches SuperQode. The menu
shows the provider's documentation when a key is missing.

For the native coding harness, choose its coding model, then select the decision
provider. Selection starts no model call:

```text
:harness use systemone
:systemone providers
:systemone provider google
:systemone shadow
:systemone status
```

For standalone typed decisions, use:

```text
:systemone connect factory_route --provider google
:systemone connect factory_route --provider openai
:systemone provider typesafe jev-1.14.0
:systemone connect factory_route
```

`connect <pack>` evaluates future messages as decision state. It does not start
a coding loop. `:systemone connect --spec <file>` loads a reviewed decision
harness. Existing Jev commands retain their default provider.

## CLI

List providers offline:

```sh
superqode harness decision-providers
```

Evaluate a pack explicitly using its provider API key:

```sh
superqode harness decision --provider google --pack factory_route \
  --prompt 'Review this change for correctness'

superqode harness decision --provider openai --pack factory_route \
  --prompt 'Review this change for correctness'
```

These commands make metered calls and return the typed result, abstentions,
provider identity and available usage. They never execute a selected command.

Use independent coding and decision providers in a native harness:

```sh
superqode harness run systemone --provider google --model YOUR_CODING_MODEL \
  --decision-provider openai --decision-model gpt-6-luna \
  --prompt 'Review this repository'
```

Decision settings default to shadow mode. After reviewing your provider/model
policy, `--decision-mode enforce --reviewed-decision-policy` explicitly enables
enforcement. Existing deterministic denials still apply. Do not copy Jev's
confidence thresholds to another provider without evaluating them.


## Check your API key and model access

In macOS, use **Test decision** before connecting. It sends one small synthetic
request and checks all three answer types. It does not read a repository or
start a coding job. Opening setup or saving a key sends no inference request.

For the CLI, set the selected provider's documented API-key environment variable
in your shell, then run:

```sh
superqode harness decision --provider google --pack provider_check \
  --prompt 'Please review this code change.' --timeout-ms 10000

superqode harness decision --provider openai --pack provider_check \
  --prompt 'Please review this code change.' --timeout-ms 10000

superqode harness decision --provider typesafe --model jev-1.14.0 \
  --pack provider_check --prompt 'Please review this code change.' --timeout-ms 10000
```

In the TUI, connect the check pack, then send the synthetic message:

```text
:systemone connect provider_check --provider google
Please review this code change.
```

Substitute `openai` or `typesafe` for another engine. Each explicit message makes
one metered request. The check validates the API contract, not decision quality;
an uncertain result can correctly abstain. Never paste an API key as a message.
Use the secure field on macOS or your shell's environment setup.

Key and permission errors point to the provider's setup documentation. Check API
billing and decision-model access if a valid key is refused. A consumer coding
subscription does not grant these API entitlements. Rate-limit waits obey the
server's retry instructions and the total timeout. Exhausted billing is reported
without repeated requests. Raw provider error messages are not displayed.

SystemOne currently sends bounded text or serialized JSON evidence and supports
Noul/Choice/Score. Vendor media APIs, TypeSafe Box questions and experimental
long-context options are outside this integration. Request and response bodies
are capped at 4 MiB; the regular harness also bounds task evidence separately.

## Harness files and context pruning

Save decision settings separately from coding-model settings:

```yaml
name: google-decisions
flavor: decision
runtime:
  backend: systemone
metadata:
  decision_provider_pinned: true
systemone:
  enabled: true
  client: live
  provider: google
  model: gemini-decision-1
  pack: factory_route
  mode: shadow
  policy_reviewed: false
  timeout_ms: 5000
```

For a coding harness, use the same `systemone` section with a native coding
runtime. `provider` chooses the documented endpoint and key variable by default.
The metadata flag pins provider/model/policy settings against ambient selection
overrides. Existing harness files without `provider` retain TypeSafe defaults.
Google/OpenAI native adapters require their documented decision endpoint and
never forward credentials across redirects.
Custom SystemOne-compatible endpoints remain supported through the TypeSafe
wire adapter, including an explicitly empty `api_key_env` for no-auth endpoints.

For process-wide routing, `SUPERQODE_SYSTEMONE_PROVIDER`,
`SUPERQODE_SYSTEMONE_MODEL`, `SUPERQODE_SYSTEMONE_ENDPOINT`, and
`SUPERQODE_SYSTEMONE_API_KEY_ENV` select the decision engine. Setting
`SUPERQODE_SYSTEMONE=live` opts the sidecar into live calls. Google/OpenAI
enforcement also requires `policy_reviewed: true` or the explicit
`SUPERQODE_SYSTEMONE_POLICY_REVIEWED=true` acknowledgement.

Context pruning retains the existing `SUPERQODE_JEV_CONTEXT` and
`SUPERQODE_JEV_CONTEXT_CLIENT` names for compatibility, but uses the selected
decision provider. Unreviewed Google/OpenAI configurations cannot enforce
context removal. Shadow mode can record recommendations while keeping the
original prompt. Tool discovery accepts the neutral judge backend `systemone`
and the existing `jev` alias.

## External harnesses and HTTP/MCP

Choose the decision provider before the routing subcommand. Its identity and
model stay separate from the external harness's coding `--provider`/`--model`:

```sh
superqode optimize --decision-provider google setup --no-live
superqode optimize --decision-provider google enable opencode
superqode optimize --decision-provider openai mcp
superqode serve --decision-provider google decisions
```

Setup with `--no-live` starts no model call. Managed launcher preferences retain
the selected decision provider/model without credentials. Existing `*-jev`
launcher names, `serve jev`, and Python `JevToolRouting` imports remain available.
The neutral Python aliases are `SystemOneToolRouting` and
`SystemOneToolRoutingClient` in `superqode.jev_tools`.

The HTTP service still exposes `/v1/route-tools` and `/mcp`; local stdio MCP
uses the same coordinator. New provider configurations forward the full tool
catalogue in shadow mode until their policy is reviewed. The explicit
`--reviewed-policy` routing-group option acknowledges a reviewed policy before
an enforce-mode request. This option is not a benchmark result.

## Evaluation and tuning

CLI Tune accepts `--decision-provider` and `--decision-model` separately from
`--reflection-lm`. The TUI Tune screen and macOS tuning screen offer the same
selection. Preparing an experiment makes no model calls. Provider, model and
adapter version are retained with the experiment; a supplied decision harness
overrides picker settings. Decision calls and reflection calls have separate
usage charges.

```sh
superqode harness tune --decision-provider google \
  --decision-model gemini-decision-1 --data reviewed-examples.csv \
  --reflection-lm openai/YOUR_REFLECTION_MODEL
```

The `systemone_rubric` evaluator is a provider-neutral alias for `jev_rubric`.
Model judgments do not replace independent repository/test outcomes. Local-only
remote workflows reject both aliases when a grader's local route is unverified.

Confidence has provider-specific semantics. TypeSafe normalizes Choice
confidence against an even split; Google documents top-outcome probability.
Retain raw distributions and evaluate abstention, false approvals, required-tool
recall, task outcomes, latency and cost on held-out examples before enforcement.
No vendor latency claim is a measurement of your Mac or workload.

TypeSafe accepts at most 10 rubric levels. Google supports up to 1,000 questions
and 255 rubric levels per request; OpenAI
supports 400 questions and 10 rubric levels. Unsupported packs fail before
sending. No adapter silently drops questions or changes rubric levels. Safety
blocks, per-question refusals, malformed responses and timeouts never become
affirmative decisions. Optional live recordings use the shared replay format.

## Record decision API calls

Recording is opt-in because successful records include redacted evidence and
question text. Review records before sharing; redaction is not a guarantee that
all private project information has been removed.

Use `--record-dir` for a standalone CLI request:

```sh
superqode harness decision --provider google --pack factory_route \
  --record-dir ./decision-records --prompt 'Review this code change'
```

For a harness, set `systemone.record_dir` or
`SUPERQODE_SYSTEMONE_RECORD_DIR`. In macOS setup, Advanced offers **Record
redacted decision API calls on this Mac**. App-managed files stay beneath the
private app state folder, grouped by project and profile.

Each evaluation writes a private file, including failures, refusals, timeouts,
cancellations and unsupported requests. Records identify the provider, model,
endpoint, latency, outcome and observed HTTP attempts. Successful records also
retain normalized answers, question fingerprints and available token usage.
Unknown usage stays unknown. Authentication headers and raw provider error
bodies are not recorded. Files use owner-only permissions.

Replay accepts successful records and skips failed evaluations when loading a
recording directory. A failed record alone cannot become a successful replay.
These local records do not upload themselves or start another model request.
