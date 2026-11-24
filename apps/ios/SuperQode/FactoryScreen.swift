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
    case .ship: return "Deterministic checks passed · ready for sign-off"
    case .hold: return "Review required before release"
    case .reject: return "Protected verification failed"
    case .pending: return "Run protected verification on desktop for a verdict"
    }
  }

  var color: Color {
    switch self {
    case .ship: return Color(red: 0.14, green: 0.64, blue: 0.42)
    case .hold: return Color(red: 0.90, green: 0.56, blue: 0.12)
    case .reject: return Color(red: 0.85, green: 0.24, blue: 0.26)
    case .pending: return CompanionTheme.purple
    }
  }

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
  let hasRecord: Bool

  static func parse(detail: [String: JSONValue]) -> SuperGaugeSnapshot {
    let evidence = detail.records("evidence")
    let qualityArtifact = evidence.last { $0.text("kind") == "factory_quality_record" }
    var record: [String: JSONValue] = [:]
    if let content = qualityArtifact?.text("content"),
      let data = content.data(using: .utf8),
      let parsed = try? JSONDecoder().decode(JSONValue.self, from: data)
    {
      record = parsed.object
    }

    let order = detail.object("work_order")
    let metadata = order.object("metadata")
    let receipt = metadata.object("factory_verification")

    guard !record.isEmpty else {
      let receiptState = receipt.text("state")
      let fallbackVerdict: SuperGaugeVerdict =
        receiptState == "passed" ? .ship : receiptState == "failed" ? .reject : .pending
      return SuperGaugeSnapshot(
        verdict: fallbackVerdict,
        profileLabel: "SuperGauge · Deterministic",
        completionRate: nil,
        totalCases: 0,
        passedCases: 0,
        sandbox: receipt.text("sandbox"),
        isolationPassed: receipt["isolation_applied"] != nil ? receipt.flag("isolation_applied") : nil,
        evaluatorsHidden: nil,
        evidenceComplete: nil,
        contaminationDetected: false,
        reasons: [],
        hasRecord: !receipt.isEmpty
      )
    }

    let decision = record.object("decision")
    let verdict = SuperGaugeVerdict(raw: decision.text("verdict"))

    let profile = record.object("profile")
    let tier = profile.text("tier")
    let profileID = profile.text("id")
    let profileLabel = [profileID.isEmpty ? "sg/coding-agent" : profileID, tier.isEmpty ? nil : tier]
      .compactMap { $0 }
      .joined(separator: " · ")

    let taskSet = record.object("task_set")
    let heldOut = Int(taskSet.number("held_out"))

    var completion: Double?
    var evidenceComplete: Bool?
    if case .array(let rows) = record["measures"] {
      for item in rows {
        let row = item.object
        let name = row.text("name")
        if name == "task.completion", case .number(let val) = row["value"] {
          completion = val
        } else if name == "assurance.evidence_complete", case .bool(let val) = row["value"] {
          evidenceComplete = val
        }
      }
    } else if case .object(let map) = record["measures"] {
      if case .number(let val) = map.object("task.completion")["value"] { completion = val }
      if case .bool(let val) = map.object("assurance.evidence_complete")["value"] { evidenceComplete = val }
    }

    let passedCases = (completion != nil && heldOut > 0) ? Int((completion! * Double(heldOut)).rounded()) : 0

    var isolationPassed: Bool?
    var evaluatorsHidden: Bool?
    var contaminationDetected = false
    if case .array(let rows) = record["gates"] {
      for item in rows {
        let gate = item.object
        let name = gate.text("name")
        let status = gate.text("status")
        if name == "safety.isolation" { isolationPassed = (status == "pass") }
        if name == "assurance.evaluator_hidden" { evaluatorsHidden = (status == "pass") }
        if name == "assurance.contamination" { contaminationDetected = (status == "fail") }
      }
    } else if case .object(let map) = record["gates"] {
      if !map.object("safety.isolation").isEmpty { isolationPassed = map.object("safety.isolation").text("status") == "pass" }
      if !map.object("assurance.evaluator_hidden").isEmpty { evaluatorsHidden = map.object("assurance.evaluator_hidden").text("status") == "pass" }
      if !map.object("assurance.contamination").isEmpty { contaminationDetected = map.object("assurance.contamination").text("status") == "fail" }
    }

    if evaluatorsHidden == nil, case .bool(let hidden) = record.object("assurance")["evaluator_independent"] {
      evaluatorsHidden = hidden
    }

    let authority = record.object("subject").object("authority")
    let sandbox = authority.text("sandbox", receipt.text("sandbox"))
    let reasons = (decision["reasons"]?.array ?? []).map(\.text)
      + (decision["reject_reasons"]?.array ?? []).map(\.text)
      + (decision["hold_reasons"]?.array ?? []).map(\.text)

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
      reasons: reasons.filter { !$0.isEmpty },
      hasRecord: true
    )
  }
}

