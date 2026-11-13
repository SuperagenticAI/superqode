# Mac and Model Studio validation for the next build

The source fixes are checked in for the Mac validation system. CI was stopped
at the user's request; do not treat the latest native refactor as validated by CI.

## Implemented changes

- Antigravity Managed Agent uses the closed/API-key catalog and Harness Hub,
  separate from subscription sign-in and billing.
- Local AI keeps its Quick Start, installed-model and runtime-profile drafts
  in memory while hidden content is removed from layout. Keys in unsaved forms
  are not serialized. Busy flags and modal windows remain local to the view.
- Native menus reuse catalog entries instead of rebuilding large SwiftUI menus.
- Quick Start has a real jump button for Runtimes & performance. The native
  smoke test uses that button and checks an unsaved endpoint across navigation.
- The existing 250 ms first-open/warm timing limits and hidden-input checks
  remain unchanged. First-open failures also enable diagnostic profiling.
- Model Studio retains region/workspace routing, preview-key isolation,
  pagination, reasoning history and streamed token usage. The Mac model picker
  now displays available limits/tool metadata, unknown pricing and required
  reasoning. DeepSeek V4 Pro and V4.1 Flash 1017 aliases use the thinking adapter.

## Native validation

Run from a clean checkout on the Mac:

```bash
swift test --build-system native --package-path apps/macos -c release
native_bin="$(swift build --build-system native --package-path apps/macos -c release --show-bin-path)"
python3 apps/macos/scripts/check-apple-model.py --helper "$native_bin/SuperQodeAppleModel" --require-available
```

The availability requirement needs a supported Mac with Apple Intelligence and
model assets ready. Build the bundled app using the existing macOS README, then
run `python3 apps/macos/scripts/smoke-test.py`. Run its Strands variant with the
separately configured runtime as described by the existing native workflow.

Manually enter a local runtime name, endpoint and context; choose a local model
and harness; navigate to another section and back, then to Advanced and back.
Verify the unsaved values survive, hidden controls cannot receive typing, and
typing/navigation remain responsive. Do not save the synthetic smoke endpoint.

The earlier native runs passed 194 Swift tests and functional draft retention,
but exceeded the navigation budget in some first-open cases. The final
data/view-lifetime refactor still needs the Mac build and timing checks.

## Model Studio account smoke

Use a disposable project and a real metered key from the selected region.
Keep credentials in the app/Keychain or local credential configuration, not
in this repository or shared test logs.

1. Select Provider API key, then Qwen International or Qwen China. Enter the
   corresponding workspace endpoint ending in `/compatible-mode/v1`.
2. Enter a key and load workspace models before saving. Confirm the previous
   saved key/endpoint are unchanged by this preview. Changing either field must
   discard an outstanding lookup's stale result.
3. Select Qwen, GLM or DeepSeek from the actual workspace catalog. Check any
   advertised limits/tool support. Unknown metadata and prices must remain
   unknown; catalog inclusion does not prove entitlement.
4. Save with session-only credentials first. Test model verifies basic inference;
   then use a tiny coding task with the normal permission prompts to check tools.
   Repeat with a Keychain key after restarting the app from Finder.
5. For supported hybrid models, compare Off and Low thinking. For GLM-5.3,
   confirm the always-thinking explanation. Check that reasoning and final text
   stream, usage is recorded when supplied, and activity ends at completion.
6. Try a wrong-region/invalid key and a Token Plan key. Expect actionable setup
   errors and no silent switch to another workspace/provider. Token Plan users
   should use Qwen Code's `/auth` route, not the metered API connection.

These checks incur provider usage charges. No paid-account inference was run
in the cloud environment because no Model Studio account key was configured.

## Release ownership

The live website metadata is already corrected to macOS 0.4.3/build 29 with
engine 2.31.9. Its existing signed DMG has not been replaced. The next source
versions are Python 2.31.10 and macOS 0.4.4/build 30, with release notes updated.
The uploader intentionally refuses changing an existing version's artifact bytes.
Python/GitHub publication is left to the release system as requested. This work
does not create tags, notarize, or upload a new installer.

After native validation, build the app from this checkout using
`apps/macos/scripts/release.sh` on an Apple Silicon Mac with the Developer ID
identity and notary profile configured. Rebuild the engine; do not use
`SKIP_ENGINE=1` with an older payload. Verify About shows 0.4.4/build 30 and the
runtime manifest and imported engine both show 2.31.10 before publishing the
signed DMG. Update the website release manifest only after the new artifact,
checksum and download links are verified.

For terminal and ACP users, publish fresh Python 2.31.10 wheel/sdist artifacts
from the same source. The repository's Publish workflow uses tag `v2.31.10` and
runs its own release checks; creating that tag starts publication and is left
to the release owner. PyPI publication alone does not update the engine already
bundled inside an installed macOS app.

Official Alibaba references checked for the integration:

- https://www.alibabacloud.com/help/en/model-studio/base-url
- https://www.alibabacloud.com/help/en/model-studio/deep-thinking
- https://www.alibabacloud.com/help/en/model-studio/deepseek-api
