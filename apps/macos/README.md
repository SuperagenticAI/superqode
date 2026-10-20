# SuperQode for macOS

Native SwiftUI and AppKit desktop workspace. No JavaScript, browser renderer or remote UI. The existing SuperQode Python execution engine is bundled privately inside the application and communicates through inherited JSON-lines pipes. The terminal product remains available independently.

## Build

Requires Xcode with the macOS SDK, Apple Silicon and macOS 14 or later. The minimum OS is the build target; clean-machine compatibility still needs release validation.

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

## Available workflows

- Open projects with a native folder picker, return to recent projects, persist drafts and browse recorded runs.
- Choose a shared HarnessSpec, provider and model, stream real engine events, inspect tools, approve or deny scoped permissions and cancel runs. Continue completed native engine sessions with matching route and harness digest.
- Browse and search the shared Harness Hub. Inspect executable definitions and send them directly to coding, evaluation or optimization. Detected ACP routes can also code through the native stream, with agent-owned authentication and native host permissions. Other catalog connections without desktop adapters say so explicitly.
- Discover local model inventory and hardware. Select Ollama models or enter an existing provider route. Connect a provider in the native app with optional macOS Keychain storage or a session-only key. Existing terminal credentials remain supported. Connection status distinguishes configured credentials from a successful model test.
- Run evaluation setup checks or explicitly authorize live execution. Compare baseline/candidate results, per-task outcomes, cost and regressions. Open saved results and export complete evidence.
- Run bounded Omni optimization with explicit live consent. Inspect staged candidate diffs and save a validated, unchanged candidate as a new project harness.
- Use Code or direct Chat mode. Direct Chat sends messages and explicit images without repository instructions or tools; both modes support recorded continuation.
- Create files and folders, attach project text files to coding tasks, and edit tracked and new non-ignored source files in the native editor, with revision checks and in-memory draft protection. Inspect Git changes, stage tracked modifications or a selected new file, unstage individual files, create local commits after confirmation, and run project checks.
- Prepare independent coding tasks in a persistent project queue. Reorder, explicitly start or pause, open recorded runs and retry after review. Each task keeps its connection; failures pause the queue. No automatic replay on restart.
- Use **Tools** for native forms generated from the installed engine’s typed WorkOrder, memory, skills, MCP, refinement, promotion, benchmarking, optimization, local engines, model downloads, policies and session commands. A live WorkOrder board shows tasks, worker leases, budgets and acceptance gates. Review arguments before execution; results stream into local run history. These are command forms, not a graphical worker monitor.
- Attach image files or explicitly paste a clipboard image using shared image bounds and immutable local snapshots. Preview selected context, pin the context window, request built-in context compaction with cost consent, use OS Dictation, or steer a supporting active runtime.
- Inspect task checkpoints and guarded undo/redo/restoration. Run interactive project commands in a persistent native terminal.
- Native menu commands, keyboard navigation, resizable split panes and dark/light/system settings.

## First launch and progressive learning

Every normal launch opens a dedicated **Welcome to SuperQode** page with the original logo, Open Project, recent projects and Getting Started. Existing projects are opened explicitly rather than silently bypassing the welcome page. The Home button, sidebar wordmark and Help → Welcome to SuperQode return there without discarding project drafts. After opening a project, the starter flow follows three steps: open a project, connect an existing agent or model, and describe the work. The project workspace tracks these steps, offers an optional project-overview prompt without sending it, and retires the starter guide after a completed coding run. Users can dismiss it or reopen it from Help → Getting Started & Learning (Command–?).

The initial sidebar shows Workspace, Files and Terminal. **Improve & more** progressively reveals Harness Hub, Models, Evaluations, Optimization, Tools and Checkpoints. Every destination remains available through the Workspace menu and its existing keyboard shortcut; navigating to an advanced destination opens its sidebar group. Advanced routing stays collapsed, task queues live under Tasks, and the run inspector is opened explicitly using Show run details. Routine engine bookkeeping is hidden behind Activity details; permissions, tool work, errors and unknown events remain visible, and exports retain full evidence. Workspace destinations share an inset content surface with 20-point outer gutters; launch content is centered with a bounded width and generous margins.

