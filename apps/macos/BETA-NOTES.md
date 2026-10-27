# SuperQode for macOS — upcoming public beta 0.1.12

Native coding workspace for Apple Silicon Macs running macOS 14 or later. Intel Macs are not supported by this build. This is beta software, with manual updates and incomplete terminal feature parity.

## Install and start

Download the notarized DMG from the official HTTPS download page, open it and drag SuperQode to Applications. Eject the disk image, then launch SuperQode from Applications. macOS may ask you to confirm opening a downloaded app; it should identify the developer and should not require bypassing security protections. If macOS reports damaged software or cannot verify the developer, stop and report it. Do not disable Gatekeeper or remove quarantine to make a public beta work.

Open a disposable or backed-up Git project, choose Connect, select the agent or model you already use, then ask for a small change. Review the diff. Existing agents may require their own installation, sign-in, subscription or API key. No installation or paid model call begins merely by opening the welcome page.

## Privacy, permissions and costs

- The app bundles its Python engine and communicates with it locally over private pipes. It does not require a SuperQode account or send history to a SuperQode cloud service.
- Configured providers and remote agents receive the requests and context sent to them. Their privacy terms and billing apply. Evaluation and optimization can make multiple paid requests; review budgets before starting them.
- This app is not an OS sandbox. Agent tools and the terminal can run as your macOS user. Use trusted agents and repositories, review permissions and commands, and keep backups. A UI file boundary is not a security boundary for arbitrary shell commands.
- Optional app-managed credentials use macOS Keychain. Existing agent credentials are managed by those agents. Local application data is under `~/Library/Application Support/SuperQode`. Removing the app does not remove this data, Keychain entries or credentials stored by external agents.
- History, terminal output and evidence exports can contain private project content. Inspect and redact anything you choose to share. There is no automatic crash-report upload in this beta.

## Upcoming 0.1.12

Source version 0.1.12 (build 13) adds a stronger harness engineering workflow:

- Inspect suite hashes, held-in/held-out counts and smoke-only grading warnings
  before starting a run. Setup checks remain separate from quality measurements.
- Select development or validation splits and compare a baseline with up to eight
  explicitly selected candidate HarnessSpecs.
- Reopen evaluation and optimization evidence from project-specific experiment
  history without launching another run.
- Open harness creation, routing budgets, tuning, benchmarks, failure mining,
  candidate ledgers and revision lifecycle forms directly from experiment pages.
- Require complete, consistent, non-smoke held-out task evidence before an Omni
  candidate passes its gate or can be saved as a project harness. Older reports
  lacking this evidence require a new validation run.

Advanced actions use the shared engine's typed forms. Interactive active-learning
annotation remains a terminal workflow; this version does not claim full TUI
parity. Native tests, interaction checks and bounded live experiments on macOS
are required before publishing 0.1.12. Public downloads remain at 0.1.11.

## Version 0.1.11

Version 0.1.11 (build 12) bundles Python engine 2.25.0 and includes the
latest native session recovery and scoped review changes:

- Per-conversation composer drafts, project navigation history, transcript reading
  positions and local recovery of unsaved file edits, with conflict handling.
- A Review workspace for This turn, Uncommitted and Branch comparisons, with
  line feedback, saved feedback drafts and guarded whole-file staging.
- Stable conversation identity across follow-up and compaction runs.
- Smoke validation covering every native workspace screen, with failures exposed
  in CI check annotations.

It also retains the Command-K palette, paginated run activity with retry, and
evaluation and held-out optimization comparisons. Release checks include 60
native Swift tests, 261 desktop and release checks, and a native smoke test
covering all ten workspace screens with local model fixtures. See [session recovery](SESSION-RECOVERY.md)
and the [review workspace](REVIEW-WORKSPACE.md) for behavior and limitations.

## What changed in this beta

- Clearer connection navigation, working dialog controls and simpler subscription and ACP selection.
- Faster composer and streaming updates, rendered Markdown, syntax-coloured code and grouped agent activity.
- Pure black and white appearance, readable branding and syntax-coloured source editing.
- Conversations stay together when switching agents, with compatible native session resume and portable context handoffs.

## Known limitations

Connection availability depends on the installed agent, its version, advertised capabilities and your account. Integrations and advanced workflows are experimental during the beta and may fail. A catalog entry does not guarantee compatibility with every account or agent version.

Full terminal parity is not included. Dedicated session fork/tree controls, global approval-mode switching, bespoke resource/optimizer dashboards and remote access to your Mac are not part of this beta. Some advanced workflows use typed command forms. Resume, model configuration and cancellation depend on the selected runtime's capabilities.

## Update, report and recover

Updates are manual. Quit SuperQode, download the newer notarized beta and replace the app in Applications. Keep a backup before upgrading; do not assume a newer data format can be opened by an older app. There is no automatic updater or remote kill switch.

Report issues at https://github.com/SuperagenticAI/superqode/issues with the app version, macOS version, agent version and reproduction steps. Do not post API keys, transcripts or private code without reviewing them first. For sensitive security reports, use the repository's security reporting policy rather than posting exploit details publicly.

If a task fails, inspect its recorded status and Git diff before retrying. Interrupted runs are not automatically replayed. Stop using the beta on important repositories if you encounter data loss, unintended execution or an authentication/credential exposure issue, and report it.
