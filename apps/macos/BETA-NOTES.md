# SuperQode for macOS public beta 0.3.8

Native coding workspace for Apple Silicon Macs running macOS 14 or later. Intel Macs are not supported by this build. This is beta software, with manual updates and incomplete terminal feature parity.

## Install and start

Download the notarized DMG from the official HTTPS download page, open it and drag SuperQode to Applications. Eject the disk image, then launch SuperQode from Applications. macOS may ask you to confirm opening a downloaded app; it should identify the developer and should not require bypassing security protections. If macOS reports damaged software or cannot verify the developer, stop and report it. Do not disable Gatekeeper or remove quarantine to make a public beta work.

Open a disposable or backed-up Git project, choose Connect, select the agent or model you already use, then ask for a small change. Review the diff. Existing agents may require their own installation, sign-in, subscription or API key. No installation or paid model call begins merely by opening the welcome page.

## Privacy, permissions and costs

- The app bundles its Python engine and communicates with it locally over private pipes. It does not require a SuperQode account or send history to a SuperQode cloud service.
- A paired iPhone reaches this Mac through your own Tailscale account. Projects, keys and history stay on the Mac. Cloud models still receive prompts from the providers you configured.
- Configured providers and remote agents receive the requests and context sent to them. Their privacy terms and billing apply. Evaluation and optimization can make multiple paid requests; review budgets before starting them.
- This app is not an OS sandbox. Agent tools and the terminal can run as your macOS user. Use trusted agents and repositories, review permissions and commands, and keep backups. A UI file boundary is not a security boundary for arbitrary shell commands.
- Optional app-managed credentials use macOS Keychain. Existing agent credentials are managed by those agents. Local application data is under `~/Library/Application Support/SuperQode`. Removing the app does not remove this data, Keychain entries or credentials stored by external agents.
- History, terminal output and evidence exports can contain private project content. Inspect and redact anything you choose to share. There is no automatic crash-report upload in this beta.

## Version 0.3.8

Version 0.3.8 (build 24) bundles Python engine 2.31.6. Signing, notarization and device verification happen separately from code preparation.

- Local model opens one guided Local AI screen for Ollama and LM Studio. It detects installations and offers the official LM Studio headless installer only after a reviewed, explicit action. Ollama links to its official download, with Homebrew offered when available.
- Review Start, Stop, model download, load and Unload operations in the app. Progress comes from the server. Stopping the LM Studio server does not unload its daemon's models; use Unload to release them. Cancelling the download observer does not cancel an LM Studio-owned transfer.
- Your Mac shows chip, unified memory and macOS. Starter suggestions use approximate weights, context/KV cache, buffers and headroom against an estimated Metal working-set budget. Ratings are not a guarantee. Qwen3-Coder-Next is only suggested at 96 GB and up.
- Context, output budget and KV cache share one contract. Loaded context is probed and reported separately from requested context. Unknown architecture metadata uses conservative estimates. Older history may be trimmed before a request; an oversized latest prompt fails clearly before sending.
- The amber notice explains local memory, heat, battery, downloads and responsibility. Models run on the Mac; tools and other configured services can still use the network.
- Guided LM Studio downloads and loads require its native REST v1 API (LM Studio 0.4 or newer). API access restrictions are reported; this flow does not collect a server authentication token.
- Advanced retains the existing workbench, storage, compatibility and other runtime controls.
- Bundling regenerates engine metadata to match packaged source, including older base payloads.

### Connection updates

- New-thread connection tiles make the supported setup paths visible at a glance. Choose an existing agent, a SuperQode harness, a local model, an API key, ACP, protocols, a custom harness or SystemOne, or browse All connections.
- Send to Thread (Command-Shift-T) adds an editable context draft to another thread or a new thread. Preview the whole conversation or start at a recorded turn, optionally include changed-file names, then review before sending. Existing drafts and the destination agent session stay intact. Long histories show an omission warning; attachments and permissions are not transferred.
- The getting-started and connection-health Connect links now open All connections, not only subscriptions.

