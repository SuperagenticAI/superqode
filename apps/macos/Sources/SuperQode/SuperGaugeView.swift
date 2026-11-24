import SwiftUI

/// SuperGauge deterministic verdict values emitted by the Factory verifier.
enum SuperGaugeVerdict: String, Equatable {
  case ship
  case hold
  case reject
  case pending

  init(raw: String) {
    switch raw.lowercased().trimmingCharacters(in: .whitespacesAndNewlines) {
    case "ship", "passed", "pass": self = .ship
    case "hold", "review": self = .hold
    case "reject", "rejected", "failed", "fail": self = .reject
    default: self = .pending
    }
  }

  var title: String {
    switch self {
    case .ship: return "SHIP"
    case .hold: return "HOLD"
    case .reject: return "REJECT"
    case .pending: return "PENDING"
    }
  }

  var subtitle: String {
    switch self {
    case .ship: return "Deterministic checks passed · ready for human sign-off"
    case .hold: return "Review required before release"
    case .reject: return "Protected verification failed"
    case .pending: return "Run protected verification to compute a SuperGauge verdict"
    }
  }

  var color: Color {
    switch self {
    case .ship: return Color(red: 0.14, green: 0.64, blue: 0.42)
    case .hold: return Color(red: 0.90, green: 0.56, blue: 0.12)
    case .reject: return Color(red: 0.85, green: 0.24, blue: 0.26)
    case .pending: return Brand.purple
    }
  }

  var symbol: String {
    switch self {
    case .ship: return "checkmark.shield.fill"
    case .hold: return "pause.circle.fill"
    case .reject: return "xmark.octagon.fill"
    case .pending: return "gauge.with.dots.needle.33percent"
    }
  }

  /// Normalized needle position along the 180-degree SuperGauge arc (0 = reject, 0.5 = hold, 0.92 = ship).
  var needlePosition: Double {
    switch self {
    case .reject: return 0.12
    case .hold: return 0.50
    case .ship: return 0.92
    case .pending: return 0.34
    }
  }
}

/// Typed summary parsed from a Factory run's SuperGauge quality record (`factory_quality_record`).
struct SuperGaugeSnapshot: Equatable {
  struct JudgeSignal: Equatable, Identifiable {
    let id: String
    let verdict: String
    let model: String
  }

  let verdict: SuperGaugeVerdict
  let profileLabel: String
  let completionRate: Double?
  let totalCases: Int
  let passedCases: Int
  let sandbox: String
  let isolationPassed: Bool?
  let evaluatorsHidden: Bool?
  let evidenceComplete: Bool?
  let contaminationDetected: Bool
  let reasons: [String]
  let judges: [JudgeSignal]
  let hasRecord: Bool

  static func parse(detail: [String: Any]) -> SuperGaugeSnapshot {
    let evidence = detail["evidence"] as? [[String: Any]] ?? []
    let qualityArtifact = evidence.last { string($0, "kind") == "factory_quality_record" }
    var record: [String: Any] = [:]
    if let content = qualityArtifact?["content"] as? String,
      let data = content.data(using: .utf8),
      let parsed = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
      record = parsed
    }

    let order = detail["work_order"] as? [String: Any] ?? [:]
    let metadata = order["metadata"] as? [String: Any] ?? [:]
    let receipt = metadata["factory_verification"] as? [String: Any] ?? [:]

    guard !record.isEmpty else {
      let receiptState = string(receipt, "state")
      let fallbackVerdict: SuperGaugeVerdict = receiptState == "passed" ? .ship : receiptState == "failed" ? .reject : .pending
      return SuperGaugeSnapshot(
        verdict: fallbackVerdict,
        profileLabel: "SuperGauge · Deterministic",
        completionRate: nil,
        totalCases: 0,
        passedCases: 0,
        sandbox: string(receipt, "sandbox"),
        isolationPassed: receipt["isolation_applied"] as? Bool,
        evaluatorsHidden: nil,
        evidenceComplete: nil,
        contaminationDetected: false,
        reasons: [],
        judges: [],
        hasRecord: !receipt.isEmpty
      )
    }

