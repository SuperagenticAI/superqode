import XCTest
@testable import SuperQode

final class WorkbenchReviewTests: XCTestCase {
  private func listing(label: String, scope: String = "turn", files: [[String: Any]] = []) -> [String: Any] {
    ["scope": scope, "label": label, "files": files, "excluded_count": 0, "truncated": false]
  }
  @MainActor private func pending(_ count: Int, _ engine: Engine) async {
    let end = ContinuousClock.now.advanced(by: .seconds(2))
    while engine.pendingRequestCount != count && ContinuousClock.now < end { await Task.yield() }
    XCTAssertEqual(engine.pendingRequestCount, count)
  }
  @MainActor func testEmptyTurnDoesNotFallBackToUncommittedProjectChanges() async {
    let pipe = Pipe(); let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let review = WorkbenchReview()
    let load = Task { await review.load(engine: engine, project: "p", job: "a", scope: .turn) }
    await pending(1, engine)
    engine.receive(["id": 1, "result": listing(label: "Turn A")])
    await load.value
    XCTAssertEqual(review.listing?.scope, .turn)
    XCTAssertEqual(review.listing?.files.count, 0)
    XCTAssertNil(review.document)
    XCTAssertEqual(engine.pendingRequestCount, 0)
    XCTAssertTrue(review.failure.isEmpty)
  }
  @MainActor func testLateResponseCannotReplaceAnotherThreadsChanges() async {
    let pipe = Pipe(); let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let review = WorkbenchReview()
    let old = Task { await review.load(engine: engine, project: "old", job: "a", scope: .turn) }
    await pending(1, engine)
    let current = Task { await review.load(engine: engine, project: "new", job: "b", scope: .uncommitted) }
    await pending(2, engine)
    engine.receive(["id": 2, "result": listing(label: "New project", scope: "uncommitted")])
    await current.value
    engine.receive(["id": 1, "result": listing(label: "Old turn")])
    await old.value
    XCTAssertEqual(review.listing?.label, "New project")
    XCTAssertEqual(review.listing?.scope, .uncommitted)
    XCTAssertTrue(review.failure.isEmpty)
  }
  @MainActor func testUnexpectedScopeIsRejectedInsteadOfMislabellingProjectChanges() async {
    let pipe = Pipe(); let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let review = WorkbenchReview()
    let load = Task { await review.load(engine: engine, project: "p", job: "a", scope: .turn) }
    await pending(1, engine)
    engine.receive(["id": 1, "result": listing(label: "Project changes", scope: "uncommitted")])
    await load.value
    XCTAssertNil(review.listing)
    XCTAssertNil(review.document)
    XCTAssertFalse(review.failure.isEmpty)
  }
  @MainActor func testInlineDiffShowsOnlyTheRequestedFileAndRevisionScope() async {
    let pipe = Pipe(); let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let review = WorkbenchReview()
    let load = Task { await review.load(engine: engine, project: "p", job: "a", scope: .turn) }
    await pending(1, engine)
    engine.receive(["id": 1, "result": listing(label: "Turn A", files: [["id": "file", "path": "main.py", "layer": "turn", "change": "modified"]])])
    await pending(1, engine)
    await review.select("file", engine: engine)
    XCTAssertEqual(engine.pendingRequestCount, 1, "Clicking the loading file must reuse its request")
    engine.receive(["id": 2, "result": ["id": "file", "path": "main.py", "layer": "turn", "scope": "turn", "label": "Turn A", "hunks": [], "issue": "", "truncated": false, "can_stage": false]])
    await load.value
    XCTAssertEqual(review.document?.path, "main.py")
    XCTAssertEqual(review.document?.scope, .turn)
    XCTAssertTrue(review.failure.isEmpty)
    await review.select("file", engine: engine)
    XCTAssertEqual(review.document?.path, "main.py", "Clicking the loaded file must keep the diff visible")
    XCTAssertEqual(engine.pendingRequestCount, 0)
  }

  @MainActor func testDisconnectClearsChangesAndRejectsAnOutstandingResponse() async {
    let pipe = Pipe(); let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let review = WorkbenchReview()
    let load = Task { await review.load(engine: engine, project: "old", job: "a", scope: .turn) }
    await pending(1, engine)
    review.reset()
    engine.receive(["id": 1, "result": listing(label: "Old turn")])
    await load.value
    XCTAssertNil(review.listing)
    XCTAssertNil(review.document)
    XCTAssertFalse(review.loading)
  }

  @MainActor func testOfflineSendKeepsDraftAndDoesNotStartAnEngineRequest() {
    let pipe = Pipe(); let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let suite = "workbench.offline.\(UUID().uuidString)"; let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: defaults, engine: engine)
    app.project = ["id": "p"]; app.model = "fixture"; app.draft = "Keep this request"
    XCTAssertFalse(app.canSubmitDraft)
    app.send(continueSession: false)
    XCTAssertEqual(app.draft, "Keep this request")
    XCTAssertEqual(engine.pendingRequestCount, 0)
    XCTAssertTrue(app.notice.contains("offline"))
    app.connected = true
    XCTAssertTrue(app.canSubmitDraft)
  }

  @MainActor func testLocalServerJobDoesNotDisableSend() {
    let pipe = Pipe(); let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let suite = "workbench.local-send.\(UUID().uuidString)"; let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: defaults, engine: engine)
    app.connected = true
    app.project = ["id": "p"]
    app.harness = "pipy"
    app.provider = "ollama"
    app.model = "qwen3:8b"
    app.draft = "hello"
    app.jobs = [["id": "server", "project": "local-model-workspace", "kind": "local", "status": "running"]]
    app.selectedJob = "server"
    app.detail = ["id": "server", "kind": "local", "status": "running", "project": "local-model-workspace"]
    XCTAssertFalse(app.active)
    XCTAssertTrue(app.canSubmitDraft)
  }
}