The native learning guide has three short stages: Start coding, Review your work and Go further. It connects the basic coding flow to diffs/recovery, then to harness selection, evaluation and bounded optimization. Opening projects or following a guide never automatically starts a model call, installation or shell.

## Start coding

The Connect implementation and remaining real-account checks are tracked in the [Connect acceptance checklist](CONNECT-ACCEPTANCE.md).

Open a project, choose **Connect…**, select a connection, describe a change and press **Start coding** (Command–Return). The coding composer shows the current connection; harness/provider/model fields live under **Advanced routing**. Harness Hub, Evaluations and Optimization remain separate destinations for improving the setup after coding.

Connect now renders the terminal's shared connection profiles and ownership ladder:

- **Connect to an existing harness → Subscriptions** uses existing vendor login for supported ACP, CLI, SDK and Prime RPC routes. The agent owns the harness and model; no redundant model fields are shown.
- **Connect a harness with your model** selects Core, RLM, PiPy, CodeGem, Workbench or another HarnessSpec first, then its local model, API-key route or experimental plan guidance. Open/Closed and language browsing use the shared catalog. Catalog-supported ACP model attachment uses the declared provider allow-list and child credential variables.
- **Protocols** provides ACP agent selection, A2A Agent Card discovery and UHP server harness discovery. A2A accepts an existing bearer token, extra headers or client certificate/key paths; UHP accepts a bearer token. Manually supplied server credentials stay in engine memory for the app session. A2A can also run the shared OAuth browser/device flow; OAuth tokens use the existing local credential store. They are excluded from saved task requests and redacted from events and diagnostics. Remote tasks go directly to the selected server; task text and explicitly attached project files are sent to that server. The app does not automatically upload the project.
- **Build your own** offers preset loading, YAML import/editing and validated creation of a new repository HarnessSpec. Existing definitions are not overwritten. A guided builder uses the shared wizard schema. Native RLM settings and A2A routing forms create validated new harness revisions.

App-owned dialogs use a shared native AppKit modal presenter. They open at the centre of the display containing their parent window, including on displays with negative desktop coordinates. Nested sign-in dialogs preserve the parent modal session and asynchronous engine progress. Close, Escape and presentation bindings share one cleanup path. System file pickers and alerts keep their standard macOS behavior.

