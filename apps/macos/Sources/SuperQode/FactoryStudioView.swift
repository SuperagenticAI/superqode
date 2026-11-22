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
  @State private var replacingDraft = false
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
  private var idle: Bool { !replacingDraft && !library.busy && !library.acceptance.busy && !library.portable.busy && !app.anyActive && !app.busy }
  private var order: [String: Any] { library.detail["work_order"] as? [String: Any] ?? [:] }
  private var stages: [[String: Any]] { library.review["stages"] as? [[String: Any]] ?? [] }
  private var tasks: [[String: Any]] { order["tasks"] as? [[String: Any]] ?? [] }
  private var bindings: [String: Any] { library.review["bindings"] as? [String: Any] ?? [:] }
  private var setup: FactorySetupState { FactorySetupState(text: library.text, review: library.review,
    savedDigest: library.expectedFileDigest, sources: library.sourceReview, runs: library.runs) }
  var body: some View {
    HStack(alignment: .top, spacing: 20) {
      FactoryNavigationHeader(navigation: library.navigation).frame(width: 172)
      Divider()
      VStack(alignment: .leading, spacing: 14) {
      HStack {
        Text(library.navigation.pageTitle).font(.title2.bold())
        Spacer()
        if FactoryNavigation.buildPages.contains(tab) {
          Button("Check definition") {
            let ticket = library.navigation.ticket()
            Task { await library.validate(engine: app.engine); if library.navigation.isCurrent(ticket), !controlsHaveChanges { syncControls() } }
          }.disabled(!idle || library.text.isEmpty)
          Button("Save changes…") { confirmation = "save" }
            .disabled(!idle || library.review.isEmpty || controlsHaveChanges || setup.saved)
        }
      }
      if !library.failure.isEmpty { Text(library.failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
      if !library.message.isEmpty { DisclosureGroup("Latest activity") { Text(library.message).font(.caption).foregroundStyle(.secondary).textSelection(.enabled) }.font(.caption) }
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
        if !library.navigation.mounted.isDisjoint(with: FactoryNavigation.improvementPages) {
          FactoryImprovementView(library: library, active: active && FactoryNavigation.improvementPages.contains(tab), onAdopt: { library.navigation.select("Definition") })
            .modifier(FactoryPaneVisibility(active: active && FactoryNavigation.improvementPages.contains(tab)))
        }
        if library.navigation.mounted.contains("Export") {
          FactoryExportView(studio: library, library: library.portable, active: active && tab == "Export")
            .modifier(FactoryPaneVisibility(active: active && tab == "Export"))
        }
        if library.navigation.mounted.contains("Sources") {
          FactorySourceControlView(library: library, active: active && tab == "Sources")
            .modifier(FactoryPaneVisibility(active: active && tab == "Sources"))
        }
        if tab == "Runs" { runs }
        if tab == "Revisions" { revisions }
        if tab == "Experiments" { ScrollView { workflowExperiment } }
        if !library.navigation.mounted.isDisjoint(with: FactoryNavigation.buildPages) {
        VStack(alignment: .leading, spacing: 12) {
        ZStack(alignment: .topLeading) {
          if library.navigation.mounted.contains("Stack") { stack.modifier(FactoryPaneVisibility(active: active && tab == "Stack")) }
          if library.navigation.mounted.contains("Configuration") { configuration.modifier(FactoryPaneVisibility(active: active && tab == "Configuration")) }
          if library.navigation.mounted.contains("Workflow") { workflow.modifier(FactoryPaneVisibility(active: active && tab == "Workflow")) }
          if library.navigation.mounted.contains("Acceptance") { ScrollView { FactoryAcceptanceSetupView(studio: library, library: library.acceptance, active: active && tab == "Acceptance") }.modifier(FactoryPaneVisibility(active: active && tab == "Acceptance")) }
          if library.navigation.mounted.contains("Definition") { definition.modifier(FactoryPaneVisibility(active: active && tab == "Definition")) }
        }
        if controlsHaveChanges { HStack { Text("Configuration has unapplied edits.").font(.caption).foregroundStyle(.orange); Button("Review configuration") { library.navigation.select("Configuration") } } }
        }.modifier(FactoryPaneVisibility(active: active && FactoryNavigation.buildPages.contains(tab)))
        }
      }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
      }
    }.padding(20)
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
        if confirmation == "save" { TextField("What changed?", text: $reason) }
        Button("Cancel", role: .cancel) { confirmation = "" }
        Button("Continue") { let action = confirmation; confirmation = ""; execute(action) }
          .disabled(confirmation == "save" && reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
      } message: { Text(confirmationMessage) }
  }

  private var stack: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        Text("What should this Factory do?").font(.headline)
        TextEditor(text: $library.description).font(.body).frame(height: 140).brandSurface().accessibilityLabel("Factory description")
        HStack {
          Text(app.provider.isEmpty || app.model.isEmpty ? "Choose a model for AI-assisted drafting." : "Drafting with \(app.provider)/\(app.model)").font(.caption).foregroundStyle(.secondary)
          Spacer()
          Button("Choose model…") { app.showConnection = true }
        }
        Button("Generate a draft…") { confirmation = "generate" }.buttonStyle(BrandButtonStyle())
          .disabled(!idle || library.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || app.provider.isEmpty || app.model.isEmpty || app.provider == "acp")
        if library.canApplyProposal {
          VStack(alignment: .leading, spacing: 10) {
            Text("A proposal is ready to review.").font(.subheadline.bold())
            ForEach(library.proposal["assumptions"] as? [String] ?? [], id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
            Button("Open proposal in editor") { library.text = string(library.proposal, "yaml"); library.proposal = [:]; library.navigation.select("Definition") }
          }.padding(14).brandSurface()
        }
        Divider()
        Text("Or start from a workflow").font(.subheadline.bold())
        Picker("Workflow", selection: $preset) { Text("Fix and verify").tag("fix-and-verify"); Text("Continuous outcomes").tag("continuous-outcomes") }
        FactoryActionRow {
          Button("Use this starter…") { confirmation = "template" }.disabled(!idle)
          Button("Reload saved…") { confirmation = "reload" }.disabled(!idle)
        }
        Divider()
        HStack {
          Text(setup.hasDraft ? "Your draft is available in the pages on the left." : "Load a starter first to establish the drafting permissions and budget.").font(.caption).foregroundStyle(.secondary)
          Spacer()
          nativeButton("factory.setup.next", action: advanceSetup, title: setup.action) { Text(setup.action).font(.caption.weight(.semibold)) }.disabled(!idle || (controlsHaveChanges && setup.hasDraft))
        }
      }.frame(maxWidth: 680, alignment: .leading).frame(maxWidth: .infinity, alignment: .leading)
    }
  }
  private var configuration: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 14) {
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

      }.frame(maxWidth: 680, alignment: .leading).frame(maxWidth: .infinity, alignment: .leading)
    }
  }

  private var workflow: some View {
    ScrollViewReader { proxy in
    ScrollView {
      VStack(alignment: .leading, spacing: 14) {
        HStack {
          Text("Stages and dependencies").font(.headline); Spacer()
          nativeButton("factory.workflow.acceptance", action: { library.navigation.select("Acceptance") }, title: "Acceptance & verification") { Text("Acceptance & verification").font(.caption) }
        }
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

      }
    }
    }
  }
  private var workflowExperiment: some View {
    VStack(alignment: .leading, spacing: 14) {
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
  private var definition: some View {
    HSplitView {
      SourceEditor(text: $library.text, path: "factory.yaml", editable: !library.busy && !replacingDraft,
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
      ScrollViewReader { proxy in
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
              nativeButton("factory.run.coverage", action: { proxy.scrollTo("factory.requirements", anchor: .top) }, title: "Requirement coverage") { Text("Requirement coverage") }
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
            FactoryRequirementTraceView(studio: library, library: library.acceptance, active: active && tab == "Runs")
              .id("factory.requirements")
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
    ["save": "Save this Factory revision?", "template": "Load a starter?", "reload": "Reload saved definition?", "trial": "Prepare a pinned trial?",
     "generate": "Generate a factory proposal?", "worker": "Run ready factory stages?", "verify": "Execute protected verification?",
     "enroll": "Enroll this Mac as a release signer?", "approve": "Authenticate candidate approval?", "apply": "Apply the approved change?", "cancel": "Stop this factory run?"][confirmation] ?? "Review factory action"
  }
  private var confirmationMessage: String {
    switch confirmation {
    case "save": return "Save the checked definition and record the reason for this revision. Existing runs keep their pinned inputs."
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
      case "save": await library.save(engine: app.engine, reason: reason)
      case "template", "reload":
        replacingDraft = true; defer { replacingDraft = false }
        await library.load(engine: app.engine, template: action == "template" ? preset : "")
        await library.validate(engine: app.engine)
        if library.project == ticket.project, !library.review.isEmpty { syncControls() }
      case "generate":
        if library.text.isEmpty { await library.load(engine: app.engine, template: preset) }
        guard library.navigation.isCurrent(ticket), !library.text.isEmpty else { return }
        await library.start(engine: app.engine, action: action, provider: app.provider, model: app.model)
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
