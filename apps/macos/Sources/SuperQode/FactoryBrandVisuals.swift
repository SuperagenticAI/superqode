import SwiftUI

private struct FactoryEmblemSilhouette: Shape {
  func path(in rect: CGRect) -> Path {
    let w = rect.width
    let h = rect.height
    var bodyPath = Path()
    bodyPath.move(to: CGPoint(x: rect.minX + w * 0.16, y: rect.minY + h * 0.80))
    bodyPath.addLine(to: CGPoint(x: rect.minX + w * 0.16, y: rect.minY + h * 0.44))
    bodyPath.addLine(to: CGPoint(x: rect.minX + w * 0.38, y: rect.minY + h * 0.56))
    bodyPath.addLine(to: CGPoint(x: rect.minX + w * 0.38, y: rect.minY + h * 0.42))
    bodyPath.addLine(to: CGPoint(x: rect.minX + w * 0.62, y: rect.minY + h * 0.55))
    bodyPath.addLine(to: CGPoint(x: rect.minX + w * 0.62, y: rect.minY + h * 0.24))
    bodyPath.addLine(to: CGPoint(x: rect.minX + w * 0.84, y: rect.minY + h * 0.24))
    bodyPath.addLine(to: CGPoint(x: rect.minX + w * 0.84, y: rect.minY + h * 0.80))
    bodyPath.closeSubpath()
    return bodyPath
  }
}

private struct FactoryEmblemWindow: Shape {
  let xFraction: CGFloat
  func path(in rect: CGRect) -> Path {
    let w = rect.width
    let h = rect.height
    let winRect = CGRect(
      x: rect.minX + w * xFraction,
      y: rect.minY + h * 0.61,
      width: w * 0.13,
      height: h * 0.13
    )
    return Path(roundedRect: winRect, cornerRadius: 1.5)
  }
}

/// Original vector emblem for Factory Studio matching the SuperQode palette.
struct FactoryStudioEmblem: View {
  var size: CGFloat = 24
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    let fg: Color = contrast == .increased ? .primary : .white
    ZStack {
      RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
        .fill(
          contrast == .increased
            ? AnyShapeStyle(Color.primary.opacity(0.14))
            : AnyShapeStyle(LinearGradient(
              colors: [Brand.purple, Brand.pink, Brand.orange],
              startPoint: .topLeading, endPoint: .bottomTrailing))
        )
      ZStack {
        FactoryEmblemSilhouette()
          .fill(fg.opacity(0.95))
        FactoryEmblemWindow(xFraction: 0.28)
          .fill(Brand.purple.opacity(contrast == .increased ? 0.4 : 0.75))
        FactoryEmblemWindow(xFraction: 0.50)
          .fill(Brand.pink.opacity(contrast == .increased ? 0.4 : 0.75))
      }
      .padding(size * 0.12)
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }
}

/// Crisp tinted vector icons for the five Factory Studio navigation groups.
struct FactoryGroupMark: View {
  let id: String
  var selected: Bool = false
  var size: CGFloat = 22
  @Environment(\.colorSchemeContrast) private var contrast

  private var symbol: String {
    switch id {
    case "build": return "square.3.layers.3d"
    case "run": return "gauge.with.dots.needle.67percent"
    case "improve": return "sparkles"
    case "export": return "shippingbox"
    case "manage": return "slider.horizontal.3"
    default: return "building.2"
    }
  }

  private var accent: Color {
    switch id {
    case "build": return Brand.purple
    case "run": return Color(red: 0.14, green: 0.62, blue: 0.42)
    case "improve": return Brand.pink
    case "export": return Color(red: 0.18, green: 0.48, blue: 0.84)
    case "manage": return Brand.orange
    default: return Brand.purple
    }
  }

  var body: some View {
    ZStack {
      RoundedRectangle(cornerRadius: size * 0.27, style: .continuous)
        .fill(
          contrast == .increased
            ? Color.primary.opacity(selected ? 0.18 : 0.08)
            : accent.opacity(selected ? 0.22 : 0.12)
        )
      Image(systemName: symbol)
        .font(.system(size: size * 0.50, weight: .semibold))
        .foregroundStyle(contrast == .increased ? Color.primary : accent)
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }
}

/// Visual tone and emblem choice for Factory Studio animations and confirmations.
enum FactoryVisualKind: Equatable {
  case factory
  case draft
  case workflow
  case save
  case trial
  case run
  case superGauge
  case touchID
  case improve
  case source
  case export
  case caution

