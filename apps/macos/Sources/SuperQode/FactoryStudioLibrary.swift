import SwiftUI
import Combine

@MainActor final class FactoryStudioLibrary: ObservableObject {
  let trialSuites = FactoryTrialSuiteLibrary()
  let operations = FactoryOperationsLibrary()
  let acceptance = FactoryAcceptanceLibrary()
  let portable = FactoryExportLibrary()
  let navigation = FactoryNavigation(initial: FactoryNavigation.initialTab)
  let modelSetup = FactoryModelSetupLibrary()
  @Published var text = "" { didSet { if text != oldValue { version += 1; review = [:]; acceptance.sourceChanged(text); modelSetup.invalidate(); setupGeneration += 1; gettingStarted = [:]; setupChecking = false } } }
  @Published var gettingStarted: [String: Any] = [:]
  @Published var setupChecking = false
  @Published var onboardingWorking = false
  @Published var demoCheck: [String: Any] = [:]
  private var onboardingOperation = UUID()
  private var setupGeneration = 0
  @Published var description = "" { didSet { if description != oldValue { version += 1 } } }
  @Published var review: [String: Any] = [:]
  @Published var improvementPlans: [[String: Any]] = []
  @Published var improvementPlan: [String: Any] = [:]
  @Published var improvementPreview: [String: Any] = [:]
  @Published var improvementResult: [String: Any] = [:]
  @Published var improvementCandidate = "" { didSet { if improvementCandidate != oldValue { improvementPreview = [:]; improvementResult = [:]; improvementComparisonJob = "" } } }
  @Published var improvementComparisonJob = ""
  var improvementGeneration = 0
  @Published var sourceReview: [String: Any] = [:]
  @Published var revisions: [[String: Any]] = []
  @Published var runs: [[String: Any]] = []
  @Published var run = "" { didSet { if run != oldValue { detail = [:]; acceptance.selectRun(run) } } }
  @Published var detail: [String: Any] = [:]
  @Published var proposal: [String: Any] = [:]
  @Published var job: [String: Any] = [:]
  @Published var busy = false
  @Published var failure = ""
  @Published var message = ""
  @Published private(set) var project = ""
  @Published private(set) var expectedFileDigest = ""
  private(set) var version = 0
  private var drafts: [String: (String, String, String)] = [:]
  private var sourceGeneration = 0
  private var operation = UUID()
  private var actionRun = ""
  private var trialRequest = UUID().uuidString
  private var trialGoal = ""
  private var acceptanceChanges: AnyCancellable?
  init() { acceptanceChanges = Publishers.Merge3(acceptance.objectWillChange, portable.objectWillChange, modelSetup.objectWillChange).sink { [weak self] in self?.objectWillChange.send() } }
  var canApplyProposal: Bool { !string(proposal, "yaml").isEmpty }
  var isAnyRunActive: Bool {
    if busy && !actionRun.isEmpty { return true }
    return runs.contains { FactoryStatus(raw: string($0, "status")).isActive }
  }
  var pendingGateCount: Int {
    let order = detail["work_order"] as? [String: Any] ?? [:]
    let tasks = order["tasks"] as? [[String: Any]] ?? []
    let taskGates = tasks.filter { FactoryStatus(raw: string($0, "status")) == .waitingHuman }.count
    if taskGates > 0 { return taskGates }
    return runs.filter { FactoryStatus(raw: string($0, "status")) == .waitingHuman }.count
  }
  var readyToShipCandidate: Bool {
    guard !string(detail, "candidate_id").isEmpty else { return false }
    let order = detail["work_order"] as? [String: Any] ?? [:]
    let status = FactoryStatus(raw: string(order, "status"))
    guard status != .shipped else { return false }
    return SuperGaugeSnapshot.parse(detail: detail).verdict == .ship
  }

  private func taskStatusMap(from detailPayload: [String: Any]) -> [String: String] {
    let order = detailPayload["work_order"] as? [String: Any] ?? [:]
    let tasks = order["tasks"] as? [[String: Any]] ?? []
    var map: [String: String] = [:]
    for task in tasks {
      let id = string(task, "task_id")
      if !id.isEmpty { map[id] = string(task, "status") }
    }
    return map
  }

