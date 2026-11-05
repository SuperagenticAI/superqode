import AppKit
import SwiftUI

/// Stable app accents for agent identities, independent of the selected model.
/// Registry glyphs are monochrome; these colours are UI accents, not vendor logos.
enum HarnessColorFamily: String, CaseIterable {
  case teal, emerald, coral, violet, blue, pink, amber, cyan

  static func resolve(icon: String, reference: String) -> HarnessColorFamily {
    switch icon.lowercased() {
    case "opencode", "opencode-v2", "goose": return .teal
    case "codex", "codex-acp", "deepagents": return .emerald
    case "claude", "claude-acp", "factory-droid", "droid": return .coral
    case "qwen", "qwen-code", "cursor", "copilot", "github-copilot-cli": return .violet
    case "kimi", "deepseek", "gemini", "antigravity": return .blue
    case "muse", "grok", "grok-build", "amp", "minimax", "minimax-code": return .pink
    case "superqode", "strands", "kiro": return .amber
    case "glm", "glm-acp-agent", "cline", "junie": return .cyan
    default:
      // Swift's Hasher changes between launches. Keep custom-harness colours stable.
      let key = icon.isEmpty ? reference : icon
      let hash = key.utf8.reduce(UInt64(14695981039346656037)) {
        ($0 ^ UInt64($1)) &* 1099511628211
      }
      return allCases[Int(hash % UInt64(allCases.count))]
    }
  }

  private var lightRGB: UInt32 {
    switch self {
    case .teal: return 0x006B69
    case .emerald: return 0x006F4D
    case .coral: return 0xA7412B
    case .violet: return 0x6840C4
    case .blue: return 0x245FC2
    case .pink: return 0xA93670
    case .amber: return 0x925800
    case .cyan: return 0x006B90
    }
  }
  private var darkRGB: UInt32 {
    switch self {
    case .teal: return 0x5EEAD4
    case .emerald: return 0x6EE7B7
    case .coral: return 0xFFAC8E
    case .violet: return 0xB8A0FF
    case .blue: return 0x82B9FF
    case .pink: return 0xFFA0D0
    case .amber: return 0xFFD080
    case .cyan: return 0x70DEFF
    }
  }

  func nsColor(dark: Bool) -> NSColor {
    let rgb = dark ? darkRGB : lightRGB
    return NSColor(srgbRed: Double((rgb >> 16) & 255) / 255,
      green: Double((rgb >> 8) & 255) / 255, blue: Double(rgb & 255) / 255, alpha: 1)
  }
  // Stable colour identities avoid replacing dynamic AppKit colour providers
  // for every badge on each navigation or engine update.
  private static let colors = Dictionary(uniqueKeysWithValues: allCases.map { family in
    (family, Color(nsColor: NSColor(name: nil) { appearance in
      family.nsColor(dark: appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua)
    }))
  })
  var color: Color { Self.colors[self]! }
}

extension HarnessIdentity {
  var colorFamily: HarnessColorFamily { .resolve(icon: iconKey, reference: id) }
  var accent: Color { colorFamily.color }
  var symbolGradient: LinearGradient {
    let companion: HarnessColorFamily
    switch colorFamily {
    case .teal, .emerald: companion = .cyan
    case .coral, .pink: companion = .amber
    case .blue, .violet: companion = .pink
    case .amber: companion = .coral
    case .cyan: companion = .blue
    }
    return LinearGradient(colors: [accent, companion.color], startPoint: .topLeading, endPoint: .bottomTrailing)
  }

  static func current(in row: [String: Any]) -> HarnessIdentity? {
    let identities = used(in: row)
    return identities.first { $0.id == string(row, "harness") } ?? identities.last
  }
}

@MainActor extension Workspace {
  /// A blank thread has no badge until the user explicitly selects a connection.
  var composerHarnessIdentity: HarnessIdentity? {
    guard !connectionDisconnected, !harness.isEmpty else { return nil }
    return HarnessIdentity(harnesses.first { string($0, "id") == harness } ?? ["id": harness])
  }
}
