import SwiftUI
import UIKit
import UniformTypeIdentifiers

/// Original mark and palette from the macOS app's BrandTheme.swift.
enum CompanionTheme {
  static let purple = Color(red: 124 / 255, green: 31 / 255, blue: 232 / 255)
  static let pink = Color(red: 233 / 255, green: 25 / 255, blue: 140 / 255)
  static let orange = Color(red: 1, green: 164 / 255, blue: 0)
  static let gradient = LinearGradient(
    colors: [purple, pink, orange], startPoint: .bottomLeading, endPoint: .topTrailing)
  static let background = Color(uiColor: UIColor { $0.userInterfaceStyle == .dark ? .black : .white })
  static let panel = Color(uiColor: UIColor {
    $0.userInterfaceStyle == .dark
      ? UIColor(white: 0.045, alpha: 1) : UIColor(white: 0.97, alpha: 1)
  })
  static let accent = Color(uiColor: UIColor {
    $0.userInterfaceStyle == .dark
      ? UIColor(red: 0.74, green: 0.53, blue: 1, alpha: 1)
      : UIColor(red: 100 / 255, green: 21 / 255, blue: 187 / 255, alpha: 1)
  })
  static let warning = Color(uiColor: UIColor {
    $0.userInterfaceStyle == .dark
      ? UIColor(red: 1, green: 0.73, blue: 0.41, alpha: 1)
      : UIColor(red: 0.58, green: 0.31, blue: 0, alpha: 1)
  })
  static func harnessColor(_ name: String) -> Color {
    let lower = name.lowercased()
    if lower.contains("claude") { return .orange }
    if lower.contains("qwen") || lower.contains("gemma") { return accent }
    if lower.contains("codex") || lower.contains("openai") { return .blue }
    if lower.contains("deepseek") { return .blue }
    if lower.contains("glm") || lower.contains("kimi") { return .pink }
    return accent
  }
  static func harnessAsset(_ name: String) -> String? {
    let lower = name.lowercased()
    if ["core", "no-tool", "pipy", "codegem", "systemone", "superqode"].contains(lower) { return "BrandMark" }
    if let exact = BundledAgentIcons.assets[lower] { return exact }
    for key in ["qwen", "claude", "codex", "gemini", "glm", "kimi", "opencode", "copilot"] {
      if lower.contains(key), let asset = BundledAgentIcons.assets[key == "glm" ? "glm-acp-agent" : key] { return asset }
    }
    return nil
  }
}

struct SuperQodeMark: View {
  var size: CGFloat = 32
  var body: some View {
    Image("BrandMark").resizable().scaledToFit().frame(width: size, height: size)
      .accessibilityLabel("SuperQode")
  }
}

struct SuperQodeWordmark: View {
  var compact = false
  var body: some View {
    HStack(spacing: 10) {
      SuperQodeMark(size: compact ? 24 : 34)
      Text("SUPERQODE").font(.system(size: compact ? 13 : 16, weight: .bold))
        .tracking(1.1).foregroundStyle(.primary)
    }.accessibilityElement(children: .ignore).accessibilityLabel("SuperQode")
  }
}

/// Same 4pt sweep as the macOS app: purple, pink, then orange.
struct ThinkingBar: View {
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Environment(\.colorSchemeContrast) private var contrast
  var body: some View {
    Group {
      if reduceMotion {
        Capsule().fill(CompanionTheme.accent.opacity(0.65))
      } else {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { timeline in
          Canvas { context, size in
            let phase = timeline.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 2) / 2
            let width = size.width * 0.46
            let x = (size.width + width) * phase - width
            let rect = CGRect(x: x, y: 0, width: width, height: size.height)
            let colors: [Color] = contrast == .increased
              ? [.primary, .primary]
              : [CompanionTheme.purple, CompanionTheme.pink, CompanionTheme.orange]
            context.fill(
              Path(roundedRect: rect, cornerRadius: size.height / 2),
              with: .linearGradient(
                Gradient(colors: colors),
                startPoint: CGPoint(x: x, y: 0),
                endPoint: CGPoint(x: x + width, y: 0)))
          }
        }
      }
    }
    .frame(height: 4)
    .background(.primary.opacity(0.07), in: Capsule())
    .clipShape(Capsule())
    .accessibilityHidden(true)
  }
}