## Version 0.3.7

Version 0.3.7 (build 23) bundles Python engine 2.31.5. It focuses on the
coding workspace.

- A new thread opens with a clear choice of agent and model. The getting
  started guide shows once and stays available from Learning.
- The message box is larger, grows with your text and can be resized. It
  keeps keyboard focus while the agent works.
- Prompts show when they were sent. Finished responses show how long the run
  took, when it finished, the model, and tokens and cost when the agent
  reports them. Runs over ACP now keep the usage the agent reports.
- Running threads show a live working time in the thread list and above the
  message box, and a waiting time while they need your approval.
  Notifications include the thread title and duration. Threads with news you
  have not opened show a dot.
- Each turn lists the files it changed, with line counts. A file opens its
  diff for that turn. Undo this turn restores the files from the turn's
  checkpoint after you confirm, and refuses when newer edits would be
  overwritten.
- Commit, push and open a pull request from a turn with your own Git setup:
  your config, keys, credential helper, signing and hooks. SuperQode never
  stores tokens and never force pushes. It warns before pushing to the
  default branch. Pull requests use the GitHub CLI when it is installed and
  signed in. SuperQode project state is never offered for commit, and Git
  actions wait while a run is active in the project.
- Agent plans and todo lists appear as a checklist in the thread. A slim
  line above the message box shows the connection and, when reported,
  context and usage limits, with a fix action when something is broken.
- Comment on diff hunks, collect the comments, and send them to the agent
  as one follow-up.
- Keyboard: Esc stops a run, Return and Esc answer a visible approval, Up
  restores your last prompt, Cmd J toggles the terminal, Cmd Option B review
  and Cmd G thread search. The threads column can be hidden with Control
  Cmd S and resized. Messages have copy buttons.
- The Mac stays awake while a run is active. You can turn this off in
  Settings. The display may still sleep.
- Opening a very broad folder, such as your home folder or Documents, asks
  for confirmation, and agents no longer fall back to your home folder as
  their working directory. This reduces macOS privacy prompts for Music,
  Photos and other folders.
- Moving between workspace sections stays responsive with long threads.

## Version 0.3.6

Version 0.3.6 (build 22) bundles Python engine 2.31.4. Private remote access
lets a paired iPhone open projects you share from this Mac. The phone uses your
own Tailscale account. SuperQode does not relay that connection, and public
Funnel stays off.

Share each project once. Show on iPhone chooses which paired phone can open
that project. A project shared later does not require pairing again. Each
project has one connection. Harness and model changes stay with that project,
including a change made on the phone.

Local inference only starts off. Off means the phone uses the harness and model
already chosen on this Mac. On means the phone may use only a model running on
this Mac. Connect this Mac starts Tailscale when it is already installed and
signed in, then publishes the private route.

A run started on the iPhone can open in the Mac discussion for the project that
is already open. The Dock icon is the black full-bleed SuperQode mark.

## Version 0.3.5

Version 0.3.5 (build 21) bundles Python engine 2.31.4. Workspace navigation
keeps the composer and file editor mounted, applies pane changes together and
keeps the transcript and review mounted beneath Files while suspending transcript
rendering on other feature pages. Response formatting and review
preparation run away from the UI thread. Recovery writes are coalesced in the
background, and unchanged model/file/Git state avoids unnecessary redraws.
Native menu actions avoid rebuilding recent history on each update, and accent
colour providers are reused while still following appearance and preference changes.
Switching Evaluations and Optimization keeps the suite form mounted, clears live-run
consent and rechecks suite diagnostics before a different experiment. Harness Studio
keeps its editing view mounted across project navigation, and inactive editors and
dialogs do not receive focus or run refresh work. Studio uses the same native
source editor as project files, with code colouring and revision-aware buffer updates.
Navigation changes refresh only views that read navigation state. Local AI retains
its search, filters and model results across page switches, with refresh tasks and
operation dialogs stopped while the page is hidden.
Navigation checks cover first-open and repeated navigation through workspace
panels and the main feature pages. Local readiness recognizes reasoning streams,
and read-tool evidence distinguishes an empty final reply from a marker reply.

