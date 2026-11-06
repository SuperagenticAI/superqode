import SwiftUI

struct EvaluationScreen: View {
  let project: String
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @State private var selectedProfile = ""
  @State private var suite = ""
  @State private var optimize = false
  @State private var live = false
  @State private var inspection: [String: JSONValue] = [:]
  @State private var working = false
  @State private var issue = ""
  @State private var confirmLive = false
  @State private var requestKey = UUID().uuidString
  @State private var maxEvals = 4
  @State private var maxCost = 1.0
  @State private var startedRun: OpenedRun?
  @State private var submitted = false
  private var profiles: [RemoteRecord] { store.profiles.filter { $0.text("project") == project && $0.flag("evaluation") } }
  private var profile: RemoteRecord? { profiles.first { $0.id == selectedProfile } }
  private var canStart: Bool {
    !working && !submitted && store.canMutate && !selectedProfile.isEmpty && !inspection.text("tasks_hash").isEmpty
      && (optimize ? store.permissions.contains("optimize") && profile?.flag("optimization") == true && live : store.permissions.contains("evaluate"))
  }
  var body: some View {
    Form {
      Section {
        ConnectionStatus()
        if !store.reachable { Button("Check Mac connection") { Task { await store.refresh() } } }
      }
      Section {
        Label("Measure what your harness can do", systemImage: "chart.bar.xaxis").font(.headline)
        Text("Runs use the Mac's evaluation engine and recorded evidence. Setup validation skips model execution.").font(.subheadline).foregroundStyle(.secondary)
      }
      Section("Configuration") {
        Picker("Connection", selection: $selectedProfile) {
          Text("Choose a connection").tag("")
          ForEach(profiles) { Text($0.text("name")).tag($0.id) }
        }
        Picker("Suite", selection: $suite) {
          Text("Choose a suite").tag("")
          ForEach(store.suites) { Text($0.text("name")).tag($0.id) }
        }
        Toggle("Stage an optimized candidate", isOn: $optimize)
          .disabled(!store.permissions.contains("optimize") || profile?.flag("optimization") != true)
        if profile?.flag("local_only") == true {
          Text("Local-only optimization is held until its reflection and optimizer routes can be verified locally. No cloud defaults are used.").font(.caption).foregroundStyle(.secondary)
        }
        Toggle("Allow live model execution", isOn: $live)
        if optimize {
          Stepper("Maximum evaluations: \(maxEvals)", value: $maxEvals, in: 1...20)
          LabeledContent("Maximum model cost") {
            TextField("USD", value: $maxCost, format: .number).keyboardType(.decimalPad).multilineTextAlignment(.trailing)
          }
        }
      }
      Section("Review before running") {
        Button("Inspect suite and verifier commands") { Task { await inspect() } }.disabled(working || !store.reachable || selectedProfile.isEmpty || suite.isEmpty)
        if !inspection.isEmpty {
          LabeledContent("Tasks", value: String(Int(inspection.number("task_count"))))
          ForEach((inspection["warnings"]?.array ?? []).map(\.text), id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
          ForEach(inspection.records("repository_checks")) { check in
            VStack(alignment: .leading, spacing: 6) {
              Text(check.id).font(.caption.bold())
              ForEach((check.raw["commands"]?.array ?? []).map(\.text), id: \.self) { Text($0).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
            }
          }
        }
      }
      if !issue.isEmpty { Section { Text(issue).foregroundStyle(.orange) } }
      Section {
        Button {
          if live { confirmLive = true } else { Task { await start() } }
        } label: { HStack { if working { ProgressView() }; Text(optimize ? "Start staged optimization" : live ? "Run live evaluation" : "Validate suite setup") } }
          .disabled(!canStart)
      } footer: { Text("Live tasks and the displayed verifier commands execute on the Mac. Cloud models may incur charges. Candidate adoption stays on the Mac.") }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background)
      .navigationDestination(item: $startedRun) { JobScreen(identity: $0.id).toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } } }
      .navigationTitle("Evaluate & optimize").navigationBarTitleDisplayMode(.inline)
      .toolbar { Button("Close") { dismiss() }.disabled(working) }
      .interactiveDismissDisabled(working)
      .onChange(of: selectedProfile) { _, _ in inspection = [:]; optimize = false }
      .onChange(of: suite) { _, _ in inspection = [:] }
      .confirmationDialog("Run live work on your Mac?", isPresented: $confirmLive, titleVisibility: .visible) {
        Button(optimize ? "Run within selected budgets" : "Run reviewed suite") { Task { await start() } }
      } message: { Text("This authorizes model calls and the verifier commands you reviewed. Commands can affect isolated evaluation workspaces and use the network according to the Mac's policy.") }
  }
  private func inspect() async {
    guard let api = store.api else { return }
    working = true; issue = ""
    defer { working = false }
    do { inspection = try await api.rpc("evals.inspect", ["profile": .string(selectedProfile), "tasks": .string(suite)]).object }
    catch { issue = error.localizedDescription }
  }
  private func start() async {
    guard let api = store.api else { return }
    working = true; issue = ""
    defer { working = false }
    var params: [String: JSONValue] = ["profile": .string(selectedProfile), "tasks": .string(suite), "tasks_hash": .string(inspection.text("tasks_hash")), "live": .bool(live)]
    if optimize { params["max_evals"] = .number(Double(maxEvals)); params["max_cost"] = .number(maxCost) }
    do {
      let result = try await api.rpc(optimize ? "optimizations.start" : "evaluations.start", params, key: requestKey).object
      guard !result.text("id").isEmpty else { throw CompanionError("The Mac returned no run ID. Check Activity before starting another experiment.") }
      submitted = true
      await store.refreshActivity()
      startedRun = OpenedRun(id: result.text("id"))
    } catch { issue = error.localizedDescription }
  }
}
