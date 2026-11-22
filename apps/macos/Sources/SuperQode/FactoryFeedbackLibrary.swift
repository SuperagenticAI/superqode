import Foundation

@MainActor final class FactoryFeedbackLibrary: ObservableObject {
  @Published private(set) var project = ""
  @Published var issues: [[String: Any]] = []
  @Published var selected = ""
  @Published var detail: [String: Any] = [:]
  @Published var observation = ""
  @Published var category = "unknown" { didSet { reviewVersion += 1 } }
  @Published var notes = "" { didSet { reviewVersion += 1 } }
  @Published var kind = "stage_goal"
  @Published var value = ""
  @Published var proposalID = ""
  @Published var proposal: [String: Any] = [:]
  @Published var busy = false
  @Published var failure = ""
  @Published var message = ""
  private var reviewVersion = 0
  private var drafts: [String: (String, String)] = [:]
  let categories = ["application_defect", "model_protocol", "provider_infrastructure", "runtime_infrastructure", "evaluation_fault", "evidence_or_recovery", "policy_budget", "unknown"]

  private func remember() { if !selected.isEmpty { drafts[project + "\n" + selected] = (category, notes) } }
  func enter(_ id: String) {
    guard id != project else { return }; remember(); project = id
    selected = ""; detail = [:]; issues = []; observation = ""; notes = ""; category = "unknown"
    proposalID = ""; proposal = [:]; busy = false; failure = ""; message = ""; value = ""
  }
  func rpc(_ engine: Engine, _ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
    var request = params; request["project"] = project
    return try await engine.call("factory.suite.feedback." + method, request) as? [String: Any] ?? [:]
  }
  func refresh(_ engine: Engine) async {
    let identity = project
    do {
      let result = try await rpc(engine, "list")
      guard project == identity, !Task.isCancelled else { return }
      issues = result["issues"] as? [[String: Any]] ?? []
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func scan(_ engine: Engine, suite: String) async {
    guard !busy, !suite.isEmpty else { return }; busy = true
    let identity = project; defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "scan", ["suite": suite, "confirmed": true])
      guard project == identity else { return }
      issues = result["issues"] as? [[String: Any]] ?? []; failure = ""
      message = "Added \(result["added_observations"] as? Int ?? 0) new recorded observations. Re-scanning the same evidence does not increase the count. No models were called."
      let unavailable = result["scan_issues"] as? [[String: Any]] ?? []
      if !unavailable.isEmpty { failure = "Some sources could not be verified: " + unavailable.map { string($0, "entry") + ": " + string($0, "issue") }.joined(separator: "\n") }
    } catch { if project == identity { failure = error.localizedDescription } }
  }
  func select(_ engine: Engine, id: String) async {
    remember(); selected = id; detail = [:]; observation = ""; proposal = [:]; proposalID = ""; value = ""
    let draft = drafts[project + "\n" + id]; category = draft?.0 ?? "unknown"; notes = draft?.1 ?? ""
    await inspect(engine, restoreReview: draft == nil)
  }
  func inspect(_ engine: Engine, restoreReview: Bool = false) async {
    let identity = project; let id = selected; let version = reviewVersion
    guard !id.isEmpty else { return }
    do {
      let result = try await rpc(engine, "detail", ["issue": id])
      guard project == identity, selected == id, !Task.isCancelled else { return }
      detail = result; failure = ""
      if restoreReview && version == reviewVersion {
        let review = (result["reviews"] as? [[String: Any]] ?? []).last ?? [:]
        category = string(review, "category", string(result, "suggested_category", "unknown")); notes = string(review, "notes")
      }
      let observations = result["observations"] as? [[String: Any]] ?? []
      if !observations.contains(where: { string($0, "id") == observation }) { observation = observations.first.map { string($0, "id") } ?? ""; resetValue() }
      if proposalID.isEmpty { proposalID = (result["proposals"] as? [[String: Any]])?.last.map { string($0, "id") } ?? "" }
      if !proposalID.isEmpty { await fetchProposal(engine) }
    } catch { if project == identity, selected == id { failure = error.localizedDescription } }
  }
  func resetValue() {
    let row = (detail["observations"] as? [[String: Any]] ?? []).first { string($0, "id") == observation } ?? [:]
    value = string(row, kind == "model_route" ? "model" : "stage_goal")
  }
  func review(_ engine: Engine, status: String) async {
    guard !busy else { return }; busy = true
    let identity = project; let id = selected; let version = reviewVersion
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "review", ["issue": id, "review_digest": string(detail, "review_digest"), "category": category, "status": status, "notes": notes, "confirmed": true])
      guard project == identity, selected == id else { return }
      detail = result; failure = ""; remember(); await refresh(engine)
      message = version == reviewVersion ? "Review recorded. Classification is operator judgment, not proof of root cause." : "Review recorded for the submitted note. Your newer edits are preserved."
    } catch { if project == identity, selected == id { failure = error.localizedDescription } }
  }
  func propose(_ engine: Engine) async {
    guard !busy else { return }; busy = true
    let identity = project; let id = selected; let source = observation
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "propose", ["issue": id, "observation": source, "review_digest": string(detail, "review_digest"), "kind": kind, "value": value, "confirmed": true])
      guard project == identity, selected == id, observation == source else { return }
      proposalID = string(result, "id"); proposal = result; failure = ""; await inspect(engine)
      message = "Unmeasured experiment proposal created. Prepare and run its paired suite explicitly."
    } catch { if project == identity, selected == id { failure = error.localizedDescription } }
  }
  func fetchProposal(_ engine: Engine) async {
    let identity = project; let id = selected; let token = proposalID
    guard !token.isEmpty else { return }
    do {
      let result = try await rpc(engine, "proposal", ["issue": id, "proposal": token])
      guard project == identity, selected == id, proposalID == token, !Task.isCancelled else { return }
      proposal = result; failure = ""
    } catch { if project == identity, selected == id, proposalID == token { failure = error.localizedDescription } }
  }
  @discardableResult func loadDraft(_ engine: Engine, into suites: FactoryTrialSuiteLibrary) async -> Bool {
    let identity = project; let id = selected; let token = proposalID; let version = suites.sourceVersion
    do {
      let result = try await rpc(engine, "proposal", ["issue": id, "proposal": token, "for_execution": true])
      guard project == identity, selected == id, proposalID == token, suites.project == identity, suites.sourceVersion == version else { message = "Suite draft changed while loading. Your edits were preserved."; return false }
      suites.selected = ""; suites.path = string(result, "suite_path"); suites.text = string(result, "suite_yaml"); suites.sourceDigest = string(result, "suite_file_digest")
      message = "Experiment loaded into the suite editor. Review its contract, then prepare and execute explicitly."
      return true
    } catch { if project == identity, selected == id { failure = error.localizedDescription }; return false }
  }
  func attach(_ engine: Engine, suite: String) async {
    guard !busy else { return }; busy = true
    let identity = project; let id = selected; let token = proposalID
    defer { if project == identity { busy = false } }
    do {
      let result = try await rpc(engine, "attach", ["issue": id, "proposal": token, "suite": suite, "confirmed": true])
      guard project == identity, selected == id, proposalID == token else { return }
      proposal = result; failure = ""; message = "Matching trial evidence linked. This grants no promotion or release authority."
    } catch { if project == identity, selected == id, proposalID == token { failure = error.localizedDescription } }
  }
}
