import SwiftUI

struct FactoryOperationsView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var library: FactoryOperationsLibrary
  var active: Bool
  @State private var selectedRun = ""
  @State private var selectedImprovement = ""
  @State private var selectedPackage = ""
  @State private var restoreName = "recovery"
  @State private var targetPlatform = "Darwin"
  @State private var targetProject = ""
  @State private var python = ""
  @State private var serviceUser = "superqode"
  @State private var confirmation = ""
  @State private var keep = 2
  @State private var days = 30
  @State private var recoveryExpanded = ProcessInfo.processInfo.arguments.contains("--factory-guided-inspect") || ProcessInfo.processInfo.arguments.contains("--factory-navigation-inspect")
  @State private var recoveryDigest = ""
  private var idle: Bool { !library.busy && !studio.busy && !studio.acceptance.busy && !app.anyActive && !app.busy }
  private var package: [String: Any] { library.packages.first { string($0, "id") == selectedPackage } ?? [:] }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 14) {
        Text("Check your worker host or choose a maintenance task.").foregroundStyle(.secondary)
        HStack {
          Button("Refresh") { Task { await library.refresh(app.engine) } }.disabled(!idle)
          Button("Run isolation checks…") { confirmation = "check" }.disabled(!idle)
          if library.busy { ProgressView().controlSize(.small) }
        }
        if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.orange).textSelection(.enabled) }
        Text(library.readiness["worker_ready"] as? Bool == true ? "Protected readiness probes passed on this host. Model routes and application acceptance need separate testing." : library.readiness["probe_executed"] as? Bool == true ? "Host checks did not pass. Inspect the findings below before starting a worker." : "Host isolation is untested in this view. Run isolation checks; application acceptance remains separate.").font(.caption)
        DisclosureGroup("Host readiness") { CodeBlock(text: pretty(library.readiness)) }
        FactoryIntakeReceiptView(studio: studio, library: studio.acceptance, active: active)
        Divider()
        DisclosureGroup("Evidence & source recovery", isExpanded: $recoveryExpanded) {
        VStack(alignment: .leading, spacing: 12) {
        Picker("Include run", selection: $selectedRun) {
          Text("Factory sources only").tag("")
          ForEach(studio.runs.map { string($0, "id") }, id: \.self) { identity in Text(identity).tag(identity) }
        }
        Picker("Include improvement", selection: $selectedImprovement) {
          Text("No improvement evidence").tag("")
          ForEach(studio.improvementPlans.map { string($0, "id") }, id: \.self) { identity in Text(identity).tag(identity) }
        }
        Button("Create verified handover…") { confirmation = "handover" }.disabled(!idle)
        Text("Packages can contain protected evaluator inputs, task prompts and outputs. Review them before sharing. Restored history is inspection-only; prepare new work against a separately restored application checkout.").font(.caption).foregroundStyle(.secondary)
        Picker("Package", selection: $selectedPackage) {
          Text("Choose a package").tag("")
          ForEach(library.packages.map { string($0, "id") }, id: \.self) { identity in Text(identity).tag(identity) }
        }
        HStack {
          Button("Verify package") { Task { await library.perform(app.engine, "verify", ["id": selectedPackage, "sha256": string(package, "sha256")]) } }.disabled(!idle || package.isEmpty)
          TextField("New recovery folder name", text: $restoreName).textFieldStyle(.roundedBorder)
            .accessibilityIdentifier("factory.operations.restore-name")
          Button("Restore sources…") { confirmation = "restore" }.disabled(!idle || package.isEmpty || restoreName.isEmpty)
        }
        }.padding(.top, 8)
        }
        Divider()
        DisclosureGroup("Runtime recovery & retirement (advanced)") {
          VStack(alignment: .leading, spacing: 12) {
            Text("Stop workers before a runtime checkpoint. It captures Git history, queue and Factory state in a private encrypted archive; keep its key separately. Restore uses the absent original project path and keeps execution disarmed until reviewed.").font(.caption).foregroundStyle(.secondary)
            Button("Create encrypted runtime checkpoint…") { confirmation = "checkpoint" }.disabled(!idle)
            TextField("Recovery or retirement receipt digest", text: $recoveryDigest).textFieldStyle(.roundedBorder)
            FactoryActionRow {
              Button("Acknowledge recovery & check host…") { confirmation = "recovery.acknowledge" }.disabled(!idle || recoveryDigest.isEmpty)
              Button("Reactivate retired instance…") { confirmation = "reactivate" }.disabled(!idle || recoveryDigest.isEmpty)
            }
            FactoryActionRow {
              Button("Review retirement") { Task { await library.perform(app.engine, "retire.preview") } }.disabled(!idle)
              Button("Retire reviewed instance…") { confirmation = "retire" }.disabled(!idle || library.retirement.isEmpty)
            }
            Text("Retirement cancels pending Factory work and blocks new execution. Evidence and worktrees stay available for inspection; no external services or credentials are deleted.").font(.caption).foregroundStyle(.secondary)
            if !library.retirement.isEmpty { DisclosureGroup("Retirement inventory") { CodeBlock(text: pretty(library.retirement)) } }
          }.padding(.top, 8)
        }
        Divider()
        DisclosureGroup("Deployment (advanced)") {
        VStack(alignment: .leading, spacing: 12) {
        Text("Generates a disabled one-shot service from the selected run's goal. Restore the application checkout and Factory sources separately. Starting the service prepares fresh target-local work after protected probes pass; it never imports an old queue. Linux has not been validated by this Mac.").font(.caption).foregroundStyle(.secondary)
        Picker("Source trial", selection: $selectedRun) {
          Text("Choose a trial").tag("")
          ForEach(studio.runs.map { string($0, "id") }, id: \.self) { Text($0).tag($0) }
        }
        Picker("Target OS", selection: $targetPlatform) { Text("macOS launchd").tag("Darwin"); Text("Linux systemd").tag("Linux") }
        TextField("Absolute project path on target", text: $targetProject).textFieldStyle(.roundedBorder)
        TextField("Absolute Python executable on target", text: $python).textFieldStyle(.roundedBorder)
        TextField("Linux service user", text: $serviceUser).textFieldStyle(.roundedBorder)
        Button("Prepare service package…") { confirmation = "deploy" }.disabled(!idle || selectedRun.isEmpty || targetProject.isEmpty || python.isEmpty)
        }.padding(.top, 8)
        }
        Divider()
        DisclosureGroup("Archive retention (advanced)") {
        VStack(alignment: .leading, spacing: 12) {
        Stepper("Keep at least \(keep) newest verified packages", value: $keep, in: 1...100).onChange(of: keep) { _, _ in library.retention = [:] }
        Stepper("Retain packages for \(days) days", value: $days, in: 1...3650).onChange(of: days) { _, _ in library.retention = [:] }
        HStack {
          Button("Preview cleanup") { Task { await library.perform(app.engine, "retention.preview", ["keep": keep, "days": days]) } }.disabled(!idle)
          Button("Apply reviewed cleanup…") { confirmation = "retention.apply" }.disabled(!idle || library.retention.isEmpty)
        }
        Text("Cleanup covers generated handover archives only. It preserves Factory sources, live run evidence, worktrees and damaged archives.").font(.caption).foregroundStyle(.secondary)
        if !library.retention.isEmpty { CodeBlock(text: pretty(library.retention)) }
        }.padding(.top, 8)
        }
        if !library.result.isEmpty { DisclosureGroup("Last operation receipt") { CodeBlock(text: pretty(library.result)) } }
      }
    }
    .task(id: app.projectID + String(active)) {
      guard active, !app.projectID.isEmpty else { return }
      library.enter(app.projectID); await library.refresh(app.engine); await studio.refreshImprovements(engine: app.engine)
    }
    .onChange(of: app.projectID) { _, _ in confirmation = ""; selectedRun = ""; selectedImprovement = ""; selectedPackage = ""; python = ""; targetProject = ""; recoveryDigest = "" }
    .onChange(of: active) { _, value in if !value { confirmation = "" } }
    .alert("Confirm Factory operation", isPresented: Binding(get: { !confirmation.isEmpty }, set: { if !$0 { confirmation = "" } })) {
      Button("Cancel", role: .cancel) { confirmation = "" }
      Button("Continue") { let action = confirmation; confirmation = ""; execute(action) }
    } message: {
      Text(confirmationMessage)
    }
  }
  private func execute(_ action: String) {
    let identity = app.projectID
    var params: [String: Any] = [:]
    if action == "handover" { params = ["runs": selectedRun.isEmpty ? [] : [selectedRun], "improvements": selectedImprovement.isEmpty ? [] : [selectedImprovement]] }
    if action == "restore" { params = ["id": selectedPackage, "sha256": string(package, "sha256"), "destination": ".superqode/factory-operations/restores/" + restoreName] }
    if action == "deploy" { params = ["platform": targetPlatform, "target_project": targetProject, "python": python, "reference": selectedRun, "user": serviceUser] }
    if action == "retention.apply" { params = ["review": library.retention] }
    if action == "retire" { params = ["digest": string(library.retirement, "digest")] }
    if ["reactivate", "recovery.acknowledge"].contains(action) { params = ["digest": recoveryDigest] }
    Task { guard app.projectID == identity else { return }; await library.perform(app.engine, action, params) }
  }
  private var confirmationMessage: String {
    switch confirmation {
    case "checkpoint": return "Encrypt this stopped instance, including Git history and private runtime records? Store its generated key separately from the archive. No models or services start."
    case "retire": return "Cancel pending Factory work in the reviewed inventory and block new execution? Evidence and worktrees are retained. Stop workers first."
    case "recovery.acknowledge": return "Run protected host probes and re-enable the recovered instance after reconciliation? Historical release approvals will be revoked. No workers start automatically."
    case "reactivate": return "Run protected host probes and re-enable this retired instance? Cancelled work remains cancelled."
    case "retention.apply": return "Delete only the generated archives listed in the current cleanup preview?"
    case "check": return "Run synthetic protected probes on this host? No model calls are made."
    case "restore": return "Recover Factory sources and inspection-only evidence into a new folder? Existing sources and queues are preserved."
    case "deploy": return "Write a disabled worker service package? Nothing is installed or started."
    default: return "Create a verified source recovery package with the selected historical evidence? Review its content before sharing."
    }
  }
}