    let decision = record["decision"] as? [String: Any] ?? [:]
    let verdict = SuperGaugeVerdict(raw: string(decision, "verdict"))

    let profile = record["profile"] as? [String: Any] ?? [:]
    let tier = string(profile, "tier")
    let profileID = string(profile, "id")
    let profileLabel = [profileID.isEmpty ? "sg/coding-agent" : profileID, tier.isEmpty ? nil : tier]
      .compactMap { $0 }
      .joined(separator: " · ")

    let taskSet = record["task_set"] as? [String: Any] ?? [:]
    let heldOut = taskSet["held_out"] as? Int ?? 0

    var completion: Double?
    var evidenceComplete: Bool?
    if let measures = record["measures"] as? [[String: Any]] {
      for row in measures {
        let name = string(row, "name")
        if name == "task.completion", let val = row["value"] as? Double {
          completion = val
        } else if name == "task.completion", let val = row["value"] as? Int {
          completion = Double(val)
        } else if name == "assurance.evidence_complete", let val = row["value"] as? Bool {
          evidenceComplete = val
        }
      }
    } else if let measures = record["measures"] as? [String: Any] {
      if let entry = measures["task.completion"] as? [String: Any] {
        completion = entry["value"] as? Double ?? (entry["value"] as? Int).map(Double.init)
      }
      if let entry = measures["assurance.evidence_complete"] as? [String: Any] {
        evidenceComplete = entry["value"] as? Bool
      }
    }

    let passedCases: Int
    if let completion, heldOut > 0 {
      passedCases = Int((completion * Double(heldOut)).rounded())
    } else {
      passedCases = 0
    }

    var isolationPassed: Bool?
    var evaluatorsHidden: Bool?
    var contaminationDetected = false
    if let gates = record["gates"] as? [[String: Any]] {
      for gate in gates {
        let name = string(gate, "name")
        let status = string(gate, "status")
        if name == "safety.isolation" { isolationPassed = (status == "pass") }
        if name == "assurance.evaluator_hidden" { evaluatorsHidden = (status == "pass") }
        if name == "assurance.contamination" { contaminationDetected = (status == "fail") }
      }
    } else if let gates = record["gates"] as? [String: Any] {
      if let g = gates["safety.isolation"] as? [String: Any] { isolationPassed = string(g, "status") == "pass" }
      if let g = gates["assurance.evaluator_hidden"] as? [String: Any] { evaluatorsHidden = string(g, "status") == "pass" }
      if let g = gates["assurance.contamination"] as? [String: Any] { contaminationDetected = string(g, "status") == "fail" }
    }

    if evaluatorsHidden == nil {
      let assurance = record["assurance"] as? [String: Any] ?? [:]
      evaluatorsHidden = assurance["evaluator_independent"] as? Bool
    }

    let subject = record["subject"] as? [String: Any] ?? [:]
    let authority = subject["authority"] as? [String: Any] ?? [:]
    let sandbox = string(authority, "sandbox", string(receipt, "sandbox"))

    let reasons = (decision["reasons"] as? [String] ?? [])
      + (decision["reject_reasons"] as? [String] ?? [])
      + (decision["hold_reasons"] as? [String] ?? [])

    let rawJudges = decision["judges"] as? [[String: Any]] ?? []
    let judges = rawJudges.map {
      JudgeSignal(
        id: string($0, "id", "judge"),
        verdict: string($0, "verdict", "hold"),
        model: string($0, "model")
      )
    }

    return SuperGaugeSnapshot(
      verdict: verdict,
      profileLabel: profileLabel,
      completionRate: completion,
      totalCases: heldOut,
      passedCases: passedCases,
      sandbox: sandbox,
      isolationPassed: isolationPassed,
      evaluatorsHidden: evaluatorsHidden,
      evidenceComplete: evidenceComplete,
      contaminationDetected: contaminationDetected,
      reasons: reasons,
      judges: judges,
      hasRecord: true
    )
  }
}

