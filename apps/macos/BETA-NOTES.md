# SuperQode for macOS public beta 0.4.7

Version 0.4.7 (build 33) bundles Python engine 2.31.14. These versions are prepared in source; native validation, signing, notarization and publication remain separate release steps.

- Local AI opens on a simple Start tab: Apple's on-device model first, then Ollama and LM Studio, your Mac's chip and memory, and one model list rated Fits, Tight or Too large.
- A compact harness menu (Core is recommended) sits next to Start coding, and returning users get a one-tap Continue.
- Runtimes, the model library, comparisons, model routes, harness compatibility and Apple model settings live in a separate Advanced tab.
- The welcome screen, the Local model tile, Connect and the harness-first path open the same Start view with the existing warm-up animation.

## 0.4.6 (build 32)

Version 0.4.6 (build 32) bundles Python engine 2.31.13.

- The API-key screen searches providers and models, shows provider logos, and keeps the model and key on one page.
- Opening a provider or closing Connect finishes the click before the sheet changes.

## 0.4.5 (build 31)

Version 0.4.5 (build 31) bundles Python engine 2.31.12.

- Bring your own key lists Google, Anthropic, OpenAI, xAI (Grok), and Meta beside the Chinese providers.
- Harness Hub opens ACP, A2A, and Unified Harness Protocol from Protocols.
- Agent activity stays visible while an agent is working.
- Apple on-device Check availability reports a result. Use for chat and Use for development stay available while a local model server is running.
- fast-agent installs from the setup screen with the app's uv and Python.

## 0.4.4 (build 30)

Version 0.4.4 (build 30) bundles Python engine 2.31.10.

- Local AI retains unsaved setup and runtime settings when navigating away, while removing hidden forms from layout. Unsaved keys stay in memory.
- Catalog menus reuse their entries to reduce navigation work. The Mac validation checklist still requires checking responsiveness on the final build.
- Model Studio setup shows available context/output limits, tool support, pricing caveats and required thinking. DeepSeek V4 Pro and V4.1 Flash 1017 use the supported thinking adapter.
- Antigravity Managed Agent appears in the API-key harness catalog and Harness Hub, separate from subscription sign-in.

## 0.4.3 (build 29)

Version 0.4.3 (build 29) bundles Python engine 2.31.9.

- Connect a metered Alibaba Cloud Model Studio workspace using its API key and endpoint. Load model IDs in the app before saving your key, then use Test model to verify inference.
- Find Apple Foundation Models, runtimes, and performance information in Local AI Quick Start.
- Browse commands from the installed Codex, Grok, and Antigravity CLIs. Set up Antigravity Managed Agent with a Gemini API key.

## 0.4.2 (build 28)

Version 0.4.2 (build 28) bundles Python engine 2.31.8.

- Apple on-device workers close their native model helpers when a job finishes.
- Antigravity model pickers display model names from current Antigravity CLI releases.
- Codex Plugins loads local marketplaces, and the Apps catalog allows more time for each page.

## 0.4.1 (build 27)

Version 0.4.1 (build 27) bundles Python engine 2.31.7.

- **Apple on-device** provides local chat, structured output and lightweight file tasks on supported Macs with macOS 26 or later and Apple Intelligence enabled.
- **Local AI → Advanced** adds runtime profiles, hardware-aware setup presets and isolated model and harness comparisons.
- **Agent controls** exposes models, settings and supported read-only commands for installed Codex and Antigravity CLIs, with an interactive vendor terminal for the full command tree.
- Slash commands ask before replacing a draft. Codex model lists can advance to the next page.

## 0.4.0 (build 26)

Native coding workspace for Apple Silicon Macs running macOS 14 or later. Intel Macs are not supported by this build. This is beta software, with manual updates and incomplete terminal feature parity.

## 0.4: local coding on this Mac

Version 0.4.0 (build 26) bundles Python engine 2.31.6. This packages the local-model work since 0.3.8, including the 0.3.9 preparation below. Recursive agents are a main tab on the left. Signing, notarization, and the public DMG happen separately. Announce this only after the signed build is the one you have run.

Connect on Local AI is three steps. Choose a harness that can run a model on this Mac. Choose an Ollama or LM Studio model that is already installed. Press Start coding. Download a model stays a separate action.

