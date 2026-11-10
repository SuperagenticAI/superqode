import XCTest

@testable import SuperQode

final class RecursiveAgentsTests: XCTestCase {
  func testDeepSeekChildEventsKeepTheLatestPhase() {
    let started: [String: Any] = [
      "type": "harness_event",
      "data": [
        "event": "subagent",
        "payload": [
          "child_session_id": "c1",
          "phase": "started",
          "parent_session_id": "parent",
        ],
      ],
    ]
    let ignored: [String: Any] = ["type": "message", "data": ["event": "subagent"]]
    let finished: [String: Any] = [
      "type": "harness_event",
      "data": [
        "event": "subagent",
        "payload": ["childSessionId": "c1", "phase": "finished"],
      ],
    ]
    let rows = RecursiveAgentTranscript.children([started, ignored, finished])
    XCTAssertEqual(rows.count, 1)
    XCTAssertEqual(rows[0]["id"] as? String, "c1")
    XCTAssertEqual(rows[0]["status"] as? String, "finished")
    XCTAssertEqual(rows[0]["parent_id"] as? String, "parent")
  }
}
