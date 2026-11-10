import SwiftUI

/// The original SuperQode mark supplies the accent palette. Content keeps a stable surface.
enum Brand {
  static let purple = Color(red: 124 / 255, green: 31 / 255, blue: 232 / 255)
  static let pink = Color(red: 233 / 255, green: 25 / 255, blue: 140 / 255)
  static let orange = Color(red: 1, green: 164 / 255, blue: 0)
  static let gradient = LinearGradient(
    colors: [purple, pink, orange], startPoint: .bottomLeading, endPoint: .topTrailing)
  // Text uses contrast-adjusted shades. The icon retains the source palette.
  // Increased Contrast uses semantic system foregrounds.
  static func wordmarkGradient(_ scheme: ColorScheme) -> LinearGradient {
    LinearGradient(
      colors: scheme == .dark
        ? [
          Color(red: 0.68, green: 0.36, blue: 1), Brand.pink, Brand.orange,
        ]
        : [
          Color(red: 100 / 255, green: 21 / 255, blue: 187 / 255),
          Color(red: 170 / 255, green: 17 / 255, blue: 101 / 255),
          Color(red: 151 / 255, green: 87 / 255, blue: 0),
        ], startPoint: .leading, endPoint: .trailing)
  }
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
          RoundedRectangle(cornerRadius: radius).fill(Color.qPanel)
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

  }
}
struct ConversationSurface: ViewModifier {
  @Environment(\.colorScheme) private var scheme
  @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
  @Environment(\.colorSchemeContrast) private var contrast
  func body(content: Content) -> some View {
    content.background {
      RoundedRectangle(cornerRadius: 14).fill(
        LinearGradient(colors: reduceTransparency || contrast == .increased ? [Color.qPanel, Color.qPanel]
          : scheme == .dark ? [.black, Color(red: 0.065, green: 0.038, blue: 0.022), .black]
          : [.white, Color(red: 1, green: 0.98, blue: 0.95), .white],
          startPoint: .topLeading, endPoint: .bottomTrailing))
    }.overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.primary.opacity(0.18), lineWidth: 1).allowsHitTesting(false))
  }
}
struct OutlinedSurface: ViewModifier {
  var radius: CGFloat
  func body(content: Content) -> some View {
    content.background(Color.qPanel, in: RoundedRectangle(cornerRadius: radius))
      .overlay(RoundedRectangle(cornerRadius: radius).stroke(.primary.opacity(0.16), lineWidth: 1).allowsHitTesting(false))
  }
}
extension View {
  func outlinedSurface(radius: CGFloat = 10) -> some View { modifier(OutlinedSurface(radius: radius)) }
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
        .padding(.horizontal, 10).padding(.vertical, 7)
    }.buttonStyle(.plain).outlinedSurface(radius: 7).controlSize(.large)
  }
}

struct BrandWordmark: View {
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast
  var body: some View {
    Text("SUPERQODE").font(.system(size: 16, weight: .bold)).tracking(0.8)
      .foregroundStyle(
        contrast == .increased
          ? AnyShapeStyle(Color.primary) : AnyShapeStyle(Brand.wordmarkGradient(scheme)))
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
  var body: some View { Color.qPanel.ignoresSafeArea() }
}

/// Colour belongs to prose; fenced source code retains a plain, selectable treatment.
struct AgentResponseView: View {
  let text: String
  var embedded = false
  @AppStorage("colourfulAgentResponses") private var colourful = false
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast
  var body: some View {
    Group {
      if embedded { ResponseDocument(text: text).equatable() }
      else {
        VStack(alignment: .leading, spacing: 14) {
          HStack(spacing: 7) {
            BrandMark().frame(width: 18, height: 18)
            Text("SuperQode").font(.system(size: 12, weight: .semibold)).foregroundStyle(Brand.wordmarkGradient(scheme))
          }
          ResponseDocument(text: text).equatable()
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading).modifier(ConversationSurface())
      }
    }.foregroundStyle(colourful && scheme == .dark && contrast != .increased
      ? AnyShapeStyle(Brand.response) : AnyShapeStyle(Color.primary))
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
    } else {
      readable.outlinedSurface(radius: 12)
    }
  }
}

