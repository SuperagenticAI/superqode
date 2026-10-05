# RLM harness design: Python, Bash, context and composition

Implementation note: this research describes the pre-2.6 audit. See
[RLM profiles and budgets](../advanced/rlm-profiles.md) for the implemented
2.6 scope and its limitations.

Research date: 2026-10-04. SuperQode baseline: released `v2.5.6`, commit
`5a9ad44af3dd5af58ae95daa5564072a87311c66`.

This is an exploration and proposed experiment plan. It does not change the
released harness, enable paid routing, or establish a performance advantage.
All nine supplied links were reviewed, including the interview transcript's
RLM, harness-design, Prime and Headlong discussion. Headlong's primary docs and
execution code were also inspected. No live model benchmark was run.

## Recommendation

Explore **RLM Hybrid**, a separate experimental harness profile with `python`
and `bash`, implemented over the existing native RLM infrastructure. Keep the
released Python-only RLM profile as the control. Avoid creating another worker,
recovery, billing or WorkOrder system just to expose a second tool.

The useful research question is whether direct Bash improves coding reliability
and efficiency while Python remains the persistent environment for context,
composition and semantic subcalls. Shell execution already exists inside our
Python namespace. A second tool principally changes how models express actions;
it does not itself add recursive reasoning or establish a new architecture.

The larger opportunity is to make repository data, conversation history,
command output and child results accessible through one durable, bounded data
surface. Then the model can construct and verify programs over that state with
small observations, rather than repeatedly consuming an expanding transcript.

## What the sources establish

These are summaries of the authors' arguments and reported experiments, not
independent reproductions. Hypotheses, training results and product features
have different evidentiary weight.

