import Foundation

@MainActor extension Workspace {
  /// Exercise the mounted workspace, including editor and inspector lifecycle
  /// callbacks, rather than measuring assignments to an unrendered model.
  func smokeNavigationResponsiveness() async throws -> [String: Any] {
    let sections = ["Workspace", "Files", "Review", "Terminal", "Checkpoints", "Workspace"]
    var worstTick = 0.0
    var currentPhase = section
    var worstPhase = ""
    var timings: [[String: Any]] = []
    let arguments = ProcessInfo.processInfo.arguments
    let snapshotIndex = arguments.firstIndex(of: "--snapshot-dir")
    let directory = snapshotIndex.flatMap { arguments.count > $0 + 1 ? URL(fileURLWithPath: arguments[$0 + 1]) : nil }
    let pid = ProcessInfo.processInfo.processIdentifier
    let profile = Task.detached(priority: .utility) {
      guard ProcessInfo.processInfo.environment["SUPERQODE_NAV_PROFILE"] == "1", let directory else { return }
      let process = Process()
      process.executableURL = URL(fileURLWithPath: "/usr/bin/sample")
      process.arguments = [String(pid), "3", "10", "-file", directory.appendingPathComponent("navigation-main-thread-sample.txt").path]
      process.standardOutput = FileHandle.nullDevice
      process.standardError = FileHandle.nullDevice
      do { try process.run(); process.waitUntilExit() } catch {}
    }
    let heartbeat = Task {
      while !Task.isCancelled {
        let start = ProcessInfo.processInfo.systemUptime
        let startedPhase = currentPhase
        do { try await Task.sleep(for: .milliseconds(10)) } catch { return }
        let elapsed = ProcessInfo.processInfo.systemUptime - start
        if elapsed > worstTick { worstTick = elapsed; worstPhase = startedPhase + " -> " + currentPhase }
      }
    }
    defer { heartbeat.cancel() }
    for _ in 0..<3 {
      for destination in sections {
        currentPhase = destination
        let started = ProcessInfo.processInfo.systemUptime
        section = destination
        try await Task.sleep(for: .milliseconds(30))
        timings.append(["section": destination, "input_resume_ms": (ProcessInfo.processInfo.systemUptime - started) * 1000])
      }
    }
    heartbeat.cancel()
    await heartbeat.value
    await profile.value
    return ["section_changes": 18, "worst_ui_heartbeat_ms": worstTick * 1000,
      "slowest_phase": worstPhase, "steps": timings]
  }
}
