import SwiftUI

@MainActor final class FactoryCampaignLibrary: ObservableObject {
  @Published var campaigns: [[String: Any]] = []
  @Published var selected = ""
  @Published var preview: [String: Any] = [:]
  @Published var busy = false
  @Published var failure = ""
  private(set) var project = ""
  private var generation = 0
  var current: [String: Any] {
    campaigns.first { string($0["manifest"] as? [String: Any] ?? [:], "id") == selected } ?? [:]
  }
  func enter(_ identity: String) {
    guard identity != project else { return }
    project = identity; generation += 1; campaigns = []; selected = ""; preview = [:]; busy = false; failure = ""
  }
  func clearPreview() { generation += 1; preview = [:] }
  func perform(_ engine: Engine, _ action: String, _ extra: [String: Any] = [:]) async {
    guard !busy, !project.isEmpty else { return }
    busy = true; generation += 1
    let identity = project; let token = generation; let selection = selected
    defer { if project == identity { busy = false } }
    var params = extra; params["project"] = identity; params["confirmed"] = true
    do {
      let response = try await engine.call("factory.campaign." + action, params) as? [String: Any] ?? [:]
      guard project == identity, generation == token, !Task.isCancelled else { return }
      if action == "event.preview" {
        guard selected == selection else { return }; preview = response
      } else {
        let listing = action == "list" ? response : try await engine.call("factory.campaign.list", ["project": identity]) as? [String: Any] ?? [:]
        guard project == identity, generation == token, !Task.isCancelled else { return }
        campaigns = listing["campaigns"] as? [[String: Any]] ?? []
        if action == "create" { selected = string(response["manifest"] as? [String: Any] ?? [:], "id") }
        else if !campaigns.contains(where: { string($0["manifest"] as? [String: Any] ?? [:], "id") == selected }) { selected = "" }
        preview = [:]
      }
      failure = ""
    } catch { if project == identity, generation == token { failure = error.localizedDescription } }
  }
}
