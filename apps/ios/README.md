# SuperQode iOS companion

The companion controls SuperQode running on your own Mac over private Tailscale HTTPS. It uses no hosted SuperQode backend. The Mac keeps execution, provider credentials, project files and recorded job history. Prompts and results travel between authorized devices over the private connection. Cloud agents still use their configured providers.

Version 0.1.0 (build 1) is prepared for App Store submission. It needs a SuperQode Mac build that includes Private remote access. The app runs on iOS 17 or newer, on iPhone and iPad. Building it needs Xcode 26 or newer with the iOS 26 SDK, which App Store Connect requires for uploads. See [APP_STORE.md](APP_STORE.md) for store metadata, review notes, screenshots and signing.

## Build

Open `apps/ios/SuperQodeCompanion.xcodeproj`, select the `SuperQodeCompanion` scheme and an iPhone simulator, and Run. There are no third-party iOS package dependencies. For a physical iPhone, choose your own development team and signing identity in Xcode. The iPhone and the Mac use the same SuperQode icon and purple, pink and orange palette. The icon fills its square, and the system applies the rounded mask. Light mode uses the black icon, dark mode uses a deep plum version of the same mark, and a tinted Home Screen uses a grayscale version. The icon PNGs are committed in the asset catalog; there is no build-time icon script. It includes light and dark themes, native Dynamic Type, VoiceOver labels and the same bundled harness logos as the Mac. To show a generic symbol instead of third-party harness logos, set `SQGenericHarnessIcons` to `YES` in `Resources/Info.plist` or add `STORE_GENERIC_HARNESS_ICONS` to the target's Swift compilation conditions. The default keeps the logos. Tap **Explore the app with sample data** to browse without accounts or a connected Mac; sample actions cannot execute. See [RELEASE.md](RELEASE.md) for Apple account setup, physical-device signing and the local archive helper.

Account-free simulator verification with ad-hoc signing (required for Keychain access):

```bash
xcodebuild test \
  -project apps/ios/SuperQodeCompanion.xcodeproj \
  -scheme SuperQodeCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro Max' \
  CODE_SIGN_IDENTITY=- CODE_SIGNING_ALLOWED=YES
```

Choose an installed simulator name using `xcrun simctl list devices available`. The `Private iOS companion` GitHub workflow chooses an installed iPhone automatically. Signing and upload are manual steps in Xcode; nothing in this repository publishes the app.

## Pair a Mac and iPhone

