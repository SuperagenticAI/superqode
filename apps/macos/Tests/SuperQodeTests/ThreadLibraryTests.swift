import XCTest

@testable import SuperQode

final class ThreadLibraryTests: XCTestCase {
  func testRecentThreadsKeepLatestTurnAndPinOrderWhileHidingArchives() {
    let rows: [[String: Any]] = [
      ["id": "old", "kind": "task", "conversation_id": "pinned", "updated": 1.0, "pinned": true],
      ["id": "latest", "kind": "task", "conversation_id": "pinned", "updated": 2.0, "pinned": true],
      ["id": "newer", "kind": "task", "conversation_id": "newer", "updated": 3.0],
      ["id": "hidden", "kind": "task", "conversation_id": "hidden", "updated": 4.0, "archived": true],
    ]
    XCTAssertEqual(groupedRecentRuns(rows).map { string($0, "id") }, ["latest", "newer"])
  }

  @MainActor func testOlderThreadNavigationPreservesDraftAndSearchScope() {
    let suite = "ThreadLibraryTests." + UUID().uuidString
    let preferences = UserDefaults(suiteName: suite)!
    addTeardownBlock { preferences.removePersistentDomain(forName: suite) }
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: preferences)
    app.project = ["id": "project"]
    app.section = "Threads"
    let library = app.threadLibrary(for: "project")
    library.query = "routing"
    library.filter = "pinned"
    app.draft = "Keep new-thread draft"
    app.openSavedThread(["project": "project", "id": "old-turn", "conversation_id": "old-root"])
    XCTAssertEqual(app.selectedJob, "old-turn")
    XCTAssertEqual(app.composerConversationID, "old-root")
    XCTAssertFalse(app.loadingConversationDraft)
    app.draft = "Research follow-up"
    app.goBack()
    XCTAssertEqual(app.section, "Threads")
    XCTAssertEqual(app.draft, "Keep new-thread draft")
    XCTAssertEqual(app.threadLibrary(for: "project").query, "routing")
    XCTAssertEqual(app.threadLibrary(for: "project").filter, "pinned")
    XCTAssertTrue(app.threadLibrary(for: "other").query.isEmpty)
  }

  @MainActor func testLateThreadSearchCannotReplaceNewerResults() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    let library = ThreadLibrary()
    let first = Task { await library.load(engine: engine, project: "project", query: "old", view: "active") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    let second = Task { await library.load(engine: engine, project: "project", query: "new", view: "active") }
    while engine.pendingRequestCount < 2 { await Task.yield() }
    engine.receive(["id": 2, "result": ["items": [["conversation_id": "new"]], "next_cursor": ""]])
    await second.value
    engine.receive(["id": 1, "result": ["items": [["conversation_id": "old"]], "next_cursor": "stale"]])
    await first.value
    XCTAssertEqual(library.rows.map { string($0, "conversation_id") }, ["new"])
    XCTAssertTrue(library.cursor.isEmpty)
    XCTAssertFalse(library.loading)
    engine.stop()
  }

  func testConnectionEvidenceDoesNotInventVerificationOrResumeSupport() {
    let unknown = acpConnectionEvidence(metadata: [:], session: [:], digest: "route")
    XCTAssertEqual(unknown.first?.state, "Not checked")
    XCTAssertEqual(unknown.first { $0.id == "resume" }?.state, "Not checked")
    let session: [String: Any] = ["capabilities": ["loadSession": false, "promptCapabilities": ["image": true]]]
    let metadata: [String: Any] = ["connected": true, "route_digest": "route"]
    let checked = acpConnectionEvidence(metadata: metadata, session: session, digest: "route")
    XCTAssertEqual(checked.first?.state, "Verified")
    XCTAssertEqual(checked.first { $0.id == "resume" }?.state, "Not advertised")
    XCTAssertEqual(checked.first { $0.id == "images" }?.state, "Advertised")
    XCTAssertEqual(checked.first { $0.id == "coding" }?.state, "Not tested by this check")
    let stale = acpConnectionEvidence(metadata: metadata, session: session, digest: "changed-route")
    XCTAssertEqual(stale.first?.state, "Not checked")
    let failed = acpConnectionEvidence(metadata: metadata.merging(["last_check_error": "Disconnected"]) { _, new in new }, session: session, digest: "route")
    XCTAssertEqual(failed.first?.state, "Failed last check")
    XCTAssertEqual(failed.first { $0.id == "images" }?.state, "Not checked")
  }
}
