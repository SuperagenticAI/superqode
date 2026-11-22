import SwiftUI

struct FactoryRequirementTraceView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var library: FactoryAcceptanceLibrary
  var active: Bool
  @State private var expanded = ProcessInfo.processInfo.arguments.contains("--factory-acceptance-inspect")
  private var requirements: [[String: Any]] { library.trace["requirements"] as? [[String: Any]] ?? [] }
  private var checks: [[String: Any]] { library.trace["application_checks"] as? [[String: Any]] ?? [] }
  private var refreshKey: String {
    let order = studio.detail["work_order"] as? [String: Any] ?? [:]
    let receipt = (order["metadata"] as? [String: Any])?["factory_verification"] as? [String: Any] ?? [:]
    return active ? app.projectID + "\n" + studio.run + "\n" + string(receipt, "artifact_id") : ""
  }
  var body: some View {
    DisclosureGroup("Requirements & application checks", isExpanded: $expanded) {
      VStack(alignment: .leading, spacing: 10) {
        Text("Coverage uses this run's pinned requirements, completed stages and bound protected evidence. A completed worker summary cannot close a requirement.").font(.caption).foregroundStyle(.secondary)
        Button("Refresh coverage") { Task { await library.refreshTrace(app.engine) } }.disabled(library.busy)
        if library.trace.isEmpty { Text("Load coverage for this trial.").font(.caption) }
        else if requirements.isEmpty { Text("This run declared no requirement mappings. Application checks are shown below.").font(.caption).foregroundStyle(.secondary) }
        ForEach(Array(requirements.enumerated()), id: \.offset) { _, row in
          VStack(alignment: .leading, spacing: 5) {
            HStack { Text(string(row, "id")).font(.subheadline.bold()); Spacer(); Pill(title: string(row, "status"), color: requirementColor(row)) }
            Text(string(row, "description")).font(.caption)
            ForEach(Array(stages(row).enumerated()), id: \.offset) { _, stage in
              Text(stageSummary(stage))
                .font(.caption).textSelection(.enabled)
              let artifacts: [String] = stageArtifacts(stage)
              if !artifacts.isEmpty { Text("Artifacts: " + artifacts.joined(separator: ", ")).font(.caption.monospaced()).foregroundStyle(.secondary).textSelection(.enabled) }
            }
            Text(checksSummary(row))
              .font(.caption)
          }.padding(10).brandSurface()
        }
        ForEach(Array(checks.enumerated()), id: \.offset) { _, check in
          VStack(alignment: .leading, spacing: 4) {
            HStack { Text(string(check, "check")).font(.caption.bold()); Pill(title: string(check, "category")); Spacer(); Text(checkStatus(check)).font(.caption) }
            if !string(check, "verification_artifact").isEmpty { Text("Verification artifact: " + string(check, "verification_artifact")).font(.caption.monospaced()).textSelection(.enabled) }
          }
        }
        Text("Historical acceptance evidence. Current release authorization remains a separate decision.").font(.caption).foregroundStyle(.secondary)
        if !library.failure.isEmpty { Text(library.failure).font(.caption).foregroundStyle(.orange) }
      }.padding(.top, 8).accessibilityIdentifier("factory.acceptance.trace")
    }.task(id: refreshKey) { guard active, !studio.run.isEmpty else { return }; await library.refreshTrace(app.engine) }
  }

  // Small typed helpers keep the view body quick for the Swift type checker.
  private func requirementColor(_ row: [String: Any]) -> Color {
    let status: String = string(row, "status")
    return status == "covered" ? Color.green : Color.orange
  }

  private func stages(_ row: [String: Any]) -> [[String: Any]] {
    let value: [[String: Any]] = row["stages"] as? [[String: Any]] ?? []
    return value
  }

  private func stageArtifacts(_ stage: [String: Any]) -> [String] {
    let value: [String] = stage["artifacts"] as? [String] ?? []
    return value
  }

  private func stageSummary(_ stage: [String: Any]) -> String {
    let name: String = string(stage, "stage")
    let completed: Bool = (stage["completed"] as? Bool) == true
    let state: String = completed ? "Completed" : "Incomplete"
    let tasks: [[String: Any]] = stage["tasks"] as? [[String: Any]] ?? []
    var parts: [String] = []
    for task in tasks {
      let id: String = string(task, "id")
      let status: String = string(task, "status")
      parts.append(id + " (" + status + ")")
    }
    let taskText: String = parts.joined(separator: ", ")
    return name + " · " + state + " · " + taskText
  }

  private func checksSummary(_ row: [String: Any]) -> String {
    let rows: [[String: Any]] = row["checks"] as? [[String: Any]] ?? []
    var parts: [String] = []
    for check in rows {
      let name: String = string(check, "check")
      let status: String = string(check, "status")
      parts.append(name + " (" + status + ")")
    }
    let text: String = parts.joined(separator: ", ")
    return "Checks: " + text
  }

  private func checkStatus(_ check: [String: Any]) -> String {
    let status: String = string(check, "status")
    if status == "missing" || status == "never_ran" { return "Not run or evidence unbound" }
    return status.capitalized
  }
}

