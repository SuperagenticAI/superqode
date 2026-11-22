import SwiftUI

struct FactoryAcceptanceSetupView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var library: FactoryAcceptanceLibrary
  var active: Bool
  @State private var selectedRequirement = ""
  @State private var requirementID = ""
  @State private var requirementDescription = ""
  @State private var selectedStages: Set<String> = []
  @State private var selectedChecks: Set<String> = []
  @State private var categoryCheck = ""
  @State private var category = "test"
  @State private var probeCheck = ""
  @State private var probeID = "startup"
  @State private var arguments = "[\"python\", \"app.py\"]"
  @State private var expectedOutput = ""
  @State private var outputMode = "stdout"
  @State private var reviewed = false
  @State private var confirmation = ""
  @State private var reviewedDigest = ""
  @State private var verifiersExpanded = ProcessInfo.processInfo.arguments.contains("--factory-acceptance-inspect")
  @State private var explicitExpanded = ProcessInfo.processInfo.arguments.contains("--factory-acceptance-inspect")
  private var idle: Bool { !studio.busy && !library.busy && !app.anyActive && !app.busy }
  private var requirements: [String: Any] { studio.review["requirements"] as? [String: Any] ?? [:] }
  private var checks: [String] { studio.review["acceptance_checks"] as? [String] ?? [] }
  private var stages: [String] { (studio.review["stages"] as? [[String: Any]] ?? []).map { string($0, "id") } }
  private var configured: [String: Any] { studio.review["application_checks"] as? [String: Any] ?? [:] }
  private var saved: Bool { FactorySetupState(text: studio.text, review: studio.review, savedDigest: studio.expectedFileDigest, sources: studio.sourceReview, runs: studio.runs).saved }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("Acceptance & verification").font(.headline)
      Text("Map each outcome to its stages and final checks. Configure protected probes, then run a fresh trial to collect evidence.")
        .font(.caption).foregroundStyle(.secondary)
      if studio.review.isEmpty { Text("Validate the definition to load its requirements and final acceptance checks.").font(.caption) }
      ForEach(checks, id: \.self) { name in
        let check = configured[name] as? [String: Any] ?? [:]
        HStack {
          Text(name).font(.subheadline.bold())
          Pill(title: string(check, "category", "test"))
          Spacer()
          Text(string(check, "evaluator").isEmpty ? "Protected evaluator missing" : "Configured · not yet measured")
            .font(.caption).foregroundStyle(string(check, "evaluator").isEmpty ? Color.orange : Color.secondary)
        }
      }
      DisclosureGroup("Requirement mappings") {
        VStack(alignment: .leading, spacing: 10) {
          ForEach(requirements.keys.sorted(), id: \.self) { name in
            let value = requirements[name] as? [String: Any] ?? [:]
            let stageNames = (value["stages"] as? [String] ?? []).joined(separator: ", ")
            let checkNames = (value["checks"] as? [String] ?? []).joined(separator: ", ")
            VStack(alignment: .leading, spacing: 3) {
              Text(name + ": " + string(value, "description")).font(.subheadline)
              Text("Stages: \(stageNames) · Checks: \(checkNames)")
                .font(.caption).foregroundStyle(.secondary)
            }
          }
          if requirements.isEmpty { Text("No requirements declared. Passing checks alone will not establish requirement coverage.").font(.caption).foregroundStyle(.secondary) }
          Picker("Edit mapping", selection: $selectedRequirement) {
            Text("New requirement").tag("")
            ForEach(requirements.keys.sorted(), id: \.self) { Text($0).tag($0) }
          }.onChange(of: selectedRequirement) { _, value in loadRequirement(value) }
          TextField("Requirement id", text: $requirementID).textFieldStyle(.roundedBorder).disabled(!selectedRequirement.isEmpty)
          TextField("Acceptance outcome", text: $requirementDescription).textFieldStyle(.roundedBorder)
          Text("Contributing stages").font(.caption.bold())
          ForEach(stages, id: \.self) { value in Toggle(value, isOn: membership(value, in: $selectedStages)).toggleStyle(.checkbox) }
          Text("Final checks").font(.caption.bold())
          ForEach(checks, id: \.self) { value in Toggle(value, isOn: membership(value, in: $selectedChecks)).toggleStyle(.checkbox) }
          FactoryActionRow {
            Button("Apply mapping to draft") { applyRequirement(removing: false) }
              .disabled(!idle || studio.review.isEmpty || requirementID.isEmpty || requirementDescription.isEmpty || selectedStages.isEmpty || selectedChecks.isEmpty)
            Button("Remove mapping from draft…") { confirmation = "remove" }.disabled(!idle || selectedRequirement.isEmpty)
          }
          Text("Mapping edits update the draft. Validate and save the revision before preparing verifiers or trials.").font(.caption).foregroundStyle(.secondary)
        }.padding(.top, 8)
      }
      DisclosureGroup("Classify an application check") {
        VStack(alignment: .leading, spacing: 8) {
          Picker("Check", selection: $categoryCheck) { Text("Choose a check").tag(""); ForEach(checks, id: \.self) { Text($0).tag($0) } }
            .onChange(of: categoryCheck) { _, value in category = string(configured[value] as? [String: Any] ?? [:], "category", "test") }
          Picker("Purpose", selection: $category) { ForEach(["test", "build", "start", "health", "service", "security"], id: \.self) { Text($0.capitalized).tag($0) } }
          Button("Apply category to draft") { let name = categoryCheck; let value = category; Task { await studio.edit(engine: app.engine, controls: ["check_categories": [name: value]]) } }
            .disabled(!idle || !checks.contains(categoryCheck))
          Text("A category describes the check's purpose. It does not establish that an application or service has been tested.").font(.caption).foregroundStyle(.secondary)
        }.padding(.top, 8)
      }
      Divider()
      DisclosureGroup("Prepare protected verifiers", isExpanded: $verifiersExpanded) {
        VStack(alignment: .leading, spacing: 10) {
          Text("Probes use Python's standard library, a read-only candidate and writable temporary storage. Network, external services and third-party packages need a separately supported execution setup.")
            .font(.caption).foregroundStyle(.secondary)
          TextField("Describe build, startup or behavior expectations", text: $library.description, axis: .vertical)
            .textFieldStyle(.roundedBorder).accessibilityIdentifier("factory.verifier.description")
          Text(app.provider.isEmpty || app.model.isEmpty ? "Select a drafting model to propose probes, or enter explicit probes below." : "Drafting model: \(app.provider)/\(app.model)")
            .font(.caption).foregroundStyle(.secondary)
          Button("Generate verifier proposal…") { confirmation = "generate" }
            .disabled(!idle || !saved || library.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || app.provider.isEmpty || app.model.isEmpty || app.provider == "acp")
          DisclosureGroup("Explicit probes", isExpanded: $explicitExpanded) {
            VStack(alignment: .leading, spacing: 8) {
              Picker("Final check", selection: $probeCheck) { Text("Choose a check").tag(""); ForEach(checks, id: \.self) { Text($0).tag($0) } }
              TextField("Probe id", text: $probeID).textFieldStyle(.roundedBorder)
              TextField("Python arguments as a JSON array", text: $arguments).textFieldStyle(.roundedBorder)
              Picker("Output expectation", selection: $outputMode) { Text("Exact stdout").tag("stdout"); Text("Stdout contains").tag("stdout_contains") }
              TextEditor(text: $expectedOutput).font(.caption.monospaced()).frame(minHeight: 50, maxHeight: 90).brandSurface().accessibilityLabel("Expected probe output")
              Button("Add probe to manifest") { appendProbe() }.disabled(!idle || !checks.contains(probeCheck) || probeID.isEmpty)
              SourceEditor(text: $library.checksText, path: "checks.json", editable: idle, documentID: "factory-verifier-checks:" + app.projectID, active: active)
                .frame(height: 150).brandSurface().accessibilityIdentifier("factory.verifier.checks")
              nativeButton("factory.verifier.prepare", action: { Task { await library.draft(app.engine) } }, title: "Prepare explicit proposal") { Text("Prepare explicit proposal") }.disabled(!idle || !saved)
            }.padding(.top, 8)
          }
          if !saved { Text("Save the validated Factory before preparing verifiers. The proposal is bound to its saved sources.").font(.caption).foregroundStyle(.orange) }
          if library.busy { HStack { ProgressView().controlSize(.small); Text("Acceptance action in progress…").font(.caption)
            if !string(library.job, "id").isEmpty { Button("Stop drafting") { Task { await library.cancelGeneration(app.engine) } } } }
          }
          ForEach(library.generationResult["assumptions"] as? [String] ?? [], id: \.self) { Text("Assumption: " + $0).font(.caption) }
          ForEach(library.generationResult["missing_capabilities"] as? [String] ?? [], id: \.self) { Text("Unsupported: " + $0).font(.caption).foregroundStyle(.orange) }
          if !library.proposal.isEmpty {
            Text("Review the proposed configuration").font(.subheadline.bold())
            Text("Configured proposal · execution not tested").font(.caption).foregroundStyle(.secondary)
            ForEach(library.proposal["missing_protected_checks"] as? [String] ?? [], id: \.self) { Text("Still missing a protected evaluator: " + $0).font(.caption).foregroundStyle(.orange) }
            DisclosureGroup("Definition diff") { CodeBlock(text: string(library.proposal, "diff")) }
            DisclosureGroup("Protected probe expectations") { CodeBlock(text: pretty(library.proposal["checks"])) }
            nativeButton("factory.verifier.review", action: { reviewed.toggle() }, title: reviewed ? "Expectations reviewed" : "Mark expectations reviewed") {
              Label(reviewed ? "Expectations reviewed" : "Mark expectations reviewed", systemImage: reviewed ? "checkmark.square.fill" : "square")
            }
            nativeButton("factory.verifier.save", action: { reviewedDigest = string(library.proposal, "digest"); confirmation = "install" }, title: "Save reviewed verifiers…") { Text("Save reviewed verifiers…") }
              .disabled(!idle || !reviewed || !saved)
          }
          if !library.failure.isEmpty { Text(library.failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
          if !library.message.isEmpty { Text(library.message).font(.caption).foregroundStyle(.secondary).textSelection(.enabled) }
        }.padding(.top, 8)
      }
    }
    .onChange(of: string(library.proposal, "digest")) { _, _ in reviewed = false; confirmation = "" }
    .onChange(of: active) { _, value in if !value { confirmation = "" } }
    .onChange(of: app.projectID) { _, _ in confirmation = ""; loadRequirement(""); categoryCheck = ""; probeCheck = ""; expectedOutput = ""; reviewed = false }
    .alert(confirmation == "install" ? "Save reviewed verifier configuration?" : confirmation == "remove" ? "Remove this requirement mapping?" : "Generate a verifier proposal?", isPresented: Binding(get: { !confirmation.isEmpty }, set: { if !$0 { confirmation = "" } })) {
      Button("Cancel", role: .cancel) { confirmation = "" }
      Button("Continue") { let action = confirmation; confirmation = ""; execute(action) }
    } message: {
      Text(confirmation == "install" ? "Save exactly the reviewed protected probes and definition. Existing runs keep their pinned inputs; prepare a new trial to test this configuration."
        : confirmation == "remove" ? "Remove the selected mapping from the draft. Save the revision explicitly after reviewing it."
        : "The selected model receives your description and saved Factory. This incurs model usage and produces an unexecuted proposal. Review its expectations independently.")
    }
  }
  private func membership(_ value: String, in selection: Binding<Set<String>>) -> Binding<Bool> {
    Binding(get: { selection.wrappedValue.contains(value) }, set: { if $0 { selection.wrappedValue.insert(value) } else { selection.wrappedValue.remove(value) } })
  }
  private func loadRequirement(_ name: String) {
    let value = requirements[name] as? [String: Any] ?? [:]
    requirementID = name; requirementDescription = string(value, "description")
    selectedStages = Set(value["stages"] as? [String] ?? []); selectedChecks = Set(value["checks"] as? [String] ?? [])
  }
  private func applyRequirement(removing: Bool) {
    var values = requirements
    if removing { values.removeValue(forKey: selectedRequirement) }
    else { values[requirementID] = ["description": requirementDescription, "stages": selectedStages.sorted(), "checks": selectedChecks.sorted()] }
    Task { await studio.edit(engine: app.engine, controls: ["requirements": values]) }
  }
  private func appendProbe() {
    do {
      guard let argv = try JSONSerialization.jsonObject(with: Data(arguments.utf8)) as? [String],
        var values = try JSONSerialization.jsonObject(with: Data(library.checksText.utf8)) as? [String: Any] else { throw EngineError(message: "Use a JSON string array for arguments and an object for manifests.") }
      var manifest = values[probeCheck] as? [String: Any] ?? ["format": "superqode.factory-probes/1"]
      var cases = manifest["cases"] as? [[String: Any]] ?? []
      guard !cases.contains(where: { string($0, "id") == probeID }) else { throw EngineError(message: "Choose a unique probe id within this check.") }
      cases.append(["id": probeID, "argv": argv, outputMode: expectedOutput]); manifest["cases"] = cases; values[probeCheck] = manifest
      library.checksText = pretty(values); library.failure = ""
    } catch { library.failure = error.localizedDescription }
  }
  private func execute(_ action: String) {
    if action == "remove" { applyRequirement(removing: true); return }
    let identity = app.projectID; let token = studio.version
    Task {
      guard app.projectID == identity else { return }
      if action == "generate" { await library.generate(app.engine, provider: app.provider, model: app.model) }
      else if action == "install", reviewedDigest == string(library.proposal, "digest"), await library.install(app.engine), studio.version == token {
        await studio.load(engine: app.engine); await studio.validate(engine: app.engine); await studio.refreshSources(engine: app.engine)
      }
    }
  }
}
