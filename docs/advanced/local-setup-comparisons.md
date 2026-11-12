# Hardware setup presets and local comparisons

Open **Local AI → Quick Start → Download or set up a model** for **Fast**,
**Balanced** and **Capable** starting points. Presets reuse fitting installed
weights before suggesting a download, including installed Gemma models with
known sizes. The curated download catalog currently favours Qwen artifacts.
Unknown-size and oversized models do not become automatic preset suggestions.

The names express resource intentions, not measured speed or quality rankings.
Fast starts with smaller fitting weights and a 4,096-token context target;
Balanced targets 8,192; Capable considers larger fitting models and targets
16,384. Hardware, model limits and the working-set estimate can reduce those
targets. Estimates include weights, context/KV cache, buffers and headroom.
MoE fit uses total resident weights. A preset cannot inherit a tested label
from evidence at a shorter context.

Selecting a card prepares a setup step. Review each install, download, load and
readiness check before running it. Presets do not silently reload another
application's server. Existing loaded context and a successful tool check still
matter. Recheck fit when changing hardware or restoring older setup state.

## Compare models and harnesses

Open **Local AI → Compare** after loading models in their runtimes.

1. Select a baseline and one to three candidates. Compare different models,
   different harnesses, or both. Core, PiPy and compatible RLM configurations
   use the shared gateway. This initial flow accepts single-agent harnesses;
   agents with explicit delegated model routes need separate evaluation.
2. Choose a shared context cap that every selected runtime supports. The
   per-request output cap is up to 2,048 tokens and the model-policy iteration
   target is 12. Backend-specific controls remain visible in the effective
   harness snapshot. A candidate has a five-minute execution bound. Runtime/model ceilings can
   still constrain requests; reported loaded context is retained in evidence.
3. Use the two built-in coding tasks, or enter a project suite path. Custom
   suites use independent repository, contains or decision graders. Suite-level
   variants and model-rubric/smoke-only graders are excluded from this flow.
4. Choose whether to send a short warmup request. Existing caches are not
   reset and external servers are not unloaded. Neither option proves a cold
   run or a prefix-cache hit. Execution order is the displayed candidate order.
5. Choose **Review comparison**, inspect the model selections and verifier
   commands, then **Run comparison**. Reviewing sends no model prompts.

Each task starts from an independent copy of one captured project snapshot.
The runner preserves the original project. These copies are not an OS sandbox:
agents and repository verifiers execute code with your user permissions.
Review scripts and use a suitable fixture. Other tools or a local proxy's own
configuration can still use the network; loopback routing is not egress isolation.

The built-in suite asks models to create a bounded-value function and an
order-preserving name deduplicator. Fixed Python checks grade actual files and
behavior independently of the model's final message. Two passing tasks provide
limited starter evidence, not production coding certification.

## Read the result

The report pairs task outcomes and exposes regressions, improvements and
incomplete grading. A failed candidate retains the baseline's results. Changed
model identity disables the adoption comparison. **Stop** cancels the supervised
worker; previous comparisons can be reopened after navigation or restart.

Reproduction details record the suite hash, shared source snapshot hash,
effective harness digest, provider/model/runtime, endpoint, requested context,
response cap, hardware, warmup policy and observed model metadata. Runtime
version, quantization, loaded context and residency stay unknown when a server
does not report them. Revision/digest observations come from the server; they
are not independent checks of model weight files. Mutable revision labels do
not count as immutable artifact identifiers.

Measured model-request timings are correlated to that candidate, excluding its
warmup and other projects' requests. First-text latency is separate from the
full task duration, which includes tools and verification. Missing measurements
remain unknown. API keys stay in the session/Keychain and ephemeral worker
environment, outside the stored comparison plan and result.

Compare exact artifacts and quantizations at matched context, with the same
tasks and cache policy. Repeat runs to understand variation. A larger model or
a single faster sample does not establish a better default.