  var symbol: String {
    switch self {
    case .factory: return "square.3.layers.3d"
    case .draft: return "wand.and.stars"
    case .workflow: return "point.3.connected.trianglepath.dotted"
    case .save: return "checkmark.seal.fill"
    case .trial: return "flask.fill"
    case .run: return "play.circle.fill"
    case .superGauge: return "gauge.with.dots.needle.67percent"
    case .touchID: return "touchid"
    case .improve: return "sparkles"
    case .source: return "arrow.triangle.branch"
    case .export: return "shippingbox.fill"
    case .caution: return "exclamationmark.triangle.fill"
    }
  }

  var accent: Color {
    switch self {
    case .factory, .draft, .workflow: return Brand.purple
    case .save, .superGauge: return Color(red: 0.14, green: 0.62, blue: 0.42)
    case .trial, .run: return Brand.pink
    case .touchID: return Brand.purple
    case .improve: return Brand.pink
    case .source, .export: return Color(red: 0.18, green: 0.48, blue: 0.84)
    case .caution: return Brand.orange
    }
  }

  var palette: [Color] {
    switch self {
    case .superGauge, .save:
      return [Color(red: 0.14, green: 0.62, blue: 0.42), Brand.purple, Color(red: 0.18, green: 0.56, blue: 0.78)]
    case .caution:
      return [Brand.orange, Brand.pink, Brand.orange]
    default:
      return [Brand.purple, Brand.pink, Brand.orange]
    }
  }
}

/// Self-contained 30fps animated orb matching Local AI's WarmupOrb.
/// Draws only inside its Canvas; never publishes workspace state.
struct FactoryActionOrb: View {
  var kind: FactoryVisualKind = .factory
  var size: CGFloat = 72
  var active: Bool = true
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Environment(\.colorSchemeContrast) private var contrast
  @AppStorage("animatedInterface") private var animated = true

  private var motion: Bool { active && animated && !reduceMotion }
  private var emphasized: Bool { contrast == .increased }