The app already contains Python and SuperQode. The home screen does not ask for Python, uv, or a terminal command. Optional harnesses, including DeepSeek Harness, install from the harness row into Application Support. The install is checked on the same Python path the coding job uses before that harness is treated as ready.

After Start coding, the app warms the selected local model so the first prompt is not the cold load. A reply is shown in the thread, including a DeepSeek reply that arrives as one message. Ollama thinking stays off unless a reasoning effort was set. Context and server settings stay on **Context and server…** on the model step. They are not a required connect step. A running server keeps the context it was started with until it is started again. The simple start path uses context 8192 and automatic KV cache.

Send stays available after Start coding, including while a local server job is still running. Each thread in the sidebar can be deleted. The conversation is the main surface.

Also in this build, from the 0.3.9 preparation: a compact new-thread connection grid, curated starter suggestions, lean prompts for small local models, and Advanced local harnesses for reviewed OpenCode and Goose.

## Advanced: Recursive agents

The left rail has a **Recursive agents** tab, and Command-K **Recursive agents** opens the same page. It is not inside Advanced, not on the new-thread grid, not on Local AI, and not on Getting started. Local AI’s harness list does not gain a Monty or Docker row.

The page explains three boundaries. It does not download a model, start a server, or send a prompt.

- **On this Mac.** Persistent Python. It runs as you, with no approval prompt. It can edit the project and start child agents. Template `rlm`.
- **In Docker.** The Python kernel runs in a container. Writes stay there. Networking is off. The card is disabled, with the reason, when Docker is not running. Template `rlm-docker`.
- **With Monty.** Read-only Python. No files, no shell, and no network. If Monty is not installed, **Install Monty** uses the same Application Support installer as DeepSeek and then checks that `pydantic_monty` loads. That is Monty 1.x. Strands keeps Monty 0.0.23 in its own runtime and is not a fourth card. Template `rlm-monty`.

Choosing a card selects that harness and opens the normal model step.

**Talk to another agent (A2A)** and **Set up A2A…** open the existing RLM routing form. A2A is the agent-to-agent protocol. It stays off until a peer is saved. Hosted peers and credit caps stay off. Protocols remains the way to call one Agent Card without RLM. This build does not open an A2A port.

The same page names DeepSeek and Super Agent. Super Agent still only drafts a reviewed harness and runs its check in Monty. Nothing is installed, and it does not load DeepSeek plugins. DeepSeek Harness remains a separate coding backend: DeepSeek owns the loop, and SuperQode hosts it. It is not the plugin market.

On an Agent Space thread whose harness is `rlm`, `rlm-docker`, `rlm-monty`, or DeepSeek, the inspector gains **Agents**. It shows which boundary is running, the current limits (depth 3, 8 children, 4 at once), whether agent-to-agent is on, and child agents already recorded. Follow-up, steer, cancel, goal, and autonomous gates are available only while a host or Docker worker is already running. Opening the panel does not start a worker. Autonomous gates stay off until turned on. Monty refuses those controls and says so. DeepSeek shows child start and finish events from the thread. Fork, export, tree, inbox, compact, history handles, and the rest of the terminal `:rlm` commands stay in the terminal.

## 0.4 release smoke checklist (on a Mac)

- Build with the normal Mac build script. Confirm About and Info.plist show 0.4.0 (26). The staged engine stays 2.31.6.
- New thread: the connection grid has no Recursive agents tile. Getting started does not mention it. Local AI harness chips include the native `rlm` backend and do not include With Monty or In Docker.
- Local AI: harness, then an installed model, then Start coding. Send works on the new thread, including while a local server job is running. **Context and server…** is on the model step only.
- The left rail **Recursive agents** tab and Command-K **Recursive agents** open the page. Advanced still contains only Local harnesses.
- With no project, the three choices stay disabled. With a project, On this Mac opens the model step on harness `rlm`. Docker is disabled when the daemon is down and says why. Monty offers Install Monty when `pydantic_monty` is missing, and that install does not add a Local AI row.
- Allow other agents… opens the routing form and does not turn agent-to-agent on by itself.
- On a non-RLM thread the inspector has Changes, Checks, and Evidence only. On an RLM thread it adds Agents. Refresh does not start a Python worker. Monty hides follow-up, steer, cancel, goal, and autonomous. A stopped host worker says those controls do not start one.
- Super Agent still drafts only. Open Super Agent and Open Local AI from the corner go to those existing screens.