/// Original vector emblem for Factory Studio matching SuperQode's brand palette.
struct FactoryStudioEmblem: View {
  var size: CGFloat = 28
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    ZStack {
      RoundedRectangle(cornerRadius: size * 0.28, style: .continuous)
        .fill(
          contrast == .increased
            ? AnyShapeStyle(Color.primary.opacity(0.14))
            : AnyShapeStyle(CompanionTheme.gradient)
        )
      Canvas { context, canvasSize in
        let w = canvasSize.width
        let h = canvasSize.height
        let fg: Color = contrast == .increased ? .primary : .white
        var bodyPath = Path()
        bodyPath.move(to: CGPoint(x: w * 0.16, y: h * 0.80))
        bodyPath.addLine(to: CGPoint(x: w * 0.16, y: h * 0.44))
        bodyPath.addLine(to: CGPoint(x: w * 0.38, y: h * 0.56))
        bodyPath.addLine(to: CGPoint(x: w * 0.38, y: h * 0.42))
        bodyPath.addLine(to: CGPoint(x: w * 0.62, y: h * 0.55))
        bodyPath.addLine(to: CGPoint(x: w * 0.62, y: h * 0.24))
        bodyPath.addLine(to: CGPoint(x: w * 0.84, y: h * 0.24))
        bodyPath.addLine(to: CGPoint(x: w * 0.84, y: h * 0.80))
        bodyPath.closeSubpath()
        context.fill(bodyPath, with: .color(fg.opacity(0.95)))

        let winSize = CGSize(width: w * 0.13, height: h * 0.13)
        let win1 = CGRect(origin: CGPoint(x: w * 0.28, y: h * 0.61), size: winSize)
        let win2 = CGRect(origin: CGPoint(x: w * 0.50, y: h * 0.61), size: winSize)
        context.fill(Path(roundedRect: win1, cornerRadius: 1.5), with: .color(CompanionTheme.purple.opacity(0.75)))
        context.fill(Path(roundedRect: win2, cornerRadius: 1.5), with: .color(CompanionTheme.pink.opacity(0.75)))
      }
      .padding(size * 0.12)
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }
}

/// Vector SuperGauge dial matching the macOS Factory Studio SuperGauge mark.
struct SuperGaugeMark: View {
  var verdict: SuperGaugeVerdict = .ship
  var size: CGFloat = 68
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    Canvas { context, canvasSize in
      let w = canvasSize.width
      let h = canvasSize.height
      let center = CGPoint(x: w * 0.50, y: h * 0.62)
      let radius = min(w, h) * 0.40
      let strokeW = max(2.2, size * 0.095)
      let emphasized = contrast == .increased

      var track = Path()
      track.addArc(center: center, radius: radius, startAngle: .degrees(180), endAngle: .degrees(360), clockwise: false)
      context.stroke(
        track,
        with: .color(Color.primary.opacity(0.11)),
        style: StrokeStyle(lineWidth: strokeW, lineCap: .round))

      let clamped = min(0.98, max(0.04, verdict.needlePosition))
      var activeArc = Path()
      activeArc.addArc(
        center: center,
        radius: radius,
        startAngle: .degrees(180),
        endAngle: .degrees(180 + 180 * clamped),
        clockwise: false)

      let arcColors: [Color] = emphasized
        ? [.primary, .primary]
        : verdict == .ship
          ? [CompanionTheme.purple, Color(red: 0.18, green: 0.56, blue: 0.78), verdict.color]
          : verdict == .hold
            ? [CompanionTheme.purple, CompanionTheme.orange, verdict.color]
            : verdict == .reject
              ? [verdict.color, CompanionTheme.pink]
              : [CompanionTheme.purple, CompanionTheme.pink, CompanionTheme.orange]

      context.stroke(
        activeArc,
        with: .linearGradient(
          Gradient(colors: arcColors),
          startPoint: CGPoint(x: center.x - radius, y: center.y),
          endPoint: CGPoint(x: center.x + radius, y: center.y)),
        style: StrokeStyle(lineWidth: strokeW, lineCap: .round))

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

      let hubR = max(2.6, size * 0.075)
      let hubRect = CGRect(x: center.x - hubR, y: center.y - hubR, width: hubR * 2, height: hubR * 2)
      context.fill(Path(ellipseIn: hubRect), with: .color(emphasized ? .primary : verdict.color))
    }
    .frame(width: size, height: size)
    .accessibilityHidden(true)
  }
}

