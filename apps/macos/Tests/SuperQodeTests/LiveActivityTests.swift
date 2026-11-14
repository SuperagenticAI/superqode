import XCTest
@testable import SuperQode

final class LiveActivityTests: XCTestCase {
  private func event(_ name: String, _ payload: [String: Any]) -> [String: Any] {
    ["type": "harness_event", "data": ["event": name, "payload": payload]]
  }

  func testRuntimeArgumentShapesShowTheAction() {
    let examples: [([String: Any], String)] = [
      (["tool_name": "bash", "args": ["command": "uv run pytest -q tests/test_server.py"]], "uv run pytest -q tests/test_server.py"),
      (["title": "Run", "rawInput": ["cmd": ["/bin/zsh", "-lc", "git diff --stat"]]], "/bin/zsh -lc git diff --stat"),
      (["name": "exec_command", "arguments": "{\"cmd\":\"git status --short\"}"], "git status --short"),
      (["tool_name": "edit", "args": ["path": "Sources/App.swift"]], "edit · Sources/App.swift"),
      (["title": "Edit", "locations": [["path": "src/main.py", "line": 10]]], "Edit · src/main.py"),
      (["name": "apply_patch", "input": ["patch": "*** Begin Patch\n*** Update File: src/main.py\n*** End Patch"]], "apply_patch · src/main.py"),
    ]
    for (payload, expected) in examples {
      XCTAssertEqual(agentToolAction(payload), expected)
      XCTAssertEqual(currentAgentActivity([event("tool_call", payload)]), expected)
    }
  }

  func testCanonicalSparseUpdatesRetainCommandUntilCompletion() {
    var events = [event("tool.requested", ["toolCallId": "one", "title": "Run", "rawInput": ["command": "python -m unittest -v"]])]
    events.append(event("tool.completed", ["toolCallId": "one", "status": "in_progress", "rawInput": ["cwd": "/workspace"]]))
    XCTAssertEqual(currentAgentActivity(events), "python -m unittest -v")
    events.append(event("tool.completed", ["toolCallId": "one", "status": "completed"]))
    XCTAssertEqual(currentAgentActivity(events), "Finished · python -m unittest -v")
  }

  func testFinishingOneParallelToolKeepsTheOtherLive() {
    var events = [event("tool_call", ["tool_call_id": "first", "tool_name": "read", "args": ["path": "README.md"]]),
      event("tool_call", ["tool_call_id": "second", "tool_name": "bash", "args": ["command": "swift test"]])]
    events.append(event("tool_result", ["tool_call_id": "second", "success": false]))
    XCTAssertEqual(currentAgentActivity(events), "read · README.md")
    events.append(event("tool_result", ["tool_call_id": "first", "success": true]))
    XCTAssertEqual(currentAgentActivity(events), "Finished · read · README.md")
  }

  func testLongCommandsArePreservedAndThinkingDoesNotHidePendingWork() {
    let command = "python -m tests " + String(repeating: "--include src/long/path ", count: 30)
    let events = [event("tool_call", ["tool_call_id": "one", "args": ["command": command]]), event("model.thinking", ["text": "Working"])]
    XCTAssertEqual(currentAgentActivity(events), command)
    XCTAssertEqual(currentAgentActivity([event("model.thinking", [:])]), "Thinking…")
  }

  func testSystemOneReadsTheRecordedHTTPResultForTheTool() throws {
    let decision = try XCTUnwrap(SystemOneActivity(event: event("systemone.decision", [
      "tool": "read_file", "provider": "google", "mode": "shadow", "action": "allow",
      "evaluation": [
        "status": "success", "requested_model": "gemini-decision-1", "http_status": 200,
        "latency_ms": 241, "question_count": 6, "usage": ["input_tokens": 128],
        "request_id": "fixture-request",
      ],
    ])))
    XCTAssertEqual(decision.tool, "read_file")
    XCTAssertEqual(decision.provider, "Google")
    XCTAssertEqual(decision.model, "gemini-decision-1")
    XCTAssertEqual(decision.outcome, "HTTP 200")
    XCTAssertEqual(decision.recommendation, "Would allow")
    XCTAssertEqual(decision.telemetry, "241 ms · 6 questions · 128 input tokens")
    XCTAssertEqual(decision.requestID, "fixture-request")
  }

  func testSystemOneDistinguishesSkippedAndReplayedEvaluationsFromLiveResults() throws {
    let skipped = try XCTUnwrap(SystemOneActivity(event: event("systemone.decision", [
      "tool": "read_file", "skipped_client": true, "action": "ask", "message": "live_unavailable",
    ])))
    XCTAssertEqual(skipped.outcome, "Skipped")
    XCTAssertTrue(skipped.recommendation.isEmpty)
    let replay = try XCTUnwrap(SystemOneActivity(event: event("systemone.decision", [
      "evaluation": ["status": "success", "http_status": 200, "replayed": true],
    ])))
    XCTAssertEqual(replay.outcome, "Replay")
    XCTAssertNil(SystemOneActivity(event: event("tool.requested", [:])))
  }
}
