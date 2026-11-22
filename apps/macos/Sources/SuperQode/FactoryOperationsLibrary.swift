import SwiftUI

@MainActor final class FactoryOperationsLibrary: ObservableObject {
  @Published var readiness: [String: Any] = [:]
  @Published var packages: [[String: Any]] = []
  @Published var result: [String: Any] = [:]
  @Published var retention: [String: Any] = [:]
  @Published var retirement: [String: Any] = [:]
  @Published var busy = false
  @Published var failure = ""
  private(set) var project = ""
  private var generation = 0

  func enter(_ identity: String) {
    guard project != identity else { return }
    project = identity; generation += 1; readiness = [:]; packages = []; result = [:]; retention = [:]; retirement = [:]; busy = false; failure = ""
  }
  func refresh(_ engine: Engine) async {
    generation += 1
    let token = generation; let identity = project
    do {
      let response = try await engine.call("factory.operations.inspect", ["project": identity]) as? [String: Any] ?? [:]
      guard project == identity, generation == token, !Task.isCancelled else { return }
      readiness = response["readiness"] as? [String: Any] ?? [:]
      packages = response["packages"] as? [[String: Any]] ?? []; failure = ""
    } catch { if project == identity, generation == token { failure = error.localizedDescription } }
  }
  func perform(_ engine: Engine, _ action: String, _ params: [String: Any] = [:]) async {
    guard !busy else { return }; busy = true; generation += 1
    let identity = project; let token = generation
    defer { if project == identity { busy = false } }
    var arguments = params; arguments["project"] = identity; arguments["confirmed"] = true
    do {
      let response = try await engine.call("factory.operations." + action, arguments) as? [String: Any] ?? [:]
      guard project == identity, generation == token else { return }
      if action == "check" { readiness = response }
      if action == "retention.preview" { retention = response }
      else if action == "retire.preview" { retirement = response }
      else { result = response; retention = [:] }
      failure = ""
      if ["handover", "retention.apply"].contains(action) { await refresh(engine) }
    } catch { if project == identity, generation == token { failure = error.localizedDescription } }
  }
}
