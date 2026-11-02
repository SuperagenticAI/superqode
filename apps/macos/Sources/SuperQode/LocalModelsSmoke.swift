import Foundation

@MainActor extension Workspace {
  func smokeLocalModelWorkbench() async throws -> String {
    let before = try await engine.call("local.models.jobs") as? [[String: Any]] ?? []
    let catalog = try await engine.call("local.models.search", ["source": "recommended", "query": "qwen", "format": "gguf"]) as? [[String: Any]] ?? []
    guard !catalog.isEmpty, catalog.allSatisfy({ $0["fit"] is [String: Any] }) else {
      throw EngineError(message: "Local AI did not reuse the shared recommendation catalog.")
    }
    let plan = try await engine.call("local.models.prepare", ["action": "download", "source": "ollama", "model": "native-fixture:8b", "engine": "ollama"]) as? [String: Any] ?? [:]
    let storage = try await engine.call("local.models.storage") as? [String: Any] ?? [:]
    let hub = try await engine.call("local.models.hub.status") as? [String: Any] ?? [:]
    let compatibility = try await engine.call("local.models.compatibility", ["project": projectID]) as? [String: Any] ?? [:]
    let coreCheck = try await engine.call("local.models.prepare", ["action": "verify", "check": "core-read", "engine": "lmstudio", "model": "native-fixture-model"]) as? [String: Any] ?? [:]
    guard !string(storage, "hf_cache").isEmpty, !string(hub, "source").isEmpty,
      (compatibility["backends"] as? [[String: Any]])?.count == 28,
      string(coreCheck, "check") == "core-read", string(coreCheck, "endpoint") == "http://127.0.0.1:1234/v1"
    else { throw EngineError(message: "Local setup, full runtime matrix or reviewed Core check was missing.") }
    var rejected = false
    do { _ = try await engine.call("local.models.start", ["plan": string(plan, "id"), "expected_digest": "stale", "command_id": "must-not-run"]) }
    catch { rejected = error.localizedDescription.contains("changed") }
    let after = try await engine.call("local.models.jobs") as? [[String: Any]] ?? []
    guard rejected, before.count == after.count else { throw EngineError(message: "Reviewing a model download started an operation or accepted a stale plan.") }
    return "passed; shared catalog, storage/Hub setup, 28-runtime matrix and digest-bound download/Core-check review without transferring weights or making model calls"
  }

  func smokeBackgroundEngine() async throws -> String {
    let state = URL(fileURLWithPath: string(project, "path")).deletingLastPathComponent().appendingPathComponent("background-state").path
    let first = Engine()
    let second = Engine()
    do {
      try first.start(background: true, stateDirectory: state)
      let status = try await first.call("engine.status") as? [String: Any] ?? [:]
      let opened = try await first.call("projects.open", ["path": string(project, "path")]) as? [String: Any] ?? [:]
      let job = try await first.call("checks.start", ["project": string(opened, "id"), "command": "sleep 1", "command_id": "native-background-fixture"]) as? [String: Any] ?? [:]
      try await first.stopAndWait()
      try second.start(background: true, stateDirectory: state)
      let reconnected = try await second.call("engine.status") as? [String: Any] ?? [:]
      guard string(status, "instance") == string(reconnected, "instance"), string(status, "mode") == "background" else {
        throw EngineError(message: "Native reconnect replaced the background engine.")
      }
      var completed = false
      for _ in 0..<100 {
        let recorded = try await second.call("jobs.get", ["id": string(job, "id")]) as? [String: Any] ?? [:]
        if string(recorded, "status") == "completed" { completed = true; break }
        if string(recorded, "status") == "failed" { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      guard completed else { throw EngineError(message: "A check did not survive native bridge disconnect.") }
      _ = try await second.call("engine.shutdown", ["instance": string(status, "instance")])
      try await second.stopAndWait()
      return "passed; actual native bridge disconnect/reconnect retains one engine and a running check without replay or provider calls"
    } catch {
      first.stop(); second.stop()
      let cleanup = Engine()
      if (try? cleanup.start(management: true, stateDirectory: state)) != nil {
        if let status = try? await cleanup.call("engine.status") as? [String: Any] {
          _ = try? await cleanup.call("engine.shutdown", ["instance": string(status, "instance"), "cancel_active": true])
        }
        cleanup.stop()
      }
      throw error
    }
  }
}