/// Dedicated vector SuperGauge emblem & precision animated dial.
/// Scales cleanly from 18pt badge size up to 84pt verdict hero dial.
struct SuperGaugeMark: View {
  var verdict: SuperGaugeVerdict = .ship
  var size: CGFloat = 68
  var animating: Bool = false
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Environment(\.colorSchemeContrast) private var contrast
  @AppStorage("animatedInterface") private var animatedInterface = true

  private var shouldSweep: Bool { animating && animatedInterface && !reduceMotion }

  var body: some View {
    Group {
      if shouldSweep {
        TimelineView(.animation(minimumInterval: 1.0 / 30)) { timeline in
          let t = timeline.date.timeIntervalSinceReferenceDate
          let sweep = 0.5 + 0.42 * sin(t * 2.8)
          dialCanvas(position: sweep, pulse: 0.5 + 0.5 * sin(t * 4.0))
        }
      } else {
        dialCanvas(position: verdict.needlePosition, pulse: 1.0)
      }
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }

  private func dialCanvas(position: Double, pulse: Double) -> some View {
    Canvas { context, canvasSize in
      let w = canvasSize.width
      let h = canvasSize.height
      let center = CGPoint(x: w * 0.50, y: h * 0.62)
      let radius = min(w, h) * 0.40
      let strokeW = max(2.2, size * 0.095)
      let emphasized = contrast == .increased

      // Subtle outer halo glow for hero sizes.
      if size >= 44 && !emphasized {
        let haloR = radius + strokeW * 0.85
        var halo = Path()
        halo.addArc(center: center, radius: haloR, startAngle: .degrees(185), endAngle: .degrees(355), clockwise: false)
        context.stroke(
          halo,
          with: .color(verdict.color.opacity(0.16 * pulse)),
          style: StrokeStyle(lineWidth: strokeW * 1.1, lineCap: .round))
      }

      // Base muted track arc (180° left-to-right).
      var track = Path()
      track.addArc(center: center, radius: radius, startAngle: .degrees(180), endAngle: .degrees(360), clockwise: false)
      context.stroke(
        track,
        with: .color(Color.primary.opacity(0.11)),
        style: StrokeStyle(lineWidth: strokeW, lineCap: .round))

      // Active arc from left to needle position with SuperQode brand/verdict gradient.
      let clamped = min(0.98, max(0.04, position))
      var activeArc = Path()
      activeArc.addArc(
        center: center,
        radius: radius,
        startAngle: .degrees(180),
        endAngle: .degrees(180 + 180 * clamped),
        clockwise: false)

      let arcColors: [Color] = emphasized
        ? [.primary, .primary]
        : animating
          ? [Brand.purple, Brand.pink, Brand.orange]
          : verdict == .ship
            ? [Brand.purple, Color(red: 0.18, green: 0.56, blue: 0.78), verdict.color]
            : verdict == .hold
              ? [Brand.purple, Brand.orange, verdict.color]
              : verdict == .reject
                ? [verdict.color, Brand.pink]
                : [Brand.purple, Brand.pink, Brand.orange]

      context.stroke(
        activeArc,
        with: .linearGradient(
          Gradient(colors: arcColors),
          startPoint: CGPoint(x: center.x - radius, y: center.y),
          endPoint: CGPoint(x: center.x + radius, y: center.y)),
        style: StrokeStyle(lineWidth: strokeW, lineCap: .round))

      // Precision tick marks on larger dials.
      if size >= 40 {
        for tick in 0...4 {
          let angle = Double.pi + (Double(tick) / 4.0) * Double.pi
          let inner = radius - strokeW * 0.85
          let outer = radius - strokeW * 0.52
          var tickPath = Path()
          tickPath.move(to: CGPoint(x: center.x + cos(angle) * inner, y: center.y + sin(angle) * inner))
          tickPath.addLine(to: CGPoint(x: center.x + cos(angle) * outer, y: center.y + sin(angle) * outer))
          context.stroke(tickPath, with: .color(Color.primary.opacity(0.28)), style: StrokeStyle(lineWidth: 1.2, lineCap: .round))
        }
      }

      // Precision needle.
      let needleAngle = Double.pi + clamped * Double.pi
      let needleLen = radius * 0.76
      let tip = CGPoint(x: center.x + cos(needleAngle) * needleLen, y: center.y + sin(needleAngle) * needleLen)
      var needle = Path()
      needle.move(to: center)
      needle.addLine(to: tip)
      context.stroke(
        needle,
        with: .color(emphasized ? .primary : verdict.color),
        style: StrokeStyle(lineWidth: max(1.8, size * 0.048), lineCap: .round))

      // Center pivot hub.
      let hubR = max(2.6, size * 0.075)
      let hubRect = CGRect(x: center.x - hubR, y: center.y - hubR, width: hubR * 2, height: hubR * 2)
      context.fill(Path(ellipseIn: hubRect), with: .color(emphasized ? .primary : verdict.color))
      let coreR = hubR * 0.45
      let coreRect = CGRect(x: center.x - coreR, y: center.y - coreR, width: coreR * 2, height: coreR * 2)
      context.fill(Path(ellipseIn: coreRect), with: .color(Color.qPanel))
    }
  }
}

/// Compact inline SuperGauge pill for run rows, suite scorecards, and headers.
struct SuperGaugeBadge: View {
  let verdict: SuperGaugeVerdict
  var showWordmark: Bool = true
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    HStack(spacing: 5) {
      SuperGaugeMark(verdict: verdict, size: 16, animating: false)
      if showWordmark {
        Text("SuperGauge")
          .font(.system(size: 10, weight: .semibold))
          .foregroundStyle(.secondary)
      }
      Text(verdict.title)
        .font(.system(size: 10, weight: .bold))
        .foregroundStyle(contrast == .increased ? Color.primary : verdict.color)
    }
    .padding(.horizontal, 8)
    .padding(.vertical, 3)
    .background(verdict.color.opacity(contrast == .increased ? 0.16 : 0.11), in: Capsule())
    .overlay(Capsule().stroke(verdict.color.opacity(0.28), lineWidth: 0.8))
  }
}

