import AppKit
import Foundation

@MainActor extension Workspace {
  /// Exercise mounted editors and inspectors. Profile only after a failed
  /// timing pass: suspending threads for stack samples must not affect its gate.
  func smokeNavigationResponsiveness() async throws -> [String: Any] {
    @MainActor func composer(in view: NSView) -> PromptEditor.Editor? {
      if let editor = view as? PromptEditor.Editor { return editor }
      return view.subviews.lazy.compactMap { composer(in: $0) }.first
    }
    @MainActor func mountedComposer() -> PromptEditor.Editor? {
      guard let content = NSApp.windows.first(where: { $0.title == "SuperQode" })?.contentView else { return nil }
      return composer(in: content)
    }
    @MainActor func measure() async throws -> [String: Any] {
      let sections = ["Workspace", "Files", "Review", "Terminal", "Checkpoints", "Workspace"]
      var worstTick = 0.0
      var currentPhase = section
      var worstPhase = ""
      var timings: [[String: Any]] = []
      var initialComposer: PromptEditor.Editor?
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
          if initialComposer == nil && destination == "Workspace" { initialComposer = mountedComposer() }
        }
      }
      heartbeat.cancel()
      await heartbeat.value
      return ["section_changes": 18, "worst_ui_heartbeat_ms": worstTick * 1000,
        "composer_editor_preserved": initialComposer != nil && initialComposer === mountedComposer(),
        "slowest_phase": worstPhase, "steps": timings]
    }

    var result = try await measure()
    guard (result["worst_ui_heartbeat_ms"] as? Double ?? 0) >= 250,
      ProcessInfo.processInfo.environment["SUPERQODE_NAV_PROFILE"] == "1" else { return result }
    let arguments = ProcessInfo.processInfo.arguments
    guard let index = arguments.firstIndex(of: "--snapshot-dir"), arguments.count > index + 1 else { return result }
    let directory = URL(fileURLWithPath: arguments[index + 1])
    let pid = ProcessInfo.processInfo.processIdentifier
    let profile = Task.detached(priority: .utility) {
      let process = Process()
      process.executableURL = URL(fileURLWithPath: "/usr/bin/sample")
      process.arguments = [String(pid), "3", "10", "-file", directory.appendingPathComponent("navigation-main-thread-sample.txt").path]
      process.standardOutput = FileHandle.nullDevice
      process.standardError = FileHandle.nullDevice
      do { try process.run(); process.waitUntilExit() } catch {}
    }
    result["profiled_diagnostic_navigation"] = try await measure()
    await profile.value
    return result
  }
}