/// The animation draws only this small canvas; it does not publish workspace state.
struct ThinkingBar: View {
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Environment(\.colorSchemeContrast) private var contrast
  @AppStorage("animatedInterface") private var animated = true
  var body: some View {
    Group {
      if reduceMotion || !animated {
        Capsule().fill(Color.qAccent.opacity(0.65))
      } else {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { timeline in
          Canvas { context, size in
            let phase = timeline.date.timeIntervalSinceReferenceDate.truncatingRemainder(dividingBy: 2) / 2
            let width = size.width * 0.46
            let x = (size.width + width) * phase - width
            let rect = CGRect(x: x, y: 0, width: width, height: size.height)
            context.fill(Path(roundedRect: rect, cornerRadius: size.height / 2), with:
              .linearGradient(Gradient(colors: contrast == .increased ? [.primary, .primary] : [Brand.purple, Brand.pink, Brand.orange]),
                startPoint: CGPoint(x: x, y: 0), endPoint: CGPoint(x: x + width, y: 0)))
          }
        }
      }
    }.frame(height: 4).background(.primary.opacity(0.07), in: Capsule()).clipShape(Capsule())
      .accessibilityHidden(true)
  }
}

/// Full-pane wait while a local model loads into memory.
struct ModelWarmupCard: View {
  var message: String
  var subject: String = ""
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Environment(\.colorSchemeContrast) private var contrast
  @AppStorage("animatedInterface") private var animated = true

  private var warming: Bool { message.localizedCaseInsensitiveContains("warm") }
  private var motion: Bool { animated && !reduceMotion }
  private var headline: String {
    if warming {
      return subject.isEmpty ? "Warming the model" : "Warming \(subject)"
    }
    let trimmed = message.trimmingCharacters(in: CharacterSet(charactersIn: ".… "))
    return trimmed.isEmpty ? "Getting ready" : trimmed
  }
  private var detail: String {
    warming ? "Loading it into memory so your first question is ready." : ""
  }

  var body: some View {
    VStack(spacing: 18) {
      WarmupOrb(active: motion, emphasized: contrast == .increased)
      Text(headline)
        .font(.title2.weight(.semibold))
        .multilineTextAlignment(.center)
        .lineLimit(3)
      if !detail.isEmpty {
        Text(detail)
          .font(.callout)
          .foregroundStyle(.secondary)
          .multilineTextAlignment(.center)
          .frame(maxWidth: 420)
      }
      ThinkingBar().frame(width: 196)
    }
    .padding(32)
    .frame(maxWidth: .infinity, maxHeight: .infinity)
    .background {
      RoundedRectangle(cornerRadius: 18, style: .continuous)
        .fill(Color.primary.opacity(0.04))
    }
    .overlay {
      RoundedRectangle(cornerRadius: 18, style: .continuous)
        .strokeBorder(
          contrast == .increased
            ? AnyShapeStyle(Color.primary.opacity(0.55))
            : AnyShapeStyle(LinearGradient(
              colors: [Brand.purple.opacity(0.55), Brand.pink.opacity(0.4), Brand.orange.opacity(0.5)],
              startPoint: .topLeading, endPoint: .bottomTrailing)),
          lineWidth: 1)
    }
    .accessibilityElement(children: .combine)
    .accessibilityLabel(detail.isEmpty ? headline : "\(headline). \(detail)")
  }
}

/// Brand mark with expanding rings. The canvas does not publish workspace state.
private struct WarmupOrb: View {
  var active: Bool
  var emphasized: Bool
  var body: some View {
    ZStack {
      if active {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { timeline in
          Canvas { context, size in
            let time = timeline.date.timeIntervalSinceReferenceDate
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            let palette: [Color] = emphasized
              ? [.primary, .primary, .primary]
              : [Brand.purple, Brand.pink, Brand.orange]
            for index in 0..<3 {
              let phase = (time / 2.6 + Double(index) / 3).truncatingRemainder(dividingBy: 1)
              let radius = 22 + phase * 42
              var ring = Path()
              ring.addEllipse(in: CGRect(
                x: center.x - radius, y: center.y - radius, width: radius * 2, height: radius * 2))
              context.stroke(
                ring,
                with: .color(palette[index].opacity((1 - phase) * 0.7)),
                lineWidth: 2)
            }
            let spin = time.truncatingRemainder(dividingBy: 2.4) / 2.4
            var arc = Path()
            arc.addArc(
              center: center, radius: 38,
              startAngle: .degrees(spin * 360 - 90),
              endAngle: .degrees(spin * 360 + 78),
              clockwise: false)
            context.stroke(
              arc,
              with: .linearGradient(
                Gradient(colors: emphasized ? [.primary, .primary] : [Brand.purple, Brand.pink, Brand.orange]),
                startPoint: CGPoint(x: 0, y: size.height),
                endPoint: CGPoint(x: size.width, y: 0)),
              style: StrokeStyle(lineWidth: 3.5, lineCap: .round))
          }
        }
      } else {
        Circle().stroke(Color.primary.opacity(0.35), lineWidth: 3).padding(26)
      }
      Circle().fill(Color.qPanel).frame(width: 64, height: 64)
      BrandMark().frame(width: 40, height: 40)
    }
    .frame(width: 148, height: 148)
    .accessibilityHidden(true)
  }
}

