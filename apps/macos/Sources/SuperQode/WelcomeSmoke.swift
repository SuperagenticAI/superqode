import AppKit
import SwiftUI

@MainActor extension Workspace {
  func smokeWelcomeStartup() async {
    var report: [String: Any] = ["native": true]
    do {
      guard recoveryIssue.isEmpty, let previous = recoverySnapshot.lastDestination,
        projects.contains(where: { string($0, "id") == previous.projectID }),
        showWelcome, projectID.isEmpty else {
        throw EngineError(message: "Normal startup opened recovery automatically or failed to load the saved recent project.")
      }
      try await Task.sleep(for: .seconds(2))
      guard showWelcome, projectID.isEmpty, recoverySnapshot.lastDestination == previous,
        jobs.isEmpty else { throw EngineError(message: "Welcome navigated or started work without user input.") }
      if let index = ProcessInfo.processInfo.arguments.firstIndex(of: "--snapshot-dir"), ProcessInfo.processInfo.arguments.count > index + 1,
        let view = NSApp.windows.first(where: { $0.isVisible && $0.contentView != nil })?.contentView,
        let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) {
        view.layoutSubtreeIfNeeded(); view.cacheDisplay(in: view.bounds, to: bitmap)
        try bitmap.representation(using: .png, properties: [:])?.write(to:
          URL(fileURLWithPath: ProcessInfo.processInfo.arguments[index + 1]).appendingPathComponent("welcome-startup.png"))
      }
      report["passed"] = true
      report["welcome_startup"] = "passed; actual boot loaded a saved editor destination and recent project, then stayed on Welcome without starting work or making provider calls"
    } catch { report["passed"] = false; report["error"] = error.localizedDescription }
    let output = ProcessInfo.processInfo.environment["SUPERQODE_SMOKE_REPORT"] ?? "/tmp/superqode-welcome-smoke.json"
    try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: output))
    shutdown(); NSApp.terminate(nil)
  }
}
