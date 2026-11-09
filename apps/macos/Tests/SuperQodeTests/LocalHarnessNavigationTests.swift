import XCTest

@testable import SuperQode

final class LocalHarnessNavigationTests: XCTestCase {
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
