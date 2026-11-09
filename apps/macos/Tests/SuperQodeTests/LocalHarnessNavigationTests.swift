import XCTest

@testable import SuperQode

final class LocalHarnessNavigationTests: XCTestCase {
  @MainActor func testOnlyDocumentedAndWiredHarnessesAreVisible() {
    XCTAssertEqual(LocalHarnessSupport.documentedIDs, Set(["superqode", "opencode", "goose"]))
    let documented: [String: Any] = ["local_support": "documented", "source_urls": ["https://example.com/docs"], "status": "Configured"]
    let rows: [[String: Any]] = [
      documented.merging(["id": "superqode"]) { _, new in new },
      documented.merging(["id": "opencode", "status": "Not installed"]) { _, new in new },
      documented.merging(["id": "goose"]) { _, new in new },
      documented.merging(["id": "codex"]) { _, new in new },
      documented.merging(["id": "unreviewed"]) { _, new in new },
      documented.merging(["id": "opencode", "status": "Unavailable"]) { _, new in new },
      documented.merging(["id": "goose", "local_support": "unverified"]) { _, new in new },
      documented.merging(["id": "goose", "source_urls": [] as [String]]) { _, new in new },
    ]
    XCTAssertEqual(LocalHarnessSupport.visibleRows(rows).compactMap { $0["id"] as? String }, ["superqode", "opencode", "goose"])
  }

  func testLocalHarnessPageIsAdvancedAndNotTheNewcomerPage() {
    let group = WorkspaceNavigationGroup.containing("Local harnesses")
    XCTAssertEqual(group.id, "advanced")
    XCTAssertNotEqual(group.id, WorkspaceNavigationGroup.containing("Models").id)
    XCTAssertFalse(WorkspaceNavigationGroup.usesCodingWorkspace("Local harnesses"))
    XCTAssertEqual(Sections.names.count, Sections.icons.count)
  }

  @MainActor func testAdvancedCommandIsUniqueAndRequiresProject() {
    let preferences = UserDefaults(suiteName: "LocalHarnessTests." + UUID().uuidString)!
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: preferences)
    let action = WorkspaceCommandAction.section("Local harnesses")
    XCTAssertFalse(app.workspaceCommand(action)?.isEnabled ?? true)
    app.connected = true
    app.project = ["id": "project", "path": "/tmp/project"]
    let matches = app.workspaceCommands.filter { $0.action == action }
    XCTAssertEqual(matches.count, 1)
    XCTAssertEqual(matches.first?.title, "Advanced: Harnesses on local models")
    XCTAssertTrue(matches.first?.isEnabled ?? false)
    XCTAssertEqual(app.workspaceCommand(.section("Models"))?.title, "Local AI")
    app.runWorkspaceCommand(action)
    XCTAssertEqual(app.section, "Local harnesses")
  }

  @MainActor func testSelectingAnotherModelLeavesTheFixedLocalProfile() {
    let preferences = UserDefaults(suiteName: "LocalHarnessTests." + UUID().uuidString)!
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: preferences)
    app.harnesses = [
      ["id": "core", "name": "Core"],
      ["id": "local-harness:fixture", "name": "Local fixture", "local_provider": "lmstudio", "local_model": "small-model"],
    ]
    app.chooseHarness("local-harness:fixture", restoreRemembered: false)
    XCTAssertEqual(app.provider, "lmstudio")
    XCTAssertEqual(app.model, "small-model")
    XCTAssertTrue(app.agentModels.isEmpty)
    app.chooseModelRoute("ollama", "other-model")
    XCTAssertEqual(app.harness, "core")
    XCTAssertEqual(app.provider, "ollama")
    XCTAssertEqual(app.model, "other-model")
  }
}
