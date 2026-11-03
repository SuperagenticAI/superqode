# SuperQode for macOS

The harness layer for coding agents. A native workspace for coding, reviewing changes, exploring Harness Hub, evaluating results and improving harnesses.

Normal launch stays on Welcome until you open a folder or choose a recent project.
Live agent activity shows the current command or file target across supported
runtime event shapes.

[**Download the latest public beta**](https://superqode.dev/downloads/macos/latest/SuperQode-arm64.dmg)

**Apple Silicon · macOS 14 or later · Signed and notarized · Python engine included**

<picture>
  <source media="(prefers-color-scheme: light)" srcset="../../assets/superqode-macos-welcome-light.png">
  <img src="../../assets/superqode-macos-welcome.png" alt="SuperQode native Mac app welcome screen" width="960">
</picture>

## Start coding

1. Open the DMG, drag SuperQode to Applications and launch it from Applications.
2. Choose **Open project** and select a repository you can safely work in.
3. Choose **Connect** and select an agent or model you already use.
4. Describe a small task, press **Enter** to send (**Shift-Enter** adds a line), review permissions and inspect the changes.

No SuperQode account, App Store installation or separate Python installation is required. External coding agents and local model servers may need their own setup. Their authentication, privacy terms, subscriptions and usage charges apply.

The welcome page and **Help → Getting Started & Learning** guide you through coding, review and more advanced capabilities. The Home button returns to Welcome without closing your project or discarding drafts.

## Composer controls and isolated drafts

For a harness that enforces SuperQode controls, choose **Code**, **Plan** or
**Chat** beside the composer. Plan inspects without writes, shell or network;
Chat answers without tools. In Code, **Ask** prompts for changes, **Auto-edit**
permits edits while keeping shell approval, and **Full** permits writes and shell
within the harness's existing limits. Network still asks when the harness allows
it. These are tool policies, not an OS sandbox. Unsupported agent/backend controls
are hidden and rejected by the engine. The next new conversation returns to Ask
after a Full task starts.

Use `@` to attach an available project file, paste an image, or drop supported
files into the composer. **Tasks → Isolate draft in a worktree** creates a branch
from the current commit and moves your unsent prompt, images and available file
attachments there. Uncommitted files remain in the source checkout; attachments
missing from the worktree stay with its source draft. Review before pressing Send.

**Super Agent** is a preview for drafting a harness and repository navigation
layout. Review the proposal, save a revision with a reason, then explicitly enable
it if a provider and model are bound. Generated harnesses use builtin tools with
recursion off. The optional Monty check only prints a next-prompt template; it does
not launch agents or install a plugin. Monty is not bundled in this macOS release.

## Your first harness check · no API key needed

1. Open a project and choose **Evaluations** under **Improve & more**.
2. Choose a built-in harness and a bundled suite such as **decision-routing**.
3. Leave **Live evaluation** off and choose **Check setup**. This validates the
   configuration without model calls. The tasks are skipped; it is not a quality score.
4. Open **Optimization → More harness workflows → Tune routing decisions from
   examples** and choose **Try practice examples · no calls**. Label the synthetic
   examples and reopen the saved round to learn the workflow. Practice cannot run
   live optimization or authorize adoption.
5. For real measurements, prepare your own graded tasks/examples, configure the
   required local model or provider keys, and explicitly authorize live execution.
   Review budgets, missing evidence and regressions before saving a candidate.

**Help → Getting Started & Learning → Harnesses** offers the same path inside the
app. Preparing an experiment or opening a screen does not start a live run.

## Choose your connection

**Harness Studio** is a primary sidebar destination for editing/importing a
HarnessSpec, validating without model calls, saving immutable revisions and
reviewing repeated read/edit checks. Choose a local model or provider route,
then select a saved revision for Agent Space. Unsaved Studio drafts last for the
current app session; saved revisions persist. Repeated checks use a restricted
read/edit profile, excluding source hooks, MCP, delegates, fallbacks and shell
execution. These checks do not certify the complete harness.

**Harness Hub** is available directly in the sidebar. Its **Build a harness**,
**Agent runtimes** and **ACP agents** actions also appear in Command-K.
Agent runtimes lists all 28 registered runtime/backend IDs, with setup status
and the supported selection path for each. See the
[complete runtime inventory](../../docs/integrations/runtimes-harnesses.md).

ACP agents now appear in a searchable icon grid with launcher/verification
filters. Open a card for guided setup, or explore the separate clients/ecosystem
directory. Threads show the distinct harnesses used, including multiple icons
after switching agents.

**Agent activity** brings app-owned threads across projects into one priority
view, with opt-in native alerts. Fork a finished thread into a new Git worktree,
review its context draft and integrate clean committed changes explicitly.

**All work** now combines the app-owned activity surface with an **External history**
tab. Connect a Codex session folder explicitly, browse/search its metadata and
review a text handoff into a new or idle thread's draft. Source files remain
unchanged; recorded external history does not imply live status or native resume.

- **Existing harness or subscription:** connect supported agents using their own accounts and model choices.
- **Harness with your model:** choose a harness, then connect a provider key or supported local model. Detected Ollama models can be selected directly.
- **Protocols:** connect through ACP, A2A or UHP where the selected agent or server supports the required operations.
- **Build your own:** start from a preset, use the guided builder, or import and edit a HarnessSpec.

Connection options depend on the runtime. Supported ACP agents expose model, mode, configuration and slash-command controls when advertised. Resume and remote cancellation also depend on the selected runtime. Existing terminal credentials remain supported, and optional app-managed provider keys can be saved in macOS Keychain.

ACP setup now includes explicit official-registry refresh, reviewed installation,
advertised agent/terminal sign-in and startup verification. Add, edit or remove
project-scoped custom ACP launch commands from the same flow. Engine and writer
leases protect restart recovery, and interrupted tasks are available for review
without automatic replay.

You can change agents within the same conversation. SuperQode keeps the local transcript and sends bounded conversation context to the selected agent. Returning to an agent resumes its compatible session when available. Agent permissions and authentication remain separate; historical images may need reattaching, and long handoffs may omit messages from agent context while retaining them in your local history.

Selecting a connection does not automatically install an agent, download weights or start a paid model call. Model tests, evaluation and optimization can incur provider charges; review their prompts and budgets before starting.

Use **Share to thread** on a finished conversation to preview recorded text and
append it to a new or idle thread's draft in the same project. Review and send
from the destination. Existing drafts are preserved; attachments and provider
sessions are not transferred. Sharing adds text to a draft and does not start
automatic agent-to-agent communication.

## Local AI and background work

**Local AI** is directly available in the sidebar and Command-K, including before
project selection. Search the shared TUI catalog or Hugging Face, review exact
GGUF/MLX files and download size, configure a supported server and select an
advertised local model for a native harness. LM Studio-compatible search uses
Hugging Face artifacts. Context/KV controls follow each runtime's capabilities.
Downloads and setup have recorded output, progress and cancellation. Available
formats, context sizes and cache settings depend on the selected server and model.

**Storage & Hub access…** configures a shared Hub cache location and verifies a
Hugging Face token, with optional macOS Keychain storage. **Harness compatibility…**
shows every registered runtime and saved check evidence. A running server's
**Check…** offers model-format probes or a bounded Core read-tool roundtrip on
generated data; these remain distinct from full coding quality. MLX installation
now uses its own environment rather than modifying the app's packages. TUI users
can use `:local serve ollama --ctx 16384 --kv-cache q8_0` or `ctx=16384 kv=q8_0`
in the inline start prompt.

While idle, **Settings → Local engine → Keep agent work running when the app
quits** opts into the private background engine. Reopening reconnects to ongoing
work without replaying prompts. App terminals close on quit; engine/Mac loss
still interrupts work.

## Your daily workspace

- **Threads:** search complete project thread metadata, pin or rename conversations,
  archive/restore finished work and return to older drafts. **Connection Diagnostics**
  shows startup evidence and advertised agent capabilities.
- **Agent Space:** stream responses, inspect tool activity, approve or deny actions, continue supported sessions and use direct Chat mode.
- **Review:** inspect turn checkpoints, uncommitted layers and committed branch diffs; select lines and add revision-bound feedback to a follow-up draft.
- **Files:** browse and edit source, create files, inspect diffs, stage or unstage changes and create local commits after confirmation.
- **Context:** attach project text or images, preview selected context and manage supported context-window and compaction controls.
- **Tasks:** prepare independent tasks, reorder the queue and explicitly start work. Failed tasks pause the queue; interrupted work is not automatically replayed.
- **Checkpoints:** inspect recorded changes and use guarded restoration, undo and redo.
- **Terminal:** run interactive project commands in the integrated native terminal.

The labelled navigation rail keeps **Build**, **Harnesses**, **Quality**, **Local AI**,
**Threads** and **Tools** visible. A feature bar shows the related destinations for
that area. **Features** opens the complete feature browser; repository shortcuts
remain available from **Pinned** when a repository layout is saved.

The sidebar is dedicated to project threads. Search by title or harness, or filter
**All**, **Working**, **Needs you** and **Pinned**. Threads show recorded harness
icons, mixed-harness history and readable status. Older records without harness
metadata show a neutral icon rather than guessing from the model.

Conversation tabs also show harness identity and status, stay in opening order,
group turns from the same conversation, and are remembered per project. Use
**Control-Tab** and **Control-Shift-Tab** to switch between open tabs. Closing a tab
keeps its conversation, unsent draft and running work; reopen it from the sidebar
or the full thread library. The plus button starts a new conversation.

**Command-K** opens the command palette. Search actions,
the twelve most recent runs in the current project, or eight recent projects.
Use Up/Down and Return to choose, or Escape to close and return to the previous
control. Unavailable actions show what they need. Menu actions and palette actions
share their shortcuts and availability rules.

The app includes session continuity and draft recovery:
conversation-specific drafts, Back/Forward navigation, file-edit recovery and
reading anchors.

The app also includes a native review workspace,
with file/hunk navigation and guarded staging of a reviewed file.

## Harness Hub, evaluation and optimization

**Harness Hub** lets you explore shared harness definitions and choose a setup for coding, evaluation or optimization. Your project can keep its own inspectable HarnessSpec.

**Evaluations** compares baselines and candidates, including per-task outcomes, costs and regressions. Review setup before authorizing live execution.

The app includes a task comparison inspector for evaluation and
optimizer held-out results. Choose a candidate, search task IDs, filter
regressions/improvements/incomplete evidence, and inspect reasons and reported
cost/time changes. Unknown usage remains unknown; smoke-only checks do not count
as task-quality improvements.

**Optimization** supports bounded Omni experiments, candidate diffs and reviewed adoption of a validated harness revision.

**Tools** provides typed command forms for additional workflows, including WorkOrders, skills, memory, MCP, refinement, promotion, local engines, model downloads and other optimizers. Some advanced capabilities use these forms rather than dedicated graphical dashboards.

## Appearance and accessibility

Choose dark, light or system appearance in Settings. SuperQode's purple, pink and orange branding adapts for readable text. Gradient responses are optional; source code and diffs keep plain text colors. Animations respect Reduce Motion, materials respect Reduce Transparency and Increased Contrast uses system text colors.

## Data and permissions

Projects and history remain on your Mac. Requests and explicitly attached context go directly to your selected provider or remote agent. There is no SuperQode cloud-history account. Local application data is stored under `~/Library/Application Support/SuperQode`.

Agents and terminal commands run with your Mac user's access; the app is not an operating-system sandbox. Use trusted agents and a backed-up repository, review commands and inspect changes. History and evidence exports may contain private project content, so review them before sharing.

## Beta notes and feedback

Some integrations and advanced workflows are experimental, and full terminal feature parity is not included. This build supports Apple Silicon; Intel Macs and remote access to your Mac are not included. Updates are manual: quit SuperQode and replace it with a newer download.

Read the [beta notes](BETA-NOTES.md), [verify the checksum](https://superqode.dev/downloads/macos/latest/SuperQode-arm64.dmg.sha256), or [report an issue](https://github.com/SuperagenticAI/superqode/issues). Include app, macOS and agent versions and remove credentials and private project content from reports.

## Build from source

Requires Xcode with the macOS SDK, Apple Silicon and macOS 14 or later.

Create the isolated engine environment and payload from the repository root:

```sh
UV_PROJECT_ENVIRONMENT=apps/macos/.build-venv uv sync --frozen --no-dev --no-editable --python 3.13
python3 apps/macos/scripts/bundle-runtime.py
python3 apps/macos/scripts/make-icon.py
apps/macos/scripts/build-app.sh
open apps/macos/release/SuperQode.app
# Optional local installers:
apps/macos/scripts/package-distribution.sh
```

SwiftPM pins SwiftTerm for the AppKit project terminal; its license is bundled with the app. The runtime builder pins the compatible Omni optimizer revision and records dependencies and source provenance. Model weights, user configuration and credentials are excluded from the bundle. Python is an execution dependency; all desktop presentation, navigation, lifecycle, dialogs and integration are Swift.

For development, `swift build --package-path apps/macos` builds the executable. The packaging script selects full Xcode when available and places compiler caches inside `.build`. `CONFIGURATION=debug apps/macos/scripts/build-app.sh` packages a debug build. Open `Package.swift` in Xcode to work on the native sources.
