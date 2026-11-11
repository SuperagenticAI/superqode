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
    let runtimeID = "native-smoke-" + UUID().uuidString.lowercased()
    let saved = try await engine.call("local.runtimes.save", ["id": runtimeID, "template": "custom", "name": "Native fixture", "endpoint": "http://127.0.0.1:9/v1", "context": 4096, "include_usage": false]) as? [String: Any] ?? [:]
    let runtimes = try await engine.call("local.runtimes.catalog") as? [String: Any] ?? [:]
    let execution = try await engine.call("local.execution.status") as? [String: Any] ?? [:]
    let apple = try await engine.call("local.apple.status") as? [String: Any] ?? [:]
    let recipe = try await engine.call("local.runtimes.setup.plan", ["id": runtimeID]) as? [String: Any] ?? [:]
    _ = try await engine.call("local.runtimes.delete", ["id": runtimeID])
    guard saved["context"] as? Int == 4096, saved["include_usage"] as? Bool == false,
      (runtimes["profiles"] as? [[String: Any]])?.contains(where: { string($0, "id") == runtimeID }) == true,
      (execution["concurrency"] as? Int ?? 0) > 0,
      apple["available"] is Bool, !string(apple, "guidance").isEmpty,
      recipe["automatic"] as? Bool == false
    else { throw EngineError(message: "Native runtime profiles, execution status, Apple availability or manual setup guidance failed.") }
    let setup = try await engine.call("local.models.quickstart.catalog", ["project": projectID]) as? [String: Any] ?? [:]
    guard (setup["setup_presets"] as? [[String: Any]])?.count == 3 else { throw EngineError(message: "Hardware setup intentions were missing.") }
    let compareID = "native-compare-" + UUID().uuidString.lowercased()
    _ = try await engine.call("local.runtimes.save", ["id": compareID, "template": "custom", "endpoint": "http://127.0.0.1:1234/v1", "context": 4096, "tools": true])
    let comparison = try await engine.call("local.comparisons.catalog", ["project": projectID]) as? [String: Any] ?? [:]
    let localRoutes = comparison["routes"] as? [[String: Any]] ?? []
    guard let route = localRoutes.first(where: { string($0, "runtime") == compareID }) else { throw EngineError(message: "The native comparison did not discover the loopback fixture model.") }
    let reviewed = try await engine.call("local.comparisons.prepare", ["project": projectID, "context": 4096, "warmup": false, "selections": [["route": string(route, "id"), "harness": "core"], ["route": string(route, "id"), "harness": "no-tool"]]]) as? [String: Any] ?? [:]
    _ = try await engine.call("local.runtimes.delete", ["id": compareID])
    guard !string(reviewed, "digest").isEmpty, (reviewed["inspection"] as? [String: Any])?["task_count"] as? Int == 2,
      reviewed["suite_content"] == nil else { throw EngineError(message: "The native comparison review was not pinned to its fixed tasks.") }
    return "passed; hardware presets, independent-grader comparison review, shared catalog, 28-runtime matrix, profile round-trip and Apple availability without transferring weights or making generation requests"
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
