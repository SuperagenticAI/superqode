# SuperQode iOS companion

The companion controls SuperQode running on your own Mac over private Tailscale HTTPS. It uses no hosted SuperQode backend. The Mac keeps execution, provider credentials, project files and recorded job history. Prompts and results travel between authorized devices over the private connection. Cloud agents still use their configured providers.

This is a new source-build preview, not the released macOS/Python version or a published iOS app. It requires the Mac source from the same branch. iOS 17 or newer and Xcode 16 or newer are required. Native builds and real-device behavior must be verified before distribution.

## Build

Open `apps/ios/SuperQodeCompanion.xcodeproj`, select the `SuperQodeCompanion` scheme and an iPhone simulator, and Run. There are no third-party iOS package dependencies. For a physical iPhone, choose your own development team and signing identity in Xcode. The app reuses the original Mac logo, icon and purple/pink/orange palette, with light/dark themes and native Dynamic Type and the same bundled harness logos as the Mac. Tap **Explore the app with sample data** to browse without accounts or a connected Mac; sample actions cannot execute. See [RELEASE.md](RELEASE.md) for Apple account setup, physical-device signing and the local archive helper.

Account-free simulator verification with ad-hoc signing (required for Keychain access):

```bash
xcodebuild test \
  -project apps/ios/SuperQodeCompanion.xcodeproj \
  -scheme SuperQodeCompanion \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  CODE_SIGN_IDENTITY=- CODE_SIGNING_ALLOWED=YES
```

Choose an installed simulator name using `xcrun simctl list devices available`. The `Private iOS companion` GitHub workflow chooses an installed iPhone automatically. Signing, App Store metadata and device distribution remain separate release work; this branch does not publish anything.

## Pair a Mac and iPhone