struct WorkingStatusText: View {
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  var body: some View {
    Group {
      if reduceMotion {
        Text("Working…")
      } else {
        TimelineView(.animation(minimumInterval: 0.5)) { timeline in
          let dots = Int(timeline.date.timeIntervalSinceReferenceDate * 2) % 3 + 1
          Text("Working" + String(repeating: ".", count: dots))
        }
      }
    }
    .frame(minWidth: 78, alignment: .leading)
    .accessibilityElement(children: .ignore)
    .accessibilityLabel("Working")
  }
}

struct CompanionWorkingCard: View {
  let status: String
  var body: some View {
    let waiting = status == "needs_approval"
    let stopping = status == "cancelling"
    VStack(alignment: .leading, spacing: 8) {
      HStack(spacing: 8) {
        SuperQodeMark(size: 22)
        if waiting {
          Text("Waiting for permission").font(.subheadline.weight(.semibold))
        } else if stopping {
          Text("Stopping agent").font(.subheadline.weight(.semibold))
        } else {
          WorkingStatusText().font(.subheadline.weight(.semibold))
        }
        Spacer(minLength: 0)
      }
      if !waiting { ThinkingBar() }
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .accessibilityElement(children: .combine)
    .accessibilityLabel(waiting ? "Waiting for permission" : stopping ? "Stopping agent" : "Working")
  }
}

struct CompanionPrimaryButton: ButtonStyle {
  @Environment(\.isEnabled) private var enabled
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  func makeBody(configuration: Configuration) -> some View {
    configuration.label.font(.body.weight(.semibold)).foregroundStyle(enabled ? Color.white : Color.secondary)
      .frame(maxWidth: .infinity).padding(.vertical, 14).padding(.horizontal, 16)
      .background(enabled ? CompanionTheme.purple : CompanionTheme.panel, in: RoundedRectangle(cornerRadius: 16))
      .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(Color.primary.opacity(enabled ? 0 : 0.15)))
      .opacity(configuration.isPressed && enabled ? 0.85 : 1)
      .animation(reduceMotion ? nil : .easeOut(duration: 0.12), value: configuration.isPressed)
  }
}

struct CompanionCard<Content: View>: View {
  let content: Content
  @Environment(\.colorSchemeContrast) private var contrast
  init(@ViewBuilder content: () -> Content) { self.content = content() }
  var body: some View {
    VStack(alignment: .leading, spacing: 14) { content }
      .frame(maxWidth: .infinity, alignment: .leading).padding(18)
      .background(CompanionTheme.panel, in: RoundedRectangle(cornerRadius: 20))
      .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(Color.primary.opacity(contrast == .increased ? 0.4 : 0.12)))
  }
}

