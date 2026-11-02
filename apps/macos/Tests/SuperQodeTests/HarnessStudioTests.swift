import XCTest
@testable import SuperQode

final class HarnessStudioTests: XCTestCase {
  @MainActor func testEditingDuringValidationRejectsLateReviewAndReleasesBusyState() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = HarnessStudioLibrary()
    studio.enter("project"); studio.text = "name: old"
    let validation = Task { await studio.validate(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.text = "name: edited"
    XCTAssertFalse(studio.busy)
    engine.receive(["id": 1, "result": ["yaml": "name: old", "review": "stale"]])
    await validation.value
    XCTAssertEqual(studio.text, "name: edited")
    XCTAssertTrue(studio.review.isEmpty)
  }

  @MainActor func testProjectSwitchKeepsEachDraftAndRejectsPreviousProjectResponse() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = HarnessStudioLibrary()
    studio.enter("first"); studio.text = "first draft"; studio.name = "first-harness"
    let loading = Task { await studio.load(engine: engine, reference: "core") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second"); studio.text = "second draft"
    engine.receive(["id": 1, "result": ["yaml": "stale preset", "name": "stale-name"]])
    await loading.value
    XCTAssertEqual(studio.text, "second draft")
    studio.enter("first")
    XCTAssertEqual(studio.text, "first draft")
    XCTAssertEqual(studio.name, "first-harness")
    XCTAssertFalse(studio.busy)
  }

  @MainActor func testValidationAppliesCanonicalTextAndKeepsFreshReview() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = HarnessStudioLibrary()
    studio.enter("project"); studio.text = "name: draft"
    let validation = Task { await studio.validate(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["yaml": "name: canonical\n", "review": "fresh", "digest": "digest"]])
    await validation.value
    XCTAssertEqual(studio.text, "name: canonical\n")
    XCTAssertEqual(string(studio.review, "review"), "fresh")
    XCTAssertFalse(studio.busy)
    studio.model = "changed-model"
    XCTAssertTrue(studio.review.isEmpty)
  }

  @MainActor func testStudioIsDiscoverableAndRequiresAProject() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.connected = true
    XCTAssertEqual(Sections.names.count, Sections.icons.count)
    XCTAssertNotNil(app.workspaceCommands.first { $0.action == .section("Harness Studio") })
    XCTAssertNotNil(app.workspaceCommands.first { $0.action == .section("Harness Studio") }?.disabledReason)
    app.project = ["id": "project"]
    XCTAssertNil(app.workspaceCommands.first { $0.action == .section("Harness Studio") }?.disabledReason)
  }

  @MainActor func testEditingDuringSaveKeepsNewDraftAndRejectsLateNavigationSignal() async throws {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = HarnessStudioLibrary()
    studio.enter("project"); studio.text = "name: saved"
    studio.review = ["review": "review", "digest": "digest"]
    let saving = Task { try await studio.save(engine: engine, reason: "Fixture") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.text = "name: new-unsaved-draft"
    engine.receive(["id": 1, "result": ["digest": "saved-digest"]])
    let shouldNavigate = try await saving.value
    XCTAssertFalse(shouldNavigate)
    XCTAssertEqual(studio.text, "name: new-unsaved-draft")
    XCTAssertEqual(studio.expectedFileDigest, "")
    XCTAssertTrue(studio.message.isEmpty)
  }
}
