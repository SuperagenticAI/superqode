import XCTest

@testable import SuperQode

final class ReviewModelsTests: XCTestCase {
  private func response() -> [String: Any] {
    [
      "id": "file", "path": "Sources/File.swift", "layer": "unstaged", "scope": "uncommitted",
      "label": "Unstaged changes", "snapshot_id": "snapshot", "base_revision": "before",
      "target_revision": "after", "issue": "", "truncated": false, "can_stage": true,
      "hunks": [
        [
          "id": 0, "header": "@@ -1,1 +1,1 @@",
          "lines": [
            [
              "id": 0, "kind": "delete", "text": "before", "old_line": 1, "new_line": NSNull(),
              "no_newline": false,
            ],
            [
              "id": 1, "kind": "add", "text": "after", "old_line": NSNull(), "new_line": 1,
              "no_newline": false,
            ],
          ],
        ]
      ],
    ]
  }

  func testReviewDecodesBothSidesAndRevisionIdentity() throws {
    let document = try ReviewDocument.decode(response())
    XCTAssertTrue(document.complete)
    XCTAssertEqual(document.snapshotID, "snapshot")
    XCTAssertEqual(document.hunks[0].lines[0].oldLine, 1)
    XCTAssertNil(document.hunks[0].lines[0].newLine)
    XCTAssertEqual(document.hunks[0].lines[1].newLine, 1)
    XCTAssertEqual(document.hunks[0].lines[1].numberLabel, "old –, new 1")
  }

  func testReverseRangeAndNewHunkSelectionCannotCrossHunks() throws {
    let hunk = try ReviewDocument.decode(response()).hunks[0]
    var selected = ReviewLineSelection()
    selected.select(1, in: 0, extending: false)
    selected.select(0, in: 0, extending: true)
    XCTAssertEqual(selected.range(in: hunk), 0...1)
    selected.select(0, in: 1, extending: true)
    XCTAssertNil(selected.range(in: hunk))
    XCTAssertEqual(selected.start, 0)
    XCTAssertEqual(selected.end, 0)
  }

  func testInvalidRangeDoesNotProduceCoordinates() throws {
    let hunk = try ReviewDocument.decode(response()).hunks[0]
    XCTAssertNil(ReviewLineSelection(hunkID: 0, start: -1, end: 1).range(in: hunk))
    XCTAssertNil(ReviewLineSelection(hunkID: 0, start: 0, end: 99).range(in: hunk))
  }

  func testMalformedCoordinatesAreRejected() throws {
    for invalid in [
      ["id": 0, "kind": "add", "text": "x", "old_line": 1, "new_line": 1, "no_newline": false],
      [
        "id": 0, "kind": "delete", "text": "x", "old_line": 0, "new_line": NSNull(),
        "no_newline": false,
      ],
      [
        "id": 8, "kind": "add", "text": "x", "old_line": NSNull(), "new_line": 1,
        "no_newline": false,
      ],
    ] as [[String: Any]] {
      var value = response()
      value["hunks"] = [["id": 0, "header": "hunk", "lines": [invalid]]]
      XCTAssertThrowsError(try ReviewDocument.decode(value))
    }
  }

  func testIncompleteOrUnavailablePreviewCannotBeComplete() throws {
    var value = response()
    value["truncated"] = true
    XCTAssertFalse(try ReviewDocument.decode(value).complete)
    value["truncated"] = false
    value["issue"] = "Unsupported file"
    XCTAssertFalse(try ReviewDocument.decode(value).complete)
    value["issue"] = ""
    value.removeValue(forKey: "base_revision")
    XCTAssertFalse(try ReviewDocument.decode(value).complete)
  }

  func testScopeAndRequestKeepProjectRunAndBaseSeparate() {
    let selection = ReviewSelection(scope: .branch, fileID: "file", baseRef: "release", hunkID: 2)
    let params = selection.parameters(project: "project", job: "run")
    XCTAssertEqual(params["project"] as? String, "project")
    XCTAssertEqual(params["job"] as? String, "run")
    XCTAssertEqual(params["base_ref"] as? String, "release")
    XCTAssertEqual(params["scope"] as? String, "branch")
  }

  func testSavedDraftAndReviewSelectionRoundTripWithRecovery() throws {
    var snapshot = WorkspaceRecoverySnapshot()
    snapshot.lastDestination = WorkspaceDestination(
      projectID: "project", projectPath: "/project", section: "Review",
      review: ReviewSelection(scope: .turn, fileID: "file", baseRef: "main", hunkID: 2))
    snapshot.composers["key"] = ComposerRecovery(reviewComments: [
      "snapshot": ReviewCommentDraft(
        path: "file.swift", snapshotID: "snapshot", text: "Unfinished review",
        selection: .init(hunkID: 2, start: 1, end: 3))
    ])
    let decoded = try JSONDecoder().decode(
      WorkspaceRecoverySnapshot.self, from: JSONEncoder().encode(snapshot))
    XCTAssertEqual(decoded.lastDestination?.review?.hunkID, 2)
    XCTAssertEqual(decoded.composers["key"]?.reviewComments?["snapshot"]?.text, "Unfinished review")
  }

  func testExistingRecoveryWithoutReviewFieldsStillDecodes() throws {
    var snapshot = WorkspaceRecoverySnapshot()
    snapshot.lastDestination = WorkspaceDestination(projectID: "project", projectPath: "/project")
    snapshot.composers["key"] = ComposerRecovery(text: "Existing draft")
    let data = try JSONEncoder().encode(snapshot)
    let json = String(decoding: data, as: UTF8.self)
    XCTAssertFalse(json.contains("reviewComments"))
    let decoded = try JSONDecoder().decode(WorkspaceRecoverySnapshot.self, from: data)
    XCTAssertNil(decoded.lastDestination?.review)
    XCTAssertEqual(decoded.composers["key"]?.text, "Existing draft")
  }

  func testInvalidTopLevelResponseIsRejected() {
    XCTAssertThrowsError(try ReviewDocument.decode("invalid"))
  }
}
