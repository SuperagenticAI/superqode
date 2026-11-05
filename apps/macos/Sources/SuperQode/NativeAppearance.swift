import AppKit
import SwiftUI

/// Native accent preferences are separate from the terminal's full theme files.
enum NativeAccent: String, CaseIterable {
  case graphite, system, purple, blue, teal, custom
  var title: String { rawValue.capitalized }
  static let preferenceKey = "nativeAccentChoice"
  static let customKey = "nativeCustomAccent"
  private static let colors: NSCache<NSString, NSColor> = {
    let cache = NSCache<NSString, NSColor>()
    cache.countLimit = 64
    return cache
  }()

  struct RGB: Equatable {
    let red: Double
    let green: Double
    let blue: Double
    var luminance: Double {
      func linear(_ c: Double) -> Double { c <= 0.04045 ? c / 12.92 : pow((c + 0.055) / 1.055, 2.4) }
      return 0.2126 * linear(red) + 0.7152 * linear(green) + 0.0722 * linear(blue)
    }
    /// Accent labels stay readable on the Mac's pure black/white surfaces.
    func readable(dark: Bool) -> RGB {
      var value = self
      for _ in 0..<100 {
        let ratio = dark ? (value.luminance + 0.05) / 0.05 : 1.05 / (value.luminance + 0.05)
        if ratio >= 4.5 { return value }
        let target = dark ? 1.0 : 0.0
        value = RGB(red: value.red + (target - value.red) * 0.06,
          green: value.green + (target - value.green) * 0.06,
          blue: value.blue + (target - value.blue) * 0.06)
      }
      return value
    }
  }

  static func parse(_ hex: String) -> RGB? {
    let raw = hex.hasPrefix("#") ? String(hex.dropFirst()) : hex
    guard raw.count == 6, raw.allSatisfy({ $0.isASCII && $0.isHexDigit }), let number = UInt32(raw, radix: 16) else { return nil }
    return RGB(red: Double((number >> 16) & 255) / 255,
      green: Double((number >> 8) & 255) / 255, blue: Double(number & 255) / 255)
  }

  static func accent(defaults: UserDefaults = .standard) -> Color {
    let choice = NativeAccent(rawValue: defaults.string(forKey: preferenceKey) ?? "") ?? .graphite
    if choice == .system { return Color(nsColor: .controlAccentColor) }
    let hex: String
    switch choice {
    case .graphite: hex = "#777777"
    case .purple: hex = "#9C6ADE"
    case .blue: hex = "#4D8DDF"
    case .teal: hex = "#2F9D92"
    case .custom: hex = defaults.string(forKey: customKey) ?? "#777777"
    case .system: hex = "#777777"
    }
    let key = (choice.rawValue + ":" + hex) as NSString
    if let color = colors.object(forKey: key) { return Color(nsColor: color) }
    let rgb = parse(hex) ?? parse("#777777")!
    let dark = (choice == .graphite ? RGB(red: 0.68, green: 0.68, blue: 0.68) : rgb).readable(dark: true)
    let light = (choice == .graphite ? RGB(red: 0.3, green: 0.3, blue: 0.3) : rgb).readable(dark: false)
    let color = NSColor(name: nil) { appearance in
      let value = appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? dark : light
      return NSColor(srgbRed: value.red, green: value.green, blue: value.blue, alpha: 1)
    }
    colors.setObject(color, forKey: key)
    return Color(nsColor: color)
  }
}

struct NativeAccentSettings: View {
  @EnvironmentObject var app: Workspace
  private var custom: Binding<Color> {
    Binding(get: {
      let rgb = NativeAccent.parse(app.customAccentHex) ?? NativeAccent.parse("#777777")!
      return Color(red: rgb.red, green: rgb.green, blue: rgb.blue)
    }, set: { color in
      guard let rgb = NSColor(color).usingColorSpace(.sRGB) else { return }
      func channel(_ value: CGFloat) -> Int { Int((min(max(value, 0), 1) * 255).rounded()) }
      app.customAccentHex = String(format: "#%02X%02X%02X", channel(rgb.redComponent),
        channel(rgb.greenComponent), channel(rgb.blueComponent))
    })
  }
  var body: some View {
    Picker("Accent", selection: $app.accentChoice) {
      ForEach(NativeAccent.allCases, id: \.rawValue) { choice in Text(choice.title).tag(choice.rawValue) }
    }
    if app.accentChoice == NativeAccent.custom.rawValue {
      ColorPicker("Custom accent", selection: custom, supportsOpacity: false)
    }
    Text("Graphite keeps the workspace neutral. Accent labels adapt for contrast; approval and error colors stay distinct. Mac accents are separate from TUI themes.")
      .font(.caption).foregroundStyle(.secondary)
  }
}
