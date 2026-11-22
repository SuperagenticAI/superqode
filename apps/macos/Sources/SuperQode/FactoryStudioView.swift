import SwiftUI

struct FactoryStudioView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var library: FactoryStudioLibrary
  var active = true
  private var tab: String { library.navigation.selection }
  @State private var preset = "fix-and-verify"
  @State private var experimentStage = ""
  @State private var experimentGoal = ""
  @State private var experimentTask = ""
  @State private var reason = ""
  @State private var goal = ""
  @State private var gateReason = ""
  @State private var confirmation = ""
  @State private var factoryName = ""
  @State private var binding = "core"
  @State private var modelRef = "ollama/qwen3:8b"
  @State private var seconds = 600
  @State private var workers = 2
  @State private var network = false
  @State private var syncedControls: FactoryControlDraft?
  private var controlDraft: FactoryControlDraft { FactoryControlDraft(name: factoryName, binding: binding,
    model: modelRef, seconds: seconds, workers: workers, network: network) }
  private var controlsHaveChanges: Bool { syncedControls.map { $0 != controlDraft } ?? false }
  private var idle: Bool { !library.busy && !app.anyActive && !app.busy }
  private var order: [String: Any] { library.detail["work_order"] as? [String: Any] ?? [:] }
  private var stages: [[String: Any]] { library.review["stages"] as? [[String: Any]] ?? [] }
  private var tasks: [[String: Any]] { order["tasks"] as? [[String: Any]] ?? [] }
  private var bindings: [String: Any] { library.review["bindings"] as? [String: Any] ?? [:] }
  private var setup: FactorySetupState { FactorySetupState(text: library.text, review: library.review,
    savedDigest: library.expectedFileDigest, sources: library.sourceReview, runs: library.runs) }
  private let layers = ["Factories-as-code", "Data and context", "Compute", "Inference", "Improvement", "Orchestration", "Access"]
  private let descriptions = [
    "Version the definition and capture immutable snapshots for each run.",
    "Pin project context, skills and protected evaluator inputs.",
    "Run isolated native worktrees within the declared budget.",
    "Bind stages to harnesses and explicitly selected model routes.",
    "Measure exact candidates against protected acceptance probes.",
    "Coordinate dependent stages and explicit human gates.",
    "Use this native app or the shared command-line engine."]

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      PageTitle(eyebrow: "Software factory", title: "Factory Studio",
        subtitle: "Start with one repeatable development workflow. Review its evidence before improving or releasing it.")
      FactoryNavigationHeader(navigation: library.navigation)
      if !library.failure.isEmpty { Text(library.failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
      if !library.message.isEmpty { Text("Last action: " + library.message).font(.caption).foregroundStyle(.secondary) }
      if library.busy { HStack { ProgressView().controlSize(.small); Text("Factory action in progress…").font(.caption); Spacer(); Button("Stop action") { Task { await library.cancel(engine: app.engine) } } } }
      ZStack(alignment: .topLeading) {
        if library.navigation.mounted.contains("Operations") {
          FactoryOperationsView(studio: library, library: library.operations, active: active && tab == "Operations")
            .modifier(FactoryPaneVisibility(active: active && tab == "Operations"))
        }
        if library.navigation.mounted.contains("Suites") {
          FactoryTrialSuiteView(studio: library, library: library.trialSuites, active: active && tab == "Suites")
            .modifier(FactoryPaneVisibility(active: active && tab == "Suites"))
        }
        if library.navigation.mounted.contains("Improve") {
          FactoryImprovementView(library: library, active: active && tab == "Improve", onAdopt: { library.navigation.select("Definition") })
            .modifier(FactoryPaneVisibility(active: active && tab == "Improve"))
        }
        if library.navigation.mounted.contains("Sources") {
          FactorySourceControlView(library: library, active: active && tab == "Sources")
            .modifier(FactoryPaneVisibility(active: active && tab == "Sources"))
        }
        if tab == "Runs" { runs }
        if tab == "Revisions" { revisions }
        if !library.navigation.mounted.isDisjoint(with: ["Stack", "Workflow", "Definition"]) {
        VStack(alignment: .leading, spacing: 12) {
        HStack {
          Text(tab == "Stack" ? "Set up your workflow" : tab == "Workflow" ? "Review the workflow" : "Review the definition").font(.headline)
          Spacer()
          Button("Validate") {
            let ticket = library.navigation.ticket()
            Task { await library.validate(engine: app.engine); if library.navigation.isCurrent(ticket), !controlsHaveChanges { syncControls() } }
          }.disabled(!idle || library.text.isEmpty)
        }
        ZStack(alignment: .topLeading) {
          if library.navigation.mounted.contains("Stack") { stack.modifier(FactoryPaneVisibility(active: active && tab == "Stack")) }
          if library.navigation.mounted.contains("Workflow") { workflow.modifier(FactoryPaneVisibility(active: active && tab == "Workflow")) }
          if library.navigation.mounted.contains("Definition") { definition.modifier(FactoryPaneVisibility(active: active && tab == "Definition")) }
        }
        HStack {
          TextField("Reason for this revision", text: $reason).textFieldStyle(.roundedBorder)
          Button("Save revision") { Task { await library.save(engine: app.engine, reason: reason) } }
            .buttonStyle(BrandButtonStyle()).disabled(!idle || library.review.isEmpty || controlsHaveChanges || reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        if controlsHaveChanges { Text("Apply or discard configuration field edits in Set up before saving or preparing a trial.").font(.caption).foregroundStyle(.secondary) }
        }.modifier(FactoryPaneVisibility(active: active && ["Stack", "Workflow", "Definition"].contains(tab)))
        }
      }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }.padding(24)
      .task(id: app.projectID + "\n" + String(active)) {
        guard active else { return }; library.enter(app.projectID)
        library.navigation.setActive(true)
        guard !app.projectID.isEmpty else { return }
        if library.text.isEmpty { await library.load(engine: app.engine) }
        await library.refresh(engine: app.engine)
      }
      .onChange(of: active) { _, value in library.navigation.setActive(value); if !value { confirmation = "" } }
      .onChange(of: string(library.review, "snapshot_digest")) { _, value in
        if !value.isEmpty, !controlsHaveChanges { syncControls() }
      }
      .onChange(of: app.projectID) { _, _ in confirmation = ""; reason = ""; goal = ""; experimentStage = ""; experimentGoal = ""; experimentTask = "" }
      .alert(confirmationTitle, isPresented: Binding(get: { !confirmation.isEmpty }, set: { if !$0 { confirmation = "" } })) {
        Button("Cancel", role: .cancel) { confirmation = "" }
        Button("Continue") { let action = confirmation; confirmation = ""; execute(action) }
      } message: { Text(confirmationMessage) }
  }

  private var stack: some View {
    HSplitView {
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          Text("Your first Factory").font(.headline)
          Text("Follow this path once, then repeat it as the workflow improves.").font(.caption).foregroundStyle(.secondary)
          let steps = ["Create a draft", "Validate & save", "Review & commit sources", "Prepare a bounded trial"]
          ForEach(steps.indices, id: \.self) { index in
            HStack(alignment: .top, spacing: 8) {
              Image(systemName: index < setup.step || (index == 3 && setup.trialPrepared) ? "checkmark.circle.fill" : "\(index + 1).circle")
                .foregroundStyle(index == setup.step ? Color.primary : Color.secondary)
              Text(steps[index]).font(.subheadline).fixedSize(horizontal: false, vertical: true)
            }.frame(maxWidth: .infinity, alignment: .leading).padding(10).brandSurface()
          }
          nativeButton("factory.setup.next", action: advanceSetup, title: setup.action) { Text(setup.action).font(.caption.weight(.semibold)) }.disabled(!idle || controlsHaveChanges)
          Text("Preparing a trial does not call models. Running stages is a separate action.").font(.caption).foregroundStyle(.secondary)
          Divider()
          Text("Inner loop").font(.subheadline.bold())
          Text("Follow the configured stages to implement changes, pause at gates, and verify results.").font(.caption).foregroundStyle(.secondary)
          Text("Outer loop").font(.subheadline.bold())
          Text("Measure failures → propose one change → compare on held-out tasks → review adoption.").font(.caption).foregroundStyle(.secondary)
          DisclosureGroup("Factory architecture") {
            ForEach(Array(layers.enumerated()), id: \.offset) { index, name in
              VStack(alignment: .leading, spacing: 3) { Text(name).font(.caption.bold()); Text(descriptions[index]).font(.caption).foregroundStyle(.secondary) }
                .padding(.vertical, 4)
            }
          }.font(.caption)
        }.padding(.trailing, 12)
      }.frame(minWidth: 200, idealWidth: 240, maxWidth: 280)
      ScrollView {
        VStack(alignment: .leading, spacing: 14) {
          Picker("Starting workflow", selection: $preset) {
            Text("Fix and verify").tag("fix-and-verify"); Text("Continuous outcomes").tag("continuous-outcomes")
          }
          FactoryActionRow {
            Button("Load starter…") { confirmation = "template" }.disabled(!idle)
            Button("Reload saved…") { confirmation = "reload" }.disabled(!idle)
          }
          Text("Describe the factory").font(.headline)
          TextEditor(text: $library.description).font(.body).frame(minHeight: 90).brandSurface()
            .accessibilityLabel("Factory description")
          Text(app.provider.isEmpty || app.model.isEmpty
            ? "Optional: select a model to generate a proposal. You can configure the starter without one."
            : "Drafting model: \(app.provider)/\(app.model)")
            .font(.caption).foregroundStyle(.secondary)
          Button("Generate proposal…") { confirmation = "generate" }
            .disabled(!idle || library.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || library.text.isEmpty || app.provider.isEmpty || app.model.isEmpty || app.provider == "acp")
          if library.canApplyProposal {
            DisclosureGroup("Generated proposal") {
              CodeBlock(text: pretty(library.proposal))
              Button("Apply proposal to draft") { library.text = string(library.proposal, "yaml"); library.proposal = [:]; library.navigation.select("Definition") }
                .disabled(!idle)
            }
          }
          Divider()
          Text("Harness, model & permissions").font(.headline)
          Text("Validate the definition to load its current bindings.").font(.caption).foregroundStyle(.secondary)
          VStack(alignment: .leading, spacing: 12) {
          TextField("Factory name", text: $factoryName).textFieldStyle(.roundedBorder)
          Picker("Harness binding", selection: $binding) {
            ForEach(bindings.keys.sorted(), id: \.self) { Text($0).tag($0) }
          }.onChange(of: binding) { _, value in modelRef = modelForBinding(value) }
          TextField("Provider/model reference", text: $modelRef).textFieldStyle(.roundedBorder)
          Stepper("Workers: \(workers)", value: $workers, in: 1...16)
          Stepper("Time budget: \(seconds) seconds", value: $seconds, in: 30...86400, step: 30)
          Toggle("Allow network for factory stages", isOn: $network)
          FactoryActionRow {
          Button("Apply controls to draft") {
            let draft = controlDraft
            Task {
              await library.edit(engine: app.engine, controls: ["name": draft.name, "binding": draft.binding,
                "model": draft.model, "max_workers": draft.workers, "max_seconds": draft.seconds, "allow_network": draft.network])
              if controlDraft == draft, library.failure.isEmpty { syncControls() }
            }
          }.disabled(!idle || library.review.isEmpty)
          Button("Discard field edits") { syncControls() }.disabled(!controlsHaveChanges)
          }
          if controlsHaveChanges { Text("Configuration fields have unapplied changes. Apply them to the draft before saving.").font(.caption).foregroundStyle(.secondary) }
          }.disabled(!idle || library.review.isEmpty)
          Divider()
          DisclosureGroup("Advanced: release signing") {
          Text("Enroll a user-presence protected Secure Enclave key on this Mac, then review and save its public key in the factory policy before preparing a trial.")
            .font(.caption).foregroundStyle(.secondary)
          Button("Enroll this Mac & add public key…") { confirmation = "enroll" }.disabled(!idle || library.text.isEmpty)
          }
          Text("Reusable skills and measured harness changes are under Improve. Proposals never activate automatically.")
            .font(.caption).foregroundStyle(.secondary)
          DisclosureGroup("Validation notes") { warnings }
        }.padding(.leading, 12)
      }.frame(minWidth: 290)
    }
  }

  private var workflow: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 14) {
        Text("Stages and dependencies").font(.headline)
        if let loop = library.review["revision_loop"] as? [String: Any], !loop.isEmpty {
          Text("Bounded revision loop").font(.subheadline)
          CodeBlock(text: pretty(loop))
        }
        if stages.isEmpty { Text("Validate a definition to preview its workflow.").foregroundStyle(.secondary) }
        ForEach(Array(stages.enumerated()), id: \.offset) { _, stage in
          VStack(alignment: .leading, spacing: 6) {
            HStack { Text(string(stage, "id")).font(.headline); Pill(title: string(stage, "role")); if stage["human_gate"] as? Bool == true { Pill(title: "Human gate", color: .orange) } }
            Text("Harness: \(string(stage, "harness")) · After: \((stage["depends_on"] as? [String] ?? []).joined(separator: ", "))")
              .font(.caption).foregroundStyle(.secondary)
            Text(string(stage, "goal")).font(.caption).textSelection(.enabled)
            if stage["inputs"] != nil || stage["outputs"] != nil {
              DisclosureGroup("Input and output contracts") { CodeBlock(text: pretty(["inputs": stage["inputs"] ?? [:], "outputs": stage["outputs"] ?? [:]])) }
            }
            if stage["when"] != nil { Text("Conditional stage: " + pretty(stage["when"])).font(.caption.monospaced()) }
          }.frame(maxWidth: .infinity, alignment: .leading).padding(14).brandSurface()
        }
        warnings
        Divider()
        Text("Whole-workflow instruction experiment").font(.headline)
        Text("Save and validate the Factory first. Select an entry, dependent or reviewer stage; only its goal changes. Inputs, outputs, branches, loops, checks and gates remain fixed. Preparing and running the exported paired suite are separate actions.").font(.caption).foregroundStyle(.secondary)
        Picker("Stage to compare", selection: $experimentStage) {
          Text("Choose a stage").tag("")
          ForEach(stages.map { string($0, "id") }, id: \.self) { Text($0).tag($0) }
        }.onChange(of: experimentStage) { _, value in experimentGoal = stages.first(where: { string($0, "id") == value }).map { string($0, "goal") } ?? "" }
        TextEditor(text: $experimentGoal).frame(minHeight: 70).brandSurface().accessibilityLabel("Proposed stage goal")
        TextField("Overall trial task", text: $experimentTask).textFieldStyle(.roundedBorder)
        Button("Export paired experiment to Trial suites") {
          let ticket = library.navigation.ticket()
          let stage = experimentStage; let goal = experimentGoal; let task = experimentTask
          Task { if await library.workflowExperiment(app.engine, stage: stage, goal: goal, workGoal: task) { follow(ticket, to: "Suites") } }
        }.disabled(!idle || experimentStage.isEmpty || experimentGoal.isEmpty || experimentTask.isEmpty || library.review.isEmpty)
        Text("Continuous outcomes prepares investigations and follow-up signals. Scheduling and deployment are separate actions.")
          .font(.caption).foregroundStyle(.secondary)
      }
    }
  }
  private var definition: some View {
    HSplitView {
      SourceEditor(text: $library.text, path: "factory.yaml", editable: !library.busy,
        documentID: "factory-studio:" + app.projectID, active: active && tab == "Definition").brandSurface().frame(minWidth: 280)
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          Text("Proposed definition diff").font(.headline)
          CodeBlock(text: string(library.review, "diff", "Validate the draft to compare it with the saved definition."))
          warnings
          if !library.review.isEmpty { DisclosureGroup("Governance & snapshot") {
            Text("Snapshot: \(string(library.review, "snapshot_digest"))").font(.caption.monospaced()).textSelection(.enabled)
            CodeBlock(text: pretty(library.review["governance"]))
          } }
        }.padding(.leading, 12)
      }.frame(minWidth: 240)
    }
  }
  private var warnings: some View {
    VStack(alignment: .leading, spacing: 6) {
      ForEach(library.review["warnings"] as? [String] ?? [], id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
    }
  }
  private var runs: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("Prepare → run stages → verify evidence → review delivery").font(.subheadline.bold())
      if !setup.saved || controlsHaveChanges {
        HStack { Text("Apply configuration fields, then validate and save the Factory before a new trial.").font(.caption).foregroundStyle(.secondary)
          Button("Open Build") { library.navigation.select("Stack") } }
      }
      HStack {
        TextField("Goal for this trial", text: $goal).textFieldStyle(.roundedBorder).accessibilityIdentifier("factory.trial.goal")
        Button("Prepare trial…") { confirmation = "trial" }
          .disabled(!idle || !setup.saved || controlsHaveChanges || goal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
      }
      Text("Preparation pins inputs without model calls. Run ready stages explicitly; release remains a separate reviewed action.")
        .font(.caption).foregroundStyle(.secondary)
    HSplitView {
      ScrollView {
        VStack(alignment: .leading, spacing: 8) {
          Button("Refresh runs") { Task { await library.refresh(engine: app.engine); await library.inspect(engine: app.engine) } }
          if library.runs.isEmpty { Text("No trials yet. Save a validated revision and prepare a trial.").font(.caption).foregroundStyle(.secondary) }
          ForEach(library.runs, id: \.description) { row in
            Button { library.run = string(row, "id"); Task { await library.inspect(engine: app.engine) } } label: {
              VStack(alignment: .leading, spacing: 5) {
                Text(string(row, "goal")).lineLimit(3); Pill(title: string(row, "status"))
                Text(String(string(row, "id").prefix(18))).font(.caption2.monospaced())
              }.frame(maxWidth: .infinity, alignment: .leading).padding(10)
                .background(library.run == string(row, "id") ? Color.qAccent.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
            }.buttonStyle(.plain)
          }
        }.padding(.trailing, 12)
      }.frame(minWidth: 210, idealWidth: 260, maxWidth: 300)
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          if !order.isEmpty {
            Text(string(order, "goal")).font(.headline); Pill(title: string(order, "status"))
            let metadata = order["metadata"] as? [String: Any] ?? [:]
            let factory = metadata["factory"] as? [String: Any] ?? [:]
            Text("Run snapshot: \(string(factory, "snapshot_digest"))").font(.caption.monospaced()).textSelection(.enabled)
            Text("Editing the draft does not change this run.").font(.caption).foregroundStyle(.secondary)
            FactoryActionRow {
              Button("Run ready stages…") { confirmation = "worker" }.disabled(!idle)
              Button("Verify candidate…") { confirmation = "verify" }.disabled(!idle)
              Button("Stop run") { confirmation = "cancel" }.disabled(library.run.isEmpty)
            }
            ForEach(tasks, id: \.description) { task in
              VStack(alignment: .leading, spacing: 6) {
                HStack { Text(string(task, "task_id")); Pill(title: string(task, "status")) }
                if string(task, "status") == "waiting_for_human" {
                  TextField("Gate decision reason", text: $gateReason).textFieldStyle(.roundedBorder)
                  HStack {
                    Button("Approve stage gate") { Task { await library.gate(engine: app.engine, task: task, decision: "approve", reason: gateReason) } }.disabled(!idle || gateReason.isEmpty)
                    Button("Hold stage") { Task { await library.gate(engine: app.engine, task: task, decision: "hold", reason: gateReason) } }.disabled(!idle || gateReason.isEmpty)
                  }
                }
              }.padding(10).brandSurface()
            }
            DisclosureGroup("Run evidence & budget") { CodeBlock(text: pretty(library.detail["cockpit"])) }
            DisclosureGroup("Protected verification receipt") { CodeBlock(text: pretty(metadata["factory_verification"])) }
            DisclosureGroup("Recorded evidence & SuperGauge") { CodeBlock(text: pretty(library.detail["evidence"])) }
            if !string(library.detail, "candidate_id").isEmpty {
              Text("Verified candidate diff").font(.headline)
              CodeBlock(text: string(library.detail, "candidate_diff"))
              if library.detail["diff_truncated"] as? Bool == true { Text("Diff exceeds the native review limit. Review the complete candidate with the CLI before approval.").foregroundStyle(.orange) }
              HStack {
                Button("Authenticate approval…") { confirmation = "approve" }
                  .disabled(!idle || library.detail["diff_truncated"] as? Bool == true || string(library.detail, "candidate_diff").isEmpty)
                Button("Apply approved change…") { confirmation = "apply" }.disabled(!idle)
              }
              Text("Delivery applies this patch to the working tree. It does not commit, push or deploy. Verification evidence remains distinct from release approval.")
                .font(.caption).foregroundStyle(.secondary)
            }
            if !library.job.isEmpty { DisclosureGroup("Latest factory action") { CodeBlock(text: pretty(library.job)) } }
          } else { Text("Select a trial to inspect its stages and evidence.").foregroundStyle(.secondary) }
        }.padding(.leading, 12)
      }.frame(minWidth: 290)
    }
    }
  }
  private func advanceSetup() {
    if !setup.hasDraft { confirmation = "template" }
    else if !setup.validated {
      let ticket = library.navigation.ticket()
      Task { await library.validate(engine: app.engine); if library.navigation.isCurrent(ticket) { syncControls(); await library.refreshSources(engine: app.engine) } }
    } else if !setup.saved { library.navigation.select("Definition") }
    else if !setup.committed { library.navigation.select("Sources") }
    else { library.navigation.select("Runs") }
  }
  private var revisions: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 12) {
        Text("Saved factory revisions").font(.headline)
        Text("Load a revision into the draft, review its diff and save it explicitly to restore it.").font(.caption).foregroundStyle(.secondary)
        ForEach(library.revisions, id: \.description) { row in
          HStack {
            Text(String(string(row, "digest").prefix(20))).font(.caption.monospaced())
            Pill(title: row["intact"] as? Bool == true ? "Intact" : "Modified", color: row["intact"] as? Bool == true ? .green : .orange)
            Spacer()
            Button("Load into draft") {
              let revision = string(row, "digest"); let ticket = library.navigation.ticket()
              Task { await library.load(engine: app.engine, revision: revision); if library.failure.isEmpty { follow(ticket, to: "Definition") } }
            }
              .disabled(!idle || row["intact"] as? Bool != true)
          }.padding(12).brandSurface()
        }
      }
    }
  }
  private func syncControls() {
    guard !library.review.isEmpty else { return }
    if !bindings.keys.contains(binding), let first = bindings.keys.sorted().first { binding = first }
    modelRef = modelForBinding(binding)
    let governance = library.review["governance"] as? [String: Any] ?? [:]
    let budget = governance["budget"] as? [String: Any] ?? [:]
    seconds = budget["max_seconds"] as? Int ?? 600; workers = budget["max_workers"] as? Int ?? 2
    network = (governance["permissions"] as? [String: Any])?["allow_network"] as? Bool ?? false
    factoryName = string(library.review, "name")
    syncedControls = controlDraft
  }
  private func modelForBinding(_ name: String) -> String {
    string(bindings[name] as? [String: Any] ?? [:], "model", (library.review["binding_models"] as? [String: String])?[name] ?? "")
  }
  private var confirmationTitle: String {
    ["template": "Load a starter?", "reload": "Reload saved definition?", "trial": "Prepare a pinned trial?",
     "generate": "Generate a factory proposal?", "worker": "Run ready factory stages?", "verify": "Execute protected verification?",
     "enroll": "Enroll this Mac as a release signer?", "approve": "Authenticate candidate approval?", "apply": "Apply the approved change?", "cancel": "Stop this factory run?"][confirmation] ?? "Review factory action"
  }
  private var confirmationMessage: String {
    switch confirmation {
    case "template", "reload": return "This replaces the current draft. Saved revisions and existing trials remain available."
    case "generate": return "The selected model receives your description and draft definition. This may incur model usage. The result is a proposal for you to review."
    case "trial": return "Pin the saved definition and its inputs to a queued WorkOrder for this goal. This step makes no model calls. The application must have a clean committed baseline."
    case "worker": return "Execute ready stages using this run’s pinned harnesses and model routes. Model calls may incur cost and stages may edit isolated worktrees. Human gates pause execution."
    case "verify": return "Execute the exact candidate in the required OS sandbox against pinned protected Python probes. Passing checks supplies acceptance evidence; it does not approve delivery."
    case "enroll": return "Create a permanent Secure Enclave signing key protected by user presence, or reuse this app’s enrolled key. Add only its public key to the draft; validate and save the policy before preparing a new trial."
    case "approve": return "Approve the exact verified candidate shown in the diff. macOS will authenticate you before signing a short-lived approval. This does not yet apply the patch."
    case "apply": return "Apply the signed, verified patch to this project’s working tree. The engine rechecks the candidate, evidence, target tree, budget and authorization."
    case "cancel": return "Cancel this run and its current Studio action. Completed evidence remains recorded."
    default: return "Review this action before continuing."
    }
  }
  private func execute(_ action: String) {
    let ticket = library.navigation.ticket()
    Task {
      guard library.project == ticket.project else { return }
      switch action {
      case "template": await library.load(engine: app.engine, template: preset)
      case "reload": await library.load(engine: app.engine)
      case "trial": await library.trial(engine: app.engine, goal: goal); if library.failure.isEmpty { follow(ticket, to: "Runs") }
      case "enroll":
        let identity = library.project; let version = library.version
        library.busy = true
        defer { if library.project == identity { library.busy = false } }
        do {
          let key = try await FactoryReleaseSigner.enroll()
          guard library.project == identity, library.version == version else { return }
          await library.edit(engine: app.engine, controls: ["public_key": key, "key_id": "this-mac"]); if library.failure.isEmpty { follow(ticket, to: "Definition") }
        } catch { if library.project == identity { library.failure = error.localizedDescription } }
      case "approve": await library.approve(engine: app.engine)
      case "cancel": await library.cancel(engine: app.engine, runOnly: true)
      default: await library.start(engine: app.engine, action: action, provider: app.provider, model: app.model)
      }
    }
  }
  private func follow(_ ticket: FactoryNavigation.Ticket, to destination: String) {
    guard app.section == "Factory Studio" else { return }
    library.navigation.follow(ticket, to: destination)
  }
}