struct FactoryOutcomeView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var library: FactoryAcceptanceLibrary
  var active: Bool
  @State private var confirmation = false
  @State private var expanded = ProcessInfo.processInfo.arguments.contains("--factory-acceptance-inspect")
  @State private var confirmedValues: [String] = []
  private var idle: Bool { !library.busy && !studio.busy && !app.anyActive && !app.busy }
  private var finished: [[String: Any]] { studio.runs.filter { ["accepted", "merged", "rolled_back", "rejected", "failed", "cancelled"].contains(string($0, "status")) } }
  private var values: [String] { [app.projectID, studio.run, library.observation, library.outcome, library.humanMinutes] }
  private var revisions: [[String: Any]] {
    let value: [[String: Any]] = library.outcomes["revisions"] as? [[String: Any]] ?? []
    return value
  }
  var body: some View {
    DisclosureGroup("Observed outcomes & costs", isExpanded: $expanded) {
        VStack(alignment: .leading, spacing: 10) {
          Text("Record an attributed business observation after a run finishes. Compare revisions on representative tasks; these observations do not establish causality or release approval.").font(.caption).foregroundStyle(.secondary)
          Button("Refresh outcomes") { Task { await library.refreshOutcomes(app.engine) } }.disabled(!idle)
          ForEach(Array(revisions.enumerated()), id: \.offset) { _, row in
            let counts: [String: Any] = row["outcomes"] as? [String: Any] ?? [:]
            let runs: Int = row["runs"] as? Int ?? 0
            let met: Int = counts["met"] as? Int ?? 0
            let notMet: Int = counts["not_met"] as? Int ?? 0
            let unknown: Int = counts["unknown"] as? Int ?? 0
            VStack(alignment: .leading, spacing: 5) {
              Text("Revision " + String(string(row, "snapshot_digest").prefix(24))).font(.caption.monospaced()).textSelection(.enabled)
              Text("\(runs) observed runs · Met: \(met) · Not met: \(notMet) · Unknown: \(unknown)").font(.caption)
              Text(costSummary(row))
                .font(.caption).accessibilityIdentifier("factory.outcomes.costs")
              DisclosureGroup("Attributed observations") { CodeBlock(text: pretty(row["observations"])) }
            }.padding(10).brandSurface()
          }
          if revisions.isEmpty { Text("No outcome observations recorded.").font(.caption).foregroundStyle(.secondary) }
          Text("Unknown cost or effort stays unknown. Revision cost includes failed and unobserved attempts and optimizer experiments run against that revision; infrastructure costs are not included.").font(.caption).foregroundStyle(.secondary)
          Divider()
          Picker("Finished run", selection: $studio.run) {
            if !finished.contains(where: { string($0, "id") == studio.run }) { Text("Choose a finished run").tag(studio.run) }
            ForEach(finished.map { string($0, "id") }, id: \.self) { Text($0).tag($0) }
          }
          TextField("Stable observation id", text: $library.observation).textFieldStyle(.roundedBorder)
          Picker("Business outcome", selection: $library.outcome) { Text("Unknown").tag("unknown"); Text("Met").tag("met"); Text("Not met").tag("not_met") }
          TextField("Human minutes (leave blank if unknown)", text: $library.humanMinutes).textFieldStyle(.roundedBorder)
          Button("Record attributed outcome…") { confirmedValues = values; confirmation = true }
            .disabled(!idle || library.observation.isEmpty || !finished.contains(where: { string($0, "id") == studio.run }))
          Text("One observation per run. A repeated id with the same values is safe; changing a recorded observation is rejected.").font(.caption).foregroundStyle(.secondary)
          if !library.failure.isEmpty { Text(library.failure).font(.caption).foregroundStyle(.orange) }
          if !library.message.isEmpty { Text(library.message).font(.caption).foregroundStyle(.secondary) }
        }.padding(.top, 8)
    }
    .task(id: app.projectID + "\n" + String(active)) { guard active else { return }; await library.refreshOutcomes(app.engine) }
    .onChange(of: active) { _, value in if !value { confirmation = false } }
    .onChange(of: values) { _, _ in confirmation = false }
    .alert("Record this business observation?", isPresented: $confirmation) {
      Button("Cancel", role: .cancel) { }
      Button("Record") { guard confirmedValues == values else { return }; Task { await library.recordOutcome(app.engine) } }
    } message: { Text("Attribute this outcome and optional human effort to the selected finished run. This is an operator report, separate from protected verification and release approval.") }
  }

  private func costSummary(_ row: [String: Any]) -> String {
    let minutes: String = FactoryAcceptanceLibrary.measurement(row["human_minutes"], decimals: 1)
    let usd: String = FactoryAcceptanceLibrary.measurement(row["cost_usd"], decimals: 2)
    let tokens: String = FactoryAcceptanceLibrary.measurement(row["total_tokens"])
    return "Human minutes: " + minutes + " · Recorded USD: " + usd + " · Tokens: " + tokens
  }
}

