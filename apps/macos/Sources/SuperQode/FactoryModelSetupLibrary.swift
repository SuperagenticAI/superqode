import Foundation
import Combine

/// Factory-local selections and read-only connection evidence. Credentials stay in Connect.
@MainActor final class FactoryModelSetupLibrary: ObservableObject {
  @Published var draftingReference = "" { didSet { if oldValue != draftingReference { invalidate() } } }
  @Published var allowCloud = true { didSet { if oldValue != allowCloud { invalidate() } } }
  @Published private(set) var draftingHarness = "no-tool"
  @Published private(set) var report: [String: Any] = [:]
  @Published private(set) var checking = false
  @Published private(set) var failure = ""
  private(set) var project = ""
  private var generation = 0
  private var selections: [String: (String, String, Bool)] = [:]

  var provider: String { draftingReference.split(separator: "/", maxSplits: 1).first.map(String.init) ?? "" }
  var model: String {
    let parts = draftingReference.split(separator: "/", maxSplits: 1)
    return parts.count == 2 ? String(parts[1]) : ""
  }
  var drafting: [String: Any] { report["drafting"] as? [String: Any] ?? [:] }
  var execution: [[String: Any]] { report["execution"] as? [[String: Any]] ?? [] }
  var draftingBlocked: Bool { !draftingReference.isEmpty && (drafting["eligible"] as? Bool) == false }
  var isPrivacyBlocked: Bool { draftingBlocked && string(drafting, "state") == "privacy-blocked" }

  func enter(_ identity: String) {
    guard identity != project else { return }
    if !project.isEmpty { selections[project] = (draftingReference, draftingHarness, allowCloud) }
    project = identity
    let saved = selections[identity]
    draftingHarness = saved?.1 ?? "no-tool"
    draftingReference = saved?.0 ?? ""
    allowCloud = saved?.2 ?? true
    invalidate()
  }

  func useConnected(provider: String, model: String, harness: String) {
    guard !provider.isEmpty, provider != "acp", !model.isEmpty else { return }
    draftingHarness = harness
    draftingReference = provider + "/" + model
    invalidate()
  }

  func invalidate() {
    generation += 1
    if !report.isEmpty { report = [:] }
    if !failure.isEmpty { failure = "" }
    if checking { checking = false }
  }

  func inspect(engine: Engine, yaml: String, checkConnections: Bool = false) async {
    guard !project.isEmpty else { return }
    generation += 1
    let token = generation; let identity = project
    checking = true; failure = ""
    defer { if project == identity, generation == token { checking = false } }
    do {
      let value = try await engine.call("factory.models.inspect", [
        "project": identity, "yaml": yaml, "drafting_model": draftingReference,
        "drafting_harness": draftingHarness, "check_connections": checkConnections,
        "allow_cloud": allowCloud,
      ]) as? [String: Any] ?? [:]
      guard project == identity, generation == token else { return }
      report = value
    } catch {
      guard project == identity, generation == token else { return }
      failure = error.localizedDescription
    }
  }
}