## 0.3.9: local evaluation and native small-model reliability

The notes in this 0.3.9 section describe that preparation. The 0.4 section above is the current newcomer path.

The newcomer Local AI layout has no new controls, harness choices or evaluation workflow. Its suggestions now use a curated registry: all shipped models are catalog-verified, never labelled tested without an explicitly imported passing Mac run. Applicable tested choices take preference for the same engine and memory tier only, and still have to fit. Existing installed models and saved setup remain available.

Advanced CLI `superqode local eval` exercises five fixed coding/tool tasks and saves local JSON with outcomes, tool validity, timing, reported throughput, context, hardware and artifact metadata. `local promote` explicitly imports passing Mac evidence. Model-written Python executes with user permissions after `--allow-execution`; this is not an OS sandbox. Nothing uploads results or promotes automatically. See [exact Mac commands, evidence scope and limitations](../../docs/local/model-evaluation.md). No model was evaluated on the build box.

The native SuperQode engine automatically uses a minimal base prompt and a compact core toolset for local models at most 9B or effective context at most 8192. Custom/project instructions and permission checks remain. Fenced JSON, single quotes, trailing commas, explicit text calls and unambiguous argument aliases can be repaired. Invalid batches execute nothing, with at most two corrective retries in both run modes. Broad discovery/delegation is unavailable in lean mode; external harnesses are not changed. Lean status and local-only aggregate counters are in doctor JSON and the existing context status tool, not newcomer controls.

Included in app 0.3.9 (25) with engine 2.31.6. No Xcode build, Swift test, installer, signing or notarization was performed on the box.

## 0.3.9: Advanced local harnesses

**Advanced > Local harnesses**, Harness Hub and Command-K **Advanced: Harnesses on local models** open a separate page for experienced users. The Local model connection tile and newcomer Local AI screen have no new choices or harness picker.

Choose a harness and a model that is already loaded in Ollama or LM Studio. Preflight checks the binary, exact loaded identifier, compatible model listing, reported loaded context and approximate fit. A model must be marked Fits. A reachable/configurable pair is labelled Configured only after preflight passes; temporary model/server/fit failures are Preflight blocked. Unknown memory, an unreported context, an unloaded model or an unreachable server blocks launch. Fit accounts for the full loaded context and assumes an unquantized KV cache when the running server's cache format is unknown.

Review the per-launch configuration, write the first message, then choose **Start thread**. This action sends that message and can begin project work. Opening the page and preflight never install a harness, download or load a model, start an agent session or send a generation prompt. Each thread keeps a project-scoped configuration and rechecks it before each turn. A changed model, launch command or context budget requires a new reviewed launch. Identical reviewed pairs reuse the same immutable profile without sharing their thread sessions. No global config files or existing local model bindings are changed.

- **SuperQode harness:** the existing built-in Core runtime, using worker-scoped endpoint, context and output overrides. Other threads and saved model defaults are unaffected.
- **OpenCode stable 1.19.5+ within major 1 (ACP):** `opencode acp` with `OPENCODE_CONFIG_CONTENT`. The generated `sq-local` OpenAI-compatible provider is the only enabled provider; main and small-model selections use the same local model, context/output limits are explicit, tool calling is native and permissions ask. ACP must accept the selected local model before a prompt is sent. Older, prerelease, other-major and unparseable builds are hidden from this page.
- **Goose stable 1.58.0+ within major 1 (ACP):** `goose acp` with its native `ollama` provider and `OLLAMA_HOST`, or its native `lmstudio` provider and `LMSTUDIO_HOST`. `GOOSE_INPUT_LIMIT` maps the context contract to Ollama num_ctx. Model, context and output settings are process-scoped. Subagent defaults use the same local provider/model, approve mode is requested, tool shim is disabled and automatic session naming is disabled. A private GOOSE_PATH_ROOT under application storage starts with only the documented built-in developer extension. The preview includes its initial config.yaml, created only on launch. Global Goose extensions/config are not imported or rewritten; project instructions, commands and any later recipe-level overrides still need review.
- **Eligibility:** only documented local integrations with a reviewed adapter appear. Other integrations are hidden, not listed as unsupported choices. Codex CLI does officially support local models with `--oss`, but this launcher has no reviewed Responses/output-limit adapter, so it stays hidden. Missing installations for allowlisted harnesses are labelled Not installed with a documentation link.

