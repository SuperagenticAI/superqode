# Safety and permissions

The selected execution route determines which permissions, isolation and recovery
controls apply. A local working directory is not an operating-system sandbox.
Check the active route details before running an unfamiliar task.

| Route | Execution and approvals | Recovery boundary |
| --- | --- | --- |
| Native Core | SuperQode tool policy and configured execution backend. Local execution uses the host account. | Conversation state and bounded Git task checkpoints where available. |
| PiPy and CodeGem | Tools run with host process permissions. These routes have no interactive tool approval manager or tool sandbox. Host-enforced workflow restrictions can still reject calls. | Conversation checkpoints do not snapshot or restore files. |
| Vendor CLI, SDK or ACP agent | The vendor owns its runtime. Supported or negotiated host controls vary by adapter and version. | Native resume, transcript replay and a fresh session are different operations. Inspect the active route. |
| RLM and optional runtimes | Host, container or other execution settings depend on the runtime configuration. | Inspect the selected runtime's checkpoint coverage. Do not infer file recovery from the checkpoint capability alone. |
| Remote harness | The server controls its execution environment and policy. | Recovery depends on the server contract. |

## File conflicts

Core, PiPy and CodeGem full-file write tools require a read before replacing an
existing file. After a developer saves a different version, the agent receives a
conflict and must reread before retrying. Content fingerprints detect changes
that preserve the modification time. Successful writes refresh the observation
so the agent can continue editing its own result.

PiPy and CodeGem replacements use a temporary file and atomic rename, preserving
permission bits and resolving symlinks to their targets. New files use exclusive
creation. This is not an operating-system compare-and-swap: an external writer
can still race the final check and rename. Atomic replacement changes inode
identity and does not preserve every filesystem ACL or extended attribute.
Shell commands, external agents and custom tools do not automatically participate
in this file conflict protocol. Core workspace-manager writes retain that
manager's own tracking behavior.

## Review and verification

The task review displays recorded commands and exit codes separately from the
assistant's answer. Missing exit codes and shell chains whose test status cannot
be established are unverified. Later recorded edits or commands make an earlier
successful check outdated. A failed check remains visible even after a retry.
“Checks recorded” describes command evidence, not proof that every requirement
was met or that no external file changed afterwards.

For supported Core, PiPy and CodeGem shell tools, recognized test commands record
bounded content fingerprints before and after execution. At task completion,
the TUI captures the final workspace off the UI thread. “Checks matched final
snapshot” requires every distinct successful check's latest run to match that
snapshot. Changed files, incomplete capture or missing evidence prevent this
stronger status. This covers Git-visible files, including untracked files, at
the recorded time. Ignored files, external dependencies, services and subsequent
changes remain outside the evidence. Non-Git workspaces, symlinks, submodules or
capture budgets can leave a result unverified. The snapshot is a consistency
observation, not an atomic filesystem snapshot or proof of test coverage.

Use the task diff to review the attempt. A conversation checkpoint is not a
backup of the working tree. Git recovery is bounded by the files captured by
that checkpoint; ignored files, external services and arbitrary shell side
effects may fall outside it. Keep valuable uncommitted work backed up.

## Permissions are route-specific

When an active route switches to different execution controls or uses transcript
replay instead of native runtime continuity, the TUI presents a route review
before changing the connection. Escape keeps the current route. Acceptance is
bound to the current connection and rejected if it changed or became busy while
the review was open. The review describes the boundary; it does not add a sandbox.

Do not assume that secrets, network access, paths outside the repository or
privileged operations are universally blocked. Those guarantees require an
execution boundary that actually enforces them. The headless opt-in for pure
permission routes remains required where configured. Selecting a model provider
does not replace the selected harness's execution policy.

For reproducible comparisons, use the [graded benchmark runner](benchmark-runner.md).
Its temporary workspace copies protect the seed from ordinary file edits; they
are not a security sandbox for arbitrary executable agents.
