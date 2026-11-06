import AppKit
import SwiftUI

struct HarnessIdentity: Identifiable, Equatable {
  let id: String
  let name: String
  let iconKey: String
  var assetName: String? { iconKey == "superqode" ? "BrandMark" : BundledAgentIcons.assets[iconKey] }

  init(_ row: [String: Any]) {
    let referenceID = string(row, "id", string(row, "harness", "core"))
    id = referenceID
    name = string(row, "name", referenceID)
    let runtime = string(row, "runtime")
    let runtimes = ["codex-cli": "codex", "codex-sdk": "codex", "claude-agent-sdk": "claude", "claude-code": "claude", "copilot-sdk": "copilot", "gemini-cli": "gemini", "factory": "factory-droid", "droid": "factory-droid", "opencode": "opencode"]
    let reference = ["acp:", "connection:", "attach:", "vendor-key:"].first { referenceID.hasPrefix($0) }
      .map { String(referenceID.dropFirst($0.count)) } ?? referenceID
    let fallback = runtimes[runtime] ?? runtimes[reference] ?? (["core", "pipy", "codegem", "systemone"].contains(referenceID) ? "superqode" : reference)
    iconKey = string(row, "icon_key", string(row, "agent_id",
      string(row, "subscription_vendor", fallback)))
  }

  static func used(in row: [String: Any]) -> [HarnessIdentity] {
    let history = row["harnesses_used"] as? [[String: Any]] ?? []
    var seen = Set<String>()
    let identities = history.map(HarnessIdentity.init).filter { seen.insert($0.id).inserted }
    if !identities.isEmpty { return identities }
    let reference = string(row, "harness")
    return reference.isEmpty || reference == "disconnected" ? [] : [HarnessIdentity(["id": reference])]
  }

  static func visible(in row: [String: Any], limit: Int) -> [HarnessIdentity] {
    let identities = used(in: row)
    guard limit > 0 else { return [] }
    let prefix = Array(identities.prefix(limit))
    guard let current = identities.first(where: { $0.id == string(row, "harness") }),
      !prefix.contains(where: { $0.id == current.id }) else { return prefix }
    return Array(prefix.prefix(limit - 1)) + [current]
  }
}

struct HarnessIcon: View {
  let identity: HarnessIdentity
  var size: CGFloat = 30
  var body: some View {
    Group {
      if let asset = identity.assetName, let image = NSImage(named: asset) {
        // Only genuinely coloured marks keep their colours; bundled SVGs stay neutral.
        Image(nsImage: image).renderingMode(identity.iconKey == "superqode" ? .original : .template)
          .resizable().scaledToFit()
      } else { Image(systemName: "cpu").resizable().scaledToFit().foregroundStyle(.secondary) }
    }.padding(size * 0.18).frame(width: size, height: size)
      .background(Color.qPanel, in: RoundedRectangle(cornerRadius: size * 0.28))
      .overlay(RoundedRectangle(cornerRadius: size * 0.28).strokeBorder(.primary.opacity(0.16)))
      .accessibilityLabel(identity.name).help(identity.name)
  }
}

struct HarnessIconStack: View {
  let row: [String: Any]
  var size: CGFloat = 26
  var limit = 3
  var emphasizeCurrent = true
  private var identities: [HarnessIdentity] { HarnessIdentity.used(in: row) }
  private var description: String {
    let lastUsed = identities.first { $0.id == string(row, "harness") }?.name ?? ""
    return "Harnesses used: " + identities.map(\.name).joined(separator: ", ")
      + (lastUsed.isEmpty ? "" : ". Last used: " + lastUsed)
  }
  var body: some View {
    HStack(spacing: -5) {
      ForEach(HarnessIdentity.visible(in: row, limit: limit)) { identity in
        HarnessIcon(identity: identity, size: size)
          .overlay(RoundedRectangle(cornerRadius: size * 0.28).strokeBorder(emphasizeCurrent && identity.id == string(row, "harness") ? Color.primary.opacity(0.16) : .clear))
      }
      if identities.count > limit {
        Text("+\(identities.count - limit)").foregroundStyle(.secondary).font(.system(size: size * 0.38, weight: .semibold))
          .frame(width: size, height: size).background(Color.qPanel, in: Circle())
          .overlay(Circle().strokeBorder(.primary.opacity(0.16)))
      }
    }.accessibilityElement(children: .ignore).accessibilityLabel(description).help(description)
  }
}
