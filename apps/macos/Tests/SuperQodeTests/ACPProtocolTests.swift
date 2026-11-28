import XCTest

@testable import SuperQode

final class ACPProtocolTests: XCTestCase {
  @MainActor private func workspace(_ defaults: UserDefaults) -> Workspace {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: defaults)
    app.project = ["id": "project-a", "path": "/tmp/project-a"]
    app.harness = "acp:claude"
    app.harnesses = [["id": "acp:claude", "desktop_kind": "acp", "available": true, "digest": "route"]]
    app.connected = true
    return app
  }

  @MainActor func testDefaultAndPersistenceAreScopedToProjectAndAgent() {
    let suite = "ACPProtocolTests." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let app = workspace(defaults)
    XCTAssertEqual(app.acpProtocolPolicy, .automatic)
    app.connectionMetadata[app.harness] = ["connected": true, "route_digest": "route", "protocol_policy": "auto"]
    app.acpProtocolPolicy = .v2
    XCTAssertEqual(app.acpProtocolPolicy, .v2)
    XCTAssertEqual(app.connectionMetadata[app.harness]?["connected"] as? Bool, false)
    XCTAssertEqual(app.acpPolicy(for: "acp:codex"), .automatic)
    XCTAssertEqual(app.acpPolicy(for: "acp:claude", project: "project-b"), .automatic)
    let restored = workspace(defaults)
    XCTAssertEqual(restored.acpProtocolPolicy, .v2)
    restored.project = ["id": "project-b"]
    XCTAssertEqual(restored.acpProtocolPolicy, .automatic)
    XCTAssertEqual(app.engine.pendingRequestCount, 0, "Saving a protocol must not send a model prompt")
  }

  @MainActor func testActiveSessionCannotChangeProtocol() {
    let suite = "ACPProtocolTests." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let app = workspace(defaults)
    app.jobs = [["id": "run", "project": "project-a", "kind": "task", "status": "running"]]
    app.acpProtocolPolicy = .v1
    XCTAssertEqual(app.acpProtocolPolicy, .automatic)
    XCTAssertTrue(app.notice.contains("active agent session"))
  }

  func testConnectionCheckMustMatchTheSelectedPolicy() {
    let route: [String: Any] = ["available": true, "digest": "route"]
    let checked: [String: Any] = ["connected": true, "route_digest": "route", "protocol_policy": "auto", "project_id": "a"]
    XCTAssertTrue(verifiedACPConnection(route: route, metadata: checked, policy: .automatic))
    XCTAssertFalse(verifiedACPConnection(route: route, metadata: checked, policy: .v1))
    XCTAssertFalse(verifiedACPConnection(route: route, metadata: checked, policy: .v2))
    XCTAssertTrue(verifiedACPConnection(route: route, metadata: checked, policy: .automatic, project: "a"))
    XCTAssertFalse(verifiedACPConnection(route: route, metadata: checked, policy: .automatic, project: "b"))
    XCTAssertFalse(verifiedACPConnection(route: route, metadata: ["connected": true, "route_digest": "route"], policy: .automatic))
  }

  func testBadgeUsesNegotiationAndExplainsFallback() {
    let requestedOnly = ACPProtocolStatus(["protocol_policy": "v2", "requested_protocol_version": 2])
    XCTAssertNil(requestedOnly.negotiated)
    XCTAssertEqual(requestedOnly.label, "ACP · Not checked")
    let actual = ACPProtocolStatus(["protocol_policy": "auto", "requested_protocol_version": 2,
      "negotiated_protocol_version": 1, "fallback": true, "fallback_reason": "Agent selected ACP v1."])
    XCTAssertEqual(actual.label, "ACP v1 · Fallback")
    XCTAssertEqual(actual.requested, 2)
    XCTAssertEqual(actual.negotiated, 1)
    XCTAssertEqual(actual.reason, "Agent selected ACP v1.")
    XCTAssertEqual(ACPProtocolStatus(["negotiated_protocol_version": 2]).label, "ACP v2 · Preview")
    XCTAssertNil(ACPProtocolStatus(["negotiated_protocol_version": 3]).negotiated)
    XCTAssertEqual(ACPProtocolPolicy.recorded(in: ["protocol_version": 2]), .automatic)
  }

  @MainActor func testForegroundIdleKeepsBackgroundSessionAndDraft() {
    let suite = "ACPProtocolTests." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let app = workspace(defaults)
    app.selectedJob = "run"
    app.detail = ["kind": "task", "status": "running", "request": ["harness": app.harness]]
    app.events = [
      ["type": "harness_event", "data": ["event": "acp_session", "payload": ["session_id": "root", "negotiated_protocol_version": 2]]],
      ["type": "harness_event", "data": ["event": "acp_update", "payload": ["sessionId": "root",
        "update": ["sessionUpdate": "state_update", "state": "idle", "background": [["type": "tool_call", "toolCallId": "task"]]]]]]
    ]
    app.draft = "Keep my next message"
    XCTAssertTrue(app.active)
    XCTAssertTrue(app.acpForegroundIdle)
    XCTAssertFalse(app.showsWorking)
    XCTAssertFalse(app.canSubmitDraft)
    app.send(continueSession: true)
    XCTAssertEqual(app.draft, "Keep my next message")
    XCTAssertTrue(app.notice.contains("Background work"))
    let snapshot = ACPActivitySnapshot(app.events)
    XCTAssertEqual(snapshot.root, "root")
    XCTAssertEqual(snapshot.summary, "Response finished · 1 background task running")
    app.detail["status"] = "completed"
    app.acpProtocolPolicy = .v1
    XCTAssertTrue(app.acpProtocolWillSwitch)
  }
}
