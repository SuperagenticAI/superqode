import XCTest
@testable import SuperQode

final class AgentProgressTests: XCTestCase {
  func event(_ name: String, _ payload: [String: Any], time: Double = 100) -> [String: Any] {
    ["type": "harness_event", "received_at": time, "data": ["event": name, "payload": payload]]
  }

  func testSparseACPUpdatesRetainCommandUntilCompletion() {
    let start = event("tool_call", ["toolCallId": "a", "title": "Shell", "rawInput": ["command": "swift test"]])
    let update = event("tool_update", ["toolCallId": "a", "status": "in_progress"], time: 110)
    let running = agentProgress([start, update])
    XCTAssertEqual(running.currentTool, "swift test")
    XCTAssertEqual(running.lastUpdate, Date(timeIntervalSince1970: 110))
    let done = agentProgress([start, update, event("tool_update", ["toolCallId": "a", "status": "completed"])])
    XCTAssertEqual(done.completedTools, 1)
    XCTAssertTrue(done.currentTool.isEmpty)
    XCTAssertTrue(done.detail.contains("swift test"))
    XCTAssertEqual(done.title, "Waiting for the next agent update")
  }

  func testClaudeArgumentsAndParallelTools() {
    let read = event("tool_call", ["tool_call_id": "read", "tool_name": "Read", "args": ["file_path": "src/main.swift"]])
    let shell = event("tool_call", ["tool_call_id": "shell", "tool_name": "Bash", "args": ["command": "git diff"]])
    XCTAssertEqual(agentProgress([read]).detail, "Read · src/main.swift")
    XCTAssertEqual(agentProgress([read, shell]).detail, "git diff")
    let progress = agentProgress([read, shell, event("tool_result", ["tool_call_id": "shell", "success": false])])
    XCTAssertEqual(progress.detail, "Read · src/main.swift")
    XCTAssertEqual(progress.failedTools, 1)
  }

  func testRepeatedIDLessToolsAndDuplicateCompletions() {
    let start = event("tool_call", ["tool_name": "bash", "arguments": ["command": "pwd"]])
    let end = event("tool_result", ["tool_name": "bash", "success": true])
    XCTAssertEqual(agentProgress([start, end, end]).completedTools, 1)
    XCTAssertEqual(agentProgress([start, end, start, end]).completedTools, 2)
  }

  func testProtocolToolsUseTheSameLiveProjection() {
    let start = event("tool.requested", ["toolCallId": "remote", "title": "Read file", "rawInput": ["path": "README.md"]])
    XCTAssertEqual(agentProgress([start]).currentTool, "Read file · README.md")
    let done = event("tool.completed", ["toolCallId": "remote", "status": "completed"])
    XCTAssertTrue(agentProgress([start, done]).currentTool.isEmpty)
    XCTAssertEqual(agentProgress([start, done]).completedTools, 1)
  }

  func testFinalAnswerAnchorSkipsActivityAndErrors() {
    let rows: [[String: Any]] = [
      ["type": "output", "coalesced": true],
      ["type": "output"],
      ["type": "output", "coalesced": true],
      ["type": "error"],
    ]
    XCTAssertEqual(finalResponseIndex(rows), 2)
    XCTAssertNil(finalResponseIndex([["type": "output"]]))
  }

  func testReportedPlanAndStreamingPhases() {
    let progress = agentProgress([
      event("plan_update", ["todos": [["content": "Read files", "status": "completed"], ["content": "Run tests", "status": "in_progress"]]]),
      event("thinking", ["text": "private reasoning"]),
    ])
    XCTAssertEqual(progress.planCompleted, 1)
    XCTAssertEqual(progress.planTotal, 2)
    XCTAssertEqual(progress.planStep, "Run tests")
    XCTAssertEqual(progress.title, "Reasoning")
    XCTAssertFalse(progress.detail.contains("private reasoning"))
    XCTAssertEqual(agentProgress([event("model_delta", ["text": "hello"])]).title, "Writing the response")
    XCTAssertEqual(agentProgress([]).title, "Waiting for the agent")
  }
}