Earlier unreleased Goose profiles require a fresh reviewed launch because provider settings changed. Their old private files are left intact.

Configured means settings and preflight passed, not that a model has demonstrated reliable tool use. Small models may fail coding tasks. External harness tools, extensions, recipes, plugins and shell commands can access the network or apply their own settings. SuperQode strips inherited provider credentials and common model-routing overrides from the worker, but this is not an OS sandbox or a guarantee that an external harness never accesses its own credential store.

Configuration evidence is recorded in [the full local harness audit](../../docs/integrations/local-harness-support.md) and its JSON companion. It covers all 57 ACP descriptors, 15 native runtimes and 30 built-in/optional harnesses, plus the requested reference-only integrations. Unverified evidence is labelled explicitly and never grants app eligibility.

- OpenCode v1.19.5 provider/config/ACP source: https://github.com/anomalyco/opencode/tree/v1.19.5/packages/opencode/src
- Goose v1.58.0 environment settings and providers: https://github.com/aaif-goose/goose/tree/v1.58.0/documentation/docs
- These are reviewed adapter version floors, not claims about the oldest upstream version with local support. Future major schemas and shared-server config propagation require a separate review.

This is unreleased preparation, with no version bump, new DMG, signing or notarization.

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

## Version 0.3.9

Version 0.3.9 (build 25) bundles Python engine 2.31.6. Signing, notarization and device verification happen separately from code preparation.

- A new thread with nothing connected shows the connection grid first. Its tiles and heading are compact so the grid fits small Mac screens, and the composer collapses to a slim Not connected bar until a connection is chosen. A draft, attachments, an existing thread or an offline local engine keep the full composer.
- Advanced > Local harnesses runs documented local-capable harnesses on a model loaded in Ollama or LM Studio, kept separate from the newcomer Local AI screen.
- Advanced CLI local evaluation and lean small-model tool reliability, described above.
- `apps/macos/scripts/release.sh` builds, signs, notarizes, staples and checksums the DMG in one command.

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


## 0.3.9 release smoke checklist (on a Mac)

- Build in Xcode or with the normal Mac build script. Confirm About and Info.plist show 0.3.9 (25). Inspect the staged runtime: one superqode dist-info, version 2.31.6, matching manifest and imported source. Rebuild using an older base payload and confirm no 2.31.4 metadata remains.
- New thread: exercise every connection grid tile, Back and All connections. Local model opens the newcomer screen. API-key setup and existing agent routes still work.
- Send to thread: Command-Shift-T, whole history and starting turn, existing and new destination, existing draft preservation, omission warning and cancel. Confirm no prompt is sent until explicitly submitted.
- Local AI before opening a project: inspect device and engine detection, notice and Learn more. Ensure merely opening it never installs, downloads or sends a model request.
- With neither engine installed: review the LM Studio official installer command and consent, observe output and re-detect. Test failure/cancel/retry. Check Get Ollama and optional Homebrew. Test Ollama.app installed but never opened and lms outside PATH.
- For each engine: start on loopback, download a small suggested model and watch byte progress, close/reopen setup, cancel/retry, load and check requested versus actual context, finish the bounded check, then Start coding. No prompt should be sent by Start coding.
- Check fit guidance on 16, 24, 32, 48, 64 and 96 GB profiles. The 80B Q4 artifact must not show Fits on 64 GB. Check long context increases the estimate and unknown size is labelled unknown.
- Send a long tool-heavy thread: old complete turns may be trimmed, tool results must stay paired, output stays within the available window, and an oversized newest prompt gets a visible error. Confirm Ollama num_ctx does not jump to a family default.
- Unload and verify memory release without deleting weights. Stop app-started Ollama and LM Studio. Adopted Ollama must not be killed. For LM Studio, Stop only appears for an app-started server; unload separately if models remain resident.
- Open Advanced and verify other runtimes, library, storage and compatibility remain accessible. Run the new LocalModelTests on macOS. Check light/dark mode, keyboard focus, narrow-window scrolling and sheet dismissal.

