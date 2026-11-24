import SwiftUI

struct FactoryTrialSuiteView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var library: FactoryTrialSuiteLibrary
  var active = true
  @State private var tab = ProcessInfo.processInfo.arguments.contains("--factory-feedback-inspect") ? "Feedback" : ProcessInfo.processInfo.arguments.contains("--factory-suite-inspect") ? "Scorecard" : "Inputs"
  @State private var confirmation = ""
  @State private var tabGeneration = UUID()
  @State private var gate: [String: Any] = [:]
  @State private var reason = ""
  private var idle: Bool { !library.busy && !studio.busy && !app.anyActive && !app.busy }
  private var rows: [[String: Any]] { library.board["entries"] as? [[String: Any]] ?? [] }
  private var chosen: [String: Any] { rows.first { string($0, "id") == library.entry } ?? [:] }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        VStack(alignment: .leading, spacing: 4) {
          Text("Paired Factory Trial Suite").font(.headline)
          Text("Replay complete workflows on the same committed application inputs. Human gates pause execution; comparisons grant no promotion or release authority.").font(.caption).foregroundStyle(.secondary)
        }
        Spacer()
        Button("Refresh history") { Task { await library.refresh(app.engine) } }.disabled(!idle)
      }
      if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.orange).textSelection(.enabled) }
      if !library.message.isEmpty { Text(library.message).font(.caption).foregroundStyle(.secondary) }
      HStack {
        Picker("Prepared suite", selection: $library.selected) {
          Text("Choose a suite").tag("")
          ForEach(library.plans, id: \.suiteID) { plan in
            Text(string(plan["suite"] as? [String: Any] ?? [:], "name") + " · " + String(string(plan, "id").prefix(16))).tag(string(plan, "id"))
          }
        }.disabled(!idle)
        Button("Open scorecard") {
          let ticket = studio.navigation.ticket(); let token = tabGeneration
          Task {
            await library.inspect(app.engine)
            if app.section == "Factory Studio", studio.navigation.isCurrent(ticket), tabGeneration == token, library.failure.isEmpty { tab = "Scorecard" }
          }
        }.disabled(!idle || library.selected.isEmpty)
      }
      Picker("Suite workspace", selection: $tab) {
        Text("Suite & inputs").tag("Inputs"); Text("Scorecard & evidence").tag("Scorecard")
        Text("Failures & proposals").tag("Feedback")
      }.pickerStyle(.segmented)
      if tab == "Inputs" { inputs }
      else if tab == "Feedback" { feedback }
      else { scorecard }
      if !library.selected.isEmpty {
        HStack {
          Text(String(library.selected.prefix(24))).font(.caption.monospaced())
          Spacer()
          if library.busy {
            ProgressView().controlSize(.small)
            Button("Stop suite job") { Task { await library.cancel(app.engine) } }
          } else {
            Button("Run / continue suite…") { confirmation = "run" }.buttonStyle(BrandButtonStyle())
              .disabled(!idle || library.board["complete"] as? Bool == true || !(library.board["issues"] as? [String] ?? []).isEmpty)
          }
        }
      }
    }
    .task(id: studio.project + "\n" + String(active)) {
      guard active, !studio.project.isEmpty else { return }
      library.enter(studio.project); await library.refresh(app.engine)
      if library.text.isEmpty { await library.loadSource(app.engine) }
    }
    .onChange(of: studio.project) { _, value in confirmation = ""; gate = [:]; library.enter(value) }
    .onChange(of: active) { _, visible in if !visible { confirmation = ""; gate = [:] } }
    .onChange(of: tab) { _, _ in tabGeneration = UUID(); confirmation = ""; gate = [:] }
    .factoryConfirmation(
      isPresented: Binding(get: { !confirmation.isEmpty }, set: { if !$0 { confirmation = "" } }),
      title: confirmation == "run" ? "Run the pinned Factory suite?" : confirmation == "retry" ? "Retry the recorded failed stage?" : "Approve this workflow gate?",
      message: confirmation == "run" ? "Execute model-driven stages, controller self-checks and protected probes in the prepared paired projects. Provider charges may apply. Token, tool and cost budgets are divided across runs; wall time is shared. Execution stops at human gates and never signs or applies an application change. Interrupted invocations may require WorkOrder recovery."
        : confirmation == "retry" ? "Authorize another attempt of this recorded failure after reviewing its evidence. Actions may repeat and provider charges may apply. Attempt and budget limits still apply; uncertain invocations require reconciliation. Earlier failures and their usage remain recorded. Continue the suite separately to execute."
        : "Continue the selected stage after reviewing its candidate patch and evidence. This is a workflow continuation decision; application acceptance and signed release remain separate.",
      kind: confirmation == "run" ? .trial : confirmation == "retry" ? .caution : .save,
      badges: confirmation == "run"
        ? [FactoryConfirmBadge(label: "Paired projects", symbol: "square.split.2x1", color: Brand.purple),
           FactoryConfirmBadge(label: "Stops at human gates", symbol: "lock.fill", color: .orange)]
        : [],
      confirmTitle: confirmation == "run" ? "Run suite" : confirmation == "retry" ? "Authorize retry" : "Approve gate",
      onCancel: { confirmation = "" },
      onConfirm: {
        let action = confirmation; let approved = gate; confirmation = ""
        let ticket = studio.navigation.ticket(); let token = tabGeneration
        Task {
          guard studio.project == ticket.project else { return }
          if action == "run" { await library.run(app.engine); showScorecard(ticket, token: token) }
          else if action == "retry" { await library.retry(app.engine, stage: string(approved, "stage"), attempt: approved["attempt"] as? Int ?? 0, reason: reason) }
          else { await library.gate(app.engine, stage: string(approved, "stage"), digest: string(approved, "digest"), decision: "approve", reason: reason) }
        }
      }
    )
  }
  private var inputs: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        TextField("Suite source under .superqode/trials", text: $library.path).textFieldStyle(.roundedBorder)
        Button("Load / starter") { Task { await library.loadSource(app.engine) } }.disabled(!idle)
        Button("Save source") { Task { await library.saveSource(app.engine) } }.disabled(!idle || library.text.isEmpty)
      }
      Text("Use a clean committed application repository. Reference saved Factory definitions or revision files, with optional per-case references. Paired revisions must preserve protected checks, governance and workflow structure. Up to eight cases use the same pinned application seed.").font(.caption).foregroundStyle(.secondary)
      SourceEditor(text: $library.text, path: "factory-trial-suite.yaml", editable: idle, documentID: "factory-trial-suite:" + studio.project, active: active).brandSurface()
      Button("Prepare paired projects: no model calls") {
        let ticket = studio.navigation.ticket(); let token = tabGeneration
        Task { await library.prepare(app.engine); if library.failure.isEmpty { showScorecard(ticket, token: token) } }
      }.disabled(!idle || library.text.isEmpty)
    }
  }
  private func showScorecard(_ ticket: FactoryNavigation.Ticket, token: UUID) {
    guard app.section == "Factory Studio", studio.navigation.isCurrent(ticket), tabGeneration == token else { return }
    tab = "Scorecard"
  }
  private var feedback: some View {
    let ticket = studio.navigation.ticket(); let token = tabGeneration
    return FactoryFeedbackView(suites: library, library: library.feedback, idle: idle, active: active, onDraft: {
      if app.section == "Factory Studio", studio.navigation.isCurrent(ticket), tabGeneration == token { tab = "Inputs" }
    })
  }
  private var scorecard: some View {
    HSplitView {
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          Text(string(library.board, "verdict", "Prepare or open a suite").capitalized).font(.title2.bold())
          let summaries = library.board["summary"] as? [String: [String: Any]] ?? [:]
          ForEach(["baseline", "candidate"], id: \.self) { variant in
            let summary = summaries[variant] ?? [:]; let usage = summary["usage"] as? [String: Any] ?? [:]
            VStack(alignment: .leading, spacing: 4) {
              Text(variant.capitalized).font(.headline)
              Text("Verified workflows: \(summary["passed"] as? Int ?? 0) / \(summary["total"] as? Int ?? 0)")
              Text("Recorded tokens: \(metric(usage, "total_tokens")) · tools: \(metric(usage, "tool_calls")) · API USD: \(metric(usage, "cost_usd"))").font(.caption)
              Text("Model ms: \(metric(usage, "latency_ms")) · recorded operator gate decisions: \(summary["operator_gate_decisions"] as? Int ?? 0)").font(.caption)
            }.padding(10).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
          }
          ForEach(library.board["issues"] as? [String] ?? [], id: \.self) { Text($0).foregroundStyle(.orange) }
          ForEach(rows, id: \.suiteID) { row in
            Button { library.entry = string(row, "id"); Task { await library.inspectEntry(app.engine) } } label: {
              HStack { VStack(alignment: .leading) { Text(string(row, "case")).font(.headline); Text(string(row, "variant")).font(.caption) }; Spacer(); Pill(title: string(row, "status"), color: string(row, "status") == "passed" ? .green : .orange) }.padding(8)
            }.buttonStyle(.plain).brandSurface()
          }
          Text("A tie is not an improvement. Missing verification or required usage holds the comparison. These small paired trials do not establish statistical reliability or sealed evaluator independence.").font(.caption).foregroundStyle(.secondary)
          DisclosureGroup("Pinned suite contract") { CodeBlock(text: pretty(library.board["plan"])) }
          if !library.job.isEmpty { DisclosureGroup("Latest suite job") { CodeBlock(text: pretty(library.job)) } }
        }.padding(.trailing, 10)
      }.frame(minWidth: 230, idealWidth: 280, maxWidth: 440)
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          Text("Entry evidence & gate review").font(.headline)
          if library.detail.isEmpty { Text("Select a baseline or candidate entry to review its patch, stage outcomes and controller evidence.").foregroundStyle(.secondary) }
          else {
            Text(string(library.detail, "project")).font(.caption.monospaced()).textSelection(.enabled)
            Text(string(chosen, "goal")).textSelection(.enabled)
            CodeBlock(text: string(library.detail, "patch", "No patch recorded yet."))
            ForEach(chosen["issues"] as? [String] ?? [], id: \.self) { Text($0).foregroundStyle(.orange) }
            TextField("Reason for the operator decision", text: $reason).textFieldStyle(.roundedBorder)
            let failed = (library.detail["tasks"] as? [[String: Any]] ?? []).filter { string($0, "status") == "failed" }
            ForEach(failed, id: \.suiteTask) { task in
              VStack(alignment: .leading, spacing: 6) {
                Text(string(task, "error")).font(.caption).foregroundStyle(.orange).textSelection(.enabled)
                Button("Authorize retry of " + string(task, "task_id") + "…") {
                  gate = ["stage": string(task, "task_id"), "attempt": task["attempts"] as? Int ?? 0]; confirmation = "retry"
                }.disabled(!idle || (task["attempts"] as? Int ?? 0) >= (task["max_attempts"] as? Int ?? 0) || !(library.board["issues"] as? [String] ?? []).isEmpty)
              }
            }
            if let gates = chosen["gates"] as? [[String: Any]], !gates.isEmpty {
              ForEach(gates, id: \.suiteStage) { value in
                HStack {
                  Text("Waiting: " + string(value, "stage")); Spacer()
                  Button("Hold") { Task { await library.gate(app.engine, stage: string(value, "stage"), digest: string(value, "digest"), decision: "hold", reason: reason) } }.disabled(!idle)
                  Button("Approve continuation…") { gate = value; confirmation = "gate" }.disabled(!idle)
                }
              }
            }
            DisclosureGroup("Stage results") { CodeBlock(text: pretty(library.detail["tasks"])) }
            DisclosureGroup("Typed handoffs and candidate bindings") { CodeBlock(text: pretty(library.detail["handoffs"])) }
            DisclosureGroup("Skipped stages and decision receipts") { CodeBlock(text: pretty(library.detail["skipped"])) }
            DisclosureGroup("Controller and agent evidence") { CodeBlock(text: pretty(library.detail["evidence"])) }
            DisclosureGroup("Recent gate, failure & retry history") { CodeBlock(text: pretty(library.detail["history"])) }
            DisclosureGroup("Protected verification") { CodeBlock(text: pretty(chosen["verification"])) }
          }
        }.padding(.leading, 10)
      }.frame(minWidth: 280)
    }
  }
  private func metric(_ values: [String: Any], _ key: String) -> String {
    guard let value = values[key], !(value is NSNull) else { return "unknown" }
    return String(describing: value)
  }
}

private extension Dictionary where Key == String, Value == Any {
  var suiteID: String { self["id"] as? String ?? "" }
  var suiteStage: String { self["stage"] as? String ?? "" }
  var suiteTask: String { self["task_id"] as? String ?? "" }
}