/// Branded hero dashboard card for SuperGauge verification results in Factory Studio Runs.
struct SuperGaugeVerdictCard: View {
  let snapshot: SuperGaugeSnapshot
  var isVerifying: Bool = false
  let rawEvidence: Any?
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack(alignment: .center, spacing: 16) {
        ZStack {
          RoundedRectangle(cornerRadius: 14, style: .continuous)
            .fill(snapshot.verdict.color.opacity(contrast == .increased ? 0.12 : 0.08))
          SuperGaugeMark(verdict: snapshot.verdict, size: 70, animating: isVerifying)
        }
        .frame(width: 82, height: 68)
        .overlay(
          RoundedRectangle(cornerRadius: 14, style: .continuous)
            .stroke(snapshot.verdict.color.opacity(0.24), lineWidth: 1)
        )

        VStack(alignment: .leading, spacing: 5) {
          HStack(spacing: 8) {
            Text("SuperGauge")
              .font(.headline.weight(.bold))
              .foregroundStyle(
                contrast == .increased
                  ? AnyShapeStyle(Color.primary)
                  : AnyShapeStyle(Brand.wordmarkGradient(scheme))
              )
            Text(snapshot.profileLabel)
              .font(.caption2.monospaced())
              .foregroundStyle(.secondary)
              .padding(.horizontal, 7)
              .padding(.vertical, 2)
              .background(Color.primary.opacity(0.06), in: Capsule())
            Spacer(minLength: 4)
            Label(isVerifying ? "VERIFYING" : snapshot.verdict.title, systemImage: snapshot.verdict.symbol)
              .font(.caption.weight(.bold))
              .foregroundStyle(contrast == .increased ? .primary : snapshot.verdict.color)
              .padding(.horizontal, 10)
              .padding(.vertical, 4)
              .background(snapshot.verdict.color.opacity(0.14), in: Capsule())
              .overlay(Capsule().stroke(snapshot.verdict.color.opacity(0.35), lineWidth: 1))
          }

          Text(isVerifying ? "Executing protected probes in the isolated sandbox…" : snapshot.verdict.subtitle)
            .font(.caption)
            .foregroundStyle(.secondary)

          if isVerifying {
            ThinkingBar().frame(maxWidth: 220).padding(.top, 2)
          } else if snapshot.hasRecord {
            HStack(spacing: 8) {
              if snapshot.totalCases > 0 {
                signalChip(
                  label: "\(snapshot.passedCases)/\(snapshot.totalCases) checks passed",
                  symbol: "checkmark.circle.fill",
                  ok: snapshot.passedCases == snapshot.totalCases
                )
              }
              if let hidden = snapshot.evaluatorsHidden {
                signalChip(
                  label: hidden ? "Evaluators hidden" : "Isolation incomplete",
                  symbol: hidden ? "eye.slash.fill" : "exclamationmark.triangle.fill",
                  ok: hidden
                )
              }
              if let isolated = snapshot.isolationPassed {
                let name = snapshot.sandbox.isEmpty || snapshot.sandbox == "none" ? "Sandbox" : snapshot.sandbox.capitalized
                signalChip(
                  label: isolated ? "\(name) sandbox" : "No sandbox",
                  symbol: isolated ? "lock.shield.fill" : "shield.slash.fill",
                  ok: isolated
                )
              }
            }
            .padding(.top, 2)
          }
        }
      }