| Source | Main finding or argument | Consequence for this proposal |
| --- | --- | --- |
| [Shape](https://alexzhang13.github.io/blog/2026/shape/) | Model input/output contracts could be designed around harness workloads. Separating recent observations from older history is a proposed direction; specialized outputs can serve narrow decisions. | Preserve an interface for small decision models. A Python/Bash harness cannot by itself change a model architecture or deliver the speculative architecture benefits. |
| [Speculative PTC](https://alexzhang13.github.io/blog/2026/spec-ptc/) | Calls can overlap streamed code generation or independent execution. The reported RLM speedup is approximately 1 to 1.2× in the tested settings. Side effects, uncertain dependencies and repeated nondeterministic calls require careful treatment. | Start with explicit batching and job handles. Investigate speculation later, with an unused-call cost metric and occurrence-specific identities. |
| [Harnesses as compositional generalizers](https://alexzhang13.github.io/blog/2026/harness/) | Context offloading and programmatic subcalls help abstract domain details. Reported length and domain transfer comes from training RLMs; successful decomposition is not automatic. | Evaluate decomposition and length transfer alongside Python tool use. Keep strategy examples small and optional rather than hardcoding every task as MapReduce. |
| [LongCoT](https://alexzhang13.github.io/blog/2026/longcot-rlm/) | Brute-force timeouts and unchecked subanswers caused failures. A revised prompt improved the reported GPT-5.2 LongCoT-mini result from 38.7% for the base model to 65.6% for the RLM experiment. | Include graph-dependent coding tasks, bounded computation and verification of intermediate answers. The result is task-specific evidence, not a universal coding improvement. |
| [Mismanaged Geniuses Hypothesis](https://alexzhang13.github.io/blog/2026/mgh/) | The expressive space of decomposition and a model's ability to use it may constrain capability more than raw model size. This is a research hypothesis with supporting experiments. | Give the model composable primitives and measure the resulting strategies. Avoid equating more child agents with better management. |
| [Language Models will be Scaffolds](https://alexzhang13.github.io/blog/2026/scaffold/) | A useful language-model system may encompass a scaffold that invokes neural models, rather than only one network. Evaluation must account for that system. | Compare complete model/harness configurations, including recursion, recovery, cost and acceptance, rather than market a renamed tool loop. |
| [Portkey's Harness Tax](https://portkey.ai/blog/the-harness-tax/) | A two-message, trivial coding task exposed large differences in request overhead. The author explicitly limits the generality of that benchmark. | Measure prompt and schema overhead locally. Token volume alone is not the invoice: caching, retries, child calls and success matter. |
| [Prime Agent](https://www.primeintellect.ai/blog/prime-agent) | A persistent IPython tool combines programmatic tools/subagents with retained sessions and editable supplemental harness state. The article reports mixed benchmark outcomes and a reward-hacking case in Factorio. | Reuse our retained execution mechanisms; investigate scoped refinement separately. Keep externally owned acceptance gates authoritative. |
| [Latent Space interview](https://www.latent.space/p/rlm) | Alex distinguishes a growing trajectory-as-prompt from systems with stored context and programmatic composition. He explicitly describes Prime as only partially offloading context, while retaining a familiar loop. | Keeping a loop is compatible with RLM. The question is what each call observes and how calls compose. The relevant discussion is around 00:40 to 01:03. |

The interview's reference to an Arena harness study is distinct from the
Portkey post. [Arena's HarnessTax study](https://arena.ai/blog/coding-agents-harness-tax)
tests 21 pairs on 30 sampled tasks from each of two benchmarks, with three
attempts per task. It reports substantial cost variation alongside relatively
small average success differences. Its own caveats include possible benchmark
exposure, workload dependence and differing turn definitions. This supports
matched evaluation; it does not prove that all harness architectures are equal.

## Prime and Headlong: what is actually different

Prime's main contribution here is a Python control environment combined with
retained agent and harness state. Its
[current README](https://github.com/PrimeIntellect-ai/prime-agent/blob/c24ac227f11f552ed1d3fa8ebc7d916937d7f6bc/README.md)
distinguishes supplemental refinement from the immutable base prompt and from
packaging new executable skills. It also distinguishes worker lifecycle
isolation from a security sandbox. These are useful boundaries to retain in
our design. Blog examples and current API names can differ; adapters should
follow a pinned implementation rather than copy examples uncritically.

Headlong's contribution is a broader agency design:

- Its [README](https://github.com/laude-institute/headlong/blob/8c1a92cef0109bd56f0714a32b179a8a99d32daa/README.md)
  describes persistent thinking, one shared thought stream, recursive Bash,
  retrievable trajectory projections and fork/test/merge experimentation.
  Continuous agency is separate from the choice of execution language.
- Its [shellm reference](https://github.com/laude-institute/headlong/blob/8c1a92cef0109bd56f0714a32b179a8a99d32daa/docs/shellm.md)
  exposes nested calls through the `shellm` executable and keeps files and
  reusable execution environments. It still returns execution observations to
  a model loop. Bash alone does not eliminate growing history.
- The inspected
  [execution implementation](https://github.com/laude-institute/headlong/blob/8c1a92cef0109bd56f0714a32b179a8a99d32daa/bin/shellm#L1548)
  launches a new `bash -e` process for each block. Persistent files and containers
  should not be confused with persistent shell variables, jobs or functions.
- Its [context renderer](https://github.com/laude-institute/headlong/blob/8c1a92cef0109bd56f0714a32b179a8a99d32daa/bin/context)
  implements bounded trajectory views with head/tail windows and pinned steps.
  The trajectory is the record; the prompt is a view over it.

Our synthesis should therefore combine Python's persistent data/control state
with Bash's practical command expression and retrievable trajectory views.
Always-on self-directed agency is a different experiment with a different cost
contract. It should not become the free-user default.

## Audit of the shipped native RLM

The findings below concern `runtime.backend: rlm`, not every SuperQode backend.
The existing [RLM Code integration](../advanced/rlm-code.md) already exposes
structural/offloaded history and opaque observations through an external
research runtime. We can use it as another comparison condition and reuse its
measurement contracts rather than duplicate that entire engine.

| Capability | Existing evidence | Assessment and next step |
| --- | --- | --- |
| Persistent code environment | [Kernel](../../src/superqode/rlm/kernel.py), [session](../../src/superqode/rlm/coding_session.py) | One Python tool, persistent globals and checkpoints. Native execution uses Python AST/exec, not an IPython kernel; notebook magics and top-level await are not implied. |
| Repository context as data | [Context](../../src/superqode/rlm/context.py) | Lazy file inventory, selection, search and source-carrying chunks already exist. Maintain these in both experimental tool surfaces. |
| Focused semantic calls | [Subcalls](../../src/superqode/rlm/subcalls.py), [ledger](../../src/superqode/rlm/subcall_ledger.py) | Tool-free queries return compact handles and support batching with root-wide admission. Preserve the cheaper query primitive instead of creating a full child for every question. |
| Real recursive coding agents | [Supervisor](../../src/superqode/rlm/supervisor.py), [mailbox](../../src/superqode/rlm/mailbox.py) | Child admission, retained inboxes, continuation and recovery exist. Do not redesign this as a second agent framework. |
| Optional network agents | [Delegation](../../src/superqode/rlm/delegation.py) | Explicit A2A peers, paid admission and reconciliation exist. Local family messaging and external A2A transport remain separate mechanisms. |
| Shell capability | `Shell.run` in [kernel](../../src/superqode/rlm/kernel.py) | Already callable from Python. String execution uses the platform shell through `shell=True`; it does not promise Bash semantics. Make an explicit Bash broker available before comparing tool count. |
| Command-result observations | `ShellResult.__repr__`, `PythonExecutionResult.observation` | Shell repr includes stdout/stderr, then the Python tool bounds observations to 20,000 characters by default. Prefer durable result handles and selective reads to incidental large output. |
| Conversation history | [PiPy harness](../../src/superqode/pipy/harness.py), [kernel globals](../../src/superqode/rlm/kernel.py) | Sessions retain history and rebuild the prompt from session context. No dedicated `history` namespace is injected into the native RLM kernel. Add a scoped read API, not unrestricted access to session storage. |
| Root observation policy | `_build_prompt` and inherited `AgentHarness` | Context/subanswers can stay outside the prompt, but completed observations still form session context with compaction. A new structural projection would be a substantive architecture experiment. |
| Capability descriptions | `_build_prompt` | The default prompt describes A2A even when disabled and describes shell/editing on restricted profiles. Generate a small accurate capability inventory; measure the token benefit before making claims. |
| Memory and refinement | Resource loading, kernel checkpointing | Working variables and loaded skills are not the same as a versioned, evidence-backed refinement system. No dedicated native RLM continual-refinement API was found. |
| Budgets and completion | [Policy](../../src/superqode/rlm/policy.py), subcall/delegation ledgers, WorkOrders | Completion gates and several bounded lanes exist. A unified cost reservation across root inference, coding children, semantic calls and remote tasks needs a separate audit and design. |

An offline observation experiment, with no model calls, stored 5,000 characters
of command stdout in a Python variable. Assignment produced an 11-character
observation; displaying the result produced 5,036 characters; returning only
exit status and output length produced 26 characters. This demonstrates an
existing mechanism and an output-design opportunity. It is not a tokenizer,
invoice, correctness or latency benchmark.

## Proposed experimental design

All APIs and profile names in this section are proposals, not shipped commands.

### One execution broker, two ways to invoke it

Build a broker used by both `shell.run`/a proposed `bash.run` Python function and
the optional model-facing `bash` tool. Both must have identical workspace,
environment, timeout, permissions, output limits and accounting. This isolates
the effect of the model-facing action language from unrelated execution changes.

For an initial experiment, execute Bash blocks in the selected Docker workspace,
with a fresh process per invocation. Python globals persist; shell variables and
`cd` do not. Files persist. Specify the working directory explicitly and return
a durable command handle with exit status, output byte counts, bounded preview
and artifact references. Read larger output through scoped slices from Python.

Do not execute direct Bash on the host when Docker was selected but is absent.
Detect Bash availability rather than assuming `/bin/sh` is Bash. On Windows,
use the selected container for Bash; do not silently substitute PowerShell or
cmd. Run tests and completion gates against the same workspace revision.

Both language surfaces share one session and one host-owned lifecycle. Serialize
workspace mutations. Independent read-only jobs may overlap; parallel editing
children should use isolated candidate workspaces with explicit merge and
verification. A Bash subprocess must not inherit provider or A2A credentials.
Any model/A2A request from generated shell code needs a scoped host bridge with
the same admission and reconciliation rules as Python.

### A context store that serves programs

Add a host-owned read-only history interface: branch-scoped search, bounded
entry reads and provenance-bearing handles for old tool results. Current
permissions apply to each read. Avoid mounting all users' session files into a
sandbox or checkpointing raw credentials.

Next, explore a structural root observation profile. The root receives current
user intent, protected instructions, recent causal steps, pending dependencies,
small execution receipts and references to older data. Full command outputs and
child findings remain stored. The model explicitly reads, transforms or sends
selected slices to focused subcalls. Preserve provider tool-call/result pairing
and branch identity while projecting history; never delete the underlying log.

This is where a new harness could differ meaningfully from a conventional
coding loop. A two-tool profile with the same expanding transcript may improve
ergonomics, but should not be presented as this architectural change.

### Composition with verification

Offer small optional examples of dependency graphs, map/filter/reduce and
candidate/test/refine programs. Let the model choose the decomposition.
Distinguish dependency scheduling from semantic retrieval; one does not replace
the other. Verify intermediate outputs where an inexpensive deterministic check
exists. A child's fluent answer is evidence, not successful local acceptance.

Long-running commands should return admitted job handles rather than block a
whole code cell. Cancellation must stop the actual process tree. Record unknown
outcomes after interrupted writes and require reconciliation before retries;
restarting a kernel is not a rollback of filesystem effects.

### Monty and cost

Keep today's Monty profile as restricted Python with no shell or repository
writes. A future Monty controller plus Docker worker is a separate composite
profile: the controller holds data and composes calls; the worker runs Bash and
changes code through an explicit broker. It needs scoped handles, revocation,
shared budgets and clear UI disclosure. Adding host Bash directly to a Monty
profile would invalidate its existing execution contract.

Monty can reduce execution overhead in suitable workloads. It does not reduce
model API tokens merely by replacing an interpreter. Record controller startup,
CPU/memory and model spend separately.

Default research runs to reactive execution, local/BYOK models, A2A off, no
background model wakeups and no paid fallback. First narrow context, use normal
code for deterministic work, and use focused queries only where semantics are
needed. Avoid selecting a cheaper submodel automatically until its outputs pass
the relevant verification and quality comparison.

### Refinement and speculation as later experiments

Propose scoped memories, prompt notes, reusable decomposition recipes and child
specifications only after a held-out evaluation exists. Record the source
failure, candidate change, validation, version and rollback reference. Apply
validated supplemental changes at turn boundaries. Keep base instructions,
credentials, permissions, spend limits and acceptance gates outside model-owned
CRUD. Do not promote failures into a global prompt automatically.

Before speculative PTC, measure explicit batching and async overlap. A possible
first speculative target is a focused query with fully known inputs, host-owned
reservation and occurrence-specific identity. External purity does not make a
model call free or deterministic. Charge unused calls; prevent duplicate
execution when the completed cell consumes a result. Never speculate Bash
mutations, coding children or paid A2A admission by default. Shadow Python
execution is not a sufficient security boundary for arbitrary code.

## Evaluation and decision gates

Use staged comparisons so that additional code does not obscure the result.

1. **Offline execution contracts:** history retrieval across compaction/restart,
   command-output handles, no key exposure, process-tree cancellation,
   interrupted-write reconciliation, two-language workspace identity and
   unchanged default Monty permissions. Deterministic fixtures cost no inference.
2. **Tool-surface pilot:** compare released Python RLM; Python RLM using the new
   Bash broker; and Python+Bash using that exact broker. Use 12 coding tasks with
   two matched repeats on one model: 72 attempts, behind an explicit experiment
   spend cap. This is exploratory, not enough for a broad superiority claim.
3. **Architecture pilot:** compare the best tool surface with and without
   structural observations/history access. Include Core/PiPy and the existing
   RLM Code LID configuration as baselines. Run a pinned Prime configuration as
   an external comparator when its execution and budget can be matched.
4. **Confirmation:** expand held-out tasks and test a second model only if the
   pilot has a useful result. Compare within each model. Preserve a final untouched
   holdout if prompts or recipes are adapted during development.

Cover small edits, build/test/pipeline tasks, large-repository investigations,
multi-file changes, dependency-graph debugging and interrupted long-running
work. Include similar task structures at increasing repository/log lengths.
Pin revisions, execution images, allowed network, instructions, reasoning
settings and evaluators. Transport-specific tests remain separate from reasoning
benchmarks. Disable paid routes and refinement in the initial surface ablation.

Record:

- Verified pass rate and severity of incorrect changes; partial progress does
  not replace the full acceptance result.
- Total cost per accepted task: root and child inference, semantic queries,
  remote tariffs, compaction/refinement, caching and compute. Preserve unknown
  usage; use provider billing fields rather than treating missing cost as zero.
- Raw input, cache reads/writes, output and reasoning tokens where available;
  estimate attribution for instructions, schemas, history and useful evidence
  without presenting estimated tokenizer counts as provider billing.
- Wall time, retries, cancellation behavior, user interventions and peak memory.
- Root-visible data volume, domain information leaked into the root prompt,
  decomposition pattern, branch/dependency checks and stability as input grows.

Report paired per-task differences and uncertainty. Root-history size and
trajectory similarity are useful proxies; they do not prove that a call is
locally in-distribution. Pilot success means a useful quality/cost/latency tradeoff
worth confirming. A failed experiment is also useful: keep the simpler profile.

## Order of work

| Priority | Deliverable | Reason |
| --- | --- | --- |
| First | Cost attribution, a durable scoped history API and command-result handles | These address observed native-RLM gaps and support every experimental surface. |
| Second | Explicit Bash broker and separate Python+Bash profile | Tests the user's idea without splitting execution/recovery infrastructure. |
| Third | Structural observation profile and matched coding evaluation | Tests the architectural claim about composition and context, not tool count. |
| Later | Validated supplemental refinement, Monty+Docker composition and speculative focused queries | Each has independent correctness and cost questions. |
| Separate | Persistent self-directed agency | Requires a goal/wake budget and lifecycle contract beyond reactive coding. |

In a future TUI experiment, put the profile under `:connect` → model harnesses
→ RLM options, labeled experimental. Show execution boundary, tool surface,
root/child spend and running command/agent handles. Provide explicit stop and
profile controls. Do not imply that the existing public A2A catalogue has become
a paid coding service.

The strongest direction is a family of measured RLM profiles over a shared,
durable execution core. Python+Bash is a reasonable member of that family to
test. History as data, selective observations and verifiable composition are
the more substantial opportunity to explore.

## Addendum: Seth Karten's Continual Harness

Reviewed the [project](https://sethkarten.ai/continual-harness/),
[paper](https://arxiv.org/html/2605.09998) methodology, results and regression
appendix, and [reference evolver](https://github.com/sethkarten/continual-harness/blob/main/agents/utils/harness_evolver.py).
This complements the existing RLM plan; it does not change the order of work.

The paper's mechanism is online refinement of prompt, subagent definitions,
skills and memory from recent trajectories, without restarting the environment.
Harness refinement does not require changing model weights; its separate
co-learning experiment does. The reference evolver runs four independently
handled passes and logs changes. Its current adaptive schedule differs from a
simple fixed interval, so implementation settings should be pinned.

Evidence is from Pokemon, not coding. Emerald Pro shows about 40% lower median
API spend; Flash results vary, and Flash-Lite refinement underperforms the
minimal baseline. Appendix C.2.1 reports a bootstrap regression as new subagents
replace established ones. The main-text Red narrative is more positive than
that appendix, so avoid a blanket claim that continued refinement always helps.
These results motivate testing, not a promised coding cost reduction.

Prime implements a bounded adaptation of the idea. Its pinned
[README](https://github.com/PrimeIntellect-ai/prime-agent/blob/c24ac227f11f552ed1d3fa8ebc7d916937d7f6bc/README.md)
and refinement code use durable supplemental entries, local by default,
with versions and rollback snapshots. `/refine` proposes edits from the
trajectory; the base prompt stays immutable. Skill descriptions are distinct
from packaging new executable skills. This is a better starting contract for
our coding harness than unrestricted rewriting of execution instructions.

Our proposed experiment is an optional refinement layer shared by native RLM
and a future Python+Bash profile. RLM still handles context inspection,
decomposition and focused model calls; refinement improves reusable guidance
across that work. A2A remains an independently selected delegation route.

Start with explicit user-triggered refinement. Use failed WorkOrders, test
results and repeated retry patterns as evidence for small project-scoped
candidates. Attach repository revision, source trajectory, validation and
rollback references. Load relevant entries on demand. Test candidates before
promotion, apply accepted changes at turn boundaries, and preserve established
entries until a replacement demonstrates improvement. Keep executable recipe
changes in the normal review/test path and run them within the selected sandbox.

Show refinement status, spend, entry diff and rollback in the TUI. Reserve a
bounded inference allowance from the task budget; avoid periodic background
refinement initially. Freeze credentials, execution permissions, A2A admission,
spend limits and completion gates outside the editable state. Compare baseline,
frozen inherited guidance and active refinement on held-out coding tasks, using
total cost per accepted task including refinement. Only consider automatic
failure-triggered refinement after this comparison shows a useful tradeoff.