  var body: some View {
    ZStack {
      if motion {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { timeline in
          Canvas { context, canvasSize in
            let time = timeline.date.timeIntervalSinceReferenceDate
            let center = CGPoint(x: canvasSize.width / 2, y: canvasSize.height / 2)
            let maxR = min(canvasSize.width, canvasSize.height) * 0.47
            let baseR = min(canvasSize.width, canvasSize.height) * 0.24
            let colors = emphasized ? [Color.primary, Color.primary, Color.primary] : kind.palette

            for index in 0..<3 {
              let phase = (time / 2.4 + Double(index) / 3).truncatingRemainder(dividingBy: 1)
              let radius = baseR + phase * (maxR - baseR)
              var ring = Path()
              ring.addEllipse(in: CGRect(
                x: center.x - radius, y: center.y - radius,
                width: radius * 2, height: radius * 2))
              context.stroke(
                ring,
                with: .color(colors[index % colors.count].opacity((1 - phase) * 0.68)),
                lineWidth: max(1.4, size * 0.024))
            }

            let spin = time.truncatingRemainder(dividingBy: 2.2) / 2.2
            var arc = Path()
            arc.addArc(
              center: center,
              radius: baseR + (maxR - baseR) * 0.42,
              startAngle: .degrees(spin * 360 - 90),
              endAngle: .degrees(spin * 360 + 82),
              clockwise: false)
            context.stroke(
              arc,
              with: .linearGradient(
                Gradient(colors: colors),
                startPoint: CGPoint(x: 0, y: canvasSize.height),
                endPoint: CGPoint(x: canvasSize.width, y: 0)),
              style: StrokeStyle(lineWidth: max(2.2, size * 0.042), lineCap: .round))
          }
        }
      } else {
        Circle()
          .stroke(
            emphasized ? AnyShapeStyle(Color.primary.opacity(0.35)) : AnyShapeStyle(Brand.gradient.opacity(0.45)),
            lineWidth: max(2, size * 0.032))
          .padding(size * 0.14)
      }

      Circle()
        .fill(Color.qPanel)
        .frame(width: size * 0.50, height: size * 0.50)
        .overlay(
          Circle().stroke(
            emphasized ? Color.primary.opacity(0.3) : kind.accent.opacity(0.28),
            lineWidth: 1)
        )

      if kind == .superGauge {
        SuperGaugeMark(verdict: .pending, size: size * 0.36, animating: motion)
      } else if kind == .factory {
        FactoryStudioEmblem(size: size * 0.34)
      } else {
        Image(systemName: kind.symbol)
          .font(.system(size: size * 0.22, weight: .semibold))
          .foregroundStyle(emphasized ? AnyShapeStyle(Color.primary) : AnyShapeStyle(Brand.gradient))
      }
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }
}

/// Animated activity banner replacing plain ProgressView spinners during Factory work.
struct FactoryActivityBanner: View {
  var title: String
  var detail: String = ""
  var kind: FactoryVisualKind = .factory
  var stopTitle: String = "Stop action"
  var onStop: (() -> Void)? = nil
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    HStack(spacing: 14) {
      FactoryActionOrb(kind: kind, size: 54, active: true)
      VStack(alignment: .leading, spacing: 5) {
        Text(title).font(.subheadline.weight(.semibold))
        if !detail.isEmpty {
          Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }
        ThinkingBar().frame(maxWidth: 220)
      }
      Spacer(minLength: 8)
      if let onStop {
        Button(stopTitle, action: onStop)
      }
    }
    .padding(.horizontal, 14)
    .padding(.vertical, 10)
    .background {
      RoundedRectangle(cornerRadius: 14, style: .continuous)
        .fill(Color.primary.opacity(0.035))
    }
    .overlay {
      RoundedRectangle(cornerRadius: 14, style: .continuous)
        .strokeBorder(
          contrast == .increased
            ? AnyShapeStyle(Color.primary.opacity(0.45))
            : AnyShapeStyle(LinearGradient(
              colors: [Brand.purple.opacity(0.48), Brand.pink.opacity(0.36), Brand.orange.opacity(0.42)],
              startPoint: .topLeading, endPoint: .bottomTrailing)),
          lineWidth: 1)
    }
  }
}

/// Compact badge metadata displayed inside inline confirmations and native sheets.
struct FactoryConfirmBadge: Identifiable, Equatable {
  let id = UUID()
  let label: String
  let symbol: String
  let color: Color
}

/// Calm, crisp emblem for confirmations and headers (never spins like a loading indicator).
struct FactoryConfirmEmblem: View {
  var kind: FactoryVisualKind = .factory
  var workflowID: String? = nil
  var size: CGFloat = 52
  @Environment(\.colorSchemeContrast) private var contrast
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @AppStorage("animatedInterface") private var animated = true
  @State private var appeared = false

