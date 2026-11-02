import XCTest

@testable import SuperQode

final class ACPOnboardingTests: XCTestCase {
  func testVerificationRequiresCurrentLaunchAndSuccessfulCheck() {
    let route: [String: Any] = ["digest": "current"]
    XCTAssertTrue(verifiedACPConnection(route: route, metadata: ["connected": true, "route_digest": "current"]))
    XCTAssertFalse(verifiedACPConnection(route: route, metadata: ["connected": true, "route_digest": "old"]))
    XCTAssertFalse(verifiedACPConnection(route: route, metadata: ["connected": false, "route_digest": "current"]))
    XCTAssertFalse(verifiedACPConnection(route: route, metadata: ["connected": true, "route_digest": "current", "last_check_error": "disconnected"]))
    XCTAssertFalse(verifiedACPConnection(route: [:], metadata: ["connected": true, "route_digest": ""]))
  }

  @MainActor func testTerminalExitCodesDistinguishSuccessfulAndFailedSignIn() async throws {
    let terminals = ProjectTerminals()
    for code: Int32 in [0, 7] {
      let id = UUID().uuidString
      terminals.start(id, path: NSTemporaryDirectory(), arguments: ["/bin/sh", "-c", "exit \(code)"])
      for _ in 0..<100 where terminals.running.contains(id) {
        try await Task.sleep(for: .milliseconds(20))
      }
      XCTAssertFalse(terminals.running.contains(id))
      XCTAssertEqual(terminals.exitCodes[id], code)
      terminals.stop(id)
    }
  }
}
