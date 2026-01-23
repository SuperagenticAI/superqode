# Homebrew Releases

This guide covers building self-contained SuperQode binaries, publishing them to GitHub Releases, and updating the Homebrew formula repo to install those binaries.

## Overview

SuperQode ships as a single-file binary produced by PyInstaller. Each release publishes per-platform archives, and the Homebrew formula downloads the correct archive for the user's platform.

Release assets produced by the workflow:

- `superqode-macos-arm64.tar.gz`
- `superqode-macos-x86_64.tar.gz`
- `superqode-linux-x86_64.tar.gz`

Each archive contains one executable: `superqode`.

## Build and Publish (GitHub Actions)

The repo includes a release workflow at `.github/workflows/release.yml` that runs on tags matching `v*` (e.g., `v0.1.0`).

1) Create and push a tag in `SuperagenticAI/superqode`:

```bash
git tag v0.1.0
git push origin v0.1.0
```

2) The workflow builds platform-specific binaries and uploads them to the GitHub Release for that tag.

3) Each release includes a `.sha256` file for every archive. These are the checksums used by Homebrew.

## Update the Homebrew Formula Repo

The Homebrew formula lives in `SuperagenticAI/homebrew-superqode`. Update the formula with the new version, URLs, and SHA256 values.

Template (replace version + sha256):

```ruby
class Superqode < Formula
  desc "SuperQode CLI"
  homepage "https://github.com/SuperagenticAI/superqode"
  version "0.1.0"

  on_macos do
    if Hardware::CPU.arm?
      url "https://github.com/SuperagenticAI/superqode/releases/download/v0.1.0/superqode-macos-arm64.tar.gz"
      sha256 "<macos-arm64-sha256>"
    else
      url "https://github.com/SuperagenticAI/superqode/releases/download/v0.1.0/superqode-macos-x86_64.tar.gz"
      sha256 "<macos-x86_64-sha256>"
    end
  end

  on_linux do
    url "https://github.com/SuperagenticAI/superqode/releases/download/v0.1.0/superqode-linux-x86_64.tar.gz"
    sha256 "<linux-x86_64-sha256>"
  end

  def install
    bin.install "superqode"
  end

  test do
    system "#{bin}/superqode", "--help"
  end
end
```

### Where to get the SHA256 values

After the release workflow completes, each archive has a corresponding `.sha256` file in the GitHub Release assets. Example filename:

- `superqode-macos-arm64.tar.gz.sha256`

Copy the hex digest from each file into the formula.

## Local build (optional)

To test a build locally before tagging:

```bash
scripts/build_binary.sh
./dist/superqode --version
```

## Troubleshooting

- If the binary fails at runtime, add missing data or imports to `superqode.spec`.
- For data files (e.g., `superqode/agents/data`), ensure `collect_data_files("superqode")` is present in the spec.
- For dynamic libs, add `collect_dynamic_libs` for the missing package in `superqode.spec`.