Thread lists, tabs and the composer use consistent harness colour accents,
including monochrome agent marks such as OpenCode. New conversations stay
disconnected and show a neutral placeholder until a connection is chosen.
Light/dark palettes keep harness labels legible; custom harness colours remain
stable between launches. Badge colour identifies the harness, not its status.

Evaluation tasks and candidates now use independent copies of one captured input
fixture and fresh harness state. Repository graders can run reviewed commands,
assert file contents and reject changes to protected tests. Verifier commands are
shown before native live runs and suite contents are pinned at submission. Older
held-out reports without isolation evidence must be rerun before candidate adoption.
Copies are not an OS sandbox; trusted verifier commands run as your user.

Local Quick Start adds Fast, Balanced and Capable starting suggestions, tool-call
and context probes, and a Core read-tool check. Missing context and probe warnings
remain visible. Recommended search includes Hugging Face families and the DS4
route; original weights require an appropriate conversion rather than an automatic
GGUF download. Provider setup adds Qwen regional API choices, Chinese-provider
shortcuts, key/endpoint guidance and official docs. Qwen Code setup uses `/auth`
inside its interactive CLI.

Pro verification remains a preview. These changes do not replace project CI and QA.

Closed engine pipes report a recoverable connection error instead of allowing
SIGPIPE to terminate the Mac app during a send or cancellation race.

## Version 0.3.4

Version 0.3.4 (build 20) bundles Python engine 2.31.3. Connection setup now explains
missing CLIs, SDKs and package managers, offers installation rechecks, and keeps
sign-in open until the vendor finishes successfully. Failed sign-in can be retried;
cancellation stops the pending CLI.

Local Quick Start guides an explicitly selected model through reviewed setup,
download and a bounded read-only tool check on generated data. Reopening resumes
progress; failed steps require an explicit retry. The existing local-model picker
refreshes when opened, without scanning caches on Welcome. New blank conversations
start disconnected rather than inheriting a remembered account.

Evaluation and local checks reject incomplete or failed executions even when
output text matches. Local cache inventory avoids linked directories and external
file targets, GGUF estimates handle underscore-separated names, and saved workspace
recovery remains readable after atomic writes on macOS.

In version 0.3.4, generic evaluations do not create a fresh workspace for every task and
candidate. Runs that modify files can affect later trials; use disposable fixtures
and independently verify comparisons before adopting a candidate. Text-matching
graders alone do not establish that a code change passes project tests.

## Version 0.3.3

Version 0.3.3 (build 19) bundles Python engine 2.31.2. Agent Activity starts
collapsed so the conversation has more room; Working text and the moving bar
remain visible during a run. Harness Hub cards and details show available
vendor logos, including Codex, Claude, Factory Droid and OpenCode.

Local AI adds DS4 setup for DeepSeek V4. Select your existing ds4-server and
GGUF weights, configure context and disk-KV storage, review the command and
explicitly start a loopback server. The last reviewed settings are remembered.
An existing server keeps its own settings. Once ready, select an advertised
model for a supported harness or run an explicit readiness check. Only an
app-owned server can be stopped from the app.

DS4 installation and weight downloads remain separate. This release validates
setup and server lifecycle; it does not claim a verified real DeepSeek coding
run. Super Agent is still a preview, and Monty is not bundled.

## Version 0.3.2

Version 0.3.2 (build 18) bundles Python engine 2.31.1 and reorganizes the
workspace around conversations. The dedicated thread sidebar provides search,
status filters and harness identities. Persistent conversation tabs keep open
work accessible, including when switching agents.

The conversation and composer use the full workbench width by default. Changes,
Checks and Evidence open on request; completion never opens the inspector
automatically. Agent activity starts expanded, with animated Working text and
the moving progress bar while a run is active. Files, Terminal, Tasks and
Checkpoints open project panels without switching the selected thread. Full
Review retains revision-bound feedback, staging and branch comparisons.