  var body: some View {
    ZStack {
      Circle()
        .fill(
          contrast == .increased
            ? AnyShapeStyle(Color.primary.opacity(0.10))
            : AnyShapeStyle(LinearGradient(
              colors: [kind.palette[0].opacity(0.16), kind.palette[1].opacity(0.10)],
              startPoint: .topLeading, endPoint: .bottomTrailing))
        )
        .overlay(
          Circle().stroke(
            contrast == .increased
              ? AnyShapeStyle(Color.primary.opacity(0.35))
              : AnyShapeStyle(LinearGradient(
                colors: [kind.palette[0].opacity(0.45), kind.palette[1].opacity(0.35)],
                startPoint: .topLeading, endPoint: .bottomTrailing)),
            lineWidth: 1.2)
        )

      if let workflowID, !workflowID.isEmpty {
        FactoryWorkflowMark(id: workflowID)
          .frame(width: size * 0.62, height: size * 0.62)
      } else if kind == .superGauge {
        SuperGaugeMark(verdict: .ship, size: size * 0.68, animating: false)
      } else if kind == .factory {
        FactoryStudioEmblem(size: size * 0.56)
      } else {
        Image(systemName: kind.symbol)
          .font(.system(size: size * 0.36, weight: .semibold))
          .foregroundStyle(contrast == .increased ? AnyShapeStyle(Color.primary) : AnyShapeStyle(Brand.gradient))
      }
    }
    .frame(width: size, height: size)
    .scaleEffect(appeared || !animated || reduceMotion ? 1.0 : 0.86)
    .opacity(appeared || !animated || reduceMotion ? 1.0 : 0.0)
    .onAppear {
      guard animated && !reduceMotion else { appeared = true; return }
      withAnimation(.spring(response: 0.32, dampingFraction: 0.78)) { appeared = true }
    }
    .accessibilityHidden(true)
  }
}

/// Smoothly animated inline confirmation drawer for quick in-flow Factory Studio actions
/// (Generate draft, Load workflow, Save revision, Prepare trial) — no jarring modal alert!
struct FactoryInlineConfirmCard: View {
  let title: String
  let message: String
  var kind: FactoryVisualKind = .factory
  var workflowID: String? = nil
  var badges: [FactoryConfirmBadge] = []
  var confirmTitle: String = "Continue"
  var confirmDisabled: Bool = false
  var inputLabel: String? = nil
  var inputText: Binding<String>? = nil
  var onCancel: () -> Void
  var onConfirm: () -> Void
  @Environment(\.colorSchemeContrast) private var contrast
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @AppStorage("animatedInterface") private var animated = true
  @State private var appeared = false

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack(alignment: .top, spacing: 14) {
        FactoryConfirmEmblem(kind: kind, workflowID: workflowID, size: 52)
        VStack(alignment: .leading, spacing: 6) {
          HStack(spacing: 8) {
            Text(title).font(.headline)
            Spacer(minLength: 4)
            Button(action: onCancel) {
              Image(systemName: "xmark")
                .font(.system(size: 11, weight: .semibold))
                .foregroundStyle(.secondary)
                .padding(5)
                .background(Color.primary.opacity(0.06), in: Circle())
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Dismiss confirmation")
          }
          if !badges.isEmpty {
            HStack(spacing: 6) {
              ForEach(badges) { badge in
                Label(badge.label, systemImage: badge.symbol)
                  .font(.caption2.weight(.semibold))
                  .foregroundStyle(contrast == .increased ? .primary : badge.color)
                  .padding(.horizontal, 8)
                  .padding(.vertical, 3)
                  .background(badge.color.opacity(contrast == .increased ? 0.18 : 0.12), in: Capsule())
              }
            }
          }
          Text(message)
            .font(.callout)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
          if let inputLabel, let inputText {
            TextField(inputLabel, text: inputText)
              .textFieldStyle(.roundedBorder)
              .frame(maxWidth: 420)
              .padding(.top, 2)
          }
          HStack(spacing: 10) {
            Button(confirmTitle, action: onConfirm)
              .buttonStyle(BrandButtonStyle())
              .disabled(confirmDisabled)
            Button("Cancel", role: .cancel, action: onCancel)
          }
          .padding(.top, 2)
        }
      }
    }
    .padding(16)
    .background {
      RoundedRectangle(cornerRadius: 16, style: .continuous)
        .fill(Color.qPanel)
    }
    .overlay {
      RoundedRectangle(cornerRadius: 16, style: .continuous)
        .strokeBorder(
          contrast == .increased
            ? AnyShapeStyle(Color.primary.opacity(0.55))
            : AnyShapeStyle(LinearGradient(
              colors: [Brand.purple.opacity(0.55), Brand.pink.opacity(0.42), Brand.orange.opacity(0.48)],
              startPoint: .topLeading, endPoint: .bottomTrailing)),
          lineWidth: 1.2)
    }
    .shadow(color: Brand.purple.opacity(0.08), radius: 14, y: 5)
    .offset(y: appeared || !animated || reduceMotion ? 0 : -8)
    .opacity(appeared || !animated || reduceMotion ? 1 : 0)
    .onAppear {
      guard animated && !reduceMotion else { appeared = true; return }
      withAnimation(.spring(response: 0.28, dampingFraction: 0.84)) { appeared = true }
    }
    .onExitCommand(perform: onCancel)
  }
}

