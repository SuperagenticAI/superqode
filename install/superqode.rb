class Superqode < Formula
  desc "Super Quality Engineering for Agentic Coding Teams"
  homepage "https://super-agentic.ai"
  version "0.1.4"

  if OS.mac?
    url "https://github.com/SuperagenticAI/superqode/releases/download/v0.1.4/superqode-0.1.4-macos-arm64.tar.gz"
    sha256 "dc436564fdf0f5aa6f7436c454a784eb5b923ea2997ebdcc28ea5fad86c8ce12"
  elsif OS.linux?
    url "https://github.com/SuperagenticAI/superqode/releases/download/v0.1.4/superqode-0.1.4-linux-arm64.tar.gz"
    sha256 "34234bc26d8842a50c16b9ac7b1827367e9c73d5bc229a043dabc6c52c57e8f0"
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
