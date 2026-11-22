import XCTest
@testable import SuperQode

final class FactoryCampaignTests: XCTestCase {
  @MainActor func testCampaignListingCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryCampaignLibrary(); library.enter("first")
    let pending = Task { await library.perform(engine, "list") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 1, "result": ["campaigns": [["manifest": ["id": "foreign"]]]]])
    await pending.value
    XCTAssertTrue(library.campaigns.isEmpty); XCTAssertFalse(library.busy)
  }
  @MainActor func testNewSelectionInvalidatesEventPreview() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryCampaignLibrary(); library.enter("project"); library.selected = "first"
    let pending = Task { await library.perform(engine, "event.preview", ["id": "first"]) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.selected = "second"; library.clearPreview()
    engine.receive(["id": 1, "result": ["source": "stale", "digest": "old"]])
    await pending.value
    XCTAssertTrue(library.preview.isEmpty); XCTAssertFalse(library.busy)
  }
  @MainActor func testRuntimeCheckpointReceiptCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryOperationsLibrary(); library.enter("first")
    let pending = Task { await library.perform(engine, "checkpoint") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 1, "result": ["key_file": "foreign/private/key", "path": "foreign/archive"]])
    await pending.value
    XCTAssertTrue(library.result.isEmpty); XCTAssertFalse(library.busy)
  }
}
