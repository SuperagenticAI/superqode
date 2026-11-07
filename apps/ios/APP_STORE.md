# App Store submission

This is the working checklist for submitting the SuperQode iOS companion, version 0.1.0 (build 1), bundle ID `dev.superqode.companion`. Nothing here uploads or publishes the app. Signing and upload are done by hand in Xcode and App Store Connect.

## Before you upload

| Item | State |
| --- | --- |
| Toolchain | Xcode 26 or newer with the iOS 26 SDK. App Store Connect has required it for uploads since 28 April 2026. |
| Deployment target | iOS 17.0, iPhone and iPad (`TARGETED_DEVICE_FAMILY = 1,2`). |
| Version | `MARKETING_VERSION = 0.1.0`, `CURRENT_PROJECT_VERSION = 1`. Raise the build number for every new upload. |
| Encryption | `ITSAppUsesNonExemptEncryption = NO` in `Resources/Info.plist`. The app uses only Apple's HTTPS and Keychain. |
| Privacy manifest | `SuperQode/PrivacyInfo.xcprivacy` declares UserDefaults (reason `CA92.1`), no tracking and no collected data. |
| Permissions | Camera only, requested when Scan is tapped. Photos use the system picker, which needs no permission. |
| App icon | Committed 1024 px PNGs without alpha: light (black field), dark (deep plum field) and tinted (grayscale). No build script generates icons. |
| Third-party logos | Shown by default for harnesses the user connected on the Mac. Set `SQGenericHarnessIcons` to `YES` in Info.plist, or build with the `STORE_GENERIC_HARNESS_ICONS` Swift flag, to show a generic symbol instead. |
| Privacy and support | In-app links in Settings, Help & about and in the Get started guide: https://superqode.dev/privacy and https://superqode.dev/support. Publish both pages before submitting; the text is in `store/privacy.md` and `store/support.md`. |
| Feature list | The in-app "What you can do on iPhone" list shows only workflows the phone can use. Mac-only work is described as staying on the Mac. |

## Signing and upload

1. Join the Apple Developer Program with the account that will own the app.
2. In Xcode, open Settings, Accounts and add that Apple account.
3. In the Certificates, Identifiers & Profiles portal, register the App ID `dev.superqode.companion`. No extra capabilities are needed. Keychain uses the app's default access group, and there is no entitlements file.
4. In App Store Connect, open Apps, New App. Choose iOS, name "SuperQode", primary language English (U.K.) or English (U.S.), bundle ID `dev.superqode.companion` and an SKU such as `superqode-ios`.
5. Open `apps/ios/SuperQodeCompanion.xcodeproj`, select the SuperQodeCompanion target, then Signing & Capabilities. Select your team and keep Automatically manage signing on.
6. Choose Any iOS Device (arm64), then Product, Archive. Or run `bash apps/ios/scripts/archive.sh --team YOURTEAMID --allow-provisioning`.
7. In Organizer, select the archive, Validate App, then Distribute App, App Store Connect, Upload.
8. When the build has processed, add it to TestFlight for an internal test on a real iPhone paired with a real Mac. Then attach it to version 0.1.0 and Submit for Review.

## App information

| Field | Draft |
| --- | --- |
| Name (30) | SuperQode |
| Subtitle (30) | Your Mac's coding agents |
| Category | Developer Tools (secondary: Productivity) |
| Price | Free, no in-app purchases |
| Copyright | 2026 Superagentic AI |
| Support URL | https://superqode.dev/support |
| Privacy policy URL | https://superqode.dev/privacy |
| Marketing URL | https://superqode.dev |
| Contact email | info@super-agentic.ai |

Promotional text (170):

> Start, steer and review coding agents running on your own Mac. Private by design: your iPhone talks straight to your Mac over your own Tailscale network.

Keywords (100):

> coding,agent,harness,developer,code review,evaluation,mac,remote,tailscale,ai,llm,local model,git

Description:

> SuperQode on iPhone is the companion to SuperQode on your Mac. Pick up your coding work from your phone: start a task, follow an agent as it works, approve or deny the exact action it asks for, steer it, or stop it.
>
> Your Mac does the work. Projects, provider keys and job history stay on your Mac. The iPhone connects straight to it over your own Tailscale network. SuperQode runs no cloud relay for your prompts, files or results.
>
> What you can do on iPhone:
> - Code and plan: start a conversation with any harness and model the Mac has shared, attach project files and screenshots, and continue the thread later.
> - Review: read working-tree and branch diffs, leave line feedback and, with permission, stage files.
> - Evaluate: run a bundled suite against a harness and compare baseline and candidate results task by task.
> - Optimize: stage an optimization run within the limits set on the Mac, then inspect its evidence.
> - Keep track: activity, approvals, task queue, checkpoints and WorkOrders from the same Mac.
>
> Private and in your control:
> - Pairing uses a one-time invitation you approve on the Mac.
> - Each iPhone gets its own grant, which expires after 30 days and can be revoked from the Mac at any time.
> - Drafts stay protected on the phone and are excluded from backups.
> - Choose Local only when you want a verified local model to do the work.
>
> Requires SuperQode on a Mac with Private remote access turned on, and Tailscale on both devices. Cloud models receive prompts from the providers you configure on the Mac. Not on a Mac yet? Tap "Explore the app with sample data" to look around.

