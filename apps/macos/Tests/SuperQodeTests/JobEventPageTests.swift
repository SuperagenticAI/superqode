import XCTest

@testable import SuperQode

final class JobEventPageTests: XCTestCase {
  private func events(_ range: ClosedRange<Int>) -> [[String: Any]] {
    range.map { ["sequence": $0, "type": "answer", "data": ["text": "chunk \($0)"]] }
  }

  func testCompletedRunStillHasUnreadPages() throws {
    let page = try JobEventPage([
      "status": "completed", "events": events(1...500),
      "next_sequence": 500, "has_more_events": true,
    ], after: 0)
    XCTAssertTrue(page.hasMore)
    XCTAssertEqual(page.nextSequence, 500)
    XCTAssertEqual(page.events.count, 500)
  }

  func testExplicitFinalFullPageDoesNotNeedAnotherFetch() throws {
    let page = try JobEventPage([
      "events": events(501...1000), "next_sequence": 1000, "has_more_events": false,
    ], after: 500)
    XCTAssertFalse(page.hasMore)
    XCTAssertEqual(page.nextSequence, 1000)
  }

  func testOlderEngineUsesFullPageFallback() throws {
    XCTAssertTrue(try JobEventPage(["events": events(1...500)], after: 0).hasMore)
    XCTAssertFalse(try JobEventPage(["events": events(501...507)], after: 500).hasMore)
  }

  func testEmptyPagePreservesCursor() throws {
    let page = try JobEventPage([
      "events": [[String: Any]](), "next_sequence": 900, "has_more_events": false,
    ], after: 900)
    XCTAssertEqual(page.nextSequence, 900)
    XCTAssertFalse(page.hasMore)
  }

  func testInterleavedRunsMayHaveNoncontiguousSequences() throws {
    let page = try JobEventPage([
      "events": [["sequence": 550], ["sequence": 571]], "next_sequence": 571,
      "has_more_events": false,
    ], after: 500)
    XCTAssertEqual(page.nextSequence, 571)
  }

  func testCancellationCanStillHaveAWriterWithoutAnotherPageYet() throws {
    let page = try JobEventPage([
      "status": "cancelled", "events": [[String: Any]](), "next_sequence": 900,
      "has_more_events": false, "event_stream_open": true,
    ], after: 900)
    XCTAssertFalse(page.hasMore)
    XCTAssertTrue(page.streamOpen)
  }

  func testInvalidPagesCannotLoopOrSkipActivity() {
    let records: [[String: Any]] = [
      ["events": [[String: Any]](), "has_more_events": true],
      ["events": [["sequence": 5], ["sequence": 5]]],
      ["events": [["sequence": 5], ["sequence": 4]]],
      ["events": [["sequence": 1]]],
      ["events": [["type": "answer"]]],
      ["events": [["sequence": 5]], "next_sequence": 6],
      ["events": events(2...502)],
    ]
    for record in records {
      XCTAssertThrowsError(try JobEventPage(record, after: 1))
    }
  }
}
