import AppKit
import Foundation

@MainActor extension Workspace {
  /// Inspect an explicit disposable Factory export through native controls.
  func inspectFactoryExport() async {
    var report: [String: Any] = [:]
    do {
      guard let root = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_VALIDATION_ROOT"], !projectID.isEmpty,
        string(project, "path").hasPrefix(root + "/.superqode/validation/") else { throw EngineError(message: "Export inspection requires a repository-local validation project") }
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio; studio.enter(projectID); section = "Factory Studio"; showWelcome = false
      // Let the mounted page finish its initial read before reviewing this fixture.
      try await Task.sleep(for: .milliseconds(250))
      await studio.load(engine: engine); await studio.validate(engine: engine)
      func find(_ id: String) -> NSButton? {
        func walk(_ view: NSView) -> NSButton? {
          if let button = view as? NSButton, button.identifier?.rawValue == id { return button }
          return view.subviews.lazy.compactMap(walk).first
        }
        return NSApp.windows.lazy.compactMap { $0.contentView.flatMap(walk) }.first
      }
      func press(_ id: String) async throws {
        for _ in 0..<120 {
          if let button = find(id), button.isEnabled { button.performClick(nil); try await Task.sleep(for: .milliseconds(100)); return }
          try await Task.sleep(for: .milliseconds(25))
        }
        throw EngineError(message: "Native export control unavailable: " + id)
      }
      try await press("factory.group.export")
      await studio.portable.refresh(engine)
      guard !studio.review.isEmpty, !studio.portable.preview.isEmpty else {
        throw EngineError(message: "Export review unavailable: " + studio.failure + studio.portable.failure)
      }
      try await press("factory.export.create")
      // Save destinations and native panels remain under the user's control.
      // This labelled controller confirms only an export into its disposable project.
      func confirm(_ view: NSView) -> NSButton? {
        if let button = view as? NSButton, button.title == "Export", button.isEnabled { return button }
        return view.subviews.lazy.compactMap(confirm).first
      }
      var confirmed = false
      for _ in 0..<120 {
        if let button = NSApp.windows.lazy.compactMap({ $0.contentView.flatMap(confirm) }).first { button.performClick(nil); confirmed = true; break }
        try await Task.sleep(for: .milliseconds(25))
      }
      guard confirmed else { throw EngineError(message: "Native export confirmation did not appear") }
      for _ in 0..<160 { if !studio.portable.package.isEmpty || !studio.portable.failure.isEmpty { break }; try await Task.sleep(for: .milliseconds(25)) }
      guard !studio.portable.package.isEmpty, studio.portable.failure.isEmpty else { throw EngineError(message: "Native export failed: " + studio.portable.failure) }
      let destination = URL(fileURLWithPath: string(project, "path")).appendingPathComponent(".superqode/native-portable-copy-" + UUID().uuidString + ".zip")
      try studio.portable.copy(to: destination)
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count == after.count else { throw EngineError(message: "Export unexpectedly started a model or worker job") }
      var screenshots: [String] = []
      if let output = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"], let window = NSApp.windows.first(where: { $0.frame.width > 600 }), let content = window.contentView {
        for width in [1440, 1280, 1024] {
          var frame = window.frame; frame.size.width = CGFloat(width); frame.size.height = 900
          window.setFrame(frame, display: true); try await Task.sleep(for: .milliseconds(100))
          for group in FactoryNavigation.groups {
            guard let button = find("factory.group." + group.id) else { throw EngineError(message: "Factory sidebar tool is missing") }
            let rect = button.convert(button.bounds, to: content)
            guard rect.minX >= 0, rect.maxX <= content.bounds.maxX + 1 else { throw EngineError(message: "Factory sidebar overflows its window") }
          }
          if let bitmap = content.bitmapImageRepForCachingDisplay(in: content.bounds) {
            content.cacheDisplay(in: content.bounds, to: bitmap)
            let url = URL(fileURLWithPath: output).deletingLastPathComponent().appendingPathComponent("factory-export-\(width).png")
            try bitmap.representation(using: .png, properties: [:])?.write(to: url); screenshots.append(url.path)
          }
        }
      }
      report = ["passed": true, "new_jobs": 0, "package": studio.portable.package,
        "copied_to": destination.path, "screenshots": screenshots, "checked_window_widths": [1440, 1280, 1024],
        "operator": "automated disposable-fixture controller", "release_authorized": false]
    } catch { report = ["passed": false, "error": error.localizedDescription] }
    if let path = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: path))
    }
  }
}
