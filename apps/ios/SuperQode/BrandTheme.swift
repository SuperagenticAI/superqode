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

struct HarnessBadge: View {
  let name: String
  var body: some View {
    let color = CompanionTheme.harnessColor(name)
    HStack(spacing: 6) {
      if let asset = CompanionTheme.harnessAsset(name) {
        Image(asset).renderingMode(asset == "BrandMark" ? .original : .template)
          .resizable().scaledToFit().frame(width: 16, height: 16).accessibilityHidden(true)
      } else { Image(systemName: "sparkles").symbolRenderingMode(.hierarchical) }
      Text(name).lineLimit(1)
    }.font(.caption.weight(.semibold)).foregroundStyle(color)
      .padding(.horizontal, 10).padding(.vertical, 6)
      .background(color.opacity(0.12), in: Capsule())
      .accessibilityElement(children: .combine)
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