struct FactoryIntakeReceiptView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var library: FactoryAcceptanceLibrary
  var active: Bool
  @State private var expanded = ProcessInfo.processInfo.arguments.contains("--factory-acceptance-inspect")
  var body: some View {
    DisclosureGroup("Intake decisions", isExpanded: $expanded) {
      VStack(alignment: .leading, spacing: 10) {
        Text("Inspect authenticated events that were queued, duplicated, filtered or rejected. Receipts contain bounded source hashes and reason codes; event content and secrets are excluded.").font(.caption).foregroundStyle(.secondary)
        Button("Refresh intake receipts") { Task { await library.refreshReceipts(app.engine) } }.disabled(library.busy)
        if library.receipts.isEmpty { Text("No authenticated intake receipts recorded.").font(.caption).foregroundStyle(.secondary) }
        ForEach(Array(library.receipts.reversed().enumerated()), id: \.offset) { _, row in
          VStack(alignment: .leading, spacing: 4) {
            HStack { Text(string(row, "source").capitalized).font(.caption.bold()); Pill(title: string(row, "status")); Spacer(); Text("\(row["count"] as? Int ?? 1) received").font(.caption) }
            Text(reason(string(row, "reason"))).font(.caption)
            Text("Event hash: " + string(row, "fingerprint")).font(.caption.monospaced()).textSelection(.enabled)
            if let received = row["last_received"] as? Double { HStack { Text(Date(timeIntervalSince1970: received), style: .date); Text(Date(timeIntervalSince1970: received), style: .time) }.font(.caption).foregroundStyle(.secondary) }
            if !string(row, "run").isEmpty { Button("Inspect queued run") { studio.run = string(row, "run"); studio.navigation.select("Runs") } }
          }.padding(10).brandSurface()
        }
        if !library.failure.isEmpty { Text(library.failure).font(.caption).foregroundStyle(.orange) }
      }.padding(.top, 8).accessibilityIdentifier("factory.intake.receipts")
    }.task(id: app.projectID + "\n" + String(active)) { guard active else { return }; await library.refreshReceipts(app.engine) }
  }
  private func reason(_ value: String) -> String {
    ["admitted": "Queued under the saved intake policy.", "duplicate_delivery": "Matched an admitted delivery and reused its run.",
      "policy_filtered": "Source, event type or action is outside the saved policy.", "delivery_conflict": "Delivery id already binds different content.",
      "stale_event": "Event timestamp is outside the replay window.", "rate_limit": "Admission ledger or hourly limit reached.",
      "queue_limit": "Pending work limit reached.", "invalid_event": "Event validation failed; inspect the source configuration and intake policy."][value]
      ?? value.replacingOccurrences(of: "_", with: " ").capitalized
  }
}
