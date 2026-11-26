import SwiftUI

struct FactoryBenchmarkSetupView: View {
  @EnvironmentObject private var app: Workspace
  @ObservedObject var library: FactoryTrialSuiteLibrary
  var idle: Bool
  @State private var confirmSave = false
  @State private var reviewedProject = ""
  @State private var reviewedDigest = ""
  private var canDraft: Bool {
    (2...8).contains(library.historySplits.count)
      && library.historySplits.values.contains("held-in") && library.historySplits.values.contains("held-out")
      && !library.historyCandidate.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
  }

  var body: some View {
    DisclosureGroup("Benchmark your past work") {
      VStack(alignment: .leading, spacing: 10) {
        Text("Choose two to eight past tasks and reserve held-out cases. Paired trials replay each task's original committed application with the same protected checks. Historical outputs never become expected answers.")
          .font(.caption).foregroundStyle(.secondary)
        Button("Load past Factory runs") { Task { await library.history(app.engine, action: "list") } }
          .disabled(!idle).accessibilityIdentifier("factory.benchmark.history")
        ScrollView {
          VStack(alignment: .leading, spacing: 8) {
            ForEach(library.historyRuns, id: \.benchmarkRunID) { run in
              HStack {
                VStack(alignment: .leading) {
                  Text(string(run, "goal")).font(.caption).lineLimit(2)
                  Text(string(run, "run")).font(.caption.monospaced()).foregroundStyle(.secondary)
                }
                Spacer()
                Picker("Dataset split", selection: Binding(
                  get: { library.historySplits[string(run, "run")] ?? "ignore" },
                  set: { value in
                    let id = string(run, "run")
                    if value == "ignore" { library.historySplits.removeValue(forKey: id) }
                    else { library.historySplits[id] = value }
                  })) {
                  Text("Skip").tag("ignore")
                  Text("Held-in").tag("held-in")
                  Text("Held-out").tag("held-out")
                }.frame(width: 180).disabled(!idle)
              }
            }
          }
        }.frame(maxHeight: 180)
        TextField("Candidate Factory path", text: $library.historyCandidate).textFieldStyle(.roundedBorder).disabled(!idle)
        Button("Draft benchmark dataset") { Task { await library.history(app.engine, action: "draft") } }
          .disabled(!idle || !canDraft)
          .accessibilityIdentifier("factory.benchmark.draft")
        if !library.historyProposal.isEmpty {
          Text(string(library.historyProposal, "notice")).font(.caption).foregroundStyle(.secondary)
          ScrollView {
            Text(string(library.historyProposal, "yaml")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
              .frame(maxWidth: .infinity, alignment: .leading)
          }.frame(maxHeight: 180)
          Button("Save reviewed workload…") {
            reviewedProject = library.project; reviewedDigest = string(library.historyProposal, "digest")
            confirmSave = true
          }.disabled(!idle).accessibilityIdentifier("factory.benchmark.save")
        }
      }.padding(.top, 8)
    }
    .factoryConfirmation(
      isPresented: $confirmSave,
      title: "Save this reviewed benchmark workload?",
      message: "Save the selected task text, original revisions and pinned Factory snapshots locally. Preparation and model execution require separate actions. No existing Factory or release authority changes.",
      kind: .save,
      badges: [
        FactoryConfirmBadge(label: "Local workload", symbol: "doc.text", color: Brand.purple),
        FactoryConfirmBadge(label: "No model calls", symbol: "bolt.slash", color: Color(red: 0.14, green: 0.62, blue: 0.42))
      ],
      confirmTitle: "Save workload sources",
      onConfirm: {
        guard idle, library.project == reviewedProject,
          string(library.historyProposal, "digest") == reviewedDigest else { return }
        Task { await library.history(app.engine, action: "install") }
      }
    )
    .onChange(of: library.project) { _, _ in confirmSave = false }
    .onChange(of: string(library.historyProposal, "digest")) { _, _ in confirmSave = false }
  }
}

private extension Dictionary where Key == String, Value == Any {
  var benchmarkRunID: String { self["run"] as? String ?? "" }
}