struct SuperGaugeBadge: View {
  let verdict: SuperGaugeVerdict
  var showWordmark: Bool = true
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    HStack(spacing: 5) {
      SuperGaugeMark(verdict: verdict, size: 16)
      if showWordmark {
        Text("SuperGauge").font(.caption2.weight(.semibold)).foregroundStyle(.secondary)
      }
      Text(verdict.title)
        .font(.caption2.weight(.bold))
        .foregroundStyle(contrast == .increased ? Color.primary : verdict.color)
    }
    .padding(.horizontal, 9)
    .padding(.vertical, 4)
    .background(verdict.color.opacity(contrast == .increased ? 0.16 : 0.11), in: Capsule())
    .overlay(Capsule().strokeBorder(verdict.color.opacity(0.28), lineWidth: 0.8))
    .accessibilityElement(children: .combine)
    .accessibilityLabel("SuperGauge " + verdict.title)
  }
}

struct SuperGaugeVerdictCard: View {
  let snapshot: SuperGaugeSnapshot

  var body: some View {
    CompanionCard {
      HStack(alignment: .center, spacing: 14) {
        SuperGaugeMark(verdict: snapshot.verdict, size: 62)
          .padding(6)
          .background(snapshot.verdict.color.opacity(0.08), in: RoundedRectangle(cornerRadius: 14))
        VStack(alignment: .leading, spacing: 5) {
          SuperGaugeBadge(verdict: snapshot.verdict)
          Text(snapshot.profileLabel)
            .font(.caption.monospaced())
            .foregroundStyle(.secondary)
          Text(snapshot.verdict.subtitle)
            .font(.footnote)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
        }
      }

      if let rate = snapshot.completionRate {
        HStack {
          Label("Held-out completion", systemImage: "checkmark.seal")
            .font(.subheadline.weight(.medium))
          Spacer()
          Text(
            snapshot.totalCases > 0
              ? "\(snapshot.passedCases)/\(snapshot.totalCases) (\(Int((rate * 100).rounded()))%)"
              : "\(Int((rate * 100).rounded()))%"
          )
          .font(.subheadline.weight(.bold).monospacedDigit())
          .foregroundStyle(snapshot.verdict.color)
        }
      }

      ScrollView(.horizontal, showsIndicators: false) {
        HStack(spacing: 8) {
          if let isolated = snapshot.isolationPassed {
            assurancePill(
              isolated ? "Isolated" + (snapshot.sandbox.isEmpty ? "" : " · " + snapshot.sandbox) : "Isolation missing",
              ok: isolated)
          }
          if let hidden = snapshot.evaluatorsHidden {
            assurancePill(hidden ? "Evaluators hidden" : "Evaluators exposed", ok: hidden)
          }
          if let complete = snapshot.evidenceComplete {
            assurancePill(complete ? "Evidence complete" : "Evidence incomplete", ok: complete)
          }
          if snapshot.contaminationDetected {
            assurancePill("Contamination detected", ok: false)
          }
        }
      }

      ForEach(snapshot.reasons, id: \.self) { reason in
        Label(reason, systemImage: "info.circle")
          .font(.caption)
          .foregroundStyle(snapshot.verdict == .ship ? Color.secondary : CompanionTheme.warning)
      }
    }
    .accessibilityIdentifier("supergauge.card")
  }

  private func assurancePill(_ label: String, ok: Bool) -> some View {
    Label(label, systemImage: ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
      .font(.caption2.weight(.semibold))
      .foregroundStyle(ok ? Color(red: 0.14, green: 0.64, blue: 0.42) : CompanionTheme.warning)
      .padding(.horizontal, 9)
      .padding(.vertical, 5)
      .background((ok ? Color.green : Color.orange).opacity(0.11), in: Capsule())
  }
}

/// Lists Factory Studio runs for a shared workspace.
struct FactoryRunsScreen: View {
  let project: String
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.scenePhase) private var scenePhase
  @State private var runs: [RemoteRecord] = []
  @State private var revisionCount = 0
  @State private var truncated = false
  @State private var loading = false
  @State private var issue = ""

