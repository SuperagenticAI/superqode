import AppKit
import Foundation

@MainActor extension Workspace {
  /// Exercise native controls on an explicitly marked disposable validation project.
  func inspectFactoryAcceptance() async {
    var report: [String: Any] = [:]
    do {
      guard let source = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_VALIDATION_ROOT"] ?? ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"],
        !projectID.isEmpty, string(project, "path").hasPrefix(source + "/.superqode/validation/") else {
        throw EngineError(message: "Acceptance inspection requires a repository-local validation project")
      }
      let root = URL(fileURLWithPath: string(project, "path"))
      guard FileManager.default.fileExists(atPath: root.appendingPathComponent(".superqode/native-acceptance-fixture.json").path) else {
        throw EngineError(message: "Acceptance inspection requires its explicit disposable fixture marker")
      }
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio; studio.enter(projectID)
      await studio.load(engine: engine); await studio.validate(engine: engine); await studio.refresh(engine: engine)
      section = "Factory Studio"; showWelcome = false
      func find(_ match: @escaping (NSButton) -> Bool) -> NSButton? {
        func walk(_ view: NSView) -> NSButton? {
          if let button = view as? NSButton, match(button) { return button }
          return view.subviews.lazy.compactMap(walk).first
        }
        return NSApp.windows.lazy.compactMap { $0.contentView.flatMap(walk) }.first
      }
      var actions = 0
      func press(_ identifier: String) async throws {
        for _ in 0..<120 {
          if let button = find({ $0.identifier?.rawValue == identifier }), button.isEnabled {
            button.performClick(nil); actions += 1; try await Task.sleep(for: .milliseconds(100)); return
          }
          try await Task.sleep(for: .milliseconds(25))
        }
        throw EngineError(message: "Native acceptance control unavailable: " + identifier)
      }
      try await press("factory.group.build"); try await press("factory.tab.Acceptance")
      let library = studio.acceptance
      library.checksText = try String(contentsOf: root.appendingPathComponent(".superqode/native-acceptance-fixture.json"), encoding: .utf8)
      try await press("factory.verifier.prepare")
      for _ in 0..<120 { if !library.proposal.isEmpty || !library.failure.isEmpty { break }; try await Task.sleep(for: .milliseconds(25)) }
      guard !library.proposal.isEmpty, library.failure.isEmpty, library.proposal["execution_started"] as? Bool == false,
        !string(library.proposal, "diff").isEmpty else { throw EngineError(message: "Native verifier draft failed: " + library.failure) }
      try await press("factory.verifier.review"); try await press("factory.verifier.save")
      var confirmed = false
      for _ in 0..<120 {
        if let button = find({ $0.title == "Continue" }), button.isEnabled { button.performClick(nil); actions += 1; confirmed = true; break }
        try await Task.sleep(for: .milliseconds(25))
      }
      guard confirmed else { throw EngineError(message: "Verifier save confirmation did not appear") }
      for _ in 0..<160 { if library.proposal.isEmpty && !library.busy { break }; try await Task.sleep(for: .milliseconds(25)) }
      guard library.proposal.isEmpty, library.failure.isEmpty else { throw EngineError(message: "Native verifier save failed: " + library.failure) }
      await studio.load(engine: engine); await studio.validate(engine: engine)
      await studio.refreshSources(engine: engine)
      let current = studio.text
      await library.draft(engine)
      guard !library.proposal.isEmpty else { throw EngineError(message: "Could not prepare stale-source validation") }
      let changed = current.replacingOccurrences(of: "name: native-research-validation", with: "name: stale-source-validation")
      guard changed != current else { throw EngineError(message: "Unexpected disposable fixture name") }
      let target = root.appendingPathComponent(".superqode/factory.yaml")
      try changed.write(to: target, atomically: true, encoding: .utf8)
      let rejected = !(await library.install(engine)) && library.failure.contains("changed")
      try current.write(to: target, atomically: true, encoding: .utf8)
      guard rejected else { throw EngineError(message: "Stale verifier source was not rejected") }
      library.failure = ""
      await studio.validate(engine: engine); await studio.refreshSources(engine: engine)
      guard let selected = studio.runs.first else { throw EngineError(message: "Expected a recorded disposable run") }
      studio.run = string(selected, "id"); await studio.inspect(engine: engine); await library.refreshTrace(engine)
      guard library.trace["requirements_declared"] as? Bool == true, library.trace["covered"] as? Int == 0 else {
        throw EngineError(message: "Unexecuted requirements unexpectedly appeared covered")
      }
      await library.refreshOutcomes(engine); await library.refreshReceipts(engine)
      let revisions = library.outcomes["revisions"] as? [[String: Any]] ?? []
      guard let outcome = revisions.first, FactoryAcceptanceLibrary.measurement(outcome["cost_usd"]) == "Unknown",
        FactoryAcceptanceLibrary.measurement(outcome["human_minutes"]) == "Unknown",
        Set(library.receipts.map { string($0, "status") }).isSuperset(of: ["queued", "duplicate", "filtered"]) else {
        throw EngineError(message: "Native receipt or unknown-cost evidence missing")
      }
      var captures: [String] = []
      for (group, tab) in [("build", "Acceptance"), ("run", "Runs"), ("improve", "ImproveEvidence"), ("manage", "Operations")] {
        studio.navigation.selectGroup(group); studio.navigation.select(tab)
        try await Task.sleep(for: .milliseconds(150))
        if group == "run" { try await press("factory.run.coverage") }
        if group == "build" {
          func editor(_ view: NSView) -> NSView? {
            if let value = view as? SourceEditor.Editor, value.sourceDocumentID == "factory-verifier-checks:" + projectID { return value }
            return view.subviews.lazy.compactMap(editor).first
          }
          if let view = NSApp.windows.lazy.compactMap({ $0.contentView.flatMap(editor) }).first {
            var parent = view.enclosingScrollView?.superview
            while let current = parent {
              if let scroll = current as? NSScrollView, let document = scroll.documentView {
                let rect = view.convert(view.bounds, to: document)
                scroll.contentView.scroll(to: NSPoint(x: 0, y: max(0, rect.minY - 120)))
                scroll.reflectScrolledClipView(scroll.contentView)
              }
              parent = current.superview
            }
          }
          try await Task.sleep(for: .milliseconds(100))
        }
        if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"], let content = NSApp.windows.first(where: { $0.contentView != nil && $0.frame.width > 600 })?.contentView,
          let bitmap = content.bitmapImageRepForCachingDisplay(in: content.bounds) {
          content.cacheDisplay(in: content.bounds, to: bitmap)
          let url = URL(fileURLWithPath: destination).deletingLastPathComponent().appendingPathComponent("acceptance-" + group + ".png")
          try bitmap.representation(using: .png, properties: [:])?.write(to: url); captures.append(url.path)
        }
      }
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count == after.count else { throw EngineError(message: "Native acceptance inspection unexpectedly started a job") }
      report = ["passed": true, "native_button_actions": actions, "reviewed_configuration_saved": true,
        "stale_source_rejected": true, "unexecuted_requirements_uncovered": true, "unknown_cost_preserved": true,
        "intake_dispositions": Array(Set(library.receipts.map { string($0, "status") })).sorted(),
        "new_jobs": 0, "human_review": false, "operator": "automated disposable-fixture controller",
        "release_authorized": false, "screenshots": captures]
    } catch { report = ["passed": false, "error": error.localizedDescription] }
    if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: destination))
    }
  }
}
