import AppKit
import SwiftUI

@MainActor extension Workspace {
  /// Disposable fixtures only, invoked by the existing isolated --smoke-test flow.
  func smokeExternalSessions(snapshotDirectory: URL?) async throws -> String {
    let projectPath = string(project, "path")
    let directory = URL(fileURLWithPath: projectPath).deletingLastPathComponent()
      .appendingPathComponent("external-session-fixture")
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    let sessionID = UUID().uuidString.lowercased()
    let file = directory.appendingPathComponent("recorded.jsonl")
    var data = Data()
    for row: [String: Any] in [
      ["type": "session_meta", "payload": ["id": sessionID, "cwd": projectPath, "cli_version": "fixture",
        "base_instructions": "Excluded fixture instructions", "git": ["branch": "feature/external-review"]]],
      ["type": "response_item", "payload": ["type": "message", "role": "user",
        "content": [["type": "input_text", "text": "Continue reviewing the external fixture change."]]]],
      ["type": "response_item", "payload": ["type": "message", "role": "assistant",
        "content": [["type": "output_text", "text": "Recorded fixture answer, ready for a reviewed handoff."]]]],
    ] {
      data.append(try JSONSerialization.data(withJSONObject: row))
      data.append(10)
    }
    try data.write(to: file)
    let originalBytes = data
    let source = try await engine.call("external.sources.add", ["provider": "codex", "path": directory.path]) as? [String: Any] ?? [:]
    let sourceID = string(source, "id")
    _ = try await engine.call("external.sources.scan", ["id": sourceID])
    let indexed = try await engine.call("external.sessions.list", ["project": projectID]) as? [String: Any] ?? [:]
    guard let row = (indexed["items"] as? [[String: Any]])?.first,
      string(row, "status") == "recorded", string(row, "session_id") == sessionID,
      !String(describing: indexed).contains("Excluded fixture instructions"),
      try Data(contentsOf: file) == originalBytes else {
      throw EngineError(message: "External indexing changed files, leaked prompts or lost provenance.")
    }
    let parameters: [String: Any] = ["id": string(row, "id"), "source": sourceID]
    let preview = try await engine.call("external.sessions.preview", parameters) as? [String: Any] ?? [:]
    guard string(preview, "text").contains("Continue reviewing the external fixture change."),
      !string(preview, "text").contains("Excluded fixture instructions") else {
      throw EngineError(message: "External preview lost supported text or included private instructions.")
    }
    let extra: [String: Any] = ["type": "response_item", "payload": ["type": "message", "role": "assistant",
      "content": [["type": "output_text", "text": "The external session changed after review."]]]]
    data.append(try JSONSerialization.data(withJSONObject: extra))
    data.append(10)
    try data.write(to: file)
    var rejectedStale = false
    do {
      _ = try await engine.call("external.sessions.preview", parameters.merging(["expected_digest": string(preview, "digest")]) { _, value in value })
    } catch { rejectedStale = error.localizedDescription.contains("changed since review") }
    guard rejectedStale else { throw EngineError(message: "External stale preview was accepted.") }
    let fresh = try await engine.call("external.sessions.preview", parameters) as? [String: Any] ?? [:]
    let priorJob = selectedJob
    let priorDraft = draft
    let jobsBefore = try await engine.call("jobs.list") as? [[String: Any]] ?? []
    guard addSharedThreadContext(string(fresh, "text"), project: projectID, target: ""),
      selectedJob.isEmpty, draft.contains("The external session changed after review.") else {
      throw EngineError(message: "External context did not reach a new draft.")
    }
    selectJob(priorJob)
    let jobsAfter = try await engine.call("jobs.list") as? [[String: Any]] ?? []
    guard draft == priorDraft, jobsBefore.count == jobsAfter.count else {
      throw EngineError(message: "External handoff changed the source draft or started a task.")
    }
    section = "Agent activity"
    workSource = "external"
    if let snapshotDirectory {
      try await Task.sleep(for: .milliseconds(600))
      try captureWindow(to: snapshotDirectory.appendingPathComponent("all-work-external.png"))
      let previewWindow = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 800, height: 660),
        styleMask: [.titled, .closable], backing: .buffered, defer: false)
      previewWindow.isReleasedWhenClosed = false
      let content = NSHostingView(rootView: ExternalSessionHandoffView(row: row, project: projectID)
        .environmentObject(self).environment(\.colorScheme, .dark).background(Color.qPanel))
      previewWindow.contentView = content
      previewWindow.makeKeyAndOrderFront(nil)
      defer { previewWindow.close() }
      try await Task.sleep(for: .milliseconds(450))
      content.layoutSubtreeIfNeeded()
      guard let bitmap = content.bitmapImageRepForCachingDisplay(in: content.bounds) else {
        throw EngineError(message: "External handoff preview could not render.")
      }
      content.cacheDisplay(in: content.bounds, to: bitmap)
      guard let png = bitmap.representation(using: .png, properties: [:]) else {
        throw EngineError(message: "External handoff capture failed.")
      }
      try png.write(to: snapshotDirectory.appendingPathComponent("external-handoff.png"))
    }
    _ = try await engine.call("external.sources.remove", ["id": sourceID])
    let remaining = try await engine.call("external.sessions.list") as? [String: Any] ?? [:]
    guard remaining["count"] as? Int == 0, try Data(contentsOf: file) == data else {
      throw EngineError(message: "Disconnect failed to remove the index or changed external files.")
    }
    workSource = "app"
    return "passed; opt-in metadata index, source provenance, text-only preview, stale-review rejection, draft preservation, no automatic task and read-only disconnect"
  }
}