  var body: some View {
    List {
      Section {
        ConnectionStatus()
        HStack(spacing: 12) {
          FactoryStudioEmblem(size: 36)
          VStack(alignment: .leading, spacing: 3) {
            Text("Factory & SuperGauge").font(.headline)
            Text("Inspect Factory runs, SuperGauge verdicts, acceptance traces and pending human gates. Factory authoring and release signing stay on your Mac.")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
        }
        .padding(.vertical, 4)
        if revisionCount > 0 {
          LabeledContent("Saved factory revisions", value: String(revisionCount))
            .font(.subheadline)
        }
      }
      .listRowBackground(CompanionTheme.panel)

      if !issue.isEmpty {
        Text(issue).foregroundStyle(CompanionTheme.warning)
      }
      if loading && runs.isEmpty {
        ProgressView("Loading Factory runs…")
      }

      ForEach(runs) { run in
        NavigationLink {
          FactoryRunDetailScreen(project: project, runID: run.id)
        } label: {
          VStack(alignment: .leading, spacing: 8) {
            Text(run.text("goal", "Factory run")).font(.headline).lineLimit(3)
            HStack {
              Text(run.text("status").replacingOccurrences(of: "_", with: " ").capitalized)
                .font(.caption.weight(.semibold))
                .foregroundStyle(statusColor(run.text("status")))
              Spacer()
              let digest = run.text("factory_digest")
              if !digest.isEmpty {
                Text(String(digest.prefix(10)))
                  .font(.caption2.monospaced())
                  .foregroundStyle(.secondary)
              }
            }
          }
          .padding(.vertical, 6)
        }
        .listRowBackground(CompanionTheme.panel)
        .accessibilityIdentifier("factory.run." + run.id)
      }

      if !loading && issue.isEmpty && runs.isEmpty {
        ContentUnavailableView(
          "No Factory runs yet",
          systemImage: "building.2",
          description: Text("Prepare and run a Factory trial in Factory Studio on your Mac to inspect its SuperGauge verdict here."))
      }
      if truncated {
        Text("More Factory runs are available on your Mac.").font(.caption).foregroundStyle(.secondary)
      }
    }
    .scrollContentBackground(.hidden)
    .background(CompanionTheme.background)
    .navigationTitle("Factory")
    .refreshable { await load() }
    .task(id: scenePhase) {
      guard scenePhase == .active else { return }
      await load()
    }
  }

  private func statusColor(_ status: String) -> Color {
    switch status {
    case "completed", "succeeded": return Color(red: 0.14, green: 0.64, blue: 0.42)
    case "failed", "rejected": return .red
    case "needs_review", "blocked": return CompanionTheme.warning
    default: return CompanionTheme.accent
    }
  }

  private func load() async {
    guard !loading, let api = store.api else { return }
    guard store.hasProjectInspection("factory") else {
      issue = "Update SuperQode on your Mac to enable Factory & SuperGauge inspection."
      return
    }
    loading = true
    defer { loading = false }
    do {
      let page = try await api.rpc("factory.list", ["project": .string(project)]).object
      try Task.checkCancellation()
      runs = page.records("runs")
      revisionCount = Int(page.number("revision_count"))
      truncated = page.flag("runs_truncated")
      issue = ""
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
}

private struct PendingGateDecision: Identifiable {
  let id = UUID().uuidString
  let stage: String
  let title: String
  let digest: String
  let decision: String
}

/// Detailed Factory run view with SuperGauge verdict, acceptance trace, human gates and candidate diff.
struct FactoryRunDetailScreen: View {
  let project: String
  let runID: String
  @EnvironmentObject private var store: CompanionStore
  @State private var detail: [String: JSONValue] = [:]
  @State private var trace: [String: JSONValue] = [:]
  @State private var loading = true
  @State private var acting = false
  @State private var issue = ""
  @State private var gateReason = ""
  @State private var pendingGate: PendingGateDecision?
  @State private var showDiff = false

  private var order: [String: JSONValue] { detail.object("work_order") }
  private var tasks: [RemoteRecord] { order.records("tasks") }
  private var gauge: SuperGaugeSnapshot { SuperGaugeSnapshot.parse(detail: detail) }
  private var canDecideGates: Bool {
    store.canMutate && store.permissions.contains("approve") && store.features.flag("factory_gates") && !acting
  }

  var body: some View {
    ScrollView {
      LazyVStack(alignment: .leading, spacing: 18) {
        ConnectionStatus()
        if loading && detail.isEmpty { ProgressView("Loading Factory run…") }
        if !issue.isEmpty {
          Label(issue, systemImage: "exclamationmark.triangle")
            .font(.subheadline)
            .foregroundStyle(CompanionTheme.warning)
        }

        if !order.isEmpty {
          CompanionCard {
            HStack(spacing: 12) {
              FactoryStudioEmblem(size: 32)
              VStack(alignment: .leading, spacing: 3) {
                Text(order.text("goal", "Factory run")).font(.headline)
                Text(order.text("status").replacingOccurrences(of: "_", with: " ").capitalized)
                  .font(.caption.weight(.semibold))
                  .foregroundStyle(CompanionTheme.accent)
              }
            }
            let cockpit = detail.object("cockpit")
            if cockpit["elapsed_seconds"] != nil {
              LabeledContent("Elapsed", value: evidenceMetric(cockpit["elapsed_seconds"]))
                .font(.caption)
            }
            if !order.text("error").isEmpty {
              Text(order.text("error")).font(.footnote).foregroundStyle(CompanionTheme.warning)
            }
          }

          SuperGaugeVerdictCard(snapshot: gauge)

          let gatedTasks = tasks.filter { task in
            let meta = task.raw.object("metadata")
            return meta.flag("human_gate") && !meta.text("gate_digest").isEmpty
              && meta.object("gate_approval").isEmpty
          }
          if !gatedTasks.isEmpty {
            CompanionCard {
              Label("Pending human gate", systemImage: "hand.raised.fill")
                .font(.headline)
                .foregroundStyle(CompanionTheme.warning)
              TextField("Optional review note", text: $gateReason)
                .textFieldStyle(.roundedBorder)
                .disabled(acting)
              ForEach(Array(gatedTasks.enumerated()), id: \.offset) { _, task in
                let meta = task.raw.object("metadata")
                let stageID = task.text("task_id")
                let digest = meta.text("gate_digest")
                VStack(alignment: .leading, spacing: 8) {
                  Text(task.text("title", stageID)).font(.subheadline.weight(.semibold))
                  HStack(spacing: 12) {
                    Button("Approve gate") {
                      pendingGate = PendingGateDecision(
                        stage: stageID, title: task.text("title", stageID), digest: digest, decision: "approve")
                    }
                    .buttonStyle(CompanionPrimaryButton())
                    Button("Hold", role: .destructive) {
                      pendingGate = PendingGateDecision(
                        stage: stageID, title: task.text("title", stageID), digest: digest, decision: "hold")
                    }
                  }
                  .disabled(!canDecideGates)
                }
              }
              if !store.permissions.contains("approve") {
                Text("Allow approvals when pairing this device on your Mac to decide Factory gates.")
                  .font(.caption).foregroundStyle(.secondary)
              }
              Text("Gate decisions control workflow continuation only. Cryptographic release sign-off stays on your Mac.")
                .font(.caption).foregroundStyle(.secondary)
            }
          }

          if !trace.isEmpty {
            traceCard
          }

          if !tasks.isEmpty {
            CompanionCard {
              Label("Stages", systemImage: "point.3.connected.trianglepath.dotted").font(.headline)
              ForEach(Array(tasks.enumerated()), id: \.offset) { _, task in
                HStack(alignment: .top) {
                  VStack(alignment: .leading, spacing: 3) {
                    Text(task.text("title", task.text("task_id"))).font(.subheadline.weight(.medium))
                    Text(task.text("role")).font(.caption).foregroundStyle(.secondary)
                  }
                  Spacer()
                  Text(task.text("status").replacingOccurrences(of: "_", with: " ").capitalized)
                    .font(.caption.weight(.semibold))
                    .foregroundStyle(task.text("status") == "succeeded" || task.text("status") == "completed" ? Color.green : CompanionTheme.accent)
                }
                if !task.text("error").isEmpty {
                  Text(task.text("error")).font(.caption).foregroundStyle(CompanionTheme.warning)
                }
              }
            }
          }

          let diff = detail.text("candidate_diff")
          if !diff.isEmpty {
            CompanionCard {
              DisclosureGroup("Candidate diff", isExpanded: $showDiff) {
                if showDiff {
                  MobileCodeBlock(code: diff, language: "diff")
                }
              }
              .font(.headline)
              if detail.flag("diff_truncated") {
                Text("Diff preview is truncated. Inspect the full candidate diff on your Mac.")
                  .font(.caption).foregroundStyle(.secondary)
              }
            }
          }
        }
      }
      .padding(20)
      .frame(maxWidth: 950)
      .frame(maxWidth: .infinity)
    }
    .background(CompanionTheme.background)
    .navigationTitle("Factory run")
    .navigationBarTitleDisplayMode(.inline)
    .refreshable { await load() }
    .task { await load() }
    .confirmationDialog(
      pendingGate?.decision == "approve" ? "Approve Factory gate?" : "Hold Factory gate?",
      isPresented: Binding(get: { pendingGate != nil }, set: { if !$0 { pendingGate = nil } }),
      titleVisibility: .visible
    ) {
      if let gate = pendingGate {
        Button(
          gate.decision == "approve" ? "Approve gate" : "Hold gate",
          role: gate.decision == "hold" ? .destructive : nil
        ) {
          Task { await submitGate(gate) }
        }
      }
    } message: {
      Text("Records your workflow gate decision against the inspected digest. This never merges code or signs a release.")
    }
  }

  private var traceCard: some View {
    let counts = trace.object("summary").object("checks")
    let checks = trace.records("application_checks")
    return CompanionCard {
      HStack {
        Label("Acceptance trace", systemImage: "checklist.checked").font(.headline)
        Spacer()
        if trace.flag("verification_bound_to_current") {
          Text("Bound").font(.caption2.weight(.semibold)).foregroundStyle(.green)
        }
      }
      LazyVGrid(columns: [GridItem(.adaptive(minimum: 80))], alignment: .leading, spacing: 10) {
        traceMetric("Passed", value: Int(counts.number("passed")), color: Color(red: 0.14, green: 0.64, blue: 0.42))
        traceMetric("Failed", value: Int(counts.number("failed")), color: .red)
        traceMetric("Blocked", value: Int(counts.number("blocked")), color: CompanionTheme.warning)
        traceMetric("Never ran", value: Int(counts.number("never_ran")), color: .secondary)
      }
      ForEach(Array(checks.enumerated()), id: \.offset) { _, row in
        VStack(alignment: .leading, spacing: 3) {
          HStack {
            Text(row.text("check")).font(.subheadline.weight(.medium))
            Spacer()
            Text(row.text("status").replacingOccurrences(of: "_", with: " ").capitalized)
              .font(.caption.weight(.semibold))
              .foregroundStyle(checkColor(row.text("status")))
          }
          if !row.text("reason").isEmpty {
            Text(row.text("reason")).font(.caption).foregroundStyle(.secondary)
          }
        }
      }
    }
  }

  private func traceMetric(_ title: String, value: Int, color: Color) -> some View {
    VStack(alignment: .leading, spacing: 2) {
      Text(String(value)).font(.title3.bold().monospacedDigit()).foregroundStyle(value > 0 ? color : .secondary)
      Text(title).font(.caption2).foregroundStyle(.secondary)
    }
  }

  private func checkColor(_ status: String) -> Color {
    switch status {
    case "passed": return Color(red: 0.14, green: 0.64, blue: 0.42)
    case "failed": return .red
    case "blocked": return CompanionTheme.warning
    default: return .secondary
    }
  }

  private func load() async {
    guard let api = store.api else { loading = false; return }
    loading = true
    defer { loading = false }
    do {
      async let inspectCall = api.rpc("factory.run.inspect", ["project": .string(project), "run": .string(runID)])
      async let traceCall = api.rpc("factory.evidence.trace", ["project": .string(project), "run": .string(runID)])
      let nextDetail = try await inspectCall.object
      let nextTrace = (try? await traceCall.object) ?? [:]
      try Task.checkCancellation()
      detail = nextDetail
      trace = nextTrace
      issue = ""
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }

  private func submitGate(_ gate: PendingGateDecision) async {
    guard let api = store.api, canDecideGates else { return }
    acting = true; issue = ""
    defer { acting = false }
    do {
      _ = try await api.rpc(
        "factory.gate",
        [
          "project": .string(project),
          "run": .string(runID),
          "stage": .string(gate.stage),
          "gate_digest": .string(gate.digest),
          "decision": .string(gate.decision),
          "reason": .string(gateReason),
        ],
        key: "factory-gate:" + gate.id)
      CompanionHaptics.notify(gate.decision == "approve" ? .success : .warning)
      gateReason = ""
      await load()
    } catch {
      issue = error.localizedDescription
    }
  }
}
