import SwiftUI

@MainActor extension Workspace {
  func changeBackgroundEngine(_ enabled: Bool) async throws {
    guard !anyActive, !busy, !openingProject, !restoringNavigation, !switchingBackgroundEngine else {
      throw EngineError(message: "Finish or stop active work before changing engine mode.")
    }
    switchingBackgroundEngine = true
    defer { switchingBackgroundEngine = false }
    if backgroundEngineMode {
      let status = try await engine.call("engine.status") as? [String: Any] ?? [:]
      _ = try await engine.call("engine.shutdown", ["instance": string(status, "instance")])
      try await waitForBackgroundExit(status["pid"] as? Int ?? 0)
    }
    try await engine.stopAndWait()
    UserDefaults.standard.set(enabled, forKey: "nativeBackgroundEngine")
    connected = false
    await boot()
  }
  func recoverBackgroundEngine() async throws {
    let control = Engine()
    try control.start(management: true)
    defer { control.stop() }
    let status = try await control.call("engine.status") as? [String: Any] ?? [:]
    guard confirm("Stop the existing background engine?",
      "This stops its \(status["active_jobs"] as? Int ?? 0) active operations. Recorded history and files remain; interrupted prompts are not replayed.", button: "Stop engine and active work") else { return }
    _ = try await control.call("engine.shutdown", ["instance": string(status, "instance"), "cancel_active": true])
    try await waitForBackgroundExit(status["pid"] as? Int ?? 0)
    try await control.stopAndWait()
    try await engine.stopAndWait()
    connected = false
    await boot()
  }
  private func waitForBackgroundExit(_ pid: Int) async throws {
    guard pid > 0 else { throw EngineError(message: "The engine did not identify its process. Reconnect before changing modes.") }
    for _ in 0..<240 {
      if kill(Int32(pid), 0) != 0 && errno == ESRCH { return }
      try await Task.sleep(for: .milliseconds(100))
    }
    throw EngineError(message: "The background engine is still closing. Wait for its workers to stop, then reconnect.")
  }
}

struct BackgroundEngineControls: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Toggle("Keep agent work running when the app quits", isOn: Binding(
        get: { app.backgroundEngineMode },
        set: { enabled in app.perform { try await app.changeBackgroundEngine(enabled) } }))
        .disabled(!app.connected || app.anyActive || app.busy || app.switchingBackgroundEngine || app.openingProject)
      Text(app.backgroundEngineMode
        ? "The background engine stays on this Mac. Reopen the app to reconnect to existing work. Terminals close with the app; stopping the engine or restarting the Mac interrupts agent work."
        : "Enable while idle to move execution to a private background engine. The app reconnects without sending a task.")
        .font(.caption).foregroundStyle(.secondary)
      if app.switchingBackgroundEngine { ProgressView("Reconnecting engine…").controlSize(.small) }
      if !app.connected {
        Button("Reconnect engine") { app.perform { try await app.engine.stopAndWait(); await app.boot() } }
          .disabled(app.switchingBackgroundEngine)
        Button("Inspect and stop an existing engine…") { app.perform { try await app.recoverBackgroundEngine() } }
      }
    }
  }
}
