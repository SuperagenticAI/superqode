import XCTest

@testable import SuperQode

final class TurnSafetyTests: XCTestCase {
  @MainActor func testCancelledOrFailedTurnChangesAreNotCached() async {
    let store = TurnChangesStore()
    await store.load(job: "turn") { throw CancellationError() }
    XCTAssertNil(store.summary("turn"), "A cancelled request must not be cached as no changes")
    await store.load(job: "turn") { throw EngineError(message: "offline") }
    XCTAssertNil(store.summary("turn"))
    await store.load(job: "turn") {
      ["available": true, "file_count": 1, "files": [["path": "a.swift", "change": "modified"]]]
    }
    XCTAssertEqual(store.summary("turn")?.fileCount, 1)
    // Cached now: the same stamp does not refetch, and a later failure keeps it.
    var fetched = false
    await store.load(job: "turn") { fetched = true; return [:] }
    XCTAssertFalse(fetched)
    await store.load(job: "turn", force: true) { throw CancellationError() }
    XCTAssertEqual(store.summary("turn")?.fileCount, 1)
  }

  @MainActor func testTurnChangesReloadWhenRunStatusChanges() async {
    let store = TurnChangesStore()
    await store.load(job: "live", stamp: "running") { ["available": true, "file_count": 1] }
    var fetched = false
    await store.load(job: "live", stamp: "completed") { fetched = true; return ["available": true, "file_count": 2] }
    XCTAssertTrue(fetched)
    XCTAssertEqual(store.summary("live")?.fileCount, 2)
  }

  @MainActor func testPendingCommentsStayWithTheirThread() {
    let suite = "SuperQodeTests." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let store = PendingCommentStore(defaults: defaults)
    let first = PendingComment(path: "a.swift", lines: "L1", excerpt: "", text: "Rename")
    store.add(first, thread: "thread-a")
    store.add(PendingComment(path: "b.swift", lines: "L2", excerpt: "", text: "Later"), thread: "thread-a")
    XCTAssertTrue(store.comments("thread-b").isEmpty)
    // Only the sent comments are removed; one added meanwhile stays.
    store.remove(ids: [first.id], thread: "thread-a")
    XCTAssertEqual(store.comments("thread-a").map(\.text), ["Later"])
    // Persisted per thread across launches.
    XCTAssertEqual(PendingCommentStore(defaults: defaults).comments("thread-a").count, 1)
  }

  func testCommitDraftNeverOverwritesTypedText() {
    XCTAssertTrue(ShipRules.mayApplyDraft(current: "", lastDraft: ""))
    XCTAssertTrue(ShipRules.mayApplyDraft(current: "  \n", lastDraft: "Old draft"))
    XCTAssertTrue(ShipRules.mayApplyDraft(current: "Old draft", lastDraft: "Old draft"))
    XCTAssertFalse(ShipRules.mayApplyDraft(current: "My own message", lastDraft: ""))
    XCTAssertFalse(ShipRules.mayApplyDraft(current: "Old draft, edited", lastDraft: "Old draft"))
  }

  func testProjectStateIsNeverOfferedForCommit() {
    XCTAssertTrue(ShipRules.isPrivate(".superqode/checkpoints/state.json"))
    XCTAssertTrue(ShipRules.isPrivate("apps/.superqode/workorders/store.sqlite3"))
    XCTAssertTrue(ShipRules.isPrivate(".superqode-edit-1234"))
    XCTAssertFalse(ShipRules.isPrivate("Sources/superqode.swift"))
    XCTAssertFalse(ShipRules.isPrivate("docs/superqode/guide.md"))
    for refused in [".env", ".env.local", "config/.env", "apps/web/.env.production", ".git/config", "home/.ssh/id_ed25519", ".aws/credentials", ".superqode/checkpoints/state.json"] {
      XCTAssertTrue(ShipRules.isRefused(refused), refused)
    }
    XCTAssertFalse(ShipRules.isRefused("Sources/environment.swift"))
    XCTAssertFalse(ShipRules.isRefused("docs/env.md"))
  }
}
