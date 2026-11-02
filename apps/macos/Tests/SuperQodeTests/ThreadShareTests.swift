import XCTest

@testable import SuperQode

final class ThreadShareTests: XCTestCase {
  @MainActor private func workspace() -> Workspace {
    let suite = "ThreadShareTests." + UUID().uuidString
    let preferences = UserDefaults(suiteName: suite)!
    addTeardownBlock { preferences.removePersistentDomain(forName: suite) }
    return Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: preferences)
  }

  @MainActor func testTransferPreservesSourceAndDestinationDrafts() {
    let app = workspace()
    app.project = ["id": "project"]
    app.jobs = [
      ["id": "a", "project": "project", "kind": "task", "status": "completed"],
      ["id": "b", "project": "project", "kind": "task", "status": "completed"],
    ]
    app.selectJob("b")
    app.draft = "Destination draft"
    app.selectJob("a")
    app.draft = "Source draft"
    XCTAssertTrue(app.addSharedThreadContext("Quoted context", project: "project", target: "b"))
    XCTAssertEqual(app.draft, "Destination draft\n\nQuoted context")
    app.selectJob("a")
    XCTAssertEqual(app.draft, "Source draft")
    XCTAssertTrue(app.addSharedThreadContext("New context", project: "project", target: ""))
    XCTAssertEqual(app.draft, "New context")
    XCTAssertTrue(app.selectedJob.isEmpty)
  }

  @MainActor func testTransferRejectsStaleProjectAndBusyTarget() {
    let app = workspace()
    app.project = ["id": "project"]
    app.jobs = [["id": "busy", "project": "project", "kind": "task", "status": "running"]]
    app.draft = "Keep me"
    XCTAssertFalse(app.addSharedThreadContext("context", project: "other", target: ""))
    XCTAssertFalse(app.addSharedThreadContext("context", project: "project", target: "busy"))
    XCTAssertFalse(app.addSharedThreadContext("context", project: "project", target: "missing"))
    XCTAssertEqual(app.draft, "Keep me")
  }

  @MainActor func testDirectConnectionCommandsAndDefaultReset() {
    let app = workspace()
    app.project = ["id": "project"]
    app.connected = true
    for page in ["builder", "runtimes", "acp"] {
      app.runWorkspaceCommand(.connectionPage(page))
      XCTAssertEqual(app.connectionStartPage, page)
      XCTAssertTrue(app.showConnection)
      app.showConnection = false
    }
    app.runWorkspaceCommand(.connect)
    XCTAssertEqual(app.connectionStartPage, "menu:root")
  }
}