Harness Hub, Harness Studio, Super Agent, Evaluations, Optimization, Local AI
and Tools remain visible by name. Navigation uses a neutral default appearance;
Settings offers native accent choices. Offline Send preserves the draft. This
release also fixes completed file mentions consuming Return, delayed image paste
attaching to the wrong draft, duplicated repository shortcuts and isolation of
filenames containing consecutive dots.

## Version 0.3.1

Version 0.3.1 (build 17) bundles Python engine 2.31.1. Supported harnesses
now expose Code, Plan and Chat, plus Ask, Auto-edit and Full permissions.
Unsupported controls are hidden and rejected by the engine. Plan restricts
writes, shell and network; Full does not reopen gates closed by the harness.
After starting a new conversation with Full, the next new-conversation draft
returns to Ask, including when navigation changes while Send is pending.

Isolate draft creates a Git worktree from the current commit and transfers
the unsent prompt, staged images and files available there. Uncommitted files
stay in the source checkout, and source-only attachments remain with its draft.
Nothing runs until you explicitly send the isolated task.

The composer adds file mentions, image paste and file drops, repository
navigation pins and a compact change summary. Agent progress uses a simple animated
Working status, with real command/file details below and raw events in the
expandable activity log. Super Agent is a reviewed
preview: proposals bind the selected provider and model, saved revisions
remain disabled until explicitly enabled, and generated harnesses use builtin
tools with recursion off. Its optional Monty check prints a template; it does
not call a model, launch a child agent or install a plugin. Monty is not bundled
in this release, so that check reports unavailable rather than using host Python.

## Version 0.3.0

Version 0.3.0 (build 16) bundles Python engine 2.31.0 and adds Harness Studio,
expanded thread organization and sharing, agent activity, reviewed external
history handoffs, guided ACP setup and recovery, opt-in background execution,
and a local-model workbench for discovery, downloads and server setup.

Strands is available through ACP, CLI, TUI and native connection guidance.
Its runtime is installed separately and preserves governed tool approvals.
Opening the app does not install runtimes, download model weights or start
paid model calls; setup and execution require explicit actions.

Harness Studio saves immutable revisions, while unsaved drafts last only for
the current session. Repeated checks use a restricted read/edit profile and
do not certify a complete harness. External history imports reviewed text,
not live sessions. Background execution requires opt-in and cannot survive
engine or Mac loss. Local compatibility checks are not coding-quality scores.
The Pro Settings section provides a link to the SuperQode website.

## Version 0.2.1

Version 0.2.1 (build 15) introduced the SuperQode Pro section in Settings.
The section now contains only a link to the SuperQode website, with no
commercial workflows or release-decision examples. The welcome tagline is
"The harness layer for coding agents". This version bundled Python engine 2.30.0.

Opening a project from Welcome now enters its workspace even if that project's
saved destination was Welcome. Saved tabs and drafts are preserved.

## Version 0.2.0

Source version 0.2.0 (build 14) presents the harness engineering update introduced
in 0.1.12 under the new macOS release version. This version preparation changes
metadata and documentation only; the bundled engine version is now 2.30.0.
Application behavior is unchanged. The update includes:

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
- Credential-free harness setup checks, offline synthetic tuning practice and a
  dedicated harness learning path in the getting-started guide.
- A dedicated native tuning screen for saved rounds, uncertainty-based example
  selection, label/rationale review and verified candidate decisions.
- More complete agent subprocess shutdown and rejection of workers that exit
  without a valid terminal result.
- A hash-verified Authlib 1.9.1 security overlay for the bundled runtime.

Other advanced actions use the shared engine's typed forms; this version does not
claim full TUI parity. Setup checks and synthetic practice are not general
quality benchmarks or release approval.

## Version 0.1.11

Version 0.1.11 (build 12) bundles Python engine 2.25.0 and includes the
latest native session recovery and scoped review changes:

- Per-conversation composer drafts, project navigation history, transcript reading
  positions and local recovery of unsaved file edits, with conflict handling.