The connection header has Back and a root breadcrumb; Escape returns one level. Main navigation has Back and Command–[. Newly opened destinations start at the top. Model forms scroll independently of the fixed navigation controls.

Start with the coding agent you already use and have signed into in Terminal. Launcher detection is not proof of a working package, account or billing route. Explicit subscription paths remove known API-billing overrides; account access is checked by the vendor. Subscription model-plan entries that are experimental/unavailable in the terminal remain guidance, not fake working connections.

A2A/UHP support streamed responses, exact recorded remote continuation, and cancellation with server acknowledgement. Interrupted streams fail visibly; they are never silently replayed. Saved remote route descriptors survive app restart, but manually supplied credentials must be reconnected. Server capability and authentication determine which operations work. Supported vendor SDK/CLI routes resume when their runtime exposes a resumable thread.

Subscription entries expose the shared vendor login commands. Browser/device flows show progress in the app; commands that require an interactive terminal run the reviewed login command in an embedded native terminal. Reviewed catalog installation recipes require explicit confirmation and run with progress and cancellation. Vendor-specific API-key routes, Prime RPC attachment and SystemOne setup use their declared engine adapters. Credentials can be session-only or saved in Keychain where offered. Account/billing verification still belongs to the vendor.

ACP model, mode, select configuration options and advertised slash commands have native controls. Scope choices are shown only when the agent offers them; an Allow once click never selects Allow always.

For local inference, select an installed Ollama chat/coding model; for a provider route, enter its model ID and key. **Remember new key** stores it in macOS Keychain; otherwise it stays in local engine memory until exit. Other local engines remain inventory/manual terminal setup workflows. No agent installation or weight download starts just by selecting a connection.
The Keychain implementation uses app-owned generic passwords with synchronization disabled ([Apple API reference](https://developer.apple.com/documentation/security/ksecclassgenericpassword)). The Python service holds app-supplied keys in memory and passes them to worker environments, without putting them into job requests or preferences. App-managed keys are redacted from desktop events, check-result exports and worker diagnostics. Project content and other runtime artifacts can still be sensitive; review before sharing.

**Test model** sends a short prompt through the no-tool harness after a confirmation that explains possible provider charges. It uses the selected project's engine context. Saving a key alone never marks the connection verified. **Forget saved key** removes the native app's Keychain item and session override; existing terminal credentials are not deleted.

Ad hoc preview builds may cause macOS Keychain access prompts when the app changes. A stable Developer ID signing identity and clean-Mac upgrade tests are required before public distribution.

Full terminal parity is still incomplete; see the [feature coverage audit](FEATURE-COVERAGE.md). Branding and Mac App Store requirements are tracked in the [submission guide](app-store/README.md).

Application data defaults to `~/Library/Application Support/SuperQode`. Requests to configured model providers are made by the local engine. There is no SuperQode network listener, account or cloud history service.

## Native appearance

The Dock icon places the original mark on a polished, rounded glass tile with purple/pink/orange lighting, an inset rim and a soft cast shadow. Transparent outer corners preserve the native macOS silhouette; each of the ten icon sizes is rendered directly from the vector source.

The original logo supplies the purple `#7C1FE8`, pink `#E9198C` and orange `#FFA400` palette. Shared SwiftUI surfaces use neutral frosted materials, restrained borders and shadows. Brand colour is concentrated in the logo, wordmark and text accents. Navigation uses native Liquid Glass on macOS 26 or later and standard materials on macOS 14–15. Primary actions use native bordered buttons with neutral surfaces and contrast-adjusted brand text. macOS owns focus, keyboard, pressed and disabled behavior; Increase Contrast uses semantic system text. The sidebar wordmark uses the original logo palette. Functional UI labels have a minimum explicit size of 11 points, prose uses the system body font, and source/diff text remains monospaced.

Agent prose uses lighter gradient tints on dark backgrounds; fenced code, command output, diffs and the editor keep plain text colours. Turn gradient responses off in Settings. Light appearance and Increase Contrast use standard response text, and Reduce Transparency replaces material surfaces with solid panels. Navigation fades and an active-agent pulse can be disabled in Settings and respect Reduce Motion. There is no continuous shimmer or animated response text. Running-app visual/accessibility review is still required before release.

## Verification

```sh
python3 apps/macos/scripts/smoke-test.py
.venv/bin/python -m pytest tests/test_desktop_configuration.py tests/test_desktop_remote_streaming.py tests/test_desktop_connect_workflow.py tests/test_desktop_context.py tests/test_desktop_tools.py tests/test_desktop_service.py tests/test_acp_client.py tests/test_acp_permission_store.py tests/test_acp_session_store.py tests/test_harness_protocol.py tests/test_acp_server.py tests/test_web_server_auth.py tests/test_harness_eval_splits.py tests/test_harness_omni.py -q
```

The native smoke test launches the actual packaged SwiftUI application against an isolated temporary Git project and engine state. It checks pipe connectivity, shared Connect menus, previous-page navigation, catalogs, command streaming, setup evaluation, real harness task streaming and continuation against a loopback provider fixture. It also produces diagnostic view renders for each main destination; AppKit material/control rendering in these captures is not a substitute for visual inspection of the running app. It also verifies Keychain save/read/update/delete using an isolated dummy item, removes that item, and verifies session-only credentials reach the fixture without being recorded in engine state. The Python desktop suite additionally exercises a real local ACP agent fixture, including approved code writes, denied writes, host terminal execution and exact resume. Additional tests exercise a scripted subscription CLI subprocess with native approve/deny decisions and direct A2A/UHP server fixtures, including secret redaction, immutable server harness selection, catalog provider limits and safe HarnessSpec creation. No paid provider calls are made. These checks do not replace accessibility, real provider or clean-Mac testing.

## Distribution

Local builds are ad hoc signed. Set `SIGNING_IDENTITY` to an installed Developer ID identity for a distribution build. Verify nested runtime signing, notarize with your Apple credentials, staple the ticket and test the quarantined download on a clean Mac before publishing. See [release requirements](RELEASE.md).
