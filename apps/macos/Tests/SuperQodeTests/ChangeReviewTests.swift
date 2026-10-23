import XCTest
@testable import SuperQode

final class ChangeReviewTests: XCTestCase {
  func testLineNumbersFollowEachSideOfPatch() {
    let rows = reviewLines("--- a/file\n+++ b/file\n@@ -10,2 +20,3 @@\n unchanged\n-old\n+new\n+extra\n\\ No newline at end of file")
    XCTAssertEqual(rows[3].old, 10)
    XCTAssertEqual(rows[3].new, 20)
    XCTAssertEqual(rows[4].old, 11)
    XCTAssertNil(rows[4].new)
    XCTAssertNil(rows[5].old)
    XCTAssertEqual(rows[5].new, 21)
    XCTAssertEqual(rows[6].new, 22)
    XCTAssertEqual(rows[7].kind, "meta")
  }
  func testSplitRowsAlignReplacementAndPreserveUnpairedAdditions() {
    let pairs = pairedReviewLines(reviewLines("@@ -1,1 +1,2 @@\n-before\n+after\n+another"))
    XCTAssertEqual(pairs.count, 3)
    XCTAssertEqual(pairs[1].left?.text, "before")
    XCTAssertEqual(pairs[1].right?.text, "after")
    XCTAssertNil(pairs[2].left)
    XCTAssertEqual(pairs[2].right?.text, "another")
  }
  func testConnectionHealthDoesNotExposeEmailIdentity() {
    XCTAssertEqual(privateConnectionMessage("Connected: person@example.com"), "Connected: [hidden account]")
  }
}
