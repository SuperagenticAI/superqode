import Foundation

@MainActor final class FactoryTrialSuiteLibrary: ObservableObject {
  let feedback = FactoryFeedbackLibrary()
  @Published private(set) var project = ""
  @Published var path = ".superqode/trials/reference.yaml" { didSet { if path != oldValue { sourceVersion += 1; sourceDigest = "" } } }
  @Published var text = "" { didSet { if text != oldValue { sourceVersion += 1 } } }
  @Published var sourceDigest = ""
  @Published var plans: [[String: Any]] = []
  @Published var selected = "" { didSet { if selected != oldValue { board = [:]; entry = ""; detail = [:] } } }
  @Published var board: [String: Any] = [:]
  @Published var entry = "" { didSet { if entry != oldValue { detail = [:] } } }
  @Published var detail: [String: Any] = [:]
  @Published var job: [String: Any] = [:]
  @Published var busy = false
  @Published var failure = ""
  @Published var message = ""
  @Published var historyRuns: [[String: Any]] = []
  @Published var historyProposal: [String: Any] = [:]
  @Published var historyCandidate = ".superqode/factory.yaml" { didSet { historyVersion += 1; historyProposal = [:] } }
  @Published var historySplits: [String: String] = [:] { didSet { historyVersion += 1; historyProposal = [:] } }
  private var historyVersion = 0
  var sourceVersion = 0
  var generation = 0
  var operation = UUID()
  private var drafts: [String: (String, String, String)] = [:]