/// Branded native confirmation sheet replacing raw macOS .alert() modals across all Factory views.
struct FactoryConfirmationSheet: View {
  let title: String
  let message: String
  var kind: FactoryVisualKind = .factory
  var badges: [FactoryConfirmBadge] = []
  var confirmTitle: String = "Continue"
  var confirmDisabled: Bool = false
  var inputLabel: String? = nil
  var inputText: Binding<String>? = nil
  var onCancel: () -> Void
  var onConfirm: () -> Void
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    VStack(spacing: 18) {
      FactoryConfirmEmblem(kind: kind, size: 74)
        .padding(.top, 6)

      VStack(spacing: 8) {
        Text(title)
          .font(.title3.weight(.semibold))
          .multilineTextAlignment(.center)

        if !badges.isEmpty {
          HStack(spacing: 6) {
            ForEach(badges) { badge in
              Label(badge.label, systemImage: badge.symbol)
                .font(.caption2.weight(.semibold))
                .foregroundStyle(contrast == .increased ? .primary : badge.color)
                .padding(.horizontal, 9)
                .padding(.vertical, 4)
                .background(badge.color.opacity(contrast == .increased ? 0.18 : 0.12), in: Capsule())
            }
          }
        }

        Text(message)
          .font(.callout)
          .foregroundStyle(.secondary)
          .multilineTextAlignment(.center)
          .fixedSize(horizontal: false, vertical: true)
          .frame(maxWidth: 420)
      }

      if let inputLabel, let inputText {
        TextField(inputLabel, text: inputText)
          .textFieldStyle(.roundedBorder)
          .frame(maxWidth: 380)
      }

      Divider()

      HStack(spacing: 10) {
        Button("Cancel", role: .cancel, action: onCancel)
          .keyboardShortcut(.cancelAction)
        Spacer()
        Button(confirmTitle, action: onConfirm)
          .buttonStyle(BrandButtonStyle())
          .disabled(confirmDisabled)
          .keyboardShortcut(.defaultAction)
      }
    }
    .padding(24)
    .frame(minWidth: 440, maxWidth: 480)
    .background(Color.qPanel)
    .overlay {
      RoundedRectangle(cornerRadius: 16, style: .continuous)
        .strokeBorder(
          contrast == .increased
            ? AnyShapeStyle(Color.primary.opacity(0.45))
            : AnyShapeStyle(LinearGradient(
              colors: [Brand.purple.opacity(0.42), Brand.pink.opacity(0.32), Brand.orange.opacity(0.38)],
              startPoint: .topLeading, endPoint: .bottomTrailing)),
          lineWidth: 1)
        .padding(1)
    }
    .onExitCommand(perform: onCancel)
  }
}

extension View {
  /// Present a branded animated Factory confirmation sheet instead of a plain system .alert().
  func factoryConfirmation(
    isPresented: Binding<Bool>,
    title: String,
    message: String,
    kind: FactoryVisualKind = .factory,
    badges: [FactoryConfirmBadge] = [],
    confirmTitle: String = "Continue",
    confirmDisabled: Bool = false,
    inputLabel: String? = nil,
    inputText: Binding<String>? = nil,
    onCancel: (() -> Void)? = nil,
    onConfirm: @escaping () -> Void
  ) -> some View {
    sheet(isPresented: isPresented) {
      FactoryConfirmationSheet(
        title: title,
        message: message,
        kind: kind,
        badges: badges,
        confirmTitle: confirmTitle,
        confirmDisabled: confirmDisabled,
        inputLabel: inputLabel,
        inputText: inputText,
        onCancel: {
          onCancel?()
          isPresented.wrappedValue = false
        },
        onConfirm: {
          onConfirm()
          isPresented.wrappedValue = false
        }
      )
    }
  }
}

/// Sleek inline banner for Factory status & error messages.
struct FactoryNoticeBanner: View {
  let text: String
  var isFailure: Bool = false
  @State private var expanded = false

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack(alignment: .top, spacing: 8) {
        Image(systemName: isFailure ? "exclamationmark.triangle.fill" : "checkmark.circle.fill")
          .font(.system(size: 13, weight: .semibold))
          .foregroundStyle(isFailure ? Color.orange : Color(red: 0.14, green: 0.62, blue: 0.42))
          .padding(.top, 1)
        Text(text)
          .font(.caption)
          .foregroundStyle(isFailure ? Color.orange : Color.primary)
          .lineLimit(expanded ? nil : 2)
          .textSelection(.enabled)
        Spacer(minLength: 4)
        if text.count > 120 {
          Button(expanded ? "Less" : "More") {
            withAnimation(.easeInOut(duration: 0.16)) { expanded.toggle() }
          }
          .font(.caption2)
          .buttonStyle(.plain)
          .foregroundStyle(.secondary)
        }
      }
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 8)
    .background(
      (isFailure ? Color.orange : Color(red: 0.14, green: 0.62, blue: 0.42)).opacity(0.08),
      in: RoundedRectangle(cornerRadius: 10, style: .continuous)
    )
    .overlay(
      RoundedRectangle(cornerRadius: 10, style: .continuous)
        .stroke((isFailure ? Color.orange : Color(red: 0.14, green: 0.62, blue: 0.42)).opacity(0.24), lineWidth: 1)
    )
  }
}

