import SwiftUI

/// The original SuperQode mark supplies the accent palette. Content keeps a stable surface.
enum Brand {
  static let purple = Color(red: 124 / 255, green: 31 / 255, blue: 232 / 255)
  static let pink = Color(red: 233 / 255, green: 25 / 255, blue: 140 / 255)
  static let orange = Color(red: 1, green: 164 / 255, blue: 0)
  static let gradient = LinearGradient(
    colors: [purple, pink, orange], startPoint: .bottomLeading, endPoint: .topTrailing)
  // Functional text uses contrast-adjusted shades; the logotype retains the
  // exact source palette. Increased Contrast uses semantic system foregrounds.
  static func textGradient(_ scheme: ColorScheme) -> LinearGradient {
    LinearGradient(
      colors: scheme == .dark
        ? [
          Color(red: 0.933, green: 0.894, blue: 1),
          Color(red: 1, green: 0.890, blue: 0.945),
          Color(red: 1, green: 0.945, blue: 0.831),
        ]
        : [
          Color(red: 0.392, green: 0.082, blue: 0.733),
          Color(red: 0.667, green: 0.067, blue: 0.396),
          Color(red: 0.592, green: 0.341, blue: 0),
        ],
      startPoint: .leading, endPoint: .trailing)
  }
  // Lighter tints keep long responses legible against the dark content surface.
  static let response = LinearGradient(
    colors: [
      Color(red: 0.85, green: 0.74, blue: 1), Color(red: 1, green: 0.74, blue: 0.88),
      Color(red: 1, green: 0.86, blue: 0.62),
    ], startPoint: .topLeading, endPoint: .bottomTrailing)
}

struct BrandSurface: ViewModifier {
  @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
  @Environment(\.colorSchemeContrast) private var contrast
  var radius: CGFloat
  func body(content: Content) -> some View {
    content
      .background {
        if reduceTransparency || contrast == .increased {
          RoundedRectangle(cornerRadius: radius).fill(Color.qPanel)
        } else {
          RoundedRectangle(cornerRadius: radius).fill(.regularMaterial)
        }
      }
      .overlay {
        RoundedRectangle(cornerRadius: radius)
          .strokeBorder(
            contrast == .increased
              ? AnyShapeStyle(Color.primary.opacity(0.5))
              : AnyShapeStyle(Color.primary.opacity(0.12)), lineWidth: 1
          )
          .allowsHitTesting(false)
      }
      .shadow(color: .black.opacity(reduceTransparency ? 0 : 0.12), radius: 14, y: 6)
  }
}
extension View {
  func brandSurface(radius: CGFloat = 14) -> some View { modifier(BrandSurface(radius: radius)) }
}

/// Delegate focus, keyboard activation, pressed and disabled states to macOS.
/// Branding belongs to the label; the button surface is neutral in both themes.
struct BrandButtonStyle: PrimitiveButtonStyle {
  @Environment(\.isEnabled) private var enabled
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast
  func makeBody(configuration: Configuration) -> some View {
    Button(role: configuration.role, action: configuration.trigger) {
      configuration.label.font(.body.weight(.semibold))
        .foregroundStyle(
          !enabled
            ? AnyShapeStyle(Color.secondary)
            : contrast == .increased
              ? AnyShapeStyle(Color.primary) : AnyShapeStyle(Brand.textGradient(scheme))
        )
        .padding(.horizontal, 4).padding(.vertical, 3)
    }.buttonStyle(.bordered).controlSize(.large).tint(.gray)
  }
}

struct BrandWordmark: View {
  @Environment(\.colorSchemeContrast) private var contrast
  var body: some View {
    Text("SUPERQODE").font(.system(size: 16, weight: .bold)).tracking(0.8)
      .foregroundStyle(
        contrast == .increased
          ? AnyShapeStyle(Color.primary) : AnyShapeStyle(Brand.gradient))
  }
}

struct BrandText: ViewModifier {
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast
  func body(content: Content) -> some View {
    content.foregroundStyle(
      contrast == .increased
        ? AnyShapeStyle(Color.primary) : AnyShapeStyle(Brand.textGradient(scheme)))
  }
}

struct BrandBackdrop: View {
  var body: some View { Color(nsColor: .windowBackgroundColor).ignoresSafeArea() }
}

/// Colour belongs to prose; fenced source code retains a plain, selectable treatment.
struct AgentResponseView: View {
  let text: String
  @AppStorage("colourfulAgentResponses") private var colourful = true
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      ForEach(Array(text.components(separatedBy: "```").enumerated()), id: \.offset) {
        index, part in
        if index.isMultiple(of: 2) {
          Text(part).font(.body).textSelection(.enabled)
            .foregroundStyle(
              colourful && scheme == .dark && contrast != .increased
                ? AnyShapeStyle(Brand.response) : AnyShapeStyle(Color.primary)
            )
            .frame(maxWidth: .infinity, alignment: .leading)
        } else {
          CodeBlock(text: part).frame(minHeight: 60, maxHeight: 280)
        }
      }
    }
  }
}

struct NavigationGlass: ViewModifier {
  @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast
  @ViewBuilder func body(content: Content) -> some View {
    let readable = content.foregroundStyle(
      scheme == .dark ? Color.white.opacity(0.92) : Color.black.opacity(0.88))
    if reduceTransparency || contrast == .increased {
      readable.background(Color.qPanel)
    } else if #available(macOS 26.0, *) {
      readable.glassEffect(.regular, in: RoundedRectangle(cornerRadius: 12))
    } else {
      readable.background(.regularMaterial, in: RoundedRectangle(cornerRadius: 12))
    }
  }
}

struct BrandActivityIndicator: View {
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @AppStorage("animatedInterface") private var animated = true
  var body: some View {
    HStack(spacing: 8) {
      if reduceMotion || !animated {
        Image(systemName: "sparkle").foregroundStyle(Brand.gradient)
      } else {
        Image(systemName: "sparkles").foregroundStyle(Brand.gradient).symbolEffect(.pulse)
      }
      Text("Agent is working").font(.caption.weight(.medium)).modifier(BrandText())
    }.accessibilityElement(children: .ignore).accessibilityLabel("Agent is working")
  }
}
