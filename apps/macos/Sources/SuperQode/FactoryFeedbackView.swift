import SwiftUI

struct FactoryFeedbackView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var suites: FactoryTrialSuiteLibrary
  @ObservedObject var library: FactoryFeedbackLibrary
  var idle: Bool
  var active: Bool
  var onDraft: () -> Void
  private var available: Bool { idle && !library.busy }
  private var observations: [[String: Any]] { library.detail["observations"] as? [[String: Any]] ?? [] }
  private var review: [String: Any] { (library.detail["reviews"] as? [[String: Any]] ?? []).last ?? [:] }
  private var canPropose: Bool { string(review, "status") == "reviewed" && ["model_protocol", "application_defect"].contains(string(review, "category")) }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Text("Failure inbox → reviewed experiment → measured trial").font(.headline); Spacer()
        Button("Scan selected suite") { Task { await library.scan(app.engine, suite: suites.selected) } }.disabled(!available || suites.selected.isEmpty)
        Button("Refresh inbox") { Task { await library.refresh(app.engine) } }.disabled(!available)
      }
      Text("Suggestions are tentative. Confirm application or model-protocol findings before tuning. Infrastructure, evaluation, budget and recovery issues need source repair. Scanning and proposal creation make no model calls.").font(.caption).foregroundStyle(.secondary)
      if library.busy { ProgressView().controlSize(.small) }
      if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.orange).textSelection(.enabled) }
      if !library.message.isEmpty { Text(library.message).font(.caption).foregroundStyle(.secondary) }
      HSplitView {
        ScrollView {
          VStack(alignment: .leading, spacing: 10) {
            if library.issues.isEmpty { Text("Scan a suite to collect recorded failures. Successful retries retain their earlier failure evidence.").foregroundStyle(.secondary) }
            ForEach(library.issues, id: \.feedbackID) { issue in
              Button { Task { await library.select(app.engine, id: string(issue, "id")) } } label: {
                VStack(alignment: .leading, spacing: 5) {
                  Text(string(issue, "suggested_category").replacingOccurrences(of: "_", with: " ").capitalized).font(.headline)
                  Text(string(issue, "symptom")).font(.caption).lineLimit(4)
                  Text("\(issue["observations"] as? Int ?? 0) recorded observations · \(issue["reused_outcomes"] as? Int ?? 0) reused outcomes").font(.caption2)
                  Text(string(issue["review"] as? [String: Any] ?? [:], "status", "unreviewed")).font(.caption)
                }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
              }.buttonStyle(.plain).brandSurface().disabled(!available)
            }
          }.padding(.trailing, 10)
        }.frame(minWidth: 200, idealWidth: 250, maxWidth: 320)
        ScrollView {
          VStack(alignment: .leading, spacing: 12) {
            if !library.detail.isEmpty {
              Text("Review evidence and classification").font(.headline)
              CodeBlock(text: pretty(library.detail["record"]))
              Picker("Classification", selection: $library.category) { ForEach(library.categories, id: \.self) { Text($0.replacingOccurrences(of: "_", with: " ")).tag($0) } }
              TextEditor(text: $library.notes).frame(minHeight: 65).brandSurface().accessibilityLabel("Failure review note")
              HStack {
                Button("Record reviewed classification") { Task { await library.review(app.engine, status: "reviewed") } }.disabled(!available || library.notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
                Button("Dismiss finding") { Task { await library.review(app.engine, status: "dismissed") } }.disabled(!available || library.notes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
              }
              Picker("Source observation", selection: $library.observation) {
                ForEach(observations, id: \.feedbackID) { row in
                  Text(string(row, "stage") + " · " + string(row, "current_stage_status", "source unavailable") + " · " + String(string(row, "id").prefix(10))).tag(string(row, "id"))
                }
              }.onChange(of: library.observation) { _, _ in library.resetValue() }
              DisclosureGroup("Evidence references and replay flags") { CodeBlock(text: pretty(observations)) }
              Text("Bounded experiment hypothesis").font(.headline)
              Picker("Change", selection: $library.kind) { Text("Selected stage goal").tag("stage_goal"); Text("Selected binding’s model").tag("model_route") }
                .onChange(of: library.kind) { _, _ in library.resetValue() }
              TextEditor(text: $library.value).font(.system(.caption, design: .monospaced)).frame(minHeight: 75).brandSurface().accessibilityLabel("Experiment change")
              Text("Change one goal or model binding only. Graph, gates, tools, permissions and protected acceptance remain fixed. Three proposals per finding and three linked evaluations per proposal are allowed; none starts automatically.").font(.caption).foregroundStyle(.secondary)
              Button("Create unmeasured experiment proposal") { Task { await library.propose(app.engine) } }.disabled(!available || !canPropose || library.observation.isEmpty || library.value.isEmpty)
              if let proposals = library.detail["proposals"] as? [[String: Any]], !proposals.isEmpty {
                Picker("Recorded proposal", selection: $library.proposalID) { ForEach(proposals, id: \.feedbackID) { Text(String(string($0, "id").prefix(18))).tag(string($0, "id")) } }
                  .onChange(of: library.proposalID) { _, _ in Task { await library.fetchProposal(app.engine) } }
              }
              if !library.proposal.isEmpty {
                Text("Measurement: " + string(library.proposal, "status", "unmeasured").replacingOccurrences(of: "_", with: " ")).font(.caption)
                CodeBlock(text: string(library.proposal, "suite_yaml"))
                HStack {
                  Button("Load proposal into suite editor") { Task { if await library.loadDraft(app.engine, into: suites) { onDraft() } } }.disabled(!available || library.proposal["runnable"] as? Bool != true)
                  Button("Link selected suite’s results") { Task { await library.attach(app.engine, suite: suites.selected) } }.disabled(!available || suites.selected.isEmpty)
                }
                DisclosureGroup("Linked measurements") { CodeBlock(text: pretty(library.proposal["evaluations"])) }
                Text("A proposal is unmeasured until its exact paired suite runs. Links require matching revisions, criteria and application inputs. Ties, regressions and holds remain visible; no result authorizes activation or release.").font(.caption).foregroundStyle(.secondary)
              }
            } else { Text("Select a finding to inspect its provenance, review it and design an experiment.").foregroundStyle(.secondary) }
          }.padding(.leading, 10)
        }.frame(minWidth: 280)
      }
    }.task(id: suites.project + "\n" + String(active)) {
      guard active else { return }; library.enter(suites.project); await library.refresh(app.engine)
    }
  }
}

private extension Dictionary where Key == String, Value == Any {
  var feedbackID: String { self["id"] as? String ?? "" }
}