/// Visual card for each optimizer engine in Factory Improvement (Native, GEPA, MetaHarness, Omni).
struct FactoryOptimizerCard: View {
  let id: String
  let title: String
  let subtitle: String
  let symbol: String
  let available: Bool
  let selected: Bool
  let action: () -> Void
  @Environment(\.colorSchemeContrast) private var contrast

  private var accent: Color {
    switch id {
    case "evaluator-optimizer": return Brand.purple
    case "gepa": return Brand.pink
    case "metaharness": return Color(red: 0.18, green: 0.48, blue: 0.84)
    case "omni": return Brand.orange
    default: return Brand.purple
    }
  }

  var body: some View {
    Button(action: action) {
      HStack(alignment: .top, spacing: 10) {
        ZStack {
          RoundedRectangle(cornerRadius: 8, style: .continuous)
            .fill(accent.opacity(selected ? 0.22 : 0.11))
          Image(systemName: symbol)
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(contrast == .increased ? Color.primary : accent)
        }
        .frame(width: 28, height: 28)

        VStack(alignment: .leading, spacing: 3) {
          HStack(spacing: 6) {
            Text(title).font(.caption.weight(.semibold))
            Spacer(minLength: 4)
            Text(available ? "Ready" : "Optional")
              .font(.system(size: 10, weight: .semibold))
              .foregroundStyle(available ? Color(red: 0.14, green: 0.62, blue: 0.42) : .secondary)
              .padding(.horizontal, 6)
              .padding(.vertical, 2)
              .background((available ? Color(red: 0.14, green: 0.62, blue: 0.42) : Color.secondary).opacity(0.12), in: Capsule())
          }
          Text(subtitle)
            .font(.caption2)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
            .multilineTextAlignment(.leading)
        }
      }
      .padding(10)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(selected ? accent.opacity(0.08) : Color.qPanel, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
      .overlay(
        RoundedRectangle(cornerRadius: 11, style: .continuous)
          .strokeBorder(
            selected
              ? (contrast == .increased ? Color.primary : accent)
              : Color.primary.opacity(0.10),
            lineWidth: selected ? 1.4 : 1)
      )
    }
    .buttonStyle(.plain)
  }
}

/// Visual before-vs-after held-out comparison score card for Factory Improvement Evidence.
struct FactoryScoreDeltaCard: View {
  let baseline: Double
  let candidate: Double
  let eligible: Bool

  private var delta: Double { candidate - baseline }
  private var deltaColor: Color {
    if eligible && delta > 0 { return Color(red: 0.14, green: 0.62, blue: 0.42) }
    if delta < 0 { return .red }
    return .orange
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Label("Held-out pass rate", systemImage: "chart.bar.xaxis")
          .font(.subheadline.weight(.semibold))
        Spacer()
        Pill(title: eligible ? "Eligible for draft review" : "Hold", color: eligible ? .green : .orange)
      }
      HStack(spacing: 16) {
        scoreColumn(label: "Baseline", value: baseline, tint: .secondary)
        Image(systemName: "arrow.right")
          .font(.system(size: 13, weight: .bold))
          .foregroundStyle(.secondary)
        scoreColumn(label: "Candidate", value: candidate, tint: deltaColor)
        Spacer()
        VStack(alignment: .trailing, spacing: 2) {
          Text(String(format: "%+.0f%%", delta * 100))
            .font(.title3.weight(.bold).monospacedDigit())
            .foregroundStyle(deltaColor)
          Text("Held-out delta").font(.caption2).foregroundStyle(.secondary)
        }
      }
    }
    .padding(14)
    .brandSurface(radius: 14)
  }

  private func scoreColumn(label: String, value: Double, tint: Color) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      Text(label).font(.caption2).foregroundStyle(.secondary)
      Text(String(format: "%.0f%%", value * 100))
        .font(.headline.monospacedDigit())
      GeometryReader { geo in
        ZStack(alignment: .leading) {
          Capsule().fill(Color.primary.opacity(0.08))
          Capsule().fill(tint)
            .frame(width: max(4, geo.size.width * min(1, max(0, value))))
        }
      }
      .frame(width: 110, height: 6)
    }
  }
}
