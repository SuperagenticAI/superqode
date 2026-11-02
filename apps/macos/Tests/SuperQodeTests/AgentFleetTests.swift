import XCTest
@testable import SuperQode

final class AgentFleetTests: XCTestCase {
  func testAttentionAndWorkingStatesStayDistinct() {
    XCTAssertEqual(activityTitle(["status": "needs_approval"]), "Needs you")
    XCTAssertEqual(activityTitle(["status": "running"]), "Working")
    XCTAssertEqual(activityTitle(["status": "interrupted"]), "Interrupted")
    XCTAssertEqual(activityTitle(["status": "failed"]), "Failed")
    XCTAssertNil(threadNotificationText("running"))
    XCTAssertNotNil(threadNotificationText("needs_approval"))
  }

  @MainActor func testNotificationsAreOptInAndRememberTheirCursorWithoutDelivering() {
    let name = "AgentFleetTests." + UUID().uuidString
    let preferences = UserDefaults(suiteName: name)!
    defer { preferences.removePersistentDomain(forName: name) }
    let alerts = ThreadNotifications(preferences: preferences)
    XCTAssertFalse(alerts.enabled)
    XCTAssertEqual(alerts.cursor, -1)
    alerts.consume(["cursor": 7, "items": [["status": "completed"]]], selected: "")
    XCTAssertEqual(ThreadNotifications(preferences: preferences).cursor, 7)
    XCTAssertFalse(alerts.enabled)
  }

  @MainActor func testLateActivityResponseCannotReplaceNewerProjectScope() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let library = AgentActivityLibrary()
    let first = Task { await library.load(engine: engine, project: "first", query: "", view: "all") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    let second = Task { await library.load(engine: engine, project: "second", query: "", view: "all") }
    while engine.pendingRequestCount < 2 { await Task.yield() }
    engine.receive(["id": 2, "result": ["items": [["id": "new-scope"]], "next_cursor": ""]])
    await second.value
    engine.receive(["id": 1, "result": ["items": [["id": "stale-scope"]], "next_cursor": "wrong"]])
    await first.value
    XCTAssertEqual(library.rows.map { string($0, "id") }, ["new-scope"])
    XCTAssertTrue(library.cursor.isEmpty)
    XCTAssertFalse(library.loading)
  }
}