1. Install [Tailscale](https://tailscale.com/download) on both devices and join your own private network. Review tailnet access rules so only the intended people/devices can reach the Mac's service. Do not use a shared SuperQode-operated tailnet.
2. In the SuperQode Mac app, open Settings, Private remote access, Set up iPhone companion.
3. Click **Connect this Mac**. SuperQode starts Tailscale when it is already installed and you are signed in, then publishes the private link. Install Tailscale first when the Mac says it is missing. No Terminal command is required. Public Funnel stays off, and another app's Tailscale service is left unchanged. The private address shown by the Mac is the one the iPhone uses. Agent work continues while the Mac app is open; a restart, logout or sleeping Mac can still interrupt access. Keeping access after you quit SuperQode is optional and reconnects the Mac app.
4. Share at least one project, enable private remote access, turn on the projects this phone may open and create a five-minute invitation. Scan the QR in the companion or enter the private address and code manually. Camera permission is requested only when Scan is tapped.
5. Share each project once. Later harness, provider and model changes on the Mac update that project for the phone. The phone can switch to the harnesses you allow for that project on the Mac, and that change updates the Mac while the project is open. A project shared after pairing appears on a phone you already paired when you turn Show on iPhone on for that project. Rebuilding the iPhone app does not add it. Local inference only starts off. Turn it on only for Core or No-tool with a verified loopback model binding created through Local AI.
6. Approve the pending request on the Mac, checking the Tailscale identity and device name. The invitation is single-use, and a separate secret is required to claim its outcome. Device credentials expire after 30 days, are hashed on the Mac and stored in this iPhone's device-only Keychain. Tokens never appear in URLs or normal preferences.
7. Disable iPhone Wi-Fi and verify over mobile data with Tailscale enabled. Create a task, check it appears on the Mac, inspect output, approve/deny an exact action and stop the same job from either device. Close/reopen the phone app and verify the recorded state returns without resubmitting the task. Revoke the device on the Mac and confirm access is refused.

Keep the Mac awake, online and logged in. SuperQode does not silently change sleep settings or install a login helper. Tailscale Serve must add user identity headers, so tagged nodes are intentionally unsupported. Public Funnel lacks those headers and is refused even if enabled after initial setup. Loopback is the proxy trust boundary; other processes already running as the same Mac user remain within that local trust boundary.

## Implemented surfaces

Code, Review, Evaluate and Optimize are prominent workspace actions. The in-app **What you can do on iPhone** list links to working phone surfaces only. See [PARITY.md](PARITY.md) for the source audit covering all 14 Mac navigation areas and 24 Tools categories. This coverage is an inventory, not a claim of full feature parity.

| Capability | Companion behavior |
| --- | --- |
| Projects | Only projects the Mac shared and turned on for this phone. The phone can switch a project's harness only to the harnesses allowed on the Mac: by default the shared harness plus SuperQode's built-in harnesses, which keep the Mac's model. Paid subscriptions and cloud agents stay off until allowed on the Mac. |
| New tasks and conversations | Code, Direct Chat for local/API model connections, and supported Plan mode; each new composer starts with no selected connection |
| Conversation library | Search, pagination, pinned/archived views and scoped rename/pin/archive |
| Protected drafts | Device-only unsent text, file edits, protected image attachments and experiment requests, explicit resume, original request ID retained after interrupted submission |
| Presentation | Original branding, light/dark themes, native markdown, selectable highlighted code and colored diffs |
| Existing jobs | Shared Mac job history, paged events, transcript, progress, status and continuation |
| Approvals | Exact current request, approve once or deny; confirmation captures the reviewed request |
| Live steering and stop | Uses the existing runtime capability and cancellation checks |
| Project review | Working-tree, branch and completed-turn diffs; revision-bound line feedback; file staging only with a separately approved Review grant |
| File editing and images | Revision-bound file editing/creation; four protected image attachments with idempotent, device/project-scoped uploads |
| Portable evidence | Thread handoff and bounded Markdown, JSON and HTML exports |
| Explicit context | Select up to ten project text files, inspect the assembled input and retain attachments in protected drafts |
| Project operations | Inspect WorkOrders, workers, budgets and checks; queued jobs; saved checkpoint diffs. Queue controls and sealed checkpoint undo/redo/restore require separate Mac-approved grants; WorkOrder management stays on the Mac |
| Evaluation | Bundled suites, verifier inspection, split selection, setup validation, explicitly authorized live execution and recorded task-level baseline/candidate comparisons |
| Optimization | Explicit Mac-configured reflection/optimizer models, evaluation/cost limits and staged evidence; no remote adoption |
| Harness selection | Routes explicitly configured and shared by the Mac, including existing supported native/ACP/protocol routes |
| Device access | Mac-approved pairing, network-identity binding, scoped permissions, expiry, local audit and revocation |

Local-only optimization is disabled until separate reflection/optimizer routes can be verified locally. It never silently uses the optimizer's cloud defaults. Custom evaluation-suite selection and candidate setup stay on the Mac. A task may edit/run commands according to its harness; the project viewer is not a global read-only execution guarantee. Opaque agents retain their own permission system, which is labelled explicitly.

## Compatibility

The phone is a client of SuperQode's engine, not a remote-control driver for every other app. It can use supported agent routes already configured on the Mac, with credentials retained there.

- Codex: existing SuperQode Codex SDK/ACP connections can be shared. This does not provide arbitrary control of the Codex desktop app's private live sessions.
- Other desktop apps are not remote-controlled from the phone. A route is available only when SuperQode already has a documented adapter for it on the Mac.
- Other clients can implement the documented companion HTTP contract and receive their own Mac-approved device grant. This is SuperQode protocol 1.

## API and boundaries

All endpoints are served through private HTTPS. The loopback backend accepts the configured private hostname, rejects foreign browser origins and requires Serve's `Tailscale-User-Login` in addition to its own device authorization. Do not expose this listener through another proxy that accepts client-supplied identity headers.

- `POST /v1/pair`: `{ "code": "<invitation>", "name": "My phone" }` returns a pending `id`, secret `claim` and expiry. Only a locally approved, unexpired invitation can begin pairing.
- `POST /v1/pair/claim`: `{ "id": "<pending>", "claim": "<secret>" }` returns pending/denied/approved state. Approval returns an opaque `token` and device ID. Claim responses remain retrievable only with that secret and network identity until the five-minute invitation expires, allowing recovery of a lost response.
- `POST /v1/rpc`: `{ "method": "companion.catalog", "params": {} }`, using `Authorization: Bearer <device-token>`. Success is `{ "result": ... }`; failure is `{ "error": "repair message" }` with a non-2xx status.
- Mutations require a unique `Idempotency-Key`. Reuse it only for the exact same request. A changed payload is rejected. An uncertain action is not automatically executed again; inspect activity first.

The catalog returns protocol version, device expiry, permission names, approved profiles, built-in suites and supported feature descriptions. Read methods: `companion.request_status`, `projects.list`, `jobs.list`, `jobs.get`, `threads.list`, `threads.get`, `conversations.get`, `files.list`, `files.read`, `git.status`, `experiments.list`, `evals.inspect`, `review.list`, `review.diff`, `review.feedback`, `checkpoints.list`, `checkpoints.diff`, `queue.list`, `workorders.snapshot`, `context.preview`, `conversations.share`, `jobs.export`. Mutations: `review.stage`, `files.write`, `files.create`, `images.upload`, `images.remove`, `queue.add/run/pause/move/remove/retry`, `checkpoints.undo/redo/restore`, `threads.update`, `tasks.start`, `evaluations.start`, `optimizations.start`, `jobs.approve`, `jobs.cancel`, `jobs.steer`. See `remote_rpc.py` for exact parameter allowlists. File staging requires the optional `review` permission, disabled by default; existing grants do not gain it. Feedback prepares a draft and never executes automatically. Start requests select `profile`; they cannot inject a provider, model, shell command, endpoint, credential or permission override.

`companion.request_status` takes the original `{ "key": "<idempotency-key>" }` and returns `not_recorded`, `uncertain`, `accepted` or `completed`, with an existing result when available. It never replays a command and is scoped to the same device and currently shared project. Coding and experiment composers save the immutable original payload and key before submission, offers an explicit status check, and reuses them for retries. A new conversation always starts blank; saved drafts are resumed separately. Drafts are protected files excluded from backups, capped at 20 entries/4 MiB, and can be cleared in Settings.

The local management methods begin with `remote.` and are only available through the existing native control pipe/private engine socket. They cannot be called through the HTTP RPC endpoint. The phone cannot open arbitrary projects, change provider credentials, invoke generic CLI commands, commit/merge code or adopt optimization candidates.

Requests, response sizes, active connections and pairing attempts are bounded. Image uploads use `/v1/images` with a 6 MiB JSON limit; file writes use `/v1/files` with a 2 MiB limit and the existing 1 MB text limit. These endpoints retain the same authentication and accept only their named methods. Ordinary RPC bodies remain limited to 160 KiB. Protected draft images have a separate 64 MiB device storage cap; draft metadata remains capped at 4 MiB. API responses are not cached. Known managed credentials are redacted from returned data. Job origin and mutation audit records contain device identity and action, not pairing or bearer secrets. Mac-side device revocation is authoritative; Disconnect on the phone removes its local Keychain credential. The companion pairs one Mac at a time.

## Release validation

Run the existing macOS build/tests plus the ad-hoc signed iOS simulator workflow and the account-free `tests/test_desktop_companion.py` suites (`.venv/bin/python -m pytest tests/test_desktop_companion.py tests/test_desktop_companion_workflows.py tests/test_ios_feature_parity.py`). Run `python3 apps/ios/scripts/audit-parity.py --check` to detect inventory drift. The iOS workflow runs real Keychain, connection lifecycle, draft recovery, markdown/highlighting tests and UI checks for blank conversations and collapsed approval details, and captures pairing, workspace, conversation, evaluation and harness-lab screens. These tests use isolated sample data, not a real private Mac connection. A real Mac/iPhone pair must verify Tailscale variants, trusted HTTPS, camera pairing, Keychain, cellular access, repeated disconnect/reconnect, foreground/background transitions, sleep/wake, engine restart and credential revocation.

The companion does not include APNs/background push, raw terminal sessions, remote provider installation, local model downloads, harness editing, commits/merges or candidate adoption. Those remain Mac workflows. Do not advertise full mobile feature parity or universal external-app compatibility until the remaining surfaces and vendor-specific paths are implemented and verified.
