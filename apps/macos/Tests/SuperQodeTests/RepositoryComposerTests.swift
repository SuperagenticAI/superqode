import XCTest
@testable import SuperQode

final class RepositoryComposerTests: XCTestCase {
  func testMentionQueryUsesTheTokenAtTheCursor() {
    XCTAssertEqual(ComposerMentions.query(in: "see @src/app"), "src/app")
    XCTAssertEqual(ComposerMentions.query(in: "mail a@b.com"), nil)
    XCTAssertEqual(ComposerMentions.query(in: "hello "), nil)
    let inserted = ComposerMentions.insert(text: "fix @src extra", prefix: "fix @src", path: "src/app.swift")
    XCTAssertEqual(inserted, "fix @src/app.swift extra")
  }

  func testSendingFullReturnsTheNextNewConversationToAsk() {
    let suite = "superqode.permission.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defaults.removePersistentDomain(forName: suite)
    let draft = WorkspaceRecoverySnapshot.key(project: "project", conversation: "")
    let created = WorkspaceRecoverySnapshot.key(project: "project", conversation: "job-1")
    PermissionMemory.store("full", composerKey: draft, defaults: defaults)
    PermissionMemory.commitNewConversation(
      "full", project: "project", conversation: "job-1", defaults: defaults)
    XCTAssertEqual(PermissionMemory.mode(for: created, defaults: defaults), "full")
    XCTAssertEqual(PermissionMemory.mode(for: draft, defaults: defaults), "ask")
    defaults.removePersistentDomain(forName: suite)
  }

  func testIsolationHandoffKeepsThePromptFilesThatExistInTheWorktree() {
    let moved = TaskIsolation.handoff(files: ["src/app.swift", "notes.txt", "/tmp/outside", "../escape"]) {
      $0 == "src/app.swift"
    }
    XCTAssertEqual(moved.files, ["src/app.swift"])
    XCTAssertEqual(moved.dropped, ["notes.txt", "/tmp/outside", "../escape"])
  }

  func testPermissionMemoryStaysAskUntilAConversationChoosesOtherwise() {
    let suite = "superqode.permission.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defaults.removePersistentDomain(forName: suite)
    XCTAssertEqual(PermissionMemory.mode(for: "draft", defaults: defaults), "ask")
    PermissionMemory.store("full", composerKey: "draft", defaults: defaults)
    PermissionMemory.store("host", composerKey: "draft", defaults: defaults)
    XCTAssertEqual(PermissionMemory.mode(for: "draft", defaults: defaults), "full")
    XCTAssertEqual(PermissionMemory.mode(for: "other", defaults: defaults), "ask")
    defaults.removePersistentDomain(forName: suite)
  }

  func testRepositoryPinsKeepKnownSectionsAndDropDuplicates() {
    XCTAssertEqual(
      RepositoryLayout.pinned(["Files", "Tools", "Files", "Not a screen", "Workspace"]),
      ["Files", "Tools", "Workspace"])
  }

  func testIsolationTitleIsBoundedAndChangeSummaryPrefersTheDiffStat() {
    XCTAssertEqual(TaskIsolation.title(from: ""), "Isolated task")
    XCTAssertEqual(TaskIsolation.title(from: String(repeating: "a", count: 200)), String(repeating: "a", count: 120))
    XCTAssertEqual(
      ChangeSummary.line(stat: " hello.txt | 1 +\n 1 file changed, 1 insertion(+)", status: " M hello.txt", diff: "diff", error: ""),
      "1 file changed, 1 insertion(+)")
    XCTAssertEqual(ChangeSummary.line(stat: "", status: "", diff: "", error: ""), nil)
    XCTAssertEqual(ChangeSummary.line(stat: "", status: " M a\n M b", diff: "", error: ""), "2 changed files")
  }

  @MainActor func testCreatorStaysInTheCatalogAndPermissionIsNotRecoveryState() throws {
    XCTAssertEqual(Sections.names.last, "Super Agent")
    XCTAssertEqual(Sections.names.count, Sections.icons.count)
    XCTAssertEqual(Sections.names.first, "Workspace")
    XCTAssertTrue(Sections.names.contains("Tools"))
    let data = try JSONEncoder().encode(ComposerRecovery(text: "draft"))
    let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
    XCTAssertNil(object?["permissionMode"])
    XCTAssertEqual(object?["mode"] as? String, "code")

    let suite = "superqode.permission.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defaults.removePersistentDomain(forName: suite)
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: defaults)
    app.project = ["id": "project"]
    app.restoreComposer(conversationID: "")
    XCTAssertEqual(app.permissionMode, "ask")
    app.permissionMode = "auto-edit"
    app.restoreComposer(conversationID: "other")
    XCTAssertEqual(app.permissionMode, "ask")
    app.restoreComposer(conversationID: "")
    XCTAssertEqual(app.permissionMode, "auto-edit")
    XCTAssertFalse(app.inspectorVisible)
    defaults.removePersistentDomain(forName: suite)
  }
}
