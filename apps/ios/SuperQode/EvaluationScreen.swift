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
  @State private var savedRequest: LocalDraft
  @State private var discard = false
  @State private var maxEvals = 4
  @State private var maxCost = 1.0
  @State private var startedRun: OpenedRun?
  @State private var submitted = false
  init(project: String, restored: LocalDraft? = nil) {
    self.project = project
    _savedRequest = State(initialValue: restored ?? LocalDraft(project: project))
  }
  private var frozen: Bool { savedRequest.attempt != nil || submitted }
  private var wrongMac: Bool { !savedRequest.origin.isEmpty && savedRequest.origin != store.address }
  private var profiles: [RemoteRecord] { store.profiles.filter { $0.text("project") == project && $0.flag("evaluation") } }
  private var profile: RemoteRecord? { profiles.first { $0.id == selectedProfile } }
  private var canStart: Bool {
    !working && !frozen && !wrongMac && store.canMutate && profile != nil && !inspection.text("tasks_hash").isEmpty
      && (optimize ? store.permissions.contains("optimize") && profile?.flag("optimization") == true && live && maxCost.isFinite && maxCost > 0 && maxCost <= 10 : store.permissions.contains("evaluate"))
  }
  var body: some View {
    Form {
      Section {
        ConnectionStatus()
        if !store.reachable { Button("Check Mac connection") { Task { await store.refresh() } } }
        if wrongMac { Text("Pair the Mac that owns this saved request to continue.").foregroundStyle(CompanionTheme.warning) }
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
      }.disabled(working || frozen)
      Section("Review before running") {
        Button("Inspect suite and verifier commands") { Task { await inspect() } }.disabled(working || frozen || !store.reachable || selectedProfile.isEmpty || suite.isEmpty)
        if !inspection.isEmpty {
          LabeledContent("Tasks", value: String(Int(inspection.number("task_count"))))
          ForEach((inspection["warnings"]?.array ?? []).map(\.text), id: \.self) { Text($0).font(.caption).foregroundStyle(CompanionTheme.warning) }
          ForEach(inspection.records("repository_checks")) { check in
            VStack(alignment: .leading, spacing: 6) {
              Text(check.id).font(.caption.bold())
              ForEach((check.raw["commands"]?.array ?? []).map(\.text), id: \.self) { Text($0).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
            }
          }
        }
      }
      if !issue.isEmpty { Section { Text(issue).foregroundStyle(CompanionTheme.warning) } }
      if savedRequest.attempt != nil && !submitted {
        Section("Saved experiment request") {
          Text("This request may already be running. Check its status first. A retry preserves the reviewed suite, authorization, budgets and original request ID.").font(.footnote)
          Button("Check request status") { Task { await reconcile() } }
            .disabled(working || !store.canMutate || wrongMac || !store.features.flag("request_reconciliation"))
          Button("Retry the same request") { Task { await start() } }.disabled(working || !store.canMutate || wrongMac)
          Button("Discard saved request", role: .destructive) { discard = true }.disabled(working)
        }
      }
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
      .task {
        if savedRequest.origin.isEmpty { savedRequest.origin = store.address }
        if let attempt = savedRequest.attempt {
          selectedProfile = attempt.params.text("profile")
          suite = attempt.params.text("tasks")
          optimize = attempt.method == "optimizations.start"
          live = attempt.params.flag("live")
          if optimize { maxEvals = Int(attempt.params.number("max_evals")); maxCost = attempt.params.number("max_cost") }
        }
      }
      .onChange(of: selectedProfile) { _, _ in if !frozen { inspection = [:]; optimize = false } }
      .onChange(of: suite) { _, _ in if !frozen { inspection = [:] } }
      .confirmationDialog("Run live work on your Mac?", isPresented: $confirmLive, titleVisibility: .visible) {
        Button(optimize ? "Run within selected budgets" : "Run reviewed suite") { Task { await start() } }
      } message: { Text("This authorizes model calls and the verifier commands you reviewed. Commands can affect isolated evaluation workspaces and use the network according to the Mac's policy.") }
      .confirmationDialog("Discard this experiment request?", isPresented: $discard, titleVisibility: .visible) {
        Button("Discard saved request", role: .destructive) { Task {
          do { try await store.drafts.remove(savedRequest.id); dismiss() }
          catch { issue = error.localizedDescription }
        } }
      } message: { Text("This removes the saved request from the iPhone. It does not cancel an experiment already accepted by the Mac. Check Activity before starting another.") }
  }
  private func inspect() async {
    guard let api = store.api, !working, !frozen else { return }
    working = true; issue = ""
    defer { working = false }
    do { inspection = try await api.rpc("evals.inspect", ["profile": .string(selectedProfile), "tasks": .string(suite)]).object }
    catch { issue = error.localizedDescription }
  }
  private func start() async {
    guard let api = store.api, store.canMutate, !working, !submitted, !wrongMac else { return }
    guard savedRequest.attempt != nil || canStart else { return }
    working = true; issue = ""
    defer { working = false }
    if savedRequest.attempt == nil {
      var params: [String: JSONValue] = ["profile": .string(selectedProfile), "tasks": .string(suite), "tasks_hash": .string(inspection.text("tasks_hash")), "live": .bool(live)]
      if optimize { params["max_evals"] = .number(Double(maxEvals)); params["max_cost"] = .number(maxCost) }
      savedRequest.prompt = (optimize ? "Optimize " : "Evaluate ") + suite
      savedRequest.profile = selectedProfile
      savedRequest.attempt = SubmissionAttempt(key: UUID().uuidString, params: params, method: optimize ? "optimizations.start" : "evaluations.start")
    }
    guard let attempt = savedRequest.attempt, let method = attempt.method,
      ["evaluations.start", "optimizations.start"].contains(method) else { return }
    do {
      try await store.drafts.save(savedRequest)
      let result = try await api.rpc(method, attempt.params, key: attempt.key).object
      guard !result.text("id").isEmpty else { throw CompanionError("The Mac returned no run ID. Check Activity before starting another experiment.") }
      await open(result.text("id"))
    } catch { issue = error.localizedDescription }
  }
  private func open(_ identity: String) async {
    submitted = true
    try? await store.drafts.remove(savedRequest.id)
    startedRun = OpenedRun(id: identity)
    await store.refreshActivity()
  }
  private func reconcile() async {
    guard let api = store.api, let attempt = savedRequest.attempt, !working else { return }
    working = true; issue = ""
    defer { working = false }
    do {
      let status = try await api.rpc("companion.request_status", ["key": .string(attempt.key)]).object
      let identity = status.object("result").text("id")
      if !identity.isEmpty { await open(identity) }
      else { issue = status.text("state") == "not_recorded"
        ? "The Mac has not recorded this experiment. You can retry its original request."
        : "The outcome is uncertain. Check Activity or inspect the Mac before starting another experiment." }
    } catch { issue = error.localizedDescription }
  }
}