struct HarnessMark: View {
  let name: String
  var iconKey: String = ""
  var size: CGFloat = 16
  private var asset: String? {
    let key = iconKey.lowercased()
    if key == "superqode" || ["core", "no-tool", "pipy", "codegem", "systemone"].contains(key) {
      return "BrandMark"
    }
    if let exact = BundledAgentIcons.assets[key] { return exact }
    return CompanionTheme.harnessAsset(iconKey.isEmpty ? name : iconKey)
  }
  private var coloured: Bool {
    guard let asset else { return false }
    return asset == "BrandMark" || BundledAgentIcons.brandColoured.contains(asset)
  }
  var body: some View {
    Group {
      if let asset {
        if coloured {
          Image(asset).resizable().renderingMode(.original).scaledToFit()
        } else {
          Image(asset).resizable().renderingMode(.template).scaledToFit()
            .foregroundStyle(CompanionTheme.harnessColor(name))
        }
      } else {
        Image(systemName: "cpu").resizable().scaledToFit().foregroundStyle(.secondary)
      }
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }
}

struct HarnessBadge: View {
  let name: String
  var iconKey: String = ""
  var body: some View {
    let color = CompanionTheme.harnessColor(name)
    HStack(spacing: 6) {
      HarnessMark(name: name, iconKey: iconKey, size: 16)
      Text(name).lineLimit(1).foregroundStyle(color)
    }.font(.caption.weight(.semibold))
      .padding(.horizontal, 10).padding(.vertical, 6)
      .background(color.opacity(0.12), in: Capsule())
      .accessibilityElement(children: .combine)
  }
}

struct HarnessChoiceSection: Identifiable {
  let id: String
  let title: String
  let subtitle: String
  let rows: [RemoteRecord]
}

enum HarnessChoiceGroup {
  /// Connect on the Mac: subscription, your model, SuperQode harnesses, ACP, then protocols.
  static let order: [(id: String, title: String, subtitle: String)] = [
    ("subscription", "Subscriptions", "Vendor plans you sign in to with your own account."),
    ("model", "Connect a model", "Open harnesses. Connect with your API key or a local model."),
    ("harness", "SuperQode harnesses", "SuperQode harnesses. The model stays the one connected on the Mac."),
    ("acp", "ACP agents", "Agents that speak Agent Client Protocol."),
    ("protocol", "Agent protocols", "Reach a remote agent with A2A or UHP."),
  ]
  static func groupID(_ row: RemoteRecord) -> String {
    let explicit = row.text("group")
    if order.contains(where: { $0.id == explicit }) { return explicit }
    let id = row.id
    if id.hasPrefix("remote:") { return "protocol" }
    if id.hasPrefix("attach:") { return "model" }
    if id.hasPrefix("connection:") { return "subscription" }
    if id.hasPrefix("acp:") { return "acp" }
    return "harness"
  }
  static func sections(_ rows: [RemoteRecord]) -> [HarnessChoiceSection] {
    let known = Set(order.map(\.id))
    var buckets: [String: [RemoteRecord]] = [:]
    var other: [RemoteRecord] = []
    for row in rows {
      let group = groupID(row)
      if known.contains(group) { buckets[group, default: []].append(row) }
      else { other.append(row) }
    }
    var result = order.compactMap { item -> HarnessChoiceSection? in
      let grouped = buckets[item.id] ?? []
      guard !grouped.isEmpty else { return nil }
      return HarnessChoiceSection(id: item.id, title: item.title, subtitle: item.subtitle, rows: grouped)
    }
    if !other.isEmpty {
      result.append(HarnessChoiceSection(
        id: "other", title: "Other harnesses",
        subtitle: "Connections from this Mac.", rows: other))
    }
    return result
  }
}

struct HarnessChoiceLabel: View {
  let choice: RemoteRecord
  var selected = false
  var body: some View {
    HStack(spacing: 12) {
      HarnessMark(name: choice.text("name"), iconKey: choice.text("icon_key"), size: 28)
      VStack(alignment: .leading, spacing: 2) {
        Text(choice.text("name")).foregroundStyle(.primary).lineLimit(1)
        let detail = choice.text("model").isEmpty ? choice.text("description") : choice.text("model")
        if !detail.isEmpty {
          Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }
      }
      Spacer(minLength: 8)
      if selected { Image(systemName: "checkmark").foregroundStyle(CompanionTheme.accent) }
    }
  }
}

enum CompanionAppearance: String, CaseIterable {
  case system, dark, light
  var scheme: ColorScheme? { self == .system ? nil : self == .dark ? .dark : .light }
  var title: String { rawValue.capitalized }
}

enum PrivateClipboard {
  static func copy(_ text: String) {
    UIPasteboard.general.setItems([[UTType.utf8PlainText.identifier: text]],
      options: [.localOnly: true, .expirationDate: Date().addingTimeInterval(120)])
  }
}

extension View {
  func companionNavigationBrand() -> some View {
    navigationBarTitleDisplayMode(.inline)
      .toolbar { ToolbarItem(placement: .principal) { SuperQodeWordmark(compact: true) } }
  }
}
