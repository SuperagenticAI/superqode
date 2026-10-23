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
      if embedded { ResponseDocument(text: text) }
      else {
        VStack(alignment: .leading, spacing: 14) {
          HStack(spacing: 7) {
            BrandMark().frame(width: 18, height: 18)
            Text("SuperQode").font(.system(size: 12, weight: .semibold)).foregroundStyle(Brand.wordmarkGradient(scheme))
          }
          ResponseDocument(text: text)
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

struct BrandActivityIndicator: View {
  var status = "running"
  var label: String {
    status == "needs_approval" ? "Waiting for permission" : status == "cancelling" ? "Stopping agent" : status == "queued" ? "Preparing agent" : "Agent is working"
  }
  var body: some View {
    HStack(spacing: 9) {
      if status == "needs_approval" { Image(systemName: "hand.raised").foregroundStyle(.orange) }
      else { ThinkingBar().frame(width: 52) }
      Text(label).font(.caption.weight(.medium)).modifier(BrandText())
    }.accessibilityElement(children: .ignore).accessibilityLabel(label)
  }
}

struct AgentWorkingCard: View {
  let status: String
  var progress = AgentProgress()
  var startedAt: Date?
  var body: some View {
    // Only this small card ticks; the transcript and workspace do not rerender each second.
    TimelineView(.periodic(from: .now, by: 1)) { timeline in
      let quiet = (progress.lastUpdate ?? startedAt).map { max(0, Int(timeline.date.timeIntervalSince($0))) }
      let waiting = (quiet ?? 0) >= 15
      let approval = status == "needs_approval"
      let stopping = status == "cancelling"
      let title = approval ? "Waiting for your approval" : stopping ? "Stopping the agent" : progress.title
      HStack(alignment: .top, spacing: 12) {
        Image(systemName: approval ? "hand.raised" : stopping ? "stop.circle" : progress.symbol)
          .font(.system(size: 20)).foregroundStyle(Color.qAccent).frame(width: 28, height: 28)
        VStack(alignment: .leading, spacing: 9) {
          HStack {
            Text(title).font(.system(size: 13, weight: .semibold)).modifier(BrandText())
            Spacer(minLength: 8)
            if let startedAt {
              Text(Self.duration(max(0, Int(timeline.date.timeIntervalSince(startedAt)))))
                .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
                .accessibilityLabel("Elapsed time")
                .accessibilityValue(Self.duration(max(0, Int(timeline.date.timeIntervalSince(startedAt)))))
            }
          }
          if !approval && !stopping { ThinkingBar().frame(maxWidth: .infinity) }
          Text(approval ? "Review the permission request to continue." : stopping ? "Waiting for the agent to acknowledge cancellation." : progress.detail)
            .font(.system(size: 12, design: progress.currentTool.isEmpty ? .default : .monospaced))
            .foregroundStyle(.primary).lineLimit(2).truncationMode(.middle).textSelection(.enabled)
          if !approval && !stopping {
            if progress.planTotal > 0 {
              HStack(spacing: 8) {
                Text("Plan: \(progress.planCompleted)/\(progress.planTotal) complete").font(.caption.weight(.medium))
                if !progress.planStep.isEmpty { Text(progress.planStep).font(.caption).lineLimit(1) }
              }.foregroundStyle(.secondary)
            }
            HStack(spacing: 8) {
              if progress.completedTools > 0 {
                Text("\(progress.completedTools) tool\(progress.completedTools == 1 ? "" : "s") finished").font(.caption)
              }
              if progress.failedTools > 0 {
                Text("\(progress.failedTools) failed").font(.caption).foregroundStyle(.orange)
              }
              if waiting, let quiet {
                Text("No new activity for \(Self.duration(quiet))").font(.caption).foregroundStyle(.secondary)
              }
            }.foregroundStyle(.secondary)
            if waiting {
              Text("Waiting for an agent update. Some tools and models stay quiet while working; you can stop the task below.")
                .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }
          }
        }
      }.padding(16).frame(maxWidth: .infinity, alignment: .leading)
        .background(Color.qPanel, in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.qAccent.opacity(0.25), lineWidth: 1))
    }.fixedSize(horizontal: false, vertical: true)
  }
  static func duration(_ seconds: Int) -> String {
    seconds < 60 ? "\(seconds)s" : "\(seconds / 60)m \(seconds % 60)s"
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