1. Install [Tailscale](https://tailscale.com/download) on both devices and join your own private network. Review tailnet access rules so only the intended people/devices can reach the Mac's service. Do not use a shared SuperQode-operated tailnet.
2. In the source-built Mac app, open Settings, Private remote access, Set up iPhone companion. Enable the existing background engine. Agent work then survives closing the app; a restart, logout or sleeping Mac can still interrupt access.
3. Configure [Tailscale Serve](https://tailscale.com/docs/features/tailscale-serve) with the Mac's Configure private Serve button, or use the displayed command when vendor approval or manual setup is needed. Verify the connection in the app. The gateway listens only on `127.0.0.1:47831`; Serve provides private HTTPS at `https://your-mac.your-tailnet.ts.net:47832`. Use the exact address shown by the Mac, including the port. The dedicated private port leaves another app's Serve service on port 443 intact. Configuration is explicit: the app does not install a VPN, replace other Serve services or enable public Funnel.
4. Open a project and select the harness/provider/model on the Mac. Share that connection. Local inference only currently requires Core or No-tool with a verified loopback model binding created through Local AI. Other agents can be shared with an explicit provider/agent-managed inference setting.
5. Enable private remote access, select the connections this phone can access, and create a five-minute invitation. Scan the QR in the companion or enter the private address and code manually. Camera permission is requested only when Scan is tapped.
6. Approve the pending request on the Mac, checking the Tailscale identity and device name. The invitation is single-use, and a separate secret is required to claim its outcome. Device credentials expire after 30 days, are hashed on the Mac and stored in this iPhone's device-only Keychain. Tokens never appear in URLs or normal preferences.
7. Disable iPhone Wi-Fi and verify over mobile data with Tailscale enabled. Create a task, check it appears on the Mac, inspect output, approve/deny an exact action and stop the same job from either device. Close/reopen the phone app and verify the recorded state returns without resubmitting the task. Revoke the device on the Mac and confirm access is refused.

Keep the Mac awake, online and logged in. The preview does not silently change sleep settings or install a login helper. Tailscale Serve must add user identity headers, so tagged nodes are intentionally unsupported. Public Funnel lacks those headers and is refused even if enabled after initial setup. Loopback is the proxy trust boundary; other processes already running as the same Mac user remain within that local trust boundary.

## Implemented surfaces

| Capability | Companion behavior |
| --- | --- |
| Projects | Only explicitly shared project connections |
| New tasks and conversations | Code, Direct Chat for local/API model connections, and supported Plan mode; each new composer starts with no selected connection |
| Conversation library | Search, pagination, pinned/archived views and scoped rename/pin/archive |
| Protected drafts | Device-only unsent text and experiment requests, explicit resume, original request ID retained after interrupted submission |
| Presentation | Original branding, light/dark themes, native markdown, selectable highlighted code and colored diffs |
| Existing jobs | Shared Mac job history, paged events, transcript, progress, status and continuation |
| Approvals | Exact current request, approve once or deny; confirmation captures the reviewed request |
| Live steering and stop | Uses the existing runtime capability and cancellation checks |
| Project review | Read-only files, working-tree status and diffs; existing path/sensitive-file checks apply |
| Evaluation | Bundled suites, verifier inspection, setup validation and explicitly authorized live execution |
| Optimization | Explicit Mac-configured reflection/optimizer models, evaluation/cost limits and staged evidence; no remote adoption |
| Harness selection | Routes explicitly configured and shared by the Mac, including existing supported native/ACP/protocol routes |
| Device access | Mac-approved pairing, network-identity binding, scoped permissions, expiry, local audit and revocation |

Local-only optimization is disabled until separate reflection/optimizer routes can be verified locally. It never silently uses the optimizer's cloud defaults. Custom evaluation-suite selection and candidate setup stay on the Mac. A task may edit/run commands according to its harness; the read-only project viewer is not a global read-only execution guarantee. Opaque agents retain their own permission system, which is labelled explicitly.

## Compatibility

The phone is a client of SuperQode's engine, not a remote-control driver for every other app. It can use supported agent routes already configured on the Mac, with credentials retained there.

- Codex: existing SuperQode Codex SDK/ACP connections can be shared. This does not provide arbitrary control of the Codex desktop app's private live sessions.
- Omnigent: the architecture follows its private Serve pattern. Direct Omnigent server integration is not claimed. A future documented adapter or compatible ACP route can reuse the same engine boundary.
- T3 Code, Orca and other GUIs: no undocumented control API is assumed. Integration requires a documented protocol/adapter and verification. The names alone do not establish compatibility.
- Other clients can implement the documented companion HTTP contract and receive their own Mac-approved device grant. This is SuperQode protocol 1, not a claim of wire compatibility with another vendor's API.

The review reference is [Omnigent's private access guide](https://github.com/omnigent-ai/omnigent/blob/main/deploy/tailscale/README.md). No Omnigent source was copied.

## API and boundaries

All endpoints are served through private HTTPS. The loopback backend accepts the configured private hostname, rejects foreign browser origins and requires Serve's `Tailscale-User-Login` in addition to its own device authorization. Do not expose this listener through another proxy that accepts client-supplied identity headers.

- `POST /v1/pair`: `{ "code": "<invitation>", "name": "My phone" }` returns a pending `id`, secret `claim` and expiry. Only a locally approved, unexpired invitation can begin pairing.
- `POST /v1/pair/claim`: `{ "id": "<pending>", "claim": "<secret>" }` returns pending/denied/approved state. Approval returns an opaque `token` and device ID. Claim responses remain retrievable only with that secret and network identity until the five-minute invitation expires, allowing recovery of a lost response.
- `POST /v1/rpc`: `{ "method": "companion.catalog", "params": {} }`, using `Authorization: Bearer <device-token>`. Success is `{ "result": ... }`; failure is `{ "error": "repair message" }` with a non-2xx status.
- Mutations require a unique `Idempotency-Key`. Reuse it only for the exact same request. A changed payload is rejected. An uncertain action is not automatically executed again; inspect activity first.

The catalog returns protocol version, device expiry, permission names, approved profiles, built-in suites and supported feature descriptions. Read methods: `companion.request_status`, `projects.list`, `jobs.list`, `jobs.get`, `threads.list`, `threads.get`, `conversations.get`, `files.list`, `files.read`, `git.status`, `experiments.list`, `evals.inspect`. Mutations: `threads.update`, `tasks.start`, `evaluations.start`, `optimizations.start`, `jobs.approve`, `jobs.cancel`, `jobs.steer`. See `remote_rpc.py` for exact parameter allowlists. Start requests select `profile`; they cannot inject a provider, model, shell command, endpoint, credential or permission override.

`companion.request_status` takes the original `{ "key": "<idempotency-key>" }` and returns `not_recorded`, `uncertain`, `accepted` or `completed`, with an existing result when available. It never replays a command and is scoped to the same device and currently shared project. Coding and experiment composers save the immutable original payload and key before submission, offers an explicit status check, and reuses them for retries. A new conversation always starts blank; saved drafts are resumed separately. Drafts are protected files excluded from backups, capped at 20 entries/4 MiB, and can be cleared in Settings.

The local management methods begin with `remote.` and are only available through the existing native control pipe/private engine socket. They cannot be called through the HTTP RPC endpoint. The phone cannot open arbitrary projects, change provider credentials, invoke generic CLI commands, commit/merge code, restore checkpoints or adopt optimization candidates.

Requests, response sizes, active connections and pairing attempts are bounded. API responses are not cached. Known managed credentials are redacted from returned data. Job origin and mutation audit records contain device identity and action, not pairing or bearer secrets. Mac-side device revocation is authoritative; Disconnect on the phone removes its local Keychain credential. This preview pairs one Mac at a time.

## Remaining release validation

Run the existing macOS build/tests plus the ad-hoc signed iOS simulator workflow and the account-free `tests/test_desktop_companion.py` suite (`.venv/bin/python -m pytest tests/test_desktop_companion.py`). The iOS workflow runs real Keychain, connection lifecycle, draft recovery, markdown/highlighting tests and UI checks for blank conversations and collapsed approval details, and captures pairing, workspace, conversation and harness-lab screens. These tests use isolated sample data, not a real private Mac connection. A real Mac/iPhone pair must verify Tailscale variants, trusted HTTPS, camera pairing, Keychain, cellular access, repeated disconnect/reconnect, foreground/background transitions, sleep/wake, engine restart and credential revocation.

This preview does not include APNs/background push, raw terminal sessions, remote provider installation, local model downloads, harness editing, commits/merges or candidate adoption. Those remain Mac workflows. Do not advertise full mobile feature parity or universal external-app compatibility until the remaining surfaces and vendor-specific paths are implemented and verified.
