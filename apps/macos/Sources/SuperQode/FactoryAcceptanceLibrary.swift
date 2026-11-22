import SwiftUI

/// Shared engine receipts with project, input and run identity kept across navigation.
@MainActor final class FactoryAcceptanceLibrary: ObservableObject {
  @Published var description = "" { didSet { if description != oldValue { invalidateProposal() } } }
  @Published var checksText = "{}" { didSet { if checksText != oldValue { invalidateProposal() } } }
  @Published private(set) var proposal: [String: Any] = [:]
  @Published private(set) var generationResult: [String: Any] = [:]
  @Published private(set) var job: [String: Any] = [:]
  @Published private(set) var trace: [String: Any] = [:]
  @Published private(set) var outcomes: [String: Any] = [:]
  @Published private(set) var receipts: [[String: Any]] = []
  @Published var observation = ""
  @Published var outcome = "unknown"
  @Published var humanMinutes = ""
  @Published private(set) var busy = false
  @Published var failure = ""
  @Published var message = ""
  private(set) var project = ""
  private(set) var run = ""
  private var source = ""
  private var inputs = 0
  private var operation = UUID()
  private var traceGeneration = 0
  private var outcomeGeneration = 0
  private var intakeGeneration = 0
  private var drafts: [String: (String, String)] = [:]
  private var observations: [String: (String, String, String)] = [:]