- A Review workspace for This turn, Uncommitted and Branch comparisons, with
  line feedback, saved feedback drafts and guarded whole-file staging.
- Stable conversation identity across follow-up and compaction runs.

It also retains the Command-K palette, paginated run activity with retry, and
evaluation and held-out optimization comparisons. Review feedback is saved as a
draft for a follow-up request; staging requires an explicit action. Recovery of
unsaved file edits offers conflict handling when files have changed on disk.

## What changed in this beta

- Clearer connection navigation, working dialog controls and simpler subscription and ACP selection.
- Faster composer and streaming updates, rendered Markdown, syntax-coloured code and grouped agent activity.
- Pure black and white appearance, readable branding and syntax-coloured source editing.
- Conversations stay together when switching agents, with compatible native session resume and portable context handoffs.

## Known limitations

Connection availability depends on the installed agent, its version, advertised capabilities and your account. Integrations and advanced workflows are experimental during the beta and may fail. A catalog entry does not guarantee compatibility with every account or agent version.

Full terminal parity is not included. Dedicated session fork/tree controls, global approval-mode switching and bespoke resource/optimizer dashboards are not part of this beta. Private iPhone access uses your own Tailscale account and stays on this Mac. Public tunnels are not used. Some advanced workflows use typed command forms. Resume, model configuration and cancellation depend on the selected runtime's capabilities.

## Update, report and recover

Updates are manual. Quit SuperQode, download the newer notarized beta and replace the app in Applications. Keep a backup before upgrading; do not assume a newer data format can be opened by an older app. There is no automatic updater or remote kill switch.

Report issues at https://github.com/SuperagenticAI/superqode/issues with the app version, macOS version, agent version and reproduction steps. Do not post API keys, transcripts or private code without reviewing them first. For sensitive security reports, use the repository's security reporting policy rather than posting exploit details publicly.

If a task fails, inspect its recorded status and Git diff before retrying. Interrupted runs are not automatically replayed. Stop using the beta on important repositories if you encounter data loss, unintended execution or an authentication/credential exposure issue, and report it.


## 0.3.8 release smoke checklist (on a Mac)

- Build in Xcode or with the normal Mac build script. Confirm About and Info.plist show 0.3.8 (24). Inspect the staged runtime: one superqode dist-info, version 2.31.6, matching manifest and imported source. Rebuild using an older base payload and confirm no 2.31.4 metadata remains.
- New thread: exercise every connection grid tile, Back and All connections. Local model opens the newcomer screen. API-key setup and existing agent routes still work.
- Send to thread: Command-Shift-T, whole history and starting turn, existing and new destination, existing draft preservation, omission warning and cancel. Confirm no prompt is sent until explicitly submitted.
- Local AI before opening a project: inspect device and engine detection, notice and Learn more. Ensure merely opening it never installs, downloads or sends a model request.
- With neither engine installed: review the LM Studio official installer command and consent, observe output and re-detect. Test failure/cancel/retry. Check Get Ollama and optional Homebrew. Test Ollama.app installed but never opened and lms outside PATH.
- For each engine: start on loopback, download a small suggested model and watch byte progress, close/reopen setup, cancel/retry, load and check requested versus actual context, finish the bounded check, then Start coding. No prompt should be sent by Start coding.
- Check fit guidance on 16, 24, 32, 48, 64 and 96 GB profiles. The 80B Q4 artifact must not show Fits on 64 GB. Check long context increases the estimate and unknown size is labelled unknown.
- Send a long tool-heavy thread: old complete turns may be trimmed, tool results must stay paired, output stays within the available window, and an oversized newest prompt gets a visible error. Confirm Ollama num_ctx does not jump to a family default.
- Unload and verify memory release without deleting weights. Stop app-started Ollama and LM Studio. Adopted Ollama must not be killed. For LM Studio, Stop only appears for an app-started server; unload separately if models remain resident.
- Open Advanced and verify other runtimes, library, storage and compatibility remain accessible. Run the new LocalModelTests on macOS. Check light/dark mode, keyboard focus, narrow-window scrolling and sheet dismissal.
