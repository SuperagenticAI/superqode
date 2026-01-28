class Superqode < Formula
  desc "Super Quality Engineering for Agentic Coding Teams"
  homepage "https://super-agentic.ai"
  version "0.1.5"

  if OS.mac?
    url "https://github.com/SuperagenticAI/superqode/releases/download/v0.1.5/superqode-0.1.5-macos-arm64.tar.gz"
    sha256 "f9c01fa9fd027ed41258187bba2a22d7803d7c2ec90a04576c653a4130a612cb"
  elsif OS.linux?
    url "https://github.com/SuperagenticAI/superqode/releases/download/v0.1.5/superqode-0.1.5-linux-arm64.tar.gz"
    sha256 "8b8e21619030b83f09eda6cd7d6b8f48267eab35777e64c3c7a97003a4816acd"
  end

  def install
    # Install the entire app directory (extracted from the tarball) to libexec
    # The tarball contains the 'superqode' folder at its root.
    libexec.install Dir["*"]

    # The executable is inside the extracted superqode folder.
    # We create a symlink in the standard Homebrew bin directory.
    bin.install_symlink libexec/"superqode"
  end

  test do
    system "#{bin}/superqode", "--version"
  end
end