  @discardableResult func workflowExperiment(_ engine: Engine, stage: String, goal: String, workGoal: String) async -> Bool {
    guard !busy else { return false }; busy = true
    let identity = project; let token = version; let source = trialSuites.sourceVersion
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "workflow.experiment", ["stage": stage, "goal": goal,
        "work_goal": workGoal, "snapshot_digest": string(review, "snapshot_digest"), "confirmed": true])
      guard project == identity, version == token, trialSuites.sourceVersion == source else {
        if project == identity { message = "A draft changed during export. Its edits were preserved; the exported experiment remains on disk." }
        return false
      }
      trialSuites.selected = ""; trialSuites.path = string(result, "suite_path")
      trialSuites.text = string(result, "suite_yaml"); trialSuites.sourceDigest = string(result, "suite_file_digest")
      failure = ""; message = "Unmeasured whole-workflow experiment exported. Review and prepare the suite, then run it explicitly."
      return true
    } catch { if project == identity { failure = error.localizedDescription }; return false }
  }

  func enter(_ identity: String) {
    guard identity != project else { return }
    setupGeneration += 1; gettingStarted = [:]; setupChecking = false
    onboardingOperation = UUID(); onboardingWorking = false; demoCheck = [:]
    let hadProject = !project.isEmpty
    trialSuites.enter(identity)
    modelSetup.enter(identity)
    operations.enter(identity)
    acceptance.enter(identity)
    portable.enter(identity)
    navigation.enter(identity)
    if hadProject { drafts[project] = (text, description, expectedFileDigest) }
    operation = UUID(); sourceGeneration += 1; improvementGeneration += 1
    project = identity
    if hadProject {
      if !sourceReview.isEmpty { sourceReview = [:] }
      if busy { busy = false }
      if !review.isEmpty { review = [:] }
      if !detail.isEmpty { detail = [:] }
      if !run.isEmpty { run = "" }
      if !improvementPlans.isEmpty { improvementPlans = [] }
      if !improvementPlan.isEmpty { improvementPlan = [:] }
      if !improvementPreview.isEmpty { improvementPreview = [:] }
      if !improvementResult.isEmpty { improvementResult = [:] }
      if !improvementCandidate.isEmpty { improvementCandidate = "" }
      if !improvementComparisonJob.isEmpty { improvementComparisonJob = "" }
      if !revisions.isEmpty { revisions = [] }
      if !runs.isEmpty { runs = [] }
      if !job.isEmpty { job = [:] }
      if !proposal.isEmpty { proposal = [:] }
      if !failure.isEmpty { failure = "" }
      if !message.isEmpty { message = "" }
    }
    let draft = drafts[identity]
    let nextText = draft?.0 ?? ""
    let nextDescription = draft?.1 ?? ""
    let nextDigest = draft?.2 ?? ""
    if text != nextText { text = nextText }
    if description != nextDescription { description = nextDescription }
    if expectedFileDigest != nextDigest { expectedFileDigest = nextDigest }
    if hadProject || !nextText.isEmpty { acceptance.sourceChanged(text) }
    trialRequest = UUID().uuidString; version += 1
  }
  func rpc(_ engine: Engine, _ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
    var params = params; params["project"] = project
    return try await engine.call("factory." + method, params) as? [String: Any] ?? [:]
  }
  func inspectGettingStarted(engine: Engine, checkConnections: Bool = false) async {
    guard !project.isEmpty else { return }
    setupGeneration += 1
    let token = setupGeneration; let identity = project; let source = version
    let drafting = modelSetup.draftingReference
    setupChecking = true
    defer { if project == identity, setupGeneration == token { setupChecking = false } }
    do {
      let value = try await rpc(engine, "onboarding.inspect", ["yaml": text, "drafting_model": drafting, "check_connections": checkConnections])
      guard project == identity, setupGeneration == token, version == source, modelSetup.draftingReference == drafting, !Task.isCancelled else { return }
      gettingStarted = value
    } catch {
      if project == identity, setupGeneration == token, version == source, modelSetup.draftingReference == drafting { failure = error.localizedDescription }
    }
  }
  func onboardingAction(engine: Engine, action: String) async {
    guard !project.isEmpty, !onboardingWorking else { return }
    let identity = project; let source = version; let token = UUID()
    let drafting = modelSetup.draftingReference
    onboardingOperation = token; onboardingWorking = true
    defer { if project == identity, onboardingOperation == token { onboardingWorking = false } }
    do {
      let value = try await rpc(engine, action, ["yaml": text, "description": description, "drafting_model": drafting, "confirmed": true])
      guard project == identity, version == source, modelSetup.draftingReference == drafting, onboardingOperation == token, !Task.isCancelled else { return }
      if action == "onboarding.draft.load" {
        text = string(value, "yaml"); review = [:]
        description = string(value, "description"); modelSetup.draftingReference = string(value, "drafting_model")
        message = "Local draft restored. Validate and review it before saving the Factory."
      } else if action == "demo.check" {
        demoCheck = value
      } else {
        message = "Draft kept locally for next time. The saved Factory is unchanged."
      }
      await inspectGettingStarted(engine: engine)
    } catch {
      if project == identity, version == source, onboardingOperation == token { failure = error.localizedDescription }
    }
  }
  func load(engine: Engine, template: String = "", revision: String = "") async {
    version += 1
    let identity = project; let token = version
    do {
      let result = try await rpc(engine, "open", ["template": template, "revision": revision])
      guard project == identity, version == token else { return }
      text = string(result, "yaml"); expectedFileDigest = string(result, "expected_file_digest")
      review = [:]; proposal = [:]; failure = ""; trialRequest = UUID().uuidString
      message = "Draft loaded. Validate and review the changes before saving."
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func validate(engine: Engine) async {
    let identity = project; let token = version
    do {
      let result = try await rpc(engine, "inspect", ["yaml": text])
      guard project == identity, version == token else { return }
      review = result; failure = ""; message = "Validated without model calls. Review the workflow, warnings and definition diff."
    } catch { if project == identity, version == token { failure = error.localizedDescription; review = [:] } }
  }
  func edit(engine: Engine, controls: [String: Any]) async {
    version += 1
    let identity = project; let token = version
    do {
      let result = try await rpc(engine, "edit", ["yaml": text, "controls": controls])
      guard project == identity, version == token else { return }
      text = string(result, "yaml"); failure = ""; await validate(engine: engine)
    } catch { if project == identity, version == token { failure = error.localizedDescription } }
  }
  func scaffoldSkill(engine: Engine, skill: String, preset: String = "") async {
    let identity = project; let token = version
    do {
      let result = try await rpc(engine, "skills.scaffold", [
        "skill": skill, "preset": preset, "yaml": text, "bind": !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty,
      ])
      guard project == identity, version == token else { return }
      let updated = string(result, "yaml")
      if !updated.isEmpty && updated != text {
        version += 1
        text = updated
        await validate(engine: engine)
      }
      let path = string(result, "path", "skills/\(skill)/SKILL.md")
      failure = ""
      message = "Added \(path) and bound it to your factory draft. Save the revision when ready."
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func scaffoldEvaluator(engine: Engine, check: String = "regression", command: String = "") async {
    let identity = project; let token = version
    guard !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
    do {
      let result = try await rpc(engine, "evaluator.scaffold", [
        "check": check, "command": command, "yaml": text,
      ])
      guard project == identity, version == token else { return }
      let updated = string(result, "yaml")
      if !updated.isEmpty && updated != text {
        text = updated
        await validate(engine: engine)
      }
      if result["written"] as? Bool == true {
        let path = string(result, "path", ".superqode/evaluators/\(check).json")
        failure = ""
        message = "Configured protected SuperGauge evaluator (\(path)). Save and commit when ready."
      } else if result["already_configured"] as? Bool != true {
        message = string(result, "reason", "Review protected expectations in Acceptance checks.")
      }
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func save(engine: Engine, reason: String) async {
    let identity = project; let token = version
    guard !busy else { return }; busy = true
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "save", ["review": string(review, "review"),
        "digest": string(review, "digest"), "expected_file_digest": expectedFileDigest, "reason": reason])
      guard project == identity, version == token else { return }
      expectedFileDigest = string(result, "digest"); trialRequest = UUID().uuidString
      await validate(engine: engine); await refresh(engine: engine)
      message = "Revision saved. Prepare a trial to pin it to a new run."
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func trial(engine: Engine, goal: String) async {
    let identity = project
    guard !busy else { return }; busy = true
    if trialGoal != goal { trialGoal = goal; trialRequest = UUID().uuidString }
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "trial", ["review": string(review, "review"),
        "digest": string(review, "digest"), "confirmed": true, "goal": goal, "request_id": trialRequest])
      guard project == identity else { return }
      run = string(result["work_order"] as? [String: Any] ?? [:], "work_order_id")
      trialRequest = UUID().uuidString
      await refresh(engine: engine); await inspect(engine: engine)
      FactorySoundEngine.play(.started)
      message = "Trial prepared. Run ready stages explicitly to make model calls."
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func refreshSources(engine: Engine) async {
    sourceGeneration += 1
    let token = sourceGeneration; let identity = project
    do {
      let result = try await rpc(engine, "source.inspect")
      guard project == identity, sourceGeneration == token, !Task.isCancelled else { return }
      sourceReview = result; failure = ""
    } catch {
      if project == identity, sourceGeneration == token, !Task.isCancelled {
        sourceReview = [:]; failure = error.localizedDescription
      }
    }
  }
  func commitSources(engine: Engine, paths: [String], message: String) async {
    await start(engine: engine, action: "source-commit", extra: ["source_review": string(sourceReview, "review"),
      "source_digest": string(sourceReview, "digest"), "paths": paths, "message": message])
  }
  func refresh(engine: Engine) async {
    let identity = project
    do {
      let result = try await rpc(engine, "list")
      guard project == identity, !Task.isCancelled else { return }
      revisions = result["revisions"] as? [[String: Any]] ?? []
      runs = result["runs"] as? [[String: Any]] ?? []
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func inspect(engine: Engine) async {
    let identity = project; let selected = run
    guard !selected.isEmpty else { return }
    do {
      let result = try await rpc(engine, "run.inspect", ["run": selected])
      guard project == identity, run == selected else { return }
      detail = result
    } catch { if project == identity, run == selected { failure = error.localizedDescription } }
  }
  func gate(engine: Engine, task: [String: Any], decision: String, reason: String) async {
    let identity = project; let selected = run
    do {
      _ = try await rpc(engine, "gate", ["run": selected, "stage": string(task, "task_id"),
        "gate_digest": string(task["metadata"] as? [String: Any] ?? [:], "gate_digest"),
        "decision": decision, "reason": reason])
      guard project == identity, run == selected else { return }
      FactorySoundEngine.play(decision == "approve" ? .stageCompleted : .cancelled)
      await inspect(engine: engine)
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func runStagesAndVerify(engine: Engine, provider: String = "", model: String = "", onVerify: (() -> Void)? = nil) async {
    let identity = project; let selected = run
    guard !busy, !selected.isEmpty else { return }
    await start(engine: engine, action: "worker", provider: provider, model: model)
    guard project == identity, run == selected, failure.isEmpty else { return }
    let order = detail["work_order"] as? [String: Any] ?? [:]
    let tasks = order["tasks"] as? [[String: Any]] ?? []
    let allDone = !tasks.isEmpty && tasks.allSatisfy { FactoryStatus(raw: string($0, "status")).isComplete }
    if allDone, detail["has_protected_evaluators"] as? Bool == true,
       SuperGaugeSnapshot.parse(detail: detail).verdict != .ship {
      onVerify?()
      await start(engine: engine, action: "verify", provider: provider, model: model)
    }
  }

  func start(engine: Engine, action: String, provider: String = "", model: String = "", workflow: String = "", allowCloud: Bool = false, executionModel: String = "", extra: [String: Any] = [:]) async {
    guard !busy else { return }
    let identity = project; let token = version; let selected = run
    let op = UUID(); operation = op; busy = true; failure = ""
    defer { if operation == op { busy = false } }
    var params: [String: Any] = ["confirmed": true, "command_id": UUID().uuidString,
      "factory_action": action, "run": selected]
    if ["source-commit", "improvement-search", "improvement-compare", "campaign-run", "campaign-worker"].contains(action) { params.merge(extra) { _, value in value } }
    if ["generate", "rlm-architect"].contains(action) { params.merge(["yaml": text, "description": description,
      "provider": provider, "model": model, "workflow": workflow]) { _, value in value } }
    if action == "rlm-architect" {
      params["allow_cloud"] = allowCloud
      if !executionModel.isEmpty { params["execution_model"] = executionModel }
    }
    if action == "apply" { params["candidate_id"] = detail["candidate_id"]; params["candidate_digest"] = detail["candidate_digest"] }
    do {
      let started = try await rpc(engine, "action.start", params)
      let id = string(started, "id")
      guard project == identity, operation == op else { return }
      job = started; actionRun = ["generate", "rlm-architect", "source-commit", "improvement-search", "improvement-compare", "campaign-run", "campaign-worker"].contains(action) ? "" : selected
      FactorySoundEngine.play(.started)
      var previousTasks: [String: String] = actionRun.isEmpty ? [:] : taskStatusMap(from: detail)
      var pollTicks = 0
      while project == identity, operation == op, !Task.isCancelled {
        let current = try await engine.call("jobs.get", ["id": id]) as? [String: Any] ?? [:]
        guard project == identity, operation == op else { return }; job = current
        if !["queued", "running", "cancelling", "needs_approval"].contains(string(current, "status")) {
          let jobStatus = string(current, "status")
          if jobStatus == "completed" {
            if action == "source-commit" {
              let result = current["result"] as? [String: Any] ?? [:]
              message = "Committed Factory sources: " + string(result, "sha") + ". " + string(result, "notice")
            }
            if ["improvement-search", "improvement-compare"].contains(action) {
              let result = current["result"] as? [String: Any] ?? [:]
              if string(improvementPlan, "id") == string(result, "plan") {
                improvementCandidate = string(result, "candidate"); improvementResult = result
                if let budget = result["budget"] { improvementPlan["budget"] = budget }
                if action == "improvement-compare" { improvementComparisonJob = id }
                if !improvementCandidate.isEmpty { await previewImprovement(engine: engine) }
                message = action == "improvement-search" ? (result["held"] as? Bool == true ? "Search is on hold. Review shared budget and usage evidence." : "Candidate staged. Run the separate held-out comparison to assess it.")
                  : (result["eligible"] as? Bool == true ? "Candidate improved on the checked held-out cases. Review the evidence before draft adoption." : "Candidate remains on hold. Review the comparison issues.")
              }
            }
            if action == "rlm-architect" {
              let result = current["result"] as? [String: Any] ?? [:]
              proposal = result
              message = version == token
                ? "RLM inspected your repository and drafted a tailored Factory. Review the receipt and apply it to the draft."
                : "Draft changed during RLM inspection. Your edits are preserved; compare the proposal before applying it."
            }
            if action == "generate" {
              let result = current["result"] as? [String: Any] ?? [:]
              proposal = result
              let localStarter = (result["assumptions"] as? [String] ?? []).contains { $0.contains("No model was called") }
              if localStarter, version == token, !string(result, "yaml").isEmpty {
                text = string(result, "yaml")
                proposal = [:]
                message = "Starter settings are in the draft. Check the definition before saving."
              } else {
                // A model proposal stays separate until the user applies it.
                message = version == token ? "Proposal ready. Review assumptions and apply it to the draft."
                  : "Draft changed during generation. Your edits are preserved; compare the proposal before applying it."
              }
            }
          } else { failure = "Factory action \(jobStatus): \(pretty(current["result"]))" }
          if action == "source-commit" { await refreshSources(engine: engine) }
          await refresh(engine: engine)
          if run == selected { await inspect(engine: engine) }
          if jobStatus == "cancelled" || jobStatus == "canceled" {
            FactorySoundEngine.play(.cancelled)
          } else if jobStatus != "completed" {
            FactorySoundEngine.play(.failed)
          } else if !actionRun.isEmpty && run == selected {
            let order = detail["work_order"] as? [String: Any] ?? [:]
            let latestTasks = order["tasks"] as? [[String: Any]] ?? []
            if let cue = FactorySoundEngine.cueForTaskTransitions(previous: previousTasks, current: latestTasks) {
              FactorySoundEngine.play(cue == .stageCompleted ? .succeeded : cue)
            } else if action == "verify" {
              let verdict = SuperGaugeSnapshot.parse(detail: detail).verdict
              FactorySoundEngine.play(verdict == .ship ? .succeeded : verdict == .reject ? .failed : .needsAttention)
            } else {
              FactorySoundEngine.play(.succeeded)
            }
          } else {
            FactorySoundEngine.play(.succeeded)
          }
          return
        }
        pollTicks += 1
        if !actionRun.isEmpty && run == selected && pollTicks % 2 == 0 {
          await inspect(engine: engine)
          if project == identity && operation == op && run == selected {
            let order = detail["work_order"] as? [String: Any] ?? [:]
            let latestTasks = order["tasks"] as? [[String: Any]] ?? []
            if let cue = FactorySoundEngine.cueForTaskTransitions(previous: previousTasks, current: latestTasks) {
              FactorySoundEngine.play(cue)
            }
            previousTasks = taskStatusMap(from: detail)
          }
        }
        try await Task.sleep(for: .seconds(1))
      }
    } catch { if project == identity, operation == op { failure = error.localizedDescription } }
  }
  func cancel(engine: Engine, runOnly: Bool = false) async {
    let identity = project; let selected = runOnly ? run : actionRun
    let id = !runOnly || actionRun == selected ? string(job, "id") : ""
    do {
      if !selected.isEmpty { _ = try await rpc(engine, "cancel", ["run": selected]) }
      if !id.isEmpty { _ = try await engine.call("jobs.cancel", ["id": id]) }
      guard project == identity else { return }
      FactorySoundEngine.play(.cancelled)
      await refresh(engine: engine); await inspect(engine: engine)
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func approve(engine: Engine) async {
    let identity = project; let selected = run
    let candidate = string(detail, "candidate_id"); let digest = string(detail, "candidate_digest")
    guard detail["diff_truncated"] as? Bool != true, !candidate.isEmpty, !busy else { return }
    busy = true; defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "release.challenge", ["run": selected, "key_id": "this-mac"])
      let payload = result["challenge"] as? [String: Any] ?? [:]
      guard project == identity, run == selected, string(payload, "candidate_id") == candidate,
        string(payload, "candidate_digest") == digest, let bytes = Data(base64Encoded: string(result, "message")) else {
        throw EngineError(message: "Candidate changed. Refresh and review its exact diff before approving.")
      }
      let signature = try await FactoryReleaseSigner.sign(message: bytes)
      guard project == identity, run == selected else { return }
      _ = try await rpc(engine, "release.authorize", ["run": selected,
        "proof": ["challenge_id": string(payload, "id"), "signature": signature]])
      FactorySoundEngine.play(.succeeded)
      await inspect(engine: engine); message = "Exact candidate approved. Apply it before this short-lived approval expires."
    } catch { if project == identity { failure = error.localizedDescription } }
  }
}

extension FactoryStudioLibrary {
  func refreshImprovements(engine: Engine) async {
    let identity = project
    do {
      let result = try await rpc(engine, "improvement.list")
      guard project == identity, !Task.isCancelled else { return }
      improvementPlans = result["plans"] as? [[String: Any]] ?? []
    } catch { if project == identity, !Task.isCancelled { failure = error.localizedDescription } }
  }
  func prepareImprovement(engine: Engine, params: [String: Any]) async {
    guard !busy else { return }; busy = true
    let identity = project; improvementGeneration += 1; let token = improvementGeneration
    defer { if project == identity { busy = false } }
    do {
      let plan = try await rpc(engine, "improvement.prepare", params)
      guard project == identity, improvementGeneration == token else { return }
      improvementPlan = plan; improvementPreview = [:]; improvementResult = [:]; improvementCandidate = ""; improvementComparisonJob = ""
      failure = ""
      await refreshImprovements(engine: engine)
      message = "Inputs pinned. Edit or import a proposal, or explicitly run the selected search engine. Final comparison is separate."
    } catch { if project == identity, improvementGeneration == token { failure = error.localizedDescription } }
  }
  func openImprovement(engine: Engine, id: String) async {
    let identity = project; improvementGeneration += 1; let token = improvementGeneration
    do {
      let plan = try await rpc(engine, "improvement.open", ["plan": id])
      guard project == identity, improvementGeneration == token, !Task.isCancelled else { return }
      improvementPlan = plan; improvementPreview = [:]
      let comparison = plan["comparison"] as? [String: Any] ?? [:]
      improvementCandidate = string(comparison, "candidate"); improvementResult = comparison
      improvementComparisonJob = string(plan, "comparison_job")
      await previewImprovement(engine: engine)
    } catch { if project == identity, improvementGeneration == token { failure = error.localizedDescription } }
  }
  func importOptimizerCandidate(engine: Engine, optimizer: String, path: String) async {
    guard !busy else { return }; busy = true
    let op = UUID(); operation = op
    let identity = project; let selected = string(improvementPlan, "id"); let token = improvementGeneration
    defer { if operation == op { busy = false } }
    do {
      let result = try await rpc(engine, "improvement.external.import", ["plan": selected, "engine": optimizer, "path": path, "confirmed": true])
      guard project == identity, string(improvementPlan, "id") == selected, improvementGeneration == token else { return }
      let candidate = string(result, "candidate")
      var candidates = improvementPlan["candidates"] as? [String] ?? []
      if !candidates.contains(candidate) { candidates.append(candidate) }
      improvementPlan["candidates"] = candidates
      improvementCandidate = candidate; failure = ""; message = string(result, "notice")
      await previewImprovement(engine: engine)
    } catch { if project == identity, string(improvementPlan, "id") == selected, improvementGeneration == token { failure = error.localizedDescription } }
  }
  func proposeImprovement(engine: Engine, yaml: String, path: String = "") async {
    let identity = project; let selected = string(improvementPlan, "id")
    do {
      var params: [String: Any] = ["plan": selected, "yaml": yaml]
      if !path.isEmpty { params["path"] = path }
      let result = try await rpc(engine, path.isEmpty ? "improvement.propose" : "improvement.import", params)
      guard project == identity, string(improvementPlan, "id") == selected else { return }
      improvementCandidate = string(result, "candidate"); improvementResult = [:]; improvementComparisonJob = ""
      await previewImprovement(engine: engine)
      failure = ""
    } catch { if project == identity, string(improvementPlan, "id") == selected { failure = error.localizedDescription } }
  }
  func previewImprovement(engine: Engine) async {
    let identity = project; let selected = string(improvementPlan, "id"); let candidate = improvementCandidate
    guard !selected.isEmpty, !candidate.isEmpty else { return }
    do {
      let result = try await rpc(engine, "improvement.preview", ["plan": selected, "candidate": candidate])
      guard project == identity, string(improvementPlan, "id") == selected, improvementCandidate == candidate else { return }
      improvementPreview = result
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func runImprovement(engine: Engine, search: Bool) async {
    await start(engine: engine, action: search ? "improvement-search" : "improvement-compare",
      extra: ["plan": string(improvementPlan, "id"), "candidate": improvementCandidate])
  }
  func refreshImprovementBudget(_ engine: Engine) async {
    let identity = project; let selected = string(improvementPlan, "id")
    guard !selected.isEmpty else { return }
    do {
      let result = try await rpc(engine, "improvement.budget", ["plan": selected])
      guard project == identity, string(improvementPlan, "id") == selected else { return }
      improvementPlan["budget"] = result
    } catch { if project == identity, string(improvementPlan, "id") == selected { failure = error.localizedDescription } }
  }
  @discardableResult func createBoundSkill(engine: Engine, binding: String, id: String, markdown: String) async -> Bool {
    guard !busy else { return false }; busy = true
    let identity = project; let token = version; let draft = text
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "improvement.skill.create", ["yaml": draft, "binding": binding,
        "skill": id, "markdown": markdown, "confirmed": true])
      guard project == identity, version == token, !Task.isCancelled else { return false }
      text = string(result, "yaml"); message = string(result, "notice")
      await validate(engine: engine); return true
    } catch { if project == identity { failure = error.localizedDescription }; return false }
  }
  @discardableResult func adoptImprovement(engine: Engine) async -> Bool {
    let identity = project; let token = version; let selected = string(improvementPlan, "id"); let candidate = improvementCandidate
    guard !busy else { return false }; busy = true
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "improvement.adopt", ["plan": selected, "candidate": candidate,
        "comparison_job": improvementComparisonJob, "confirmed": true])
      guard project == identity, version == token, string(improvementPlan, "id") == selected, improvementCandidate == candidate else { return false }
      text = string(result, "yaml"); message = string(result, "notice")
      await validate(engine: engine); return true
    } catch { if project == identity { failure = error.localizedDescription }; return false }
  }
}