  func enter(_ value: String) {
    guard project != value else { return }
    feedback.enter(value)
    if !project.isEmpty { drafts[project] = (path, text, sourceDigest) }
    generation += 1; operation = UUID(); project = value
    historyRuns = []; historySplits = [:]; historyCandidate = ".superqode/factory.yaml"; historyProposal = [:]
    selected = ""; board = [:]; detail = [:]; plans = []; job = [:]; busy = false; failure = ""; message = ""
    if let draft = drafts[value] { path = draft.0; text = draft.1; sourceDigest = draft.2 }
    else { path = ".superqode/trials/reference.yaml"; text = ""; sourceDigest = "" }
  }
  func rpc(_ engine: Engine, _ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
    var request = params; request["project"] = project
    return try await engine.call("factory.suite." + method, request) as? [String: Any] ?? [:]
  }
  func history(_ engine: Engine, action: String) async {
    guard !busy else { return }; busy = true
    let identity = project; let token = historyVersion; let source = sourceVersion
    let proposal = historyProposal
    failure = ""
    defer { if project == identity { busy = false } }
    do {
      var params: [String: Any] = [:]
      if action == "draft" {
        params = ["held_in": historySplits.filter { $0.value == "held-in" }.keys.sorted(),
          "held_out": historySplits.filter { $0.value == "held-out" }.keys.sorted(), "candidate": historyCandidate]
      } else if action == "install" {
        params = ["proposal": proposal, "digest": string(proposal, "digest"), "confirmed": true]
      }
      let result = try await rpc(engine, "history." + action, params)
      guard project == identity, historyVersion == token, sourceVersion == source, !Task.isCancelled else { return }
      if action == "list" { historyRuns = result["runs"] as? [[String: Any]] ?? [] }
      else if action == "draft" { historyProposal = result }
      else {
        path = string(result, "path"); await loadSource(engine)
        guard project == identity, historyVersion == token, failure.isEmpty else { return }
        historyProposal = [:]; message = "Historical workload saved. Review the suite, then prepare and run it explicitly."
      }
      failure = ""
    } catch { if project == identity, historyVersion == token { failure = error.localizedDescription } }
  }
  func refresh(_ engine: Engine) async {
    let identity = project
    do {
      let result = try await rpc(engine, "list")
      guard project == identity, !Task.isCancelled else { return }
      plans = result["suites"] as? [[String: Any]] ?? []
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func loadSource(_ engine: Engine) async {
    let identity = project; let chosen = path; let version = sourceVersion
    do {
      let value = try await rpc(engine, "source.open", ["path": chosen])
      guard project == identity, path == chosen, sourceVersion == version, !Task.isCancelled else { return }
      text = string(value, "yaml"); sourceDigest = string(value, "expected_file_digest"); failure = ""
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func saveSource(_ engine: Engine) async {
    let identity = project; let chosen = path; let source = text
    do {
      let value = try await rpc(engine, "source.save", ["path": chosen, "yaml": source, "expected_file_digest": sourceDigest])
      guard project == identity, path == chosen, !Task.isCancelled else { return }
      sourceDigest = string(value, "digest"); message = "Suite source saved. Prepare a new suite to pin these inputs."; failure = ""
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func prepare(_ engine: Engine) async {
    guard !busy else { return }; busy = true
    let identity = project; generation += 1; let token = generation; let source = text
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "prepare", ["yaml": source, "confirmed": true])
      guard project == identity, generation == token, !Task.isCancelled else { return }
      selected = string(result["plan"] as? [String: Any] ?? [:], "id"); board = result; failure = ""
      message = "Paired application projects and Factory snapshots prepared. No model execution has started."
      await refresh(engine)
    } catch { if project == identity, generation == token { failure = error.localizedDescription } }
  }
  func inspect(_ engine: Engine) async {
    let identity = project; let chosen = selected
    guard !chosen.isEmpty else { return }
    do {
      let result = try await rpc(engine, "inspect", ["suite": chosen])
      guard project == identity, selected == chosen, !Task.isCancelled else { return }
      board = result; failure = ""
    } catch { if project == identity, selected == chosen { failure = error.localizedDescription } }
  }
  func inspectEntry(_ engine: Engine) async {
    let identity = project; let chosen = selected; let row = entry
    guard !chosen.isEmpty, !row.isEmpty else { return }
    do {
      let result = try await rpc(engine, "entry", ["suite": chosen, "entry": row])
      guard project == identity, selected == chosen, entry == row, !Task.isCancelled else { return }
      detail = result; failure = ""
    } catch { if project == identity, selected == chosen, entry == row { failure = error.localizedDescription } }
  }
  func gate(_ engine: Engine, stage: String, digest: String, decision: String, reason: String) async {
    let identity = project; let chosen = selected; let row = entry
    do {
      let value = try await rpc(engine, "gate", ["suite": chosen, "entry": row, "stage": stage, "gate_digest": digest, "decision": decision, "reason": reason, "confirmed": true])
      guard project == identity, selected == chosen, entry == row else { return }
      board = value; failure = ""; await inspectEntry(engine)
    } catch { if project == identity, selected == chosen, entry == row { failure = error.localizedDescription } }
  }
  func run(_ engine: Engine) async {
    guard !busy, !selected.isEmpty else { return }
    let identity = project; let chosen = selected; let token = UUID(); operation = token; busy = true; failure = ""
    defer { if operation == token { busy = false } }
    do {
      let value = try await engine.call("factory.action.start", ["project": identity, "suite": chosen, "factory_action": "suite-run", "confirmed": true, "command_id": UUID().uuidString]) as? [String: Any] ?? [:]
      guard project == identity, selected == chosen, operation == token else { return }
      job = value; let id = string(value, "id")
      while !Task.isCancelled {
        let state = try await engine.call("jobs.get", ["id": id]) as? [String: Any] ?? [:]
        guard project == identity, selected == chosen, operation == token else { return }; job = state
        if !["queued", "running", "needs_approval", "cancelling"].contains(string(state, "status")) {
          let jobFailure = string(state, "status") != "completed" ? "Suite job \(string(state, "status")): \(pretty(state["result"]))" : ""
          await inspect(engine)
          if !entry.isEmpty { await inspectEntry(engine) }
          if !jobFailure.isEmpty { failure = jobFailure }
          message = "Suite checkpoint updated. Review gates, outcomes and missing evidence before continuing."
          return
        }
        try await Task.sleep(for: .milliseconds(350))
      }
    } catch { if project == identity, selected == chosen, operation == token { failure = error.localizedDescription } }
  }
  func retry(_ engine: Engine, stage: String, attempt: Int, reason: String) async {
    let identity = project; let chosen = selected; let row = entry
    do {
      let value = try await rpc(engine, "retry", ["suite": chosen, "entry": row, "stage": stage, "attempt": attempt, "reason": reason, "confirmed": true])
      guard project == identity, selected == chosen, entry == row else { return }
      board = value; failure = ""; await inspectEntry(engine)
    } catch { if project == identity, selected == chosen, entry == row { failure = error.localizedDescription } }
  }
  func cancel(_ engine: Engine) async {
    let id = string(job, "id"); guard busy, !id.isEmpty else { return }
    do { _ = try await engine.call("jobs.cancel", ["id": id]) }
    catch { failure = error.localizedDescription }
  }
}
