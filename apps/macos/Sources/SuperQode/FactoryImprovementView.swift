import SwiftUI

struct FactoryImprovementView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var library: FactoryStudioLibrary
  var active = true
  var onAdopt: () -> Void
  @State private var capabilities: [String: Any] = [:]
  @State private var binding = "coder"
  @State private var targetKind = "harness"
  @State private var skill = ""
  @State private var stage = ""
  @State private var routeModelsText = ""
  @State private var creatingSkill = false
  @State private var newSkillID = "review"
  @State private var newSkillText = "---\nname: review\ndescription: Check requested output before responding\n---\nRead the requested output format and check the response before returning it.\n"
  @State private var tasksPath = ".superqode/evals/factory-improvement.yaml"
  @State private var fixture = "@empty"
  @State private var enableSearch = false
  @State private var optimizerEngine = "evaluator-optimizer"
  @State private var maxEvals = 4
  @State private var seconds = 120
  @State private var suiteText = ""
  @State private var suiteDigest = ""
  @State private var suiteVersion = 0
  @State private var candidateText = ""
  @State private var candidateVersion = 0
  @State private var candidatePath = ""
  @State private var externalEngine = "metaharness"
  @State private var externalPath = ""
  @State private var selectedPlan = ""
  @State private var confirmation = ""
  @State private var tabGeneration = UUID()
  @State private var tab = ProcessInfo.processInfo.arguments.contains("--factory-optimization-inspect") ? "Evidence" : "Inputs"
  private var planID: String { string(library.improvementPlan, "id") }
  private var idle: Bool { !library.busy && !app.anyActive && !app.busy }
  private var compared: Bool { library.improvementPreview["compared"] as? Bool == true || !library.improvementComparisonJob.isEmpty || library.improvementPlan["compared"] as? Bool == true }
  private var reflection: String { app.provider + "/" + app.model }
  private var eligible: Bool { library.improvementResult["eligible"] as? Bool == true && !library.improvementComparisonJob.isEmpty }
  private var boundSkills: [String] { (capabilities["bound_skills"] as? [String: [String]])?[binding] ?? [] }
  private var skillPlan: Bool { string(library.improvementPlan, "target_kind") == "skill" }
  private var planKind: String { string(library.improvementPlan, "target_kind", "harness") }
  private var engines: [[String: Any]] { capabilities["optimizer_engines"] as? [[String: Any]] ?? [] }
  private func engineAvailable(_ id: String) -> Bool { engines.first { string($0, "id") == id }?["available"] as? Bool == true }
  private var stages: [[String: Any]] { (capabilities["workflow_stages"] as? [[String: Any]] ?? []).filter { string($0, "harness") == binding } }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        VStack(alignment: .leading, spacing: 4) {
          Text("Measure → propose → compare → review").font(.headline)
          Text("Change one surface at a time. Keep a proposal only when separate held-out evidence supports it.")
            .font(.caption).foregroundStyle(.secondary)
        }
        Spacer()
        Button("Refresh experiments") { Task { await library.refreshImprovements(engine: app.engine) } }.disabled(!idle)
      }
      HStack {
        Picker("Prepared experiment", selection: $selectedPlan) {
          Text("Choose a prepared experiment").tag("")
          ForEach(library.improvementPlans.map { string($0, "id") }, id: \.self) { identity in
            Text(String(identity.prefix(20))).tag(identity)
          }
        }
        Button("Open") {
          let ticket = library.navigation.ticket(); let token = candidateVersion; let selected = selectedPlan
          Task {
            await library.openImprovement(engine: app.engine, id: selected)
            guard library.navigation.isCurrent(ticket), selectedPlan == selected, candidateVersion == token else { return }
            candidateText = string(library.improvementPlan, "baseline_yaml")
          }
        }
          .disabled(!idle || selectedPlan.isEmpty)
      }
      Picker("Improvement workspace", selection: $tab) {
        Text("Inputs & suite").tag("Inputs"); Text("Candidate & diff").tag("Candidate"); Text("Comparison evidence").tag("Evidence")
      }.pickerStyle(.segmented)
      DisclosureGroup("Optimisation methods & availability") {
        ForEach((capabilities["techniques"] as? [[String: Any]] ?? []).map { string($0, "id") }, id: \.self) { identity in
          let row = (capabilities["techniques"] as? [[String: Any]] ?? []).first { string($0, "id") == identity } ?? [:]
          VStack(alignment: .leading, spacing: 3) {
            Text(string(row, "name")).font(.caption.bold())
            Text(string(row, "mode") + (identity == "gepa" && capabilities["gepa"] as? Bool != true ? " · not installed" : ""))
              .font(.caption).foregroundStyle(.secondary)
          }.padding(.vertical, 3)
        }
        Text("External search is not launched or metered by Factory. Its proposals still require the same protected surface checks and fresh native comparison.")
          .font(.caption).foregroundStyle(.secondary)
      }.font(.caption)
      FactoryCampaignView(studio: library, active: active)
      if tab == "Inputs" { inputs }
      else if tab == "Candidate" { candidate }
      else { evidence }
      if !planID.isEmpty {
        VStack(alignment: .leading, spacing: 7) {
          Text("Pinned experiment " + String(planID.prefix(20))).font(.caption.monospaced())
          FactoryActionRow {
          Button("Run metered search…") { confirmation = "search" }
            .disabled(!idle || compared || !engineAvailable(string(library.improvementPlan, "optimizer_engine", "gepa")) || string(library.improvementPlan, "reflection_model").isEmpty)
          Button("Compare held-out outputs…") { confirmation = "compare" }
            .disabled(!idle || compared || library.improvementCandidate.isEmpty)
          Button("Adopt into draft…") { confirmation = "adopt" }.buttonStyle(BrandButtonStyle()).disabled(!idle || !eligible)
          }
        }
      }
      Text("Evidence applies to the selected surface and these output tasks. Entry-stage experiments do not evaluate the full workflow. Copied fixtures are not an OS sandbox. Application verification and signed release approval remain separate.")
        .font(.caption).foregroundStyle(.secondary)
    }
    .task(id: library.project + "\n" + String(active)) {
      guard active else { return }
      let identity = library.project
      do {
        let result = try await library.rpc(app.engine, "improvement.capabilities")
        guard library.project == identity, !Task.isCancelled else { return }
        capabilities = result
        let bindings = result["bindings"] as? [String] ?? []
        if !bindings.contains(binding), let first = bindings.first { binding = first; syncTargets() }
        else { reconcileTargets() }
        await library.refreshImprovements(engine: app.engine)
      } catch { if library.project == identity, !Task.isCancelled { library.failure = error.localizedDescription } }
    }
    .onChange(of: suiteText) { _, _ in suiteVersion += 1 }
    .onChange(of: candidateText) { _, _ in candidateVersion += 1 }
    .onChange(of: tasksPath) { _, _ in suiteVersion += 1; suiteDigest = ""; suiteText = "" }
    .onChange(of: binding) { _, _ in syncTargets() }
    .onChange(of: active) { _, visible in if !visible { confirmation = ""; creatingSkill = false } }
    .onChange(of: tab) { _, _ in tabGeneration = UUID(); confirmation = "" }
    .onChange(of: library.project) { _, _ in confirmation = ""; creatingSkill = false; capabilities = [:]; skill = ""; stage = ""; routeModelsText = ""; suiteText = ""; candidateText = ""; selectedPlan = "" }
    .sheet(isPresented: $creatingSkill) { skillForm }
    .alert(confirmationTitle, isPresented: Binding(get: { !confirmation.isEmpty }, set: { if !$0 { confirmation = "" } })) {
      Button("Cancel", role: .cancel) {}
      Button("Continue") { let action = confirmation; confirmation = ""; execute(action) }
    } message: { Text(confirmationMessage) }
  }

  private var inputs: some View {
    HSplitView {
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          Text("Experiment contract").font(.headline)
          Text("Preparation reads the saved Factory. Commit application changes first. Existing trials and the draft are not modified.")
            .font(.caption).foregroundStyle(.secondary)
          Picker("Harness binding", selection: $binding) {
            ForEach(capabilities["bindings"] as? [String] ?? [], id: \.self) { Text($0).tag($0) }
          }
          Picker("Improve", selection: $targetKind) {
            Text("Harness instructions").tag("harness"); Text("Bound skill instructions").tag("skill")
            Text("Primary model route").tag("route"); Text("Workflow entry-stage goal").tag("workflow")
          }
          if targetKind == "route" {
            Text("Pinned model choices (one provider/model per line, including the baseline)").font(.caption)
            TextEditor(text: $routeModelsText).font(.system(.caption, design: .monospaced)).frame(minHeight: 80).brandSurface()
            Text("Only these explicitly selected models can enter this experiment. Factory cloud and subscription policies still apply. Models may incur provider charges.").font(.caption).foregroundStyle(.secondary)
          }
          if targetKind == "workflow" {
            Picker("Ungated entry stage", selection: $stage) {
              Text("Choose a stage").tag("")
              ForEach(stages.map { string($0, "id") }, id: \.self) { Text($0).tag($0) }
            }
            Text("Tune this stage’s goal using the native WorkOrder prompt and role restrictions. Dependencies, human gates, checks and graph stay fixed. Stages with predecessors or human gates require a future adapter.").font(.caption).foregroundStyle(.secondary)
          }
          if targetKind == "skill" {
            Picker("Bound skill", selection: $skill) {
              Text("Choose a skill").tag("")
              ForEach(boundSkills, id: \.self) { Text($0).tag($0) }
            }
            Text("Skills are explicit Markdown instructions appended to this harness. Save a new binding before preparing its experiment.")
              .font(.caption).foregroundStyle(.secondary)
          }
          Button("Create skill & bind to draft…") { creatingSkill = true }.disabled(!idle || library.text.isEmpty)
          TextField("Project-relative suite path", text: $tasksPath).textFieldStyle(.roundedBorder)
          TextField("Fixture directory or @empty", text: $fixture).textFieldStyle(.roundedBorder)
          Text("@empty creates a disposable empty fixture for output tasks. Use a project-relative directory for an explicit application fixture.")
            .font(.caption).foregroundStyle(.secondary)
          Stepper("Optimizer metric calls: \(maxEvals)", value: $maxEvals, in: 1...20)
          Stepper("Shared experiment time: \(seconds) seconds", value: $seconds, in: 10...600, step: 10)
          Picker("Optimizer engine", selection: $optimizerEngine) {
            Text("Native evaluator–optimizer").tag("evaluator-optimizer")
            Text("GEPA (optional dependency)").tag("gepa")
            Text("MetaHarness (metered gateway)").tag("metaharness")
            Text("Omni portfolio (native + GEPA + MetaHarness)").tag("omni")
          }
          Toggle("Prepare metered search", isOn: $enableSearch).disabled(!engineAvailable(optimizerEngine))
          Text("Evaluation model comes from the pinned harness. Reflection model: \(reflection)").font(.caption).foregroundStyle(.secondary)
          Button("Prepare experiment") { execute("prepare") }.disabled(!idle || binding.isEmpty || tasksPath.isEmpty || fixture.isEmpty || (targetKind == "skill" && skill.isEmpty) || (targetKind == "workflow" && stage.isEmpty) || (targetKind == "route" && routeModelsText.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty))
          if capabilities["gepa"] as? Bool != true {
            Text("GEPA is unavailable. Native evaluator–optimizer and manual candidate import use the same metered comparison contract. Nothing is installed automatically.")
              .font(.caption).foregroundStyle(.orange)
          }
          if !planID.isEmpty {
            DisclosureGroup("Pinned contract") { CodeBlock(text: pretty(library.improvementPlan.filter { $0.key != "baseline_yaml" })) }
          }
          Text("One final held-out comparison is allowed per plan. Reusing a suite across new experiments weakens its independence; replace held-out cases deliberately.")
            .font(.caption).foregroundStyle(.secondary)
        }.padding(.trailing, 12)
      }.frame(minWidth: 230, idealWidth: 280, maxWidth: 390)
      VStack(alignment: .leading, spacing: 10) {
        HStack {
          Text("Graded evaluation suite").font(.headline); Spacer()
          Button("Load / starter") { Task { await loadSuite() } }.disabled(!idle)
          Button("Save suite") { Task { await saveSuite() } }.disabled(!idle || suiteText.isEmpty)
        }
        Text("Use deterministic contains or decision graders, with held-in and held-out cases. Replace starter cases with meaningful labels before drawing conclusions.")
          .font(.caption).foregroundStyle(.secondary)
        SourceEditor(text: $suiteText, path: "improvement-tasks.yaml", editable: idle,
          documentID: "factory-improvement-suite:" + library.project, active: active).brandSurface()
      }.padding(.leading, 12).frame(minWidth: 280)
    }
  }
  private var candidate: some View {
    HSplitView {
      VStack(alignment: .leading, spacing: 10) {
        Text(candidateTitle).font(.headline)
        Text(candidateScope)
          .font(.caption).foregroundStyle(.secondary)
        HStack {
          Button("Load pinned baseline") { candidateText = string(library.improvementPlan, "baseline_yaml") }.disabled(!idle || planID.isEmpty)
          Button("Stage edited proposal") { Task { await library.proposeImprovement(engine: app.engine, yaml: candidateText) } }.disabled(!idle || planID.isEmpty || candidateText.isEmpty)
        }
        SourceEditor(text: $candidateText, path: skillPlan ? "SKILL.md" : "candidate-" + planKind + ".yaml", editable: idle,
          documentID: "factory-improvement-candidate:" + library.project, active: active).brandSurface()
        HStack {
          TextField("Optional project-relative candidate file", text: $candidatePath).textFieldStyle(.roundedBorder)
          Button("Import") { Task { await library.proposeImprovement(engine: app.engine, yaml: "", path: candidatePath) } }
            .disabled(!idle || planID.isEmpty || candidatePath.isEmpty)
        }
        if let candidates = library.improvementPlan["candidates"] as? [String], !candidates.isEmpty {
          Picker("Saved candidate", selection: $library.improvementCandidate) {
            Text("Choose candidate").tag("")
            ForEach(candidates, id: \.self) { Text(String($0.prefix(16))).tag($0) }
          }.onChange(of: library.improvementCandidate) { _, _ in Task { await library.previewImprovement(engine: app.engine) } }
        }
        if planKind == "harness" {
          DisclosureGroup("Import a MetaHarness or Omni proposal") {
            Picker("External optimizer", selection: $externalEngine) { Text("MetaHarness run").tag("metaharness"); Text("GEPA Omni result JSON").tag("omni") }
            TextField("Project-relative run directory or result JSON", text: $externalPath).textFieldStyle(.roundedBorder)
            Button("Import as an unmeasured proposal…") { confirmation = "external-import" }.disabled(!idle || planID.isEmpty || externalPath.isEmpty)
            Text("No external engine is started. Imported scores cannot approve adoption; the Factory runs its own metered held-out comparison.").font(.caption).foregroundStyle(.secondary)
          }.font(.caption)
        }
      }.frame(minWidth: 280).padding(.trailing, 12)
      ScrollView {
        VStack(alignment: .leading, spacing: 10) {
          Text("Pinned candidate diff").font(.headline)
          Text(String(library.improvementCandidate.prefix(20))).font(.caption.monospaced()).textSelection(.enabled)
          CodeBlock(text: string(library.improvementPreview, "diff", "Stage or generate a candidate to review its diff."))
          Text("Editing this box does not change an already staged candidate. Stage your changes explicitly before comparison.")
            .font(.caption).foregroundStyle(.secondary)
        }.padding(.leading, 12)
      }.frame(minWidth: 300)
    }
  }
  private var evidence: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 12) {
        HStack {
          Text("Shared optimizer usage").font(.headline)
          Spacer()
          Button("Refresh usage") { Task { await library.refreshImprovementBudget(app.engine) } }.disabled(planID.isEmpty)
        }
        CodeBlock(text: pretty(library.improvementPlan["budget"] ?? library.improvementResult["budget"] ?? library.improvementPreview["budget"]))
        Text("One plan budget covers reflection, held-in scoring and final comparison. Unknown or interrupted usage keeps admission and adoption on hold. A request already in flight can exceed a limit; its usage remains recorded. Time starts at the first operation and includes time between actions.").font(.caption).foregroundStyle(.secondary)
        Text("Held-out comparison").font(.headline)
        if library.improvementResult.isEmpty {
          Text("Run a comparison for measured evidence. An imported or generated proposal has no adoption authority.")
            .foregroundStyle(.secondary)
        } else {
          Pill(title: eligible ? "Eligible for draft review" : "Hold", color: eligible ? .green : .orange)
          if let before = library.improvementResult["baseline_score"] as? Double,
            let after = library.improvementResult["candidate_score"] as? Double {
            Text(String(format: "Held-out pass rate: %.0f%% baseline → %.0f%% candidate", before * 100, after * 100)).font(.headline)
          }
          Text("Eligibility requires a strictly higher pass rate with no baseline successes regressed and complete pinned grading and required budget evidence.")
            .font(.caption).foregroundStyle(.secondary)
          CodeBlock(text: pretty(library.improvementResult))
        }
        if !library.job.isEmpty { DisclosureGroup("Latest engine job") { CodeBlock(text: pretty(library.job)) } }
        Text("Adoption loads a Factory draft; harness and skill proposals also create an immutable component. Review the diff, save a revision, commit sources and prepare a new trial explicitly. Application release approval remains separate.")
          .font(.caption).foregroundStyle(.secondary)
      }
    }
  }
  private var confirmationTitle: String {
    ["search": "Run metered optimizer search?", "compare": "Run final held-out comparison?", "adopt": "Adopt this proposal into a draft?"][confirmation] ?? "Review improvement action"
  }
  private var confirmationMessage: String {
    switch confirmation {
    case "external-import": return "Read the selected project-local optimizer artifact and stage its candidate after the normal Factory surface audit. External scores and spending are not Factory evaluation evidence. No model is called by import."
    case "search": return "Run the pinned optimizer with the selected reflection route and held-in examples only. Reflection and evaluation share the plan budget with the later held-out comparison. Uncertain usage stops new work; a running request can finish over a limit. Results are staged for separate comparison."
    case "compare": return "Run baseline and candidate on the pinned held-out tasks in separate fixture copies. This makes model calls and consumes this plan’s one final comparison attempt. Missing, stale, regressing or unmetered required evidence keeps adoption on hold."
    case "adopt": return "Load the exact reviewed proposal into the Factory draft. Skill and harness proposals also create an immutable source component. Review and save the draft, then prepare a new trial explicitly."
    default: return "Review the prepared experiment contract."
    }
  }
  private func execute(_ action: String) {
    let ticket = library.navigation.ticket(); let tabToken = tabGeneration
    Task {
      guard library.project == ticket.project else { return }
      switch action {
      case "external-import": await library.importOptimizerCandidate(engine: app.engine, optimizer: externalEngine, path: externalPath)
      case "prepare":
        await library.prepareImprovement(engine: app.engine, params: ["binding": binding, "tasks": tasksPath,
          "target_kind": targetKind, "skill": skill,
          "stage": stage, "route_models": targetKind == "route" ? routeModelsText.split(whereSeparator: \.isNewline).map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty } : [],
          "fixture": fixture, "max_evals": maxEvals, "max_seconds": seconds,
          "optimizer_engine": optimizerEngine,
          "reflection_model": !enableSearch || app.model.isEmpty ? "" : reflection])
        guard library.navigation.isCurrent(ticket), tabGeneration == tabToken else { return }
        candidateText = string(library.improvementPlan, "baseline_yaml"); selectedPlan = planID
      case "search", "compare":
        await library.runImprovement(engine: app.engine, search: action == "search")
        if app.section == "Factory Studio", library.navigation.isCurrent(ticket), tabGeneration == tabToken { tab = "Evidence" }
      case "adopt":
        if await library.adoptImprovement(engine: app.engine), app.section == "Factory Studio",
          library.navigation.isCurrent(ticket), tabGeneration == tabToken { onAdopt() }
      default: break
      }
    }
  }
  private func syncTargets() {
    skill = boundSkills.first ?? ""; stage = stages.first.map { string($0, "id") } ?? ""
    routeModelsText = ((capabilities["route_models"] as? [String: [String]])?[binding] ?? []).joined(separator: "\n")
  }
  private func reconcileTargets() {
    if !boundSkills.contains(skill) { skill = boundSkills.first ?? "" }
    if !stages.contains(where: { string($0, "id") == stage }) { stage = stages.first.map { string($0, "id") } ?? "" }
    if routeModelsText.isEmpty { routeModelsText = ((capabilities["route_models"] as? [String: [String]])?[binding] ?? []).joined(separator: "\n") }
  }
  private var candidateTitle: String {
    ["skill": "Candidate SKILL.md", "route": "Candidate model route", "workflow": "Candidate entry-stage goal"][planKind] ?? "Candidate HarnessSpec"
  }
  private var candidateScope: String {
    switch planKind {
    case "skill": return "Edit the Markdown instructions only. Frontmatter and other skills remain pinned."
    case "route": return "Change only model to one of the pinned choices. Harness instructions, skills, tools, permissions, fallback policy and criteria stay fixed."
    case "workflow": return "Change only goal for the pinned entry stage. Stage identity, roles, dependencies, checks, human gates and graph stay fixed."
    default: return "Only system instructions, role text and description can change. Routes, tools, context paths, permissions and criteria remain pinned."
    }
  }
  private var skillForm: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("Create a bound Factory skill").font(.headline)
      Text("Creates a project skill file and adds it to the current draft’s \(binding) binding. Review and save the draft before use. Markdown instructions do not grant tools or execute scripts.")
        .font(.caption).foregroundStyle(.secondary)
      TextField("Skill ID (lowercase letters, digits, hyphens)", text: $newSkillID).textFieldStyle(.roundedBorder)
      SourceEditor(text: $newSkillText, path: "SKILL.md", editable: idle,
        documentID: "factory-new-skill:" + library.project, active: creatingSkill).brandSurface()
      HStack {
        Button("Cancel") { creatingSkill = false }.disabled(!idle)
        Spacer()
        Button("Create skill & bind to draft") {
          Task {
            if await library.createBoundSkill(engine: app.engine, binding: binding, id: newSkillID, markdown: newSkillText) {
              creatingSkill = false; onAdopt()
            }
          }
        }.buttonStyle(BrandButtonStyle()).disabled(!idle || newSkillID.isEmpty || newSkillText.isEmpty)
      }
      if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.red).textSelection(.enabled) }
    }.padding(20).frame(minWidth: 680, minHeight: 520)
  }
  private func loadSuite() async {
    let identity = library.project; let path = tasksPath; let token = suiteVersion; let before = suiteText
    do {
      let result = try await library.rpc(app.engine, "improvement.suite.open", ["path": path])
      guard library.project == identity, tasksPath == path, suiteVersion == token, suiteText == before, !Task.isCancelled else { return }
      suiteText = string(result, "yaml"); suiteDigest = string(result, "expected_file_digest")
    } catch { if library.project == identity { library.failure = error.localizedDescription } }
  }
  private func saveSuite() async {
    let identity = library.project; let path = tasksPath; let text = suiteText
    do {
      let result = try await library.rpc(app.engine, "improvement.suite.save", ["path": path, "yaml": text, "expected_file_digest": suiteDigest])
      guard library.project == identity, tasksPath == path, !Task.isCancelled else { return }
      suiteDigest = string(result, "digest"); library.message = "Suite saved. Prepare a new experiment to pin these criteria."
    } catch { if library.project == identity { library.failure = error.localizedDescription } }
  }
}