  func enter(_ identity: String) {
    guard identity != project else { return }
    if !project.isEmpty { drafts[project] = (description, checksText); saveObservation() }
    project = identity; run = ""; source = ""; inputs += 1; operation = UUID()
    traceGeneration += 1; outcomeGeneration += 1; intakeGeneration += 1
    proposal = [:]; generationResult = [:]; job = [:]; trace = [:]; outcomes = [:]; receipts = []
    busy = false; failure = ""; message = ""
    description = drafts[identity]?.0 ?? ""; checksText = drafts[identity]?.1 ?? "{}"
    observation = ""; outcome = "unknown"; humanMinutes = ""
  }
  func sourceChanged(_ value: String) {
    guard source != value else { return }; source = value; invalidateProposal()
  }
  private func invalidateProposal() { inputs += 1; proposal = [:]; generationResult = [:] }
  private func saveObservation() {
    if !run.isEmpty { observations[project + "\n" + run] = (observation, outcome, humanMinutes) }
  }
  func selectRun(_ value: String) {
    guard run != value else { return }; saveObservation(); run = value
    traceGeneration += 1; trace = [:]
    let saved = observations[project + "\n" + value]
    observation = saved?.0 ?? ""; outcome = saved?.1 ?? "unknown"; humanMinutes = saved?.2 ?? ""
  }
  private func call(_ engine: Engine, _ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
    var arguments = params; arguments["project"] = project
    return try await engine.call("factory." + method, arguments) as? [String: Any] ?? [:]
  }
  func refreshTrace(_ engine: Engine) async {
    guard !project.isEmpty, !run.isEmpty else { return }
    traceGeneration += 1
    let identity = project; let selected = run; let token = traceGeneration
    do {
      let result = try await call(engine, "evidence.trace", ["run": selected])
      guard project == identity, run == selected, token == traceGeneration, !Task.isCancelled else { return }
      trace = result; failure = ""
    } catch { if project == identity, run == selected, token == traceGeneration, !Task.isCancelled { trace = [:]; failure = error.localizedDescription } }
  }
  func refreshOutcomes(_ engine: Engine) async {
    guard !project.isEmpty else { return }; outcomeGeneration += 1
    let identity = project; let token = outcomeGeneration
    do {
      let result = try await call(engine, "evidence.outcomes")
      guard project == identity, token == outcomeGeneration, !Task.isCancelled else { return }
      outcomes = result; failure = ""
    } catch { if project == identity, token == outcomeGeneration, !Task.isCancelled { failure = error.localizedDescription } }
  }
  func refreshReceipts(_ engine: Engine) async {
    guard !project.isEmpty else { return }; intakeGeneration += 1
    let identity = project; let token = intakeGeneration
    do {
      let result = try await call(engine, "intake.receipts")
      guard project == identity, token == intakeGeneration, !Task.isCancelled else { return }
      receipts = result["decisions"] as? [[String: Any]] ?? []; failure = ""
    } catch { if project == identity, token == intakeGeneration, !Task.isCancelled { failure = error.localizedDescription } }
  }
  func draft(_ engine: Engine) async { await propose(engine, provider: "", model: "") }
  func generate(_ engine: Engine, provider: String, model: String) async { await propose(engine, provider: provider, model: model) }
  private func propose(_ engine: Engine, provider: String, model: String) async {
    guard !busy, !project.isEmpty else { return }
    let identity = project; let token = inputs; let op = UUID(); operation = op; busy = true
    failure = ""; proposal = [:]; generationResult = [:]; job = [:]
    defer { if project == identity, operation == op { busy = false } }
    do {
      var result: [String: Any]
      if provider.isEmpty {
        guard checksText.utf8.count <= 250000,
          let checks = try JSONSerialization.jsonObject(with: Data(checksText.utf8)) as? [String: Any] else {
          throw EngineError(message: "Enter a bounded JSON object mapping final check names to protected probe manifests.")
        }
        result = try await call(engine, "verifier.draft", ["checks": checks, "yaml": source])
      } else {
        let started = try await call(engine, "action.start", ["factory_action": "verifier-generate",
          "confirmed": true, "command_id": UUID().uuidString, "yaml": source,
          "description": description, "provider": provider, "model": model])
        guard project == identity, operation == op else { return }; job = started
        let id = string(started, "id")
        while true {
          let current = try await engine.call("jobs.get", ["id": id]) as? [String: Any] ?? [:]
          guard project == identity, operation == op, !Task.isCancelled else { return }; job = current
          if !["queued", "running", "cancelling", "needs_approval"].contains(string(current, "status")) {
            guard string(current, "status") == "completed" else { throw EngineError(message: "Verifier drafting " + string(current, "status") + ": " + pretty(current["result"])) }
            result = current["result"] as? [String: Any] ?? [:]; break
          }
          try await Task.sleep(for: .milliseconds(500))
        }
      }
      guard project == identity, operation == op, !Task.isCancelled else { return }
      guard token == inputs else { message = "Inputs changed during drafting. Your edits are preserved; prepare a fresh verifier proposal."; return }
      generationResult = result
      proposal = provider.isEmpty ? result : result["proposal"] as? [String: Any] ?? [:]
      message = proposal.isEmpty ? "Review the unsupported capabilities before choosing an execution setup."
        : "Proposal prepared. Review every expectation and the definition diff before saving. No checks have run."
    } catch { if project == identity, operation == op, token == inputs, !Task.isCancelled { failure = error.localizedDescription } }
  }
  func install(_ engine: Engine) async -> Bool {
    guard !busy, !project.isEmpty, !proposal.isEmpty else { return false }
    let identity = project; let token = inputs; let op = UUID(); operation = op; busy = true
    let reviewed = proposal; job = [:]
    defer { if project == identity, operation == op { busy = false } }
    do {
      let result = try await call(engine, "verifier.install", ["proposal": reviewed, "digest": string(reviewed, "digest"), "confirmed": true])
      guard project == identity, operation == op else { return false }
      proposal = [:]
      guard token == inputs else { message = "Reviewed verifiers were saved. Newer draft edits are preserved; reload the saved definition when ready."; return false }
      failure = ""; message = "Verifier configuration saved. Prepare a fresh trial to measure the protected checks."
      return result["saved"] as? Bool == true
    } catch { if project == identity, operation == op { failure = error.localizedDescription }; return false }
  }
  func recordOutcome(_ engine: Engine) async {
    guard !busy, !project.isEmpty, !run.isEmpty else { return }
    let identity = project; let selected = run; let op = UUID(); operation = op; busy = true
    defer { if project == identity, operation == op { busy = false } }
    do {
      var minutes: Any = NSNull()
      if !humanMinutes.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
        guard let value = Double(humanMinutes), value.isFinite, (0...525600).contains(value) else {
          throw EngineError(message: "Enter finite human minutes from 0 to 525600, or leave them unknown.")
        }; minutes = value
      }
      _ = try await call(engine, "evidence.record-outcome", ["run": selected, "observation": observation,
        "outcome": outcome, "human_minutes": minutes, "confirmed": true])
      guard project == identity, run == selected, operation == op else { return }
      failure = ""; message = "Attributed outcome recorded for this run. It is separate from verification and release approval."
      await refreshOutcomes(engine)
    } catch { if project == identity, run == selected, operation == op { failure = error.localizedDescription } }
  }
  func cancelGeneration(_ engine: Engine) async {
    let id = string(job, "id"); guard busy, !id.isEmpty else { return }
    let identity = project
    do { _ = try await engine.call("jobs.cancel", ["id": id]) }
    catch { if project == identity { failure = error.localizedDescription } }
  }
  static func measurement(_ value: Any?, decimals: Int = 0) -> String {
    guard let number = value as? NSNumber, number.doubleValue.isFinite else { return "Unknown" }
    return String(format: "%.*f", decimals, number.doubleValue)
  }
}
