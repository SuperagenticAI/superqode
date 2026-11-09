import XCTest

@testable import SuperQode

final class ThreadDraftTextTests: XCTestCase {
  func testEmptyDestinationReceivesContext() {
    XCTAssertEqual(ThreadDraftText.appending("Context", to: ""), "Context")
  }

  func testExistingTypedDraftIsPreservedExactly() {
    XCTAssertEqual(ThreadDraftText.appending("Context", to: "My unfinished prompt  "),
      "My unfinished prompt  \n\nContext")
  }

  func testEmptyContextDoesNotChangeDraft() {
    XCTAssertEqual(ThreadDraftText.appending("", to: "Keep me"), "Keep me")
  }

  @MainActor func testSendCommandUsesShiftAndDoesNotRunWithoutAThread() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.connected = true
    app.project = ["id": "project", "path": "/tmp/project"]
    let command = app.workspaceCommand(.sendToThread)
    XCTAssertEqual(command?.key, "t")
    XCTAssertTrue(command?.shiftKey == true)
    XCTAssertFalse(command?.isEnabled ?? true)
    app.runWorkspaceCommand(.sendToThread)
    XCTAssertNil(app.sendToThreadRequest)
  }
}
