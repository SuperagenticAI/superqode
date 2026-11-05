import Foundation

@MainActor extension Workspace {
  /// Exercise the mounted workspace, including editor and inspector lifecycle
  /// callbacks, rather than measuring assignments to an unrendered model.
  func smokeNavigationResponsiveness() async throws -> [String: Any] {
    let sections = ["Workspace", "Files", "Review", "Terminal", "Checkpoints", "Workspace"]
    var worstTick = 0.0
    let heartbeat = Task {
      while !Task.isCancelled {
        let start = ProcessInfo.processInfo.systemUptime
        do { try await Task.sleep(for: .milliseconds(10)) } catch { return }
        worstTick = max(worstTick, ProcessInfo.processInfo.systemUptime - start)
      }
    }
    defer { heartbeat.cancel() }
    for _ in 0..<3 {
      for destination in sections {
        section = destination
        try await Task.sleep(for: .milliseconds(30))
      }
    }
    heartbeat.cancel()
    await heartbeat.value
    guard worstTick < 0.25 else {
      throw EngineError(message: "Workspace navigation blocked UI input for more than 250 ms")
    }
    return ["section_changes": 18, "worst_ui_heartbeat_ms": worstTick * 1000]
  }
}
