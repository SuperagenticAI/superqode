import XCTest
@testable import SuperQode

final class ExternalSessionTests: XCTestCase {
  @MainActor func testLateExternalPageCannotReplaceNewScope() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let library = ExternalSessionLibrary()
    let first = Task { await library.load(engine: engine, source: "first", project: "", query: "") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": [["id": "first"]]])
    while engine.pendingRequestCount < 1 { await Task.yield() }
    let second = Task { await library.load(engine: engine, source: "second", project: "", query: "") }
    while engine.pendingRequestCount < 2 { await Task.yield() }
    engine.receive(["id": 3, "result": [["id": "second"]]])
    while engine.pendingRequestCount < 2 { await Task.yield() }
    engine.receive(["id": 4, "result": ["items": [["id": "new-scope"]], "count": 1, "next_cursor": ""]])
    await second.value
    engine.receive(["id": 2, "result": ["items": [["id": "stale-scope"]], "count": 50, "next_cursor": "stale"]])
    await first.value
    XCTAssertEqual(library.rows.map { string($0, "id") }, ["new-scope"])
    XCTAssertEqual(library.sources.map { string($0, "id") }, ["second"])
    XCTAssertEqual(library.count, 1)
    XCTAssertTrue(library.cursor.isEmpty)
    XCTAssertFalse(library.loading)
  }

  @MainActor func testChangedScopeClearsOldRowsAndIgnoresLateSourceResponse() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let library = ExternalSessionLibrary()
    library.rows = [["id": "previous-filter"]]
    library.cursor = "old"
    library.count = 99
    let load = Task { await library.load(engine: engine, source: "", project: "new-project", query: "") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    XCTAssertTrue(library.rows.isEmpty)
    XCTAssertTrue(library.cursor.isEmpty)
    XCTAssertEqual(library.count, 0)
    load.cancel()
    engine.receive(["id": 1, "result": [["id": "should-not-publish"]]])
    await load.value
    XCTAssertEqual(engine.pendingRequestCount, 0)
    XCTAssertTrue(library.sources.isEmpty)
    XCTAssertFalse(library.loading)
  }

  @MainActor func testExternalContextPreservesDraftsAndDoesNotStartATask() {
    let suite = "ExternalSessionTests." + UUID().uuidString
    let preferences = UserDefaults(suiteName: suite)!
    defer { preferences.removePersistentDomain(forName: suite) }
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: preferences)
    app.project = ["id": "project"]
    app.jobs = [["id": "existing", "project": "project", "kind": "task", "status": "completed"]]
    app.selectJob("")
    app.draft = "New thread draft"
    app.selectJob("existing")
    app.draft = "Existing thread draft"
    let context = "External Codex conversation context\nRecorded request"
    XCTAssertTrue(app.addSharedThreadContext(context, project: "project", target: ""))
    XCTAssertEqual(app.draft, "New thread draft\n\n" + context)
    app.selectJob("existing")
    XCTAssertEqual(app.draft, "Existing thread draft")
    XCTAssertEqual(app.jobs.count, 1)
    XCTAssertEqual(app.engine.pendingRequestCount, 0)
    XCTAssertEqual(Sections.title(for: "Agent activity"), "All work")
    XCTAssertEqual(HarnessIdentity(["id": "codex-cli", "icon_key": "codex"]).iconKey, "codex")
  }
}
