import XCTest
@testable import SuperQode

final class HandoffTests: XCTestCase {
  private let ready: [String: Any] = ["job": "turn", "ready": true, "reason": ""]
  private func turn(status: String = "completed", mode: String = "code", project: String = "p") -> [String: Any] {
    ["id": "turn", "project": project, "kind": "task", "status": status, "request": ["interaction_mode": mode]]
  }

  func testSendToMenuNeedsAFinishedCodingTurnInThisProject() {
    func reason(job: String = "turn", detail: [String: Any]? = nil, active: Bool = false,
      source: [String: Any]? = nil, connected: Bool = true, project: String = "p") -> String? {
      HandoffMenuRules.blocker(connected: connected, projectID: project, job: job, anyActive: active,
        detail: detail ?? turn(), source: source ?? ready)
    }
    XCTAssertNil(reason())
    XCTAssertEqual(reason(connected: false), "The local engine is not running.")
    XCTAssertEqual(reason(project: ""), "Open a project first.")
    XCTAssertEqual(reason(job: ""), "Select a finished coding turn first.")
    XCTAssertEqual(reason(detail: turn(project: "other")), "This turn belongs to another project. Open that project.")
    XCTAssertEqual(reason(detail: turn(status: "running")), "Wait for this turn to finish, then send it.")
    XCTAssertEqual(reason(detail: turn(mode: "chat")), "This is a chat turn. Send a finished coding turn instead.")
    XCTAssertEqual(reason(active: true), "Finish the current run first.")
    XCTAssertEqual(reason(source: ["job": "older", "ready": true]), "Checking this turn…")
    XCTAssertEqual(reason(source: ["job": "turn", "ready": false, "reason": "No local coding harness is available in this project."]),
      "No local coding harness is available in this project.")
  }

  func testRunHeaderShowsSendToOnlyForFinishedCodingTurns() {
    XCTAssertTrue(HandoffMenuRules.isFinishedCodingTurn(turn()))
    XCTAssertTrue(HandoffMenuRules.isFinishedCodingTurn(turn(status: "failed")))
    XCTAssertFalse(HandoffMenuRules.isFinishedCodingTurn(turn(status: "running")))
    XCTAssertFalse(HandoffMenuRules.isFinishedCodingTurn(turn(mode: "chat")))
    XCTAssertFalse(HandoffMenuRules.isFinishedCodingTurn(["kind": "check", "status": "completed"]))
  }

  func testUnavailableTargetsKeepTheirReasonInTheMenu() {
    let ok: [String: Any] = ["id": "exo:home", "title": "exo cluster (localhost:52415)", "available": true]
    let blocked: [String: Any] = ["id": "exo:home", "title": "exo cluster (localhost:52415)", "available": false,
      "reason": "No model is running in exo. Start one in Local AI → exo cluster."]
    XCTAssertTrue(HandoffMenuRules.available(ok))
    XCTAssertEqual(HandoffMenuRules.itemTitle(ok), "exo cluster (localhost:52415)…")
    XCTAssertFalse(HandoffMenuRules.available(blocked))
    XCTAssertEqual(HandoffMenuRules.itemTitle(blocked),
      "exo cluster (localhost:52415) · No model is running in exo. Start one in Local AI → exo cluster.")
  }

  func testExoPanelDescribesNodesAndModelStatus() {
    let gb = 1024 * 1024 * 1024
    let cluster: [String: Any] = ["node_count": 2, "installed_memory_bytes": NSNumber(value: 256 * gb),
      "available_memory_bytes": NSNumber(value: 160 * gb)]
    XCTAssertTrue(ExoModelRows.clusterLine(cluster).hasPrefix("On your network · 2 nodes · "))
    XCTAssertTrue(ExoModelRows.clusterLine(["node_count": 1]).hasSuffix("1 node"))
    let node: [String: Any] = ["id": "a", "name": "Studio", "chip": "Apple M3 Ultra",
      "ram_total_bytes": NSNumber(value: 192 * gb), "ram_available_bytes": NSNumber(value: 120 * gb)]
    XCTAssertTrue(ExoModelRows.nodeLine(node).hasPrefix("Studio · Apple M3 Ultra · "))
    XCTAssertEqual(ExoModelRows.nodeLine(["id": "node-b", "name": "node-b", "chip": ""]), "node-b")
    XCTAssertEqual(ExoModelRows.status(["status": "running"]), "Running")
    XCTAssertEqual(ExoModelRows.status(["status": "downloaded"]), "Downloaded")
    XCTAssertEqual(ExoModelRows.status(["status": "downloading", "progress": NSNumber(value: 0.25)]), "Downloading 25%")
    XCTAssertTrue(ExoModelRows.detail(["context": 32768, "nodes": ["Studio", "node-b"]]).hasSuffix("on Studio, node-b"))
    XCTAssertEqual(ExoModelRows.message(running: 0, all: [["status": "downloaded"]]),
      "No model is running in exo. Start a downloaded model below, then run the tool check.")
    XCTAssertEqual(ExoModelRows.message(running: 0, all: []),
      "exo has no downloaded models yet. Download one in exo, then check again.")
  }
}
