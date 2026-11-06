# iOS signing and distribution

The iOS app stays in this repository under the repository's Apache 2.0 license. It has its own Xcode target and signing identity. Its source does not require a hosted SuperQode service or embedded Apple credentials.

## Where accounts belong

| Account or credential | Where to configure it |
| --- | --- |
| Apple Developer account | Xcode Settings, Accounts; sign in there on your Mac |
| Apple development team | Select your team under the iOS target's Signing & Capabilities |
| Bundle identifier | The iOS target in Xcode; register the matching app in App Store Connect |
| Signing certificates/private keys | Xcode-managed signing and your Mac's Keychain |
| Tailscale account | The Tailscale app on the Mac and iPhone |
| Model keys and agent subscriptions | SuperQode on the Mac, as with existing desktop connections |
| Companion device authorization | Created by pairing; stored in the iPhone's device-only Keychain |

Do not put an Apple password, signing private key, App Store Connect `.p8` key or provider token in this repository. No Apple API key is needed for local development through Xcode. This project does not upload an archive automatically.

## Build without an Apple account

On a Mac with Xcode 16 or newer, open `SuperQodeCompanion.xcodeproj`, select an iPhone simulator and Run. Simulator CI uses ad-hoc signing, which allows the Keychain tests to exercise real secure storage. Tap **Explore the app with sample data** to inspect the complete interface without Tailscale or a connected Mac. Explore mode is clearly labelled, runs offline and cannot execute tasks.

The icon preparation build phase reuses the existing Mac icon and makes its square background opaque for iOS. The original logo files and purple, pink and orange artwork are retained. No third-party iOS packages are needed.

## Install on your own iPhone

1. Add your Apple account in Xcode Settings, Accounts.
2. Open the project, select the SuperQodeCompanion target, then Signing & Capabilities.
3. Select your team, enable automatic signing and choose a bundle ID registered to that team. The supplied ID is `dev.superqode.companion`; choose your own if it is unavailable.
4. Connect the iPhone, enable Developer Mode if iOS asks, select it in Xcode and Run.
5. Pair to the matching Mac build using its Private remote access settings. Test over mobile data with Tailscale enabled.

An Apple Developer Program membership is needed for TestFlight and App Store distribution. A personal team can be used for development subject to Apple's device and expiry limits.

## Create a release archive later

Use Xcode Product, Archive, or run:

```bash
bash apps/ios/scripts/archive.sh --team YOURTEAMID --bundle-id your.registered.bundle.id
```

Replace `YOURTEAMID` with your actual 10-character Team ID, not an account password. Configure signing once in Xcode, or explicitly add `--allow-provisioning` if you want Xcode to contact Apple to create/update provisioning profiles. The script preserves existing archives and never uploads or publishes a build.

Open the `.xcarchive` in Organizer, Validate App, and choose your distribution option. In App Store Connect, create the app using the same bundle ID and supply store metadata, support/privacy URLs, age rating, encryption answers and release notes. No public release has been created by this implementation.

## Review and release checks

Read [PARITY.md](PARITY.md) before describing mobile capabilities. The app highlights daily coding, review, evaluation and optimization; its inventory explicitly marks partial, preview and Mac-only workflows. Run `python3 apps/ios/scripts/audit-parity.py --check` when Mac navigation or Tools categories change.

- Run the iOS unit tests, including the isolated Keychain test, submission recovery and draft-protection tests. Review dark/light simulator captures.
- Install on a physical iPhone/iPad and check camera pairing, protected drafts, text input, large accessibility text, rotation, VoiceOver and reconnection.
- Verify revision-bound review feedback, stale-diff refusal and optional staging with both read-only and Review-enabled device grants. Confirm attached context contains only selected project files.
- Compare a real baseline/candidate run, including regressions, incomplete grading and missing cost records. Check WorkOrders, queue and checkpoint inspection against the Mac; their management stays there.
- Verify cellular access, Mac engine restart, sleep/wake behavior, approvals, stop, grant expiry and revocation with a real Tailscale account.
- Check a real installed local model and any vendor harnesses you intend to list as supported. No universal control of other apps' private sessions is claimed.
- Resolve failing Mac-side release checks before distributing the companion as public-ready. The preview branch previously recorded inconsistent Mac navigation timing; keep that gate visible.
- Review the app's privacy disclosures against the actual distribution. App preferences use UserDefaults for appearance. Device grants are not synced; draft files are protected and excluded from backups. Requested output is displayed on the phone; cloud agents can contact their providers.

For App Review, explain that this is a companion to a user-owned Mac with private Tailscale access. Reviewers can inspect the interface using the labelled, read-only Explore mode without accounts. Supply any additional hardware demonstration, access or video Apple requests through App Store Connect. Explore mode is not evidence that real-device networking has been verified.

The application provides coding, review, evaluation and supported staged optimization. Background push notifications, raw terminal sessions, provider installation, model downloads and direct candidate adoption remain outside the phone interface. Do not advertise those as shipped mobile features.