/// Animate only the status text, without publishing changes to the workspace.
struct WorkingStatusText: View {
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @AppStorage("animatedInterface") private var animated = true
  var body: some View {
    Group {
      if reduceMotion || !animated {
        Text("Working…")
      } else {
        TimelineView(.animation(minimumInterval: 0.5)) { timeline in
          let dots = Int(timeline.date.timeIntervalSinceReferenceDate * 2) % 3 + 1
          Text("Working" + String(repeating: ".", count: dots))
        }
      }
    }.frame(minWidth: 78, alignment: .leading)
      .accessibilityElement(children: .ignore).accessibilityLabel("Working")
  }
}

struct BrandActivityIndicator: View {
  var status = "running"
  var label: String {
    status == "needs_approval" ? "Waiting for permission" : status == "cancelling" ? "Stopping agent" : "Working…"
  }
  var body: some View {
    HStack(spacing: 9) {
      if status == "needs_approval" {
        Image(systemName: "hand.raised").foregroundStyle(.orange)
        Text(label).font(.caption.weight(.medium)).modifier(BrandText())
      } else if status == "cancelling" {
        ThinkingBar().frame(width: 52)
        Text(label).font(.caption.weight(.medium)).modifier(BrandText())
      } else {
        ThinkingBar().frame(width: 52)
        WorkingStatusText().font(.caption.weight(.medium)).modifier(BrandText())
      }
    }.accessibilityElement(children: .ignore).accessibilityLabel(label)
  }
}

struct AgentWorkingCard: View {
  let status: String
  var activity = ""
  /// Run start, for "Working for 12m 03s".
  var startedAt: Date?
  /// When the run began waiting for approval, for "Waiting for you 2m".
  var waitingSince: Date?
  /// Compact plan progress, e.g. "Plan 2 of 5 done · Run tests".
  var planLine = ""
  var body: some View {
    HStack(spacing: 10) {
      BrandMark().frame(width: 18, height: 18)
      VStack(alignment: .leading, spacing: 4) {
        HStack(spacing: 8) {
          if status == "needs_approval" || status == "cancelling" {
            Text(BrandActivityIndicator(status: status).label).font(.system(size: 12, weight: .semibold)).modifier(BrandText())
            if status == "needs_approval", let waitingSince {
              LiveElapsedText(prefix: "Waiting for you ", since: waitingSince, compact: true)
                .font(.system(size: 12)).foregroundStyle(.secondary)
            } else if let startedAt {
              LiveElapsedText(prefix: "", since: startedAt)
                .font(.system(size: 12)).foregroundStyle(.secondary)
            }
          } else if let startedAt {
            LiveElapsedText(prefix: "Working for ", since: startedAt)
              .font(.system(size: 12, weight: .semibold)).modifier(BrandText())
              .accessibilityLabel("Working")
          } else {
            WorkingStatusText().font(.system(size: 12, weight: .semibold)).modifier(BrandText())
          }
          if status != "needs_approval" { ThinkingBar().frame(width: 72, height: 4) }
          Spacer(minLength: 0)
        }
        if !planLine.isEmpty {
          Label(planLine, systemImage: "checklist").font(.system(size: 12)).foregroundStyle(.secondary)
            .lineLimit(1).truncationMode(.tail).help(planLine)
        }
        if status == "needs_approval" || status == "cancelling" || !activity.isEmpty {
          Text(status == "needs_approval" ? "Waiting for your approval" : status == "cancelling" ? "Waiting for the agent to stop" : activity)
            .font(.system(size: 12, design: .monospaced)).foregroundStyle(.secondary)
            .lineLimit(1).textSelection(.enabled).help(activity)
            .accessibilityLabel("Current agent activity")
        }
      }
    }.padding(.horizontal, 12).padding(.vertical, 8).frame(maxWidth: .infinity, alignment: .leading)
      .background(Color.qPanel, in: RoundedRectangle(cornerRadius: 12))
      .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.qAccent.opacity(0.12), lineWidth: 1))
  }
}

/// Account identity is absent from the view tree until deliberately revealed.
struct PrivateAccountDetails: View {
  let identity: String
  @State private var revealed = false
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Label("Signed-in account", systemImage: "person.crop.circle").font(.caption.weight(.medium))
        Spacer()
        Button(revealed ? "Hide account" : "Reveal account") { revealed.toggle() }.font(.caption)
      }
      if revealed { Text(identity).font(.caption).textSelection(.enabled) }
      else { Text("Account details are hidden for screen sharing.").font(.caption).foregroundStyle(.secondary) }
    }.onDisappear { revealed = false }.onChange(of: identity) { _, _ in revealed = false }
  }
}