### Advanced local harness smoke checks (on a Mac)

- Build and run the macOS app in Xcode. Verify Advanced > Local harnesses, Harness Hub and Command-K all reach the same separate page. Confirm the newcomer connection tile, Models and guided Local AI remain unchanged and show no harness options.
- Open Advanced without loaded models, with either server offline and with missing allowlisted binaries. Confirm honest status, installation links and disabled Start thread. Install an unwired integration or an older/prerelease/other-major OpenCode or Goose build; it must not appear as an unsupported row. Only SuperQode, reviewed OpenCode and reviewed Goose may appear. Merely opening or refreshing must not start an agent or send a generation request.
- Load a small tool-capable model in Ollama and LM Studio separately. Confirm exact loaded model identifiers, requested/loaded/use context, maximum output, Fits and the previewed loopback endpoint. Test a missing compatible model ID and a server that does not report loaded context; both must block.
- Select an oversized model, an unknown-size model and an excessive loaded context. Confirm launch is blocked rather than silently lowering the displayed memory estimate to a smaller request budget.
- For SuperQode, OpenCode 1.19.5+ within major 1 and Goose 1.58.0+ within major 1, review configuration and explicitly submit a harmless first message. Confirm a new thread opens using the selected harness/model, replies appear, permission prompts work and a second message resumes the same session. Never use an important repository for the first check.
- For OpenCode, check that ACP accepts the exact sq-local model and refusal stops before sending. Verify main and small-model settings remain local. For Goose, verify native provider `ollama`/`lmstudio`, host-only endpoint, matching main/subagent model, context/output limits and Ollama GOOSE_INPUT_LIMIT. The private config must select that same provider and enable only the developer extension. Global configuration must remain unchanged and approval behavior must work. Review any later extension or recipe changes.
- Switch to an unrelated thread and confirm its endpoint, keys, model and context are unchanged. Restart the app and reopen the local thread. Change/unload its model or stop its engine; continuation must block with a visible error, never fall back to a cloud model.
- Check configuration files before and after launch: global files must remain unchanged. Retry the same accepted launch command after a lost response and confirm no duplicate job. Exercise light/dark mode, narrow layout, keyboard access, project switching during preflight and draft preservation on launch failure.
- Run LocalHarnessNavigationTests and the existing macOS unit tests in Xcode. Python fixture tests cover configuration and thread routing, not real installed third-party harness versions or macOS compilation.

### Local model evaluation and reliability smoke checks (on a Mac)

- Build the bundled engine and app in Xcode. Exercise the connection grid and Send to Thread again. Confirm Local model still opens the same simple newcomer screen, with no new controls, harness choices or evaluation prompts. All shipped starter descriptions must be catalog-verified, with no fabricated Tested claim.
- On a disposable Mac account, follow the linked evaluation guide for Ollama and LM Studio separately. Explicitly consent, inspect all five task outcomes and retained fixtures, and confirm a failing/partial/simulated report cannot promote. Unknown token usage must stay null. No report may be overwritten automatically.
- Import a passing run, refresh Local AI and check only fitting tested suggestions for that engine/tier take priority. Other engines and lower-memory or larger-context setups must retain catalog-verified fallbacks. Installed models and saved selection must remain available. Inspect recorded artifact/quantization before interpreting Tested.
- In a disposable native local thread, check a 4B/9B model and an unknown-size alias at 8K context use the compact toolset. Check a larger model above 8K and a cloud thread keep their ordinary profiles. Ensure custom/project instructions remain and permission prompts still apply.
- Exercise fenced arguments, single quotes, trailing commas, an explicit text call and an unambiguous wrong argument name. Check repaired values, especially file content, are unchanged. Conflicting names and wrong types must not execute a tool. An invalid batch must not execute valid sibling edits either.
- Make the model return three invalid batches in streaming and non-streaming turns. Confirm exactly two corrective retries and a visible stop, no repeated mutations or infinite loop. Check doctor JSON and get_context_remaining report local counters and lean mode; no counters, prompts or results should be uploaded.
