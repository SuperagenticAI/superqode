import AppKit
import Foundation

@MainActor extension Workspace {
  /// Exercise this app's actual tab buttons and native editors, with no inference.
  func inspectFactoryNavigation() async {
    var report: [String: Any] = [:]
    do {
      guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"] ?? ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_VALIDATION_ROOT"], !projectID.isEmpty,
        URL(fileURLWithPath: string(project, "path")).standardizedFileURL.path.hasPrefix(source + "/.superqode/validation/") else {
        throw EngineError(message: "Navigation inspection requires a repository-local validation project")
      }
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio
      let documentID = "factory-studio:" + projectID
      let definitionURL = URL(fileURLWithPath: string(project, "path")).appendingPathComponent(".superqode/factory.yaml")
      let originalFile = try Data(contentsOf: definitionURL)
      section = "Factory Studio"; showWelcome = false
      func find<T: NSView>(_ type: T.Type, matching: @escaping (T) -> Bool) -> T? {
        func descend(_ view: NSView) -> T? {
          if let match = view as? T, matching(match) { return match }
          return view.subviews.lazy.compactMap { descend($0) }.first
        }
        return NSApp.windows.lazy.compactMap { $0.contentView.flatMap(descend) }.first
      }
      func settle() async throws { try await Task.sleep(for: .milliseconds(60)) }
      var nativeActions = 0
      func press(_ identifier: String) async throws {
        for _ in 0..<100 {
          if let button = find(NSButton.self, matching: { $0.identifier?.rawValue == identifier }), button.isEnabled {
            button.performClick(nil); nativeActions += 1; try await settle()
            return
          }
          try await Task.sleep(for: .milliseconds(20))
        }
        throw EngineError(message: "Native Factory navigation control did not appear: " + identifier)
      }
      func click(_ destination: String) async throws {
        guard let group = FactoryNavigation.groups.first(where: { $0.destinations.contains(destination) }) else { throw EngineError(message: "Unknown Factory page") }
        if studio.navigation.group.id != group.id || group.destinations.count == 1 { try await press("factory.group." + group.id) }
        if group.destinations.count > 1 { try await press("factory.tab." + destination) }
        guard studio.navigation.selection == destination, section == "Factory Studio" else {
          throw EngineError(message: "Factory page changed unexpectedly: " + destination)
        }
      }
      func recoveryField() -> NSTextField? {
        find(NSTextField.self, matching: { $0.identifier?.rawValue == "factory.operations.restore-name" || $0.placeholderString == "New recovery folder name" })
      }
      func edit(_ field: NSTextField, _ value: String) {
        field.stringValue = value
        field.delegate?.controlTextDidChange?(Notification(name: NSControl.textDidChangeNotification, object: field))
      }
      try await click("Operations")
      guard let field = recoveryField() else { throw EngineError(message: "Native recovery name field missing") }
      let originalName = field.stringValue
      edit(field, "unsaved-navigation-check")
      try await click("Definition")
      guard let editor = find(SourceEditor.Editor.self, matching: { $0.sourceDocumentID == documentID }) else {
        throw EngineError(message: "Native Factory source editor missing")
      }
      let originalText = studio.text
      editor.string = originalText + "\n# Unsaved navigation check\n"
      editor.delegate?.textDidChange?(Notification(name: NSText.didChangeNotification, object: editor))
      let draft = editor.string
      let caret = NSRange(location: (draft as NSString).length, length: 0)
      editor.setSelectedRange(caret)
      for _ in 0..<2 {
        for item in FactoryNavigation.tabs { try await click(item.id) }
      }
      try await click("Definition")
      let sameEditor = find(SourceEditor.Editor.self, matching: { $0.sourceDocumentID == documentID })
      guard sameEditor === editor, editor.string == draft, editor.selectedRange() == caret else {
        throw EngineError(message: "Tab switching replaced the Factory editor, draft or caret")
      }
      try await click("Operations")
      guard recoveryField() === field, field.stringValue == "unsaved-navigation-check",
        !editor.interactionEnabled, !editor.isEditable, editor.window?.firstResponder !== editor else {
        throw EngineError(message: "Tab switching lost the form or left a hidden editor active")
      }
      let ticket = studio.navigation.ticket()
      let delayed = Task { @MainActor in
        try await Task.sleep(for: .milliseconds(150))
        return studio.navigation.follow(ticket, to: "Runs")
      }
      try await click("Workflow")
      guard try await delayed.value == false, studio.navigation.selection == "Workflow" else {
        throw EngineError(message: "Delayed completion overrode the selected tab")
      }
      let leaving = studio.navigation.ticket()
      section = "Workspace"; try await settle()
      guard !studio.navigation.follow(leaving, to: "Runs"), section == "Workspace" else {
        throw EngineError(message: "Hidden Factory completion changed navigation")
      }
      section = "Factory Studio"; try await settle(); try await click("Operations")
      studio.text = originalText; edit(field, originalName)
      var layoutWidths: [Int] = []
      var screenshots: [String] = []
      var mainSections: [String] = []
      var starterChecked = false
      var fieldsChecked = false
      if ProcessInfo.processInfo.arguments.contains("--factory-guided-inspect"),
        let window = field.window, let content = window.contentView {
        for destination in Sections.names {
          section = destination; try await settle()
          guard section == destination else { throw EngineError(message: "Main navigation redirected from " + destination) }
          mainSections.append(destination)
        }
        section = "Factory Studio"; try await settle()
        await studio.validate(engine: engine); await studio.refreshSources(engine: engine)
        try await click("Configuration")
        guard let nameField = find(NSTextField.self, matching: { $0.placeholderString == "Factory name" }),
          nameField.stringValue == string(studio.review, "name"), !nameField.stringValue.isEmpty else {
          throw EngineError(message: "Validated Factory controls were not populated")
        }
        let savedName = nameField.stringValue
        edit(nameField, "unsaved-controls-check"); try await settle()
        try await click("Operations"); try await click("Configuration")
        guard nameField.stringValue == "unsaved-controls-check" else { throw EngineError(message: "Tab switching replaced unapplied configuration fields") }
        edit(nameField, savedName); fieldsChecked = true; try await settle()
        try await click("Stack")
        studio.text = ""; try await settle()
        try await press("factory.setup.next")
        var continued = false
        for _ in 0..<100 {
          if let button = find(NSButton.self, matching: { $0.title == "Continue" }), button.isEnabled {
            button.performClick(nil); nativeActions += 1; continued = true; break
          }
          try await Task.sleep(for: .milliseconds(20))
        }
        guard continued else { throw EngineError(message: "Starter confirmation did not appear") }
        for _ in 0..<100 {
          if !studio.text.isEmpty { break }
          try await Task.sleep(for: .milliseconds(20))
        }
        guard !studio.text.isEmpty else { throw EngineError(message: "Starter draft was not created") }
        try await press("factory.setup.next")
        for _ in 0..<100 {
          if !studio.review.isEmpty { break }
          try await Task.sleep(for: .milliseconds(20))
        }
        guard !studio.review.isEmpty, studio.failure.isEmpty else { throw EngineError(message: "Starter validation failed") }
        starterChecked = true
        studio.text = originalText
        await studio.validate(engine: engine); await studio.refreshSources(engine: engine); try await settle()
        let originalFrame = window.frame
        for width in [1440, 1280, 1024] {
          var frame = window.frame; frame.size.width = CGFloat(width); frame.size.height = 900
          window.setFrame(frame, display: true); try await settle()
          for group in FactoryNavigation.groups {
            try await press("factory.group." + group.id)
            if group.id == "build" { try await click("Stack") }
            if group.id == "run" { try await click("Runs") }
            if group.id == "manage" { try await click("Operations") }
            if group.id == "manage" { await studio.operations.refresh(engine) }
            for item in FactoryNavigation.groups {
              guard let button = find(NSButton.self, matching: { $0.identifier?.rawValue == "factory.group." + item.id }) else { throw EngineError(message: "Missing primary navigation") }
              let rect = button.convert(button.bounds, to: content)
              guard rect.minX >= content.bounds.minX, rect.maxX <= content.bounds.maxX + 1 else { throw EngineError(message: "Factory navigation overflows at width \(width)") }
            }
            if width == 1280,
              let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"],
              let bitmap = content.bitmapImageRepForCachingDisplay(in: content.bounds) {
              content.cacheDisplay(in: content.bounds, to: bitmap)
              let url = URL(fileURLWithPath: destination).deletingLastPathComponent().appendingPathComponent("factory-" + group.id + "-1280.png")
              try bitmap.representation(using: .png, properties: [:])?.write(to: url)
              screenshots.append(url.path)
            }
          }
          layoutWidths.append(width)
        }
        window.setFrame(originalFrame, display: true)
        try await click("Stack")
      }
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count == after.count else { throw EngineError(message: "Navigation check started a job") }
      guard try Data(contentsOf: definitionURL) == originalFile else { throw EngineError(message: "Navigation check changed saved Factory sources") }
      report = ["passed": true, "native_tab_clicks": nativeActions, "form_preserved": true,
        "source_editor_and_caret_preserved": true, "hidden_editor_disabled": true,
        "stale_completion_rejected": true, "new_jobs": 0, "source_files_written": false,
        "primary_areas": FactoryNavigation.groups.map(\.title), "checked_window_widths": layoutWidths,
        "main_navigation_sections": mainSections, "screenshots": screenshots,
        "empty_draft_starter_flow": starterChecked, "configuration_fields_preserved": fieldsChecked]
    } catch { report = ["passed": false, "error": error.localizedDescription] }
    if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: destination))
    }
  }
}
