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
  @State private var activeAction = ""
  @State private var replacingDraft = false
  @State private var factoryName = ""
  @State private var binding = "core"
  @State private var modelRef = "ollama/qwen3:8b"
  @State private var seconds = 600
  @State private var workers = 2
  @State private var network = false
  @State private var syncedControls: FactoryControlDraft?
  @State private var runDetailTab = ProcessInfo.processInfo.arguments.contains("--factory-acceptance-inspect") ? "checks" : "pipeline"
  @State private var showTour = false
  @State private var uiSkillPreset = "web"
  @State private var appliedRLMSnapshot: FactoryRLMLineageSnapshot?
  @AppStorage("factoryShowNextStepGuide") private var showNextStepGuide = true
  private static let inlineConfirmActions: Set<String> = ["generate", "rlm-architect", "template", "reload", "save", "trial"]
  private var showingInlineConfirm: Bool { Self.inlineConfirmActions.contains(confirmation) }
  private var showingSheetConfirm: Bool { !confirmation.isEmpty && !showingInlineConfirm }
  private var controlDraft: FactoryControlDraft { FactoryControlDraft(name: factoryName, binding: binding,
    model: modelRef, seconds: seconds, workers: workers, network: network) }
  private var controlsHaveChanges: Bool { syncedControls.map { $0 != controlDraft } ?? false }
  private var idle: Bool { !replacingDraft && !library.busy && !library.acceptance.busy && !library.portable.busy && !app.anyActive && !app.busy }
  private var order: [String: Any] { library.detail["work_order"] as? [String: Any] ?? [:] }
  private var stages: [[String: Any]] { library.review["stages"] as? [[String: Any]] ?? [] }
  private var tasks: [[String: Any]] { order["tasks"] as? [[String: Any]] ?? [] }
  private var bindings: [String: Any] { library.review["bindings"] as? [String: Any] ?? [:] }
  private var setup: FactorySetupState {
    FactorySetupState(
      text: library.text,
      review: library.review,
      savedDigest: library.expectedFileDigest,
      sources: library.sourceReview,
      runs: library.runs,
      hasSuite: !library.trialSuites.plans.isEmpty,
      hasImprovement: !library.improvementPlans.isEmpty
    )
  }
  private var sidebarBadges: FactorySidebarBadges {
    FactorySidebarBadges(
      isRunning: library.isAnyRunActive,
      pendingGates: library.pendingGateCount,
      readyToShip: library.readyToShipCandidate,
      hasUnappliedControls: controlsHaveChanges,
      hasUnsavedDraft: setup.hasDraft && !setup.saved
    )
  }
  var body: some View {
    HStack(alignment: .top, spacing: 20) {
      FactoryNavigationHeader(navigation: library.navigation, badges: sidebarBadges).frame(width: 178)
      Divider()
      VStack(alignment: .leading, spacing: 14) {
      headerBar
      if showNextStepGuide {
        FactoryNextStepStrip(
          setup: setup,
          controlsHaveChanges: controlsHaveChanges,
          idle: idle,
          onPrimaryAction: advanceGuidedStep,
          onOpenTour: { showTour = true },
          onHide: { showNextStepGuide = false }
        )
      }
      if showingInlineConfirm {
        FactoryInlineConfirmCard(
          title: confirmationTitle,
          message: confirmationMessage,
          kind: confirmationKind,
          workflowID: confirmation == "template" ? preset : nil,
          badges: confirmationBadges,
          confirmTitle: confirmationActionTitle,
          confirmDisabled: confirmation == "save" && reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
          inputLabel: confirmation == "save" ? "What changed?" : nil,
          inputText: confirmation == "save" ? $reason : nil,
          onCancel: { dismissConfirmation() },
          onConfirm: {
            let action = confirmation
            dismissConfirmation()
            execute(action)
          }
        )
        .id(confirmation + ":" + preset)
      }
      if !library.failure.isEmpty {
        FactoryNoticeBanner(text: library.failure, isFailure: true)
      }
      if !library.message.isEmpty && !library.busy {
        FactoryNoticeBanner(text: library.message, isFailure: false)
      }
      if library.busy || replacingDraft {
        FactoryActivityBanner(
          title: activityTitle,
          detail: activityDetail,
          kind: activityKind,
          stopTitle: "Stop action",
          onStop: library.busy ? { Task { await library.cancel(engine: app.engine) } } : nil
        )
        .transition(.opacity.combined(with: .scale(scale: 0.98)))
      }
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
      .onChange(of: app.projectID) { _, _ in confirmation = ""; activeAction = ""; reason = ""; goal = ""; experimentStage = ""; experimentGoal = ""; experimentTask = "" }
      .factoryConfirmation(
        isPresented: Binding(get: { showingSheetConfirm }, set: { if !$0 { dismissConfirmation() } }),
        title: confirmationTitle,
        message: confirmationMessage,
        kind: confirmationKind,
        badges: confirmationBadges,
        confirmTitle: confirmationActionTitle,
        onCancel: { dismissConfirmation() },
        onConfirm: {
          let action = confirmation
          dismissConfirmation()
          execute(action)
        }
      )
      .sheet(isPresented: $showTour) {
        FactoryTourSheet(
          onJumpToPage: { destination in library.navigation.select(destination) },
          onStartStarter: { workflowID in
            library.navigation.select("Stack")
            chooseWorkflow(workflowID)
          }
        )
      }
  }

  private var headerBar: some View {
    HStack(spacing: 10) {
      FactoryGroupMark(id: library.navigation.group.id, selected: true, size: 26)
      Text(library.navigation.pageTitle).font(.title2.bold())
      Spacer()
      if FactoryNavigation.buildPages.contains(tab) {
        Button("Check definition") {
          let ticket = library.navigation.ticket()
          activeAction = "validate"
          Task {
            defer { if activeAction == "validate" { activeAction = "" } }
            await library.validate(engine: app.engine)
            if library.navigation.isCurrent(ticket), !controlsHaveChanges { syncControls() }
          }
        }.disabled(!idle || library.text.isEmpty)
        Button("Save changes…") { requestConfirmation("save") }
          .disabled(!idle || library.review.isEmpty || controlsHaveChanges || setup.saved)
      }
      Button { showTour = true } label: {
        Label("Tour", systemImage: "book.pages")
      }
      .help("Walk through how to build a Software Factory before running anything")
      .accessibilityIdentifier("factory.tour.open")
      Button { showNextStepGuide.toggle() } label: {
        Label(showNextStepGuide ? "Guide" : "Show guide", systemImage: showNextStepGuide ? "checklist.checked" : "checklist")
      }
      .help(showNextStepGuide ? "Hide the Next-Step progress strip" : "Show the Next-Step progress strip")
      .accessibilityIdentifier("factory.guide.toggle")
      FactorySoundToggleButton()
    }
  }

  private var stack: some View {
    ScrollViewReader { proxy in
      ScrollView {
        VStack(alignment: .leading, spacing: 18) {
          if library.canApplyProposal {
            Group {
              if let rlmSnapshot = FactoryRLMLineageSnapshot.parse(proposal: library.proposal) {
                FactoryRLMProposalCard(
                  snapshot: rlmSnapshot,
                  assumptions: library.proposal["assumptions"] as? [String] ?? [],
                  missingCapabilities: library.proposal["missing_capabilities"] as? [String] ?? [],
                  busy: !idle,
                  onApply: { chosenSkills in applyRLMProposal(snapshot: rlmSnapshot, skills: chosenSkills) },
                  onApplyYamlOnly: { applyRLMProposal(snapshot: rlmSnapshot, skills: []) },
                  onDismiss: { library.proposal = [:] }
                )
              } else {
                VStack(alignment: .leading, spacing: 10) {
                  Text("A proposal is ready to review.").font(.subheadline.bold())
                  ForEach(library.proposal["assumptions"] as? [String] ?? [], id: \.self) { Text($0).font(.caption).foregroundStyle(.secondary) }
                  Button("Open proposal in editor") { library.text = string(library.proposal, "yaml"); library.proposal = [:]; library.navigation.select("Definition") }
                }.padding(14).brandSurface()
              }
            }
            .id("factory-proposal-top")
          }
          HStack(spacing: 8) {
            FactoryStudioEmblem(size: 22)
            Text("What should this Factory do?").font(.headline)
          }
          TextEditor(text: $library.description).font(.body).frame(height: 120).brandSurface().accessibilityLabel("Factory description")
          HStack {
            Text(app.provider.isEmpty || app.model.isEmpty || app.provider == "acp" ? "Generate starter settings from this description. No model is required." : "Drafting with \(app.provider)/\(app.model). If that model cannot draft, starter settings are built here.").font(.caption).foregroundStyle(.secondary)
            Spacer()
            Button("Choose harness and model…") { app.openConnections(returningTo: "Factory Studio") }
          }
          VStack(alignment: .leading, spacing: 6) {
            HStack(spacing: 10) {
              Button { requestConfirmation("rlm-architect") } label: {
                Label("Build On-Demand Software Factory…", systemImage: "sparkles")
              }
              .buttonStyle(BrandButtonStyle())
              .disabled(!idle)
              .help("Inspect this repository and your goal using Recursive Language Models (RLM) to assemble the right stages, agents, checks, and skills automatically")
              .accessibilityIdentifier("factory.rlm.architect")

              Button("Generate a draft…") { requestConfirmation("generate") }
                .disabled(!idle || library.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            Text("Powered by Recursive Language Models (RLM): inspects your repository and task read-only, selects the right stages, agent roles, test checks, and skills, and drafts a reviewable factory.yaml before anything runs.")
              .font(.caption)
              .foregroundStyle(.secondary)
              .fixedSize(horizontal: false, vertical: true)
          }
          Divider()
          Text("Start from a workflow").font(.subheadline.bold())
          Text("Click a card to load its settings. A model is not required.").font(.caption).foregroundStyle(.secondary)
          workflowGrid
          Button("Reload saved…") { requestConfirmation("reload") }.disabled(!idle)
          Divider()
          HStack {
            Text(setup.hasDraft ? "Your draft is available in the pages on the left." : "Load a starter first to establish the drafting permissions and budget.").font(.caption).foregroundStyle(.secondary)
            Spacer()
            nativeButton("factory.setup.next", action: advanceSetup, title: setup.action) { Text(setup.action).font(.caption.weight(.semibold)) }.disabled(!idle || (controlsHaveChanges && setup.hasDraft))
          }
        }.frame(maxWidth: .infinity, alignment: .leading)
      }
      .onChange(of: library.canApplyProposal) { _, ready in
        if ready {
          withAnimation(.easeInOut(duration: 0.25)) {
            proxy.scrollTo("factory-proposal-top", anchor: .top)
          }
        }
      }
    }
  }

  private struct WorkflowCard: Identifiable {
    let id: String
    let title: String
    let detail: String
    var badge: String = ""
  }

  private static let workflowCards: [WorkflowCard] = [
    WorkflowCard(id: "fix-and-verify", title: "Fix and verify", detail: "Investigate a problem, make a small fix, and check it.", badge: "Start here"),
    WorkflowCard(id: "triage-spec-build", title: "Triage, spec & build", detail: "Triage ambiguity, gate features on a human-approved spec, build, and verify.", badge: "Two gates"),
    WorkflowCard(id: "continuous-outcomes", title: "Continuous outcomes", detail: "Deliver a change and keep the feedback."),
    WorkflowCard(id: "build-test-deploy", title: "Build, test, deploy", detail: "Build the change, test it, and wait before release."),
    WorkflowCard(id: "kanban", title: "Kanban", detail: "Move one item from selection to a reviewed finish."),
    WorkflowCard(id: "scrum", title: "Scrum", detail: "Refine, build, review, then note the next improvement."),
    WorkflowCard(id: "xp", title: "XP", detail: "Name the story, write the check, then implement it."),
    WorkflowCard(id: "lean", title: "Lean", detail: "Name the value, build only that, then improve the flow."),
  ]

  private var workflowGrid: some View {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 220), spacing: 8)], spacing: 8) {
      ForEach(Self.workflowCards) { card in
        Button { chooseWorkflow(card.id) } label: {
          ConnectionCardLabel(title: card.title, subtitle: card.detail, status: card.badge) {
            FactoryWorkflowMark(id: card.id).frame(width: 36, height: 36)
          }
        }
        .buttonStyle(ConnectionChoiceStyle(selected: preset == card.id))
        .disabled(!idle)
        .accessibilityIdentifier("factory.workflow." + card.id)
        .accessibilityLabel(card.title + ". " + card.detail)
      }
    }
  }

  private func chooseWorkflow(_ id: String) {
    guard idle else { return }
    preset = id
    if library.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      execute("template")
    } else {
      requestConfirmation("template")
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
          HStack(spacing: 8) {
            TextField("Provider/model reference", text: $modelRef).textFieldStyle(.roundedBorder)
            if !app.provider.isEmpty && !app.model.isEmpty && app.provider != "acp" {
              Button("Use \(app.provider)/\(app.model)") {
                modelRef = "\(app.provider)/\(app.model)"
              }
              .font(.caption)
              .help("Fill from your currently connected SuperQode workspace model")
            }
          }
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
          DisclosureGroup("Built-in Factory skills (Merge Risk & UI Verification)") {
            VStack(alignment: .leading, spacing: 10) {
              Text("Scaffold reusable Markdown skills under skills/ and bind them to your factory draft so agents self-mitigate merge risk and record visual proof.")
                .font(.caption).foregroundStyle(.secondary)
              HStack(spacing: 8) {
                Button {
                  Task { await library.scaffoldSkill(engine: app.engine, skill: "merge-risk") }
                } label: {
                  Label("Add merge-risk skill", systemImage: "shield.checkered")
                }
                .disabled(!idle)
                Picker("UI target", selection: $uiSkillPreset) {
                  Text("Web / Playwright").tag("web")
                  Text("macOS App").tag("macos")
                  Text("CLI / Terminal").tag("cli")
                }
                .labelsHidden()
                .frame(width: 150)
                Button {
                  let chosen = uiSkillPreset
                  Task { await library.scaffoldSkill(engine: app.engine, skill: "ui-verification", preset: chosen) }
                } label: {
                  Label("Add ui-verification skill", systemImage: "photo.on.rectangle.angled")
                }
                .disabled(!idle)
              }
            }
            .padding(.top, 6)
          }
          Divider()
          DisclosureGroup("Advanced: release signing") {
          Text("Enroll a user-presence protected Secure Enclave key on this Mac, then review and save its public key in the factory policy before preparing a trial.")
            .font(.caption).foregroundStyle(.secondary)
          Button { requestConfirmation("enroll") } label: {
            Label("Enroll this Mac & add public key…", systemImage: "touchid")
          }.disabled(!idle || library.text.isEmpty)
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
        VStack(alignment: .leading, spacing: 0) {
          ForEach(Array(stages.enumerated()), id: \.offset) { index, stage in
            let deps = stage["depends_on"] as? [String] ?? []
            let gated = stage["human_gate"] as? Bool == true
            VStack(alignment: .leading, spacing: 8) {
              HStack(spacing: 8) {
                Text("\(index + 1)")
                  .font(.caption2.weight(.bold).monospacedDigit())
                  .foregroundStyle(.white)
                  .frame(width: 20, height: 20)
                  .background(gated ? Color.orange : Brand.purple, in: Circle())
                Text(string(stage, "id")).font(.headline)
                Pill(title: string(stage, "role"))
                if gated {
                  Label("Human gate", systemImage: "lock.fill")
                    .font(.caption2.weight(.semibold))
                    .foregroundStyle(.orange)
                    .padding(.horizontal, 8)
                    .padding(.vertical, 3)
                    .background(Color.orange.opacity(0.14), in: Capsule())
                }
                Spacer(minLength: 4)
                Label(string(stage, "harness"), systemImage: "cpu")
                  .font(.caption2.monospaced())
                  .foregroundStyle(.secondary)
                  .padding(.horizontal, 7)
                  .padding(.vertical, 3)
                  .background(Color.primary.opacity(0.05), in: Capsule())
              }
              if !deps.isEmpty {
                Label("After: " + deps.joined(separator: ", "), systemImage: "arrow.turn.down.right")
                  .font(.caption)
                  .foregroundStyle(.secondary)
              }
              Text(string(stage, "goal")).font(.caption).textSelection(.enabled)
              if stage["inputs"] != nil || stage["outputs"] != nil {
                DisclosureGroup("Input and output contracts") { CodeBlock(text: pretty(["inputs": stage["inputs"] ?? [:], "outputs": stage["outputs"] ?? [:]])) }
              }
              if let when = stage["when"] as? [String: Any] {
                let input = string(when, "input")
                let field = string(when, "field")
                let eq = when["equals"].map { String(describing: $0) } ?? ""
                let target = field.isEmpty ? input : "\(input).\(field)"
                Label("Conditional: runs when \(target) = \(eq)", systemImage: "arrow.triangle.branch")
                  .font(.caption.monospaced())
                  .foregroundStyle(Brand.purple)
                  .padding(.horizontal, 8)
                  .padding(.vertical, 3)
                  .background(Brand.purple.opacity(0.09), in: Capsule())
              }
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(14)
            .brandSurface()
            .overlay(
              RoundedRectangle(cornerRadius: 14, style: .continuous)
                .strokeBorder(gated ? Color.orange.opacity(0.32) : Color.clear, lineWidth: 1)
                .allowsHitTesting(false)
            )

            if index < stages.count - 1 {
              HStack {
                VStack(spacing: 0) {
                  Rectangle().fill(Brand.purple.opacity(0.35)).frame(width: 2, height: 12)
                  Image(systemName: "chevron.down")
                    .font(.system(size: 9, weight: .bold))
                    .foregroundStyle(Brand.purple.opacity(0.65))
                }
                .padding(.leading, 22)
                Spacer()
              }
              .padding(.vertical, 2)
            }
          }
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
    VStack(alignment: .leading, spacing: 10) {
      definitionGuide
      if let snapshot = appliedRLMSnapshot {
        FactoryOnDemandSummaryBanner(
          snapshot: snapshot,
          onViewStages: { library.navigation.select("Workflow") },
          onEditConfig: { library.navigation.select("Configuration") },
          onDismiss: { appliedRLMSnapshot = nil }
        )
      }
      definitionEditor
    }
  }

  private var definitionGuide: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack(spacing: 12) {
        Button { library.navigation.select("Stack") } label: {
          Label("Back to workflows", systemImage: "chevron.left")
        }
        .accessibilityIdentifier("factory.definition.back")
        Spacer(minLength: 8)
        Button(definitionNextTitle) { continueFromDefinition() }
          .buttonStyle(BrandButtonStyle())
          .disabled(!idle || library.text.isEmpty)
          .accessibilityIdentifier("factory.definition.next")
      }
      Text(definitionNextDetail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }
  }

  private var definitionNextTitle: String {
    if controlsHaveChanges { return "Review configuration" }
    if !setup.validated { return "Check definition" }
    if !setup.saved { return "Save this revision…" }
    if !setup.committed { return "Review source changes" }
    return setup.trialPrepared ? "Open the trial" : "Prepare a trial"
  }

  private var definitionNextDetail: String {
    if controlsHaveChanges { return "Apply the configuration edits, then come back and check this definition." }
    if !setup.validated { return "This is a draft. Read it, then check it. Nothing runs until you save and start a trial." }
    if !setup.saved { return "The check matches this draft. Save the revision when it looks right." }
    if !setup.committed { return "The revision is saved. Review the source changes before a trial." }
    if !setup.trialPrepared { return "Sources are ready. Prepare a trial when you want this factory to run." }
    return "A trial is already prepared. Open it when you want to run the stages."
  }

  private func continueFromDefinition() {
    if controlsHaveChanges {
      library.navigation.select("Configuration")
    } else if !setup.validated {
      let ticket = library.navigation.ticket()
      Task {
        await library.validate(engine: app.engine)
        if library.navigation.isCurrent(ticket), !controlsHaveChanges { syncControls() }
      }
    } else if !setup.saved {
      requestConfirmation("save")
    } else if !setup.committed {
      library.navigation.select("Sources")
    } else {
      library.navigation.select("Runs")
    }
  }

  private var definitionEditor: some View {
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
      runComposerBar
      HSplitView {
        runListPane
          .frame(minWidth: 220, idealWidth: 264, maxWidth: 310)
        ScrollViewReader { proxy in
          ScrollView {
            runDetailContent(proxy: proxy)
              .padding(.leading, 14)
          }
          .frame(minWidth: 320)
        }
      }
    }
  }

  private var runComposerBar: some View {
    VStack(alignment: .leading, spacing: 8) {
      if !setup.saved || controlsHaveChanges {
        HStack(spacing: 8) {
          Image(systemName: "info.circle.fill").foregroundStyle(Brand.orange)
          Text("Save your Factory definition before starting a new trial.")
            .font(.caption).foregroundStyle(.secondary)
          Spacer()
          Button("Open Build") { library.navigation.select("Stack") }
            .controlSize(.small)
        }
        .padding(.horizontal, 12)
        .padding(.vertical, 8)
        .background(Brand.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
      }
      HStack(spacing: 8) {
        TextField("Describe the goal for a new trial…", text: $goal)
          .textFieldStyle(.roundedBorder)
          .accessibilityIdentifier("factory.trial.goal")
        Button("Prepare trial…") { requestConfirmation("trial") }
          .buttonStyle(BrandButtonStyle())
          .disabled(!idle || !setup.saved || controlsHaveChanges || goal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
      }
      if library.runs.isEmpty {
        HStack(spacing: 6) {
          Text("Try a starter goal:").font(.caption2).foregroundStyle(.secondary)
          ForEach([
            "Audit tests and fix one failing check",
            "Review a core module and propose one focused cleanup",
            "Add regression unit tests for a recent change",
          ], id: \.self) { sample in
            Button(sample) { goal = sample }
              .buttonStyle(.bordered)
              .controlSize(.mini)
          }
        }
      }
    }
  }

  private var runListPane: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 8) {
        HStack {
          Text("Trials")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
          if !library.runs.isEmpty {
            Text("\(library.runs.count)")
              .font(.caption2.weight(.semibold).monospacedDigit())
              .foregroundStyle(.secondary)
              .padding(.horizontal, 6)
              .padding(.vertical, 1.5)
              .background(Color.primary.opacity(0.06), in: Capsule())
          }
          Spacer()
          Button {
            Task { await library.refresh(engine: app.engine); await library.inspect(engine: app.engine) }
          } label: {
            Image(systemName: "arrow.clockwise")
              .font(.system(size: 11, weight: .semibold))
          }
          .buttonStyle(.plain)
          .help("Refresh runs")
          .accessibilityLabel("Refresh runs")
        }
        .padding(.horizontal, 2)
        if library.runs.isEmpty {
          VStack(alignment: .leading, spacing: 6) {
            Text("No trials yet")
              .font(.subheadline.weight(.medium))
            Text("Enter a goal above to pin a new trial without making model calls.")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
          .padding(12)
          .frame(maxWidth: .infinity, alignment: .leading)
          .brandSurface(radius: 10)
        }
        ForEach(library.runs, id: \.description) { row in
          let rowID = string(row, "id")
          let isSelected = library.run == rowID
          Button {
            library.run = rowID
            Task { await library.inspect(engine: app.engine) }
          } label: {
            FactoryRunListCard(
              row: row,
              selected: isSelected,
              activeRunBusy: isSelected && library.busy && (activeAction == "worker" || activeAction == "verify")
            )
          }
          .buttonStyle(.plain)
        }
      }
      .padding(.trailing, 12)
    }
  }

  @ViewBuilder
  private func runDetailContent(proxy: ScrollViewProxy) -> some View {
    if order.isEmpty {
      VStack(spacing: 10) {
        FactoryStudioEmblem(size: 38)
        Text("Select a trial to inspect its pipeline")
          .font(.headline)
        Text("Track stage progress, SuperGauge checks, diffs and delivery approvals here.")
          .font(.caption)
          .foregroundStyle(.secondary)
      }
      .frame(maxWidth: .infinity)
      .padding(.vertical, 48)
    } else {
      let metadata = order["metadata"] as? [String: Any] ?? [:]
      let factory = metadata["factory"] as? [String: Any] ?? [:]
      let gaugeSnapshot = SuperGaugeSnapshot.parse(detail: library.detail)
      let orderStatus = FactoryStatus(raw: string(order, "status"))
      let candidateID = string(library.detail, "candidate_id")
      let doneCount = tasks.filter { FactoryStatus(raw: string($0, "status")).isComplete }.count

      VStack(alignment: .leading, spacing: 14) {
        HStack(alignment: .top, spacing: 10) {
          VStack(alignment: .leading, spacing: 5) {
            Text(string(order, "goal"))
              .font(.headline)
              .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 6) {
              FactoryStatusBadge(status: orderStatus)
              if !tasks.isEmpty {
                Text("\(doneCount)/\(tasks.count) stages")
                  .font(.caption2.weight(.semibold).monospacedDigit())
                  .foregroundStyle(.secondary)
                  .padding(.horizontal, 7)
                  .padding(.vertical, 3.5)
                  .background(Color.primary.opacity(0.05), in: Capsule())
              }
              if gaugeSnapshot.hasRecord {
                SuperGaugeBadge(verdict: gaugeSnapshot.verdict, showWordmark: false)
              }
              if let mergeRisk = FactoryMergeRiskSnapshot.parse(detail: library.detail) {
                FactoryMergeRiskBadge(level: mergeRisk.overall)
              }
            }
          }
          Spacer(minLength: 6)
        }

        FactoryPipelineStepper(
          orderStatus: orderStatus,
          tasks: tasks,
          gaugeVerdict: gaugeSnapshot.verdict,
          hasCandidate: !candidateID.isEmpty,
          isBusy: library.busy,
          activeAction: activeAction
        )

        runActionBar(
          proxy: proxy,
          orderStatus: orderStatus,
          gaugeSnapshot: gaugeSnapshot,
          hasCandidate: !candidateID.isEmpty,
          allStagesDone: !tasks.isEmpty && doneCount == tasks.count
        )

        Picker("Run detail view", selection: $runDetailTab) {
          Text("Pipeline").tag("pipeline")
          Text("Changes & Checks").tag("checks")
          Text("Diagnostics").tag("diagnostics")
        }
        .pickerStyle(.segmented)
        .labelsHidden()
        .frame(maxWidth: 360)

        if runDetailTab == "pipeline" {
          runPipelinePane(gaugeSnapshot: gaugeSnapshot)
        } else if runDetailTab == "checks" {
          runChecksAndDiffPane(candidateID: candidateID)
        } else {
          runDiagnosticsPane(factory: factory, metadata: metadata)
        }
      }
    }
  }

  private func runActionBar(
    proxy: ScrollViewProxy,
    orderStatus: FactoryStatus,
    gaugeSnapshot: SuperGaugeSnapshot,
    hasCandidate: Bool,
    allStagesDone: Bool
  ) -> some View {
    let stagePhasePrimary = !allStagesDone && orderStatus != .shipped
    let verifyPhasePrimary = allStagesDone && gaugeSnapshot.verdict != .ship && orderStatus != .shipped
    let approvePhasePrimary = gaugeSnapshot.verdict == .ship && hasCandidate && orderStatus != .shipped

    return FactoryActionRow {
      if stagePhasePrimary {
        Button("Run ready stages…") { requestConfirmation("worker") }
          .buttonStyle(BrandButtonStyle())
          .disabled(!idle)
      } else {
        Button("Run ready stages…") { requestConfirmation("worker") }
          .disabled(!idle)
      }

      if verifyPhasePrimary {
        Button { requestConfirmation("verify") } label: {
          HStack(spacing: 5) {
            SuperGaugeMark(verdict: gaugeSnapshot.verdict, size: 15, animating: false)
            Text("Verify candidate…")
          }
        }
        .buttonStyle(BrandButtonStyle())
        .disabled(!idle)
      } else {
        Button { requestConfirmation("verify") } label: {
          HStack(spacing: 5) {
            SuperGaugeMark(verdict: gaugeSnapshot.verdict, size: 15, animating: false)
            Text("Verify candidate…")
          }
        }
        .disabled(!idle)
      }

      if approvePhasePrimary {
        Button { requestConfirmation("approve") } label: {
          Label("Authenticate approval…", systemImage: "touchid")
        }
        .buttonStyle(BrandButtonStyle())
        .disabled(!idle || library.detail["diff_truncated"] as? Bool == true || string(library.detail, "candidate_diff").isEmpty)
      }

      Button("Stop run") { requestConfirmation("cancel") }
        .disabled(library.run.isEmpty)

      nativeButton("factory.run.coverage", action: {
        runDetailTab = "checks"
        Task { @MainActor in
          proxy.scrollTo("factory.requirements", anchor: .top)
        }
      }, title: "Requirement coverage") {
        Text("Requirement coverage")
      }
    }
  }

  private func runPipelinePane(gaugeSnapshot: SuperGaugeSnapshot) -> some View {
    VStack(alignment: .leading, spacing: 12) {
      if tasks.isEmpty {
        Text("No stage tasks recorded for this trial yet.")
          .font(.caption)
          .foregroundStyle(.secondary)
          .padding(12)
          .frame(maxWidth: .infinity, alignment: .leading)
          .brandSurface(radius: 10)
      } else {
        VStack(alignment: .leading, spacing: 0) {
          ForEach(Array(tasks.enumerated()), id: \.offset) { index, task in
            let currentStatus = FactoryStatus(raw: string(task, "status"))
            FactoryStageRowCard(
              index: index,
              task: task,
              idle: idle,
              gateReason: $gateReason,
              onApprove: {
                let reasonText = gateReason
                Task { await library.gate(engine: app.engine, task: task, decision: "approve", reason: reasonText) }
              },
              onHold: {
                let reasonText = gateReason
                Task { await library.gate(engine: app.engine, task: task, decision: "hold", reason: reasonText) }
              }
            )
            if index < tasks.count - 1 {
              HStack {
                VStack(spacing: 0) {
                  Rectangle()
                    .fill(currentStatus.isComplete ? Color(red: 0.14, green: 0.64, blue: 0.42).opacity(0.55) : Color.primary.opacity(0.16))
                    .frame(width: 2, height: 10)
                  Image(systemName: "chevron.down")
                    .font(.system(size: 8.5, weight: .bold))
                    .foregroundStyle(currentStatus.isComplete ? Color(red: 0.14, green: 0.64, blue: 0.42).opacity(0.75) : Color.secondary.opacity(0.55))
                }
                .padding(.leading, 24)
                Spacer()
              }
              .padding(.vertical, 2)
            }
          }
        }
      }

      SuperGaugeVerdictCard(
        snapshot: gaugeSnapshot,
        isVerifying: library.busy && activeAction == "verify",
        rawEvidence: library.detail["evidence"],
        mergeRisk: FactoryMergeRiskSnapshot.parse(detail: library.detail)
      )
    }
  }

  private func runChecksAndDiffPane(candidateID: String) -> some View {
    VStack(alignment: .leading, spacing: 12) {
      FactoryVisualProofView(detail: library.detail)

      FactoryRequirementTraceView(studio: library, library: library.acceptance, active: active && tab == "Runs")
        .id("factory.requirements")

      if !candidateID.isEmpty {
        VStack(alignment: .leading, spacing: 10) {
          HStack {
            Text("Verified candidate diff").font(.headline)
            Spacer()
            Text(String(candidateID.prefix(16)))
              .font(.caption2.monospaced())
              .foregroundStyle(.secondary)
          }
          CodeBlock(text: string(library.detail, "candidate_diff"))
          if library.detail["diff_truncated"] as? Bool == true {
            Text("Diff exceeds the native review limit. Review the complete candidate with the CLI before approval.")
              .font(.caption)
              .foregroundStyle(.orange)
          }
          HStack(spacing: 8) {
            Button { requestConfirmation("approve") } label: {
              Label("Authenticate approval…", systemImage: "touchid")
            }
            .buttonStyle(BrandButtonStyle())
            .disabled(!idle || library.detail["diff_truncated"] as? Bool == true || string(library.detail, "candidate_diff").isEmpty)
            Button("Apply approved change…") { requestConfirmation("apply") }
              .disabled(!idle)
          }
          Text("Delivery applies this patch to the working tree only — it never commits, pushes or deploys.")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        .padding(12)
        .brandSurface(radius: 12)
      } else {
        Text("Run stages and verify with SuperGauge to inspect the candidate diff here.")
          .font(.caption)
          .foregroundStyle(.secondary)
          .padding(12)
          .frame(maxWidth: .infinity, alignment: .leading)
          .brandSurface(radius: 10)
      }
    }
  }

  private func runDiagnosticsPane(factory: [String: Any], metadata: [String: Any]) -> some View {
    VStack(alignment: .leading, spacing: 10) {
      VStack(alignment: .leading, spacing: 4) {
        Text("Pinned snapshot")
          .font(.caption.weight(.semibold))
          .foregroundStyle(.secondary)
        Text(string(factory, "snapshot_digest", "Unavailable"))
          .font(.caption.monospaced())
          .textSelection(.enabled)
        Text("Editing the draft definition never alters this run's pinned inputs.")
          .font(.caption2)
          .foregroundStyle(.secondary)
      }
      .padding(10)
      .frame(maxWidth: .infinity, alignment: .leading)
      .brandSurface(radius: 10)

      DisclosureGroup("Run evidence & budget") { CodeBlock(text: pretty(library.detail["cockpit"])) }
      DisclosureGroup("Protected verification receipt") { CodeBlock(text: pretty(metadata["factory_verification"])) }
      if !library.job.isEmpty {
        DisclosureGroup("Latest factory action") { CodeBlock(text: pretty(library.job)) }
      }
    }
  }
  private func advanceGuidedStep() {
    if controlsHaveChanges {
      library.navigation.select("Configuration")
      return
    }
    if !setup.hasDraft {
      preset = "fix-and-verify"
      execute("template")
      return
    }
    if !setup.validated {
      let ticket = library.navigation.ticket()
      activeAction = "validate"
      Task {
        defer { if activeAction == "validate" { activeAction = "" } }
        await library.validate(engine: app.engine)
        if library.navigation.isCurrent(ticket) { syncControls(); await library.refreshSources(engine: app.engine) }
      }
      return
    }
    if !setup.saved {
      if tab != "Definition" { library.navigation.select("Definition") }
      requestConfirmation("save")
      return
    }
    library.navigation.select(setup.nextDestination)
  }

  private func advanceSetup() {
    if !setup.hasDraft { requestConfirmation("template") }
    else if !setup.validated {
      let ticket = library.navigation.ticket()
      activeAction = "validate"
      Task {
        defer { if activeAction == "validate" { activeAction = "" } }
        await library.validate(engine: app.engine)
        if library.navigation.isCurrent(ticket) { syncControls(); await library.refreshSources(engine: app.engine) }
      }
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
  private func workflowTitle(_ id: String) -> String {
    Self.workflowCards.first { $0.id == id }?.title ?? "this starter"
  }
  private func modelForBinding(_ name: String) -> String {
    string(bindings[name] as? [String: Any] ?? [:], "model", (library.review["binding_models"] as? [String: String])?[name] ?? "")
  }
  private var confirmationTitle: String {
    ["save": "Save this Factory revision?", "template": "Load \(workflowTitle(preset))?", "reload": "Reload saved definition?", "trial": "Prepare a pinned trial?",
     "generate": "Generate a factory proposal?", "rlm-architect": "Build On-Demand Software Factory with RLM?", "worker": "Run ready factory stages?", "verify": "Execute protected verification?",
     "enroll": "Enroll this Mac as a release signer?", "approve": "Authenticate candidate approval?", "apply": "Apply the approved change?", "cancel": "Stop this factory run?"][confirmation] ?? "Review factory action"
  }
  private var confirmationMessage: String {
    switch confirmation {
    case "save": return "Save the checked definition and record the reason for this revision. Existing runs keep their pinned inputs."
    case "template", "reload": return "This replaces the current draft. Saved revisions and existing trials remain available."
    case "generate": return app.provider.isEmpty || app.model.isEmpty || app.provider == "acp"
      ? "This builds starter factory settings from your description on this Mac. No model is called."
      : "The selected model receives your description and draft definition. This may incur model usage. If that model cannot draft, starter settings are built here instead. The result is a proposal for you to review."
    case "rlm-architect": return app.provider.isEmpty || app.model.isEmpty || app.provider == "acp"
      ? "SuperQode inspects this repository read-only (manifests, tests, build setup, and high-risk paths) using Recursive Language Model (RLM) context indexing, then chooses the right stages, agent roles, test checks, and skills for your project. Nothing is written or executed until you review and save."
      : "SuperQode inspects this repository read-only with Recursive Language Model (RLM) context indexing and runs up to 2 bounded sub-queries with \(app.provider)/\(app.model) to assemble the right stages, agent roles, test checks, and skills for your task. Nothing is written or executed until you review and save."
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
  private func requestConfirmation(_ action: String) {
    confirmation = action
  }
  private func dismissConfirmation() {
    confirmation = ""
  }
  private var confirmationKind: FactoryVisualKind {
    switch confirmation {
    case "generate", "rlm-architect": return .draft
    case "template", "reload": return .workflow
    case "save": return .save
    case "trial": return .trial
    case "worker": return .run
    case "verify": return .superGauge
    case "enroll", "approve": return .touchID
    case "apply": return .save
    case "cancel": return .caution
    default: return .factory
    }
  }
  private var confirmationActionTitle: String {
    switch confirmation {
    case "save": return "Save revision"
    case "template": return "Load \(workflowTitle(preset))"
    case "reload": return "Reload saved"
    case "generate": return "Generate draft"
    case "rlm-architect": return "Inspect repo & build"
    case "trial": return "Prepare trial"
    case "worker": return "Run stages"
    case "verify": return "Run SuperGauge"
    case "enroll": return "Enroll Touch ID"
    case "approve": return "Sign with Touch ID"
    case "apply": return "Apply change"
    case "cancel": return "Stop run"
    default: return "Continue"
    }
  }
  private var confirmationBadges: [FactoryConfirmBadge] {
    let noModel = app.provider.isEmpty || app.model.isEmpty || app.provider == "acp"
    switch confirmation {
    case "generate":
      return noModel
        ? [FactoryConfirmBadge(label: "Built on this Mac", symbol: "desktopcomputer", color: Color(red: 0.14, green: 0.62, blue: 0.42)),
           FactoryConfirmBadge(label: "No model call", symbol: "bolt.slash", color: Brand.purple)]
        : [FactoryConfirmBadge(label: "\(app.provider)/\(app.model)", symbol: "sparkles", color: Brand.pink)]
    case "rlm-architect":
      return noModel
        ? [FactoryConfirmBadge(label: "On-Demand · Read-Only Scan", symbol: "sparkles", color: Brand.purple),
           FactoryConfirmBadge(label: "No model call", symbol: "bolt.slash", color: Color(red: 0.14, green: 0.62, blue: 0.42))]
        : [FactoryConfirmBadge(label: "On-Demand · Read-Only Scan", symbol: "sparkles", color: Brand.purple),
           FactoryConfirmBadge(label: "\(app.provider)/\(app.model)", symbol: "cpu", color: Brand.pink)]
    case "template", "reload":
      return [FactoryConfirmBadge(label: "Draft only", symbol: "doc.text", color: Brand.purple),
              FactoryConfirmBadge(label: "No model call", symbol: "bolt.slash", color: Color(red: 0.14, green: 0.62, blue: 0.42))]
    case "save":
      return [FactoryConfirmBadge(label: "Pinned revision", symbol: "checkmark.seal", color: Color(red: 0.14, green: 0.62, blue: 0.42))]
    case "trial":
      return [FactoryConfirmBadge(label: "No model call", symbol: "bolt.slash", color: Color(red: 0.14, green: 0.62, blue: 0.42)),
              FactoryConfirmBadge(label: "Pinned inputs", symbol: "pin.fill", color: Brand.purple)]
    case "worker":
      return [FactoryConfirmBadge(label: "Isolated worktrees", symbol: "arrow.triangle.branch", color: Brand.purple),
              FactoryConfirmBadge(label: "Hidden evaluators", symbol: "eye.slash", color: Brand.pink)]
    case "verify":
      return [FactoryConfirmBadge(label: "SuperGauge", symbol: "gauge.with.dots.needle.67percent", color: Color(red: 0.14, green: 0.62, blue: 0.42)),
              FactoryConfirmBadge(label: "OS Sandbox", symbol: "lock.shield", color: Brand.purple)]
    case "enroll", "approve":
      return [FactoryConfirmBadge(label: "Secure Enclave", symbol: "touchid", color: Brand.purple)]
    default:
      return []
    }
  }
  private var activityTitle: String {
    if replacingDraft { return "Loading workflow starter…" }
    switch activeAction {
    case "generate": return "Drafting Factory settings…"
    case "rlm-architect": return "Building On-Demand Software Factory…"
    case "validate": return "Checking Factory definition…"
    case "save": return "Saving pinned Factory revision…"
    case "trial": return "Preparing pinned trial…"
    case "worker": return "Running Factory stages in isolated worktrees…"
    case "verify": return "Verifying candidate with SuperGauge…"
    case "enroll": return "Enrolling Secure Enclave key…"
    case "approve": return "Waiting for Touch ID approval…"
    case "apply": return "Applying verified candidate…"
    default: return "Factory action in progress…"
    }
  }
  private var activityDetail: String {
    switch activeAction {
    case "generate": return app.provider.isEmpty || app.model.isEmpty || app.provider == "acp" ? "Building starter settings locally on this Mac." : "Drafting with \(app.provider)/\(app.model)."
    case "rlm-architect": return "Scanning repository manifests, test setup, and high-risk paths to pick the right stages, agents, and skills."
    case "verify": return "Running pinned protected probes inside the OS sandbox."
    case "worker": return "Hidden evaluator files are masked from workers."
    case "approve": return "Authenticate on this Mac to sign the exact verified candidate."
    default: return "You can stop this action at any time."
    }
  }
  private var activityKind: FactoryVisualKind {
    if replacingDraft { return .workflow }
    switch activeAction {
    case "generate", "rlm-architect": return .draft
    case "save", "apply": return .save
    case "trial": return .trial
    case "worker": return .run
    case "verify": return .superGauge
    case "enroll", "approve": return .touchID
    default: return .factory
    }
  }
  private func execute(_ action: String) {
    let ticket = library.navigation.ticket()
    activeAction = action
    Task {
      defer { if activeAction == action { activeAction = "" } }
      guard library.project == ticket.project else { return }
      switch action {
      case "save": await library.save(engine: app.engine, reason: reason)
      case "template", "reload":
        replacingDraft = true; defer { replacingDraft = false }
        await library.load(engine: app.engine, template: action == "template" ? preset : "")
        await library.validate(engine: app.engine)
        if library.project == ticket.project, !library.review.isEmpty { syncControls() }
        if action == "template", library.navigation.isCurrent(ticket), library.failure.isEmpty, !library.text.isEmpty {
          library.navigation.select("Definition")
        }
      case "generate":
        if library.text.isEmpty { await library.load(engine: app.engine, template: preset) }
        guard library.navigation.isCurrent(ticket), !library.text.isEmpty else { return }
        await library.start(engine: app.engine, action: action, provider: app.provider, model: app.model, workflow: preset)
        if library.navigation.isCurrent(ticket), library.failure.isEmpty, library.message.hasPrefix("Starter settings") {
          library.navigation.select("Definition")
        }
      case "rlm-architect":
        await library.start(engine: app.engine, action: action, provider: app.provider, model: app.model, workflow: "")
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
  private func applyRLMProposal(snapshot: FactoryRLMLineageSnapshot, skills: [FactoryRLMLineageSnapshot.RecommendedSkill]) {
    let proposedYaml = string(library.proposal, "yaml")
    guard !proposedYaml.isEmpty else { return }
    let projectIdentity = library.project
    library.text = proposedYaml
    library.proposal = [:]
    appliedRLMSnapshot = snapshot
    // Jump immediately to the editable Definition page so the user sees their new factory right away.
    library.navigation.select("Definition")
    Task {
      for skill in skills {
        await library.scaffoldSkill(engine: app.engine, skill: skill.name, preset: skill.preset.isEmpty ? "web" : skill.preset)
      }
      await library.validate(engine: app.engine)
      if library.project == projectIdentity, !library.review.isEmpty {
        syncControls()
      }
    }
  }

  private func follow(_ ticket: FactoryNavigation.Ticket, to destination: String) {
    guard app.section == "Factory Studio" else { return }
    library.navigation.follow(ticket, to: destination)
  }
}
