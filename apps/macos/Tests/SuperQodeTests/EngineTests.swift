import XCTest

@testable import SuperQode

final class EngineTests: XCTestCase {
  func testFragmentedRepliesAreDeliveredOnce() async {
    let frames = EngineFrames()
    let received = expectation(description: "reply")
    frames.receive(
      Data("{\"id\":1,\"res".utf8), deliver: { _ in XCTFail() }, failure: { _ in XCTFail() })
    frames.receive(
      Data("ult\":true}\n".utf8),
      deliver: { object in
        XCTAssertEqual(object["id"] as? Int, 1)
        received.fulfill()
      }, failure: { _ in XCTFail() })
    await fulfillment(of: [received], timeout: 2)
  }

  func testMalformedReplyFailsInsteadOfDisappearing() async {
    let failed = expectation(description: "protocol error")
    EngineFrames().receive(
      Data("invalid-json\n".utf8), deliver: { _ in XCTFail() }, failure: { _ in failed.fulfill() })
    await fulfillment(of: [failed], timeout: 2)
  }

  func testUnterminatedOversizedReplyFails() async {
    let failed = expectation(description: "frame limit")
    EngineFrames().receive(
      Data(repeating: 65, count: EngineFrames.maximumFrameBytes + 1),
      deliver: { _ in XCTFail() }, failure: { _ in failed.fulfill() })
    await fulfillment(of: [failed], timeout: 2)
  }

  @MainActor func testTimeoutReleasesPendingCallAndIgnoresLateReply() async {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .milliseconds(20), input: pipe.fileHandleForWriting)
    do {
      _ = try await engine.call("test")
      XCTFail("Expected timeout")
    } catch { XCTAssertTrue(error.localizedDescription.contains("timed out")) }
    XCTAssertEqual(engine.pendingRequestCount, 0)
    engine.receive(["id": 1, "result": true])
    engine.stop()
  }

  @MainActor func testCancellationReleasesPendingCall() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    let request = Task { try await engine.call("test") }
    while engine.pendingRequestCount == 0 { await Task.yield() }
    request.cancel()
    do {
      _ = try await request.value
      XCTFail("Expected cancellation")
    } catch { XCTAssertTrue(error is CancellationError) }
    XCTAssertEqual(engine.pendingRequestCount, 0)
    engine.stop()
  }

  @MainActor func testReplyCancelsDeadline() async throws {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .milliseconds(30), input: pipe.fileHandleForWriting)
    let request = Task { try await engine.call("test") }
    while engine.pendingRequestCount == 0 { await Task.yield() }
    engine.receive(["id": 1, "result": "ok"])
    let value = try await request.value
    XCTAssertEqual(value as? String, "ok")
    try await Task.sleep(for: .milliseconds(60))
    XCTAssertEqual(engine.pendingRequestCount, 0)
    engine.stop()
  }
}