      if !snapshot.reasons.isEmpty {
        VStack(alignment: .leading, spacing: 4) {
          ForEach(snapshot.reasons, id: \.self) { reason in
            HStack(alignment: .top, spacing: 6) {
              Image(systemName: snapshot.verdict == .reject ? "xmark.circle.fill" : "exclamationmark.circle.fill")
                .font(.caption)
                .foregroundStyle(snapshot.verdict.color)
                .padding(.top, 1)
              Text(reason).font(.caption).textSelection(.enabled)
            }
          }
        }
        .padding(10)
        .frame(maxWidth: .infinity, alignment: .leading)
        .background(snapshot.verdict.color.opacity(0.08), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      }

      if !snapshot.judges.isEmpty {
        VStack(alignment: .leading, spacing: 4) {
          Text("Advisory model judges (can hold or reject, never approve)")
            .font(.caption2)
            .foregroundStyle(.secondary)
          HStack(spacing: 6) {
            ForEach(snapshot.judges) { judge in
              HStack(spacing: 4) {
                Text(judge.id).font(.caption2.weight(.semibold))
                Text(judge.verdict.uppercased())
                  .font(.system(size: 9, weight: .bold))
                  .foregroundStyle(SuperGaugeVerdict(raw: judge.verdict).color)
              }
              .padding(.horizontal, 8)
              .padding(.vertical, 3)
              .background(Color.primary.opacity(0.05), in: Capsule())
            }
          }
        }
      }

      DisclosureGroup("Recorded evidence & SuperGauge receipt") {
        CodeBlock(text: pretty(rawEvidence))
          .padding(.top, 6)
      }
      .font(.caption)
    }
    .padding(14)
    .background(Color.qPanel, in: RoundedRectangle(cornerRadius: 14, style: .continuous))
    .overlay(
      RoundedRectangle(cornerRadius: 14, style: .continuous)
        .strokeBorder(
          contrast == .increased
            ? AnyShapeStyle(Color.primary.opacity(0.45))
            : AnyShapeStyle(LinearGradient(
              colors: [snapshot.verdict.color.opacity(0.45), Brand.purple.opacity(0.28), Brand.pink.opacity(0.24)],
              startPoint: .topLeading, endPoint: .bottomTrailing)),
          lineWidth: 1.2)
    )
  }

  private func signalChip(label: String, symbol: String, ok: Bool) -> some View {
    let tint: Color = ok ? Color(red: 0.14, green: 0.62, blue: 0.42) : .orange
    return Label(label, systemImage: symbol)
      .font(.caption2.weight(.semibold))
      .foregroundStyle(contrast == .increased ? Color.primary : tint)
      .padding(.horizontal, 8)
      .padding(.vertical, 3)
      .background(tint.opacity(0.11), in: Capsule())
  }
}
