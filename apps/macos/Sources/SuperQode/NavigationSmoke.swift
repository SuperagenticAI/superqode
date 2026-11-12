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
    @MainActor func mountedStudioEditor() -> SourceEditor.Editor? {
      @MainActor func find(in view: NSView) -> SourceEditor.Editor? {
        if let editor = view as? SourceEditor.Editor,
          editor.sourceDocumentID == "harness-studio:" + projectID { return editor }
        return view.subviews.lazy.compactMap { find(in: $0) }.first
      }
      guard let content = NSApp.windows.first(where: { $0.title == "SuperQode" })?.contentView else { return nil }
      return find(in: content)
    }
    /// The Models page keeps its workspace switcher mounted while hidden; the
    /// Local AI content itself mounts only when the page is active.
    @MainActor func mountedModelsSwitcher() -> NSSegmentedControl? {
      @MainActor func find(in view: NSView) -> NSSegmentedControl? {
        if let control = view as? NSSegmentedControl,
          (0..<control.segmentCount).contains(where: { control.label(forSegment: $0) == "Quick Start" }) {
          return control
        }
        return view.subviews.lazy.compactMap { find(in: $0) }.first
      }
      guard let content = NSApp.windows.first(where: { $0.title == "SuperQode" })?.contentView else { return nil }
      return find(in: content)
    }
    @MainActor func measure(passes: Int) async throws -> [String: Any] {
      let sections = [
        "Workspace", "Files", "Review", "Terminal", "Checkpoints", "Workspace",
        "Harness Hub", "Harness Studio", "Super Agent", "Evaluations", "Optimization",
        "Models", "Tools", "Threads", "Workspace", "Harness Studio", "Workspace",
      ]
      var worstTick = 0.0
      var currentPhase = section
      var worstPhase = ""
      var timings: [[String: Any]] = []
      var initialComposer: PromptEditor.Editor?
      var initialStudioEditor: SourceEditor.Editor?
      var studioEditorPreserved = true
      var initialModelsSwitcher: NSSegmentedControl?
      var modelsSwitcherPreserved = true
      let (ready, signal) = AsyncStream<Bool>.makeStream()
      let heartbeat = Task {
        signal.yield(true)
        signal.finish()
        while !Task.isCancelled {
          let start = ProcessInfo.processInfo.systemUptime
          let startedPhase = currentPhase
          do { try await Task.sleep(for: .milliseconds(10)) } catch { return }
          let elapsed = ProcessInfo.processInfo.systemUptime - start
          if elapsed > worstTick { worstTick = elapsed; worstPhase = startedPhase + " -> " + currentPhase }
        }
      }
      defer { heartbeat.cancel() }
      var readiness = ready.makeAsyncIterator()
      _ = await readiness.next()
      for _ in 0..<passes {
        for destination in sections {
          currentPhase = destination
          let started = ProcessInfo.processInfo.systemUptime
          section = destination
          try await Task.sleep(for: .milliseconds(30))
          timings.append(["section": destination, "input_resume_ms": (ProcessInfo.processInfo.systemUptime - started) * 1000])
          if initialComposer == nil && destination == "Workspace" { initialComposer = mountedComposer() }
          if destination == "Models" {
            let control = mountedModelsSwitcher()
            if let initialModelsSwitcher { modelsSwitcherPreserved = modelsSwitcherPreserved && control === initialModelsSwitcher }
            else { initialModelsSwitcher = control; modelsSwitcherPreserved = control != nil }
          }
          if destination == "Harness Studio" {
            let editor = mountedStudioEditor()
            if let initialStudioEditor { studioEditorPreserved = studioEditorPreserved && editor === initialStudioEditor }
            else { initialStudioEditor = editor; studioEditorPreserved = editor != nil }
          }
        }
      }
      heartbeat.cancel()
      await heartbeat.value
      return ["section_changes": sections.count * passes, "worst_ui_heartbeat_ms": worstTick * 1000,
        "composer_editor_preserved": initialComposer != nil && initialComposer === mountedComposer(),
        "models_page_preserved": initialModelsSwitcher != nil && modelsSwitcherPreserved,
        "models_page_disabled_while_hidden": initialModelsSwitcher.map { !$0.isEnabled } ?? false,
        "studio_editor_preserved": initialStudioEditor != nil && studioEditorPreserved,
        "studio_editor_disabled_while_hidden": initialStudioEditor.map {
          !$0.interactionEnabled && !$0.isEditable && $0.window?.firstResponder !== $0
        } ?? false,
        "slowest_phase": worstPhase, "steps": timings]
    }

    // First-open construction is part of the user experience too. Preserve and
    // gate it separately rather than hiding it in an untimed warm-up.
    let firstOpen = try await measure(passes: 1)
    var result = try await measure(passes: 3)
    result["first_open"] = firstOpen
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
    result["profiled_diagnostic_navigation"] = try await measure(passes: 3)
    await profile.value
    return result
  }
}


@MainActor func requireResponsiveNavigation(_ result: [String: Any]) throws {
  if let firstOpen = result["first_open"] as? [String: Any] {
    try requireResponsiveNavigation(firstOpen)
  }
  guard result["models_page_preserved"] as? Bool == true,
    result["models_page_disabled_while_hidden"] as? Bool == true else {
    throw EngineError(message: "Navigation recreated the Local AI page or left it enabled while hidden")
  }
  guard result["composer_editor_preserved"] as? Bool == true else {
    throw EngineError(message: "Navigation recreated the native composer instead of preserving it")
  }
  guard result["studio_editor_preserved"] as? Bool == true else {
    throw EngineError(message: "Navigation recreated the Harness Studio editor instead of preserving it")
  }
  guard result["studio_editor_disabled_while_hidden"] as? Bool == true else {
    throw EngineError(message: "The hidden Harness Studio editor still accepts input or retains focus")
  }
  guard (result["worst_ui_heartbeat_ms"] as? Double ?? .infinity) < 250 else {
    throw EngineError(message: "Workspace navigation blocked UI input: \(result)")
  }
}