What's New (0.1.0):

> First release of the SuperQode iPhone and iPad companion.

## Age rating

Answer the questionnaire for what the app does: no advertising, no user-to-user messaging, no unrestricted web access, no gambling, no mature content of its own. Conversations show text produced by models the user configured on their own Mac. Answer the generative AI question honestly for that, then review the rating App Store Connect proposes before you accept it.

## App Privacy (nutrition label)

Choose **Data Not Collected**. The developer receives no data from the app. Prompts, files and results travel only between the user's own iPhone and their own Mac. Any cloud model is the user's own provider account, configured on the Mac, and is not a service the app sends data to. There are no analytics, ads or tracking SDKs, and no third-party packages.

## Review notes

Paste into App Review Information, Notes:

> SuperQode for iPhone is a companion to SuperQode running on the user's own Mac. It has no hosted backend and no accounts of its own. The phone connects only to the user's Mac over the user's own Tailscale private network, and the Mac must approve each iPhone.
>
> To review without a Mac: on the first screen, scroll down and tap "Explore the app with sample data". Explore mode is clearly labelled, runs offline with built-in sample data, and cannot start real work. Suggested path:
> 1. Projects: open the "SuperQode Studio" sample workspace on "Studio Mac".
> 2. Tap New thread to see the composer, the harness and model picker, and the Code, Plan and Chat modes.
> 3. Open a sample conversation to see streamed output, a code diff and an action waiting for approval.
> 4. Open Harness lab to see evaluation results and a staged optimization.
> 5. Open Settings to see the connection, appearance, data controls and the privacy and support links.
> 6. Tap the grid button on Projects to see "What you can do on iPhone".
>
> Real use needs SuperQode on a Mac with Private remote access turned on and the free Tailscale app on both devices. The camera is used only to scan the pairing QR code shown on the Mac. A screen recording of a real Mac and iPhone pairing and running a task is available on request, and we can join a call if that helps.
>
> Harness logos are shown only for tools the user has installed and connected on their own Mac, to identify them.

No demo account is needed: the app has no sign-in. Leave "Sign-in required" unchecked.

Demo video: record about 60 to 90 seconds on a real device, showing the Mac creating an invitation, the iPhone scanning it, the Mac approving the iPhone, then a task started on the phone appearing on the Mac with an approval. Upload it as an unlisted link and paste the link into the review notes, or send it when App Review asks.

## Screenshots

App Store Connect needs these sizes. Each can have up to 10 screenshots; 3 to 6 is a good set.

| Display | Device to capture on | Portrait size |
| --- | --- | --- |
| iPhone 6.9" (required) | iPhone 17 Pro Max, 16 Pro Max or 15 Pro Max (or Simulator) | 1320 x 2868 (1290 x 2796 also accepted) |
| iPad 13" (required while iPad is supported) | iPad Pro 13-inch (M4 or M5) or iPad Air 13-inch (or Simulator) | 2064 x 2752 (2048 x 2732 also accepted) |

Smaller iPhone and iPad sizes are scaled from these automatically.

Screens to capture, in this order. Use dark appearance for most, and one in light:

1. Projects: a workspace with an active run and the Code, Review, Evaluate and Optimize actions.
2. Conversation: an agent's answer with highlighted code and a diff.
3. Approval: an action waiting for approval with Approve once and Deny.
4. New thread: the harness and model picker open.
5. Harness lab: evaluation results comparing baseline and candidate.
6. Pairing: the Get started screen with Scan Mac invitation.
7. Projects in light appearance.

Tips: use real projects or the sample workspace with clean names. Explore mode shows an "Explore mode, sample data" label; that is accurate, but captures from a real paired Mac look better. In Simulator, run `xcrun simctl status_bar booted override --time 9:41 --batteryState charged --batteryLevel 100 --wifiBars 3` for a clean status bar, then File, Save Screen (Cmd+S).

The CI workflow `Private iOS companion` captures pairing, projects (dark and light), conversation, evaluation and harness lab screens at 1206 x 2622 (iPhone 6.3"). Those are useful for checking layout, but they are not an accepted upload size.

## After approval

- Choose manual release, so you can publish the website pages and release notes first.
- Tag the release in this repository and note the App Store version in `CHANGELOG.md`.
