import XCTest
@testable import SuperQode

final class FactorySetupTests: XCTestCase {
  private let review: [String: Any] = ["review": "native-review", "yaml": "draft", "digest": "saved", "snapshot_digest": "snapshot"]
  func testAnEditedOrUnvalidatedDraftCannotAppearReady() {
    let empty = FactorySetupState(text: "", review: [:], savedDigest: "", sources: [:], runs: [])
    XCTAssertEqual(empty.action, "Load a starter")
    let changed = FactorySetupState(text: "new draft", review: review, savedDigest: "saved", sources: [:], runs: [])
    XCTAssertFalse(changed.validated); XCTAssertFalse(changed.saved); XCTAssertEqual(changed.action, "Validate draft")
  }
  func testValidationDoesNotImplySavingOrCommitting() {
    let unsaved = FactorySetupState(text: "draft", review: review, savedDigest: "old", sources: [:], runs: [])
    XCTAssertTrue(unsaved.validated); XCTAssertFalse(unsaved.saved); XCTAssertFalse(unsaved.committed)
    XCTAssertEqual(unsaved.action, "Review & save")
    let saved = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: [:], runs: [])
    XCTAssertTrue(saved.saved); XCTAssertFalse(saved.committed); XCTAssertEqual(saved.action, "Review source changes")
  }
  func testSourceEvidenceMustMatchAndEveryDeclaredSourceMustBeUnchanged() {
    for sources: [String: Any] in [
      ["snapshot_digest": "other", "files": [["changed": false]]],
      ["snapshot_digest": "snapshot", "files": [["changed": true]]],
      ["snapshot_digest": "snapshot", "files": [[:]]],
      ["snapshot_digest": "snapshot", "files": []]] {
      let state = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: sources, runs: [])
      XCTAssertFalse(state.committed)
    }
  }
  func testReadyJourneyPointsToAnExplicitTrialWithoutPretendingItRan() {
    let sources: [String: Any] = ["snapshot_digest": "snapshot", "files": [["changed": false]]]
    let ready = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: sources, runs: [["factory_digest": "other"]])
    XCTAssertTrue(ready.committed); XCTAssertFalse(ready.trialPrepared); XCTAssertEqual(ready.action, "Prepare a trial")
    let queued = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: sources, runs: [["factory_digest": "snapshot", "status": "queued"]])
    XCTAssertTrue(queued.trialPrepared); XCTAssertEqual(queued.action, "Open trials")
  }
}
