import XCTest

@testable import SuperQode

#if canImport(Combine)
  import Combine
#endif

final class WorkspaceSessionTests: XCTestCase {
  @MainActor private func workspace(store: WorkspaceRecoveryStore? = nil, engine: Engine? = nil)
    -> Workspace
  {
    let suite = "SuperQodeTests." + UUID().uuidString
    let defaults = UserDefaults(suiteName: suite)!
    addTeardownBlock { defaults.removePersistentDomain(forName: suite) }
    let app = Workspace(
      recoveryStore: store ?? WorkspaceRecoveryStore(directory: nil), preferences: defaults,
      engine: engine)
    addTeardownBlock {
      await MainActor.run { app.saveDraft() }
    }
    app.project = ["id": "project", "path": "/tmp/project"]
    app.showWelcome = false
    app.jobs = [
      ["id": "a", "project": "project", "kind": "task", "conversation_id": "root-a"],
      ["id": "a-next", "project": "project", "kind": "task", "conversation_id": "root-a"],
      ["id": "b", "project": "project", "kind": "task", "conversation_id": "root-b"],
    ]
    return app
  }

  @MainActor func testConversationDraftsRemainSeparateAndSiblingTurnsShareOneDraft() async {
    let app = workspace()
    app.draft = "New-task draft"
    app.selectJob("a")
    XCTAssertEqual(app.draft, "")
    app.draft = "Draft A"
    app.contextFiles = ["a.swift"]
    app.imageAttachments = [["id": "snapshot", "name": "design.png"]]
    app.selectJob("b")
    XCTAssertTrue(app.draft.isEmpty)
    XCTAssertTrue(app.contextFiles.isEmpty)
    app.draft = "Draft B"
    app.selectJob("a-next")
    XCTAssertEqual(app.draft, "Draft A")
    XCTAssertEqual(app.contextFiles, ["a.swift"])
    XCTAssertEqual(app.imageAttachments.first?["id"] as? String, "snapshot")
    app.selectJob("")
    XCTAssertEqual(app.draft, "New-task draft")
    app.selectJob("b")
    XCTAssertEqual(app.draft, "Draft B")
  }

  @MainActor func testBackAndForwardRestoreExactDestinationAndDraft() async {
    let app = workspace()
    app.selectJob("a")
    app.draft = "Keep A"
    app.selectedFile = "Sources/A.swift"
    app.inspectorVisible = true
    app.checkpointID = "checkpoint-a"
    app.checkpointPath = "Sources/A.swift"
    app.section = "Files"
    let destination = app.currentDestination
    app.selectJob("b", targetSection: "Workspace")
    app.draft = "Keep B"
    app.goBack()
    XCTAssertEqual(app.currentDestination, destination)
    XCTAssertEqual(app.draft, "Keep A")
    app.goForward()
    XCTAssertEqual(app.selectedJob, "b")
    XCTAssertEqual(app.section, "Workspace")
    XCTAssertEqual(app.draft, "Keep B")
    XCTAssertFalse(app.inspectorVisible)
    app.goBack()
    app.section = "Terminal"
    XCTAssertTrue(app.forwardHistory.isEmpty)
  }

  @MainActor func testLegacyProjectDraftMigratesOnlyToNewTaskAndOnlyOnce() async {
    let app = workspace()
    app.preferences.set(["project": "Legacy draft"], forKey: "nativeDrafts")
    app.migrateLegacyDraft(settings: [:])
    app.restoreComposer(conversationID: "root-a")
    XCTAssertTrue(app.draft.isEmpty)
    app.restoreComposer(conversationID: "")
    XCTAssertEqual(app.draft, "Legacy draft")
    app.draft = "New value"
    app.saveDraft()
    app.migrateLegacyDraft(settings: ["drafts": ["project": "Older engine draft"]])
    app.restoreComposer(conversationID: "")
    XCTAssertEqual(app.draft, "New value")
  }

  @MainActor func testDelayedAcceptanceClearsOnlyItsOriginalPayload() async {
    let app = workspace()
    app.selectJob("a")
    app.draft = "Accepted A"
    app.contextFiles = ["a.swift"]
    let key = app.composerKey
    let submitted = app.composerRecovery
    app.selectJob("b")
    app.draft = "Untouched B"
    app.contextFiles = ["b.swift"]
    app.clearAcceptedSubmission(key: key, submitted: submitted)
    XCTAssertEqual(app.draft, "Untouched B")
    XCTAssertEqual(app.contextFiles, ["b.swift"])
    app.selectJob("a")
    XCTAssertTrue(app.draft.isEmpty)
    XCTAssertTrue(app.contextFiles.isEmpty)
  }

  @MainActor func testDelayedAcceptancePreservesNewerEditsInOriginalSession() async {
    let app = workspace()
    app.selectJob("a")
    app.draft = "Accepted"
    let key = app.composerKey
    let submitted = app.composerRecovery
    app.draft = "Newer text"
    app.contextFiles = ["new.swift"]
    app.selectJob("b")
    app.clearAcceptedSubmission(key: key, submitted: submitted)
    app.selectJob("a")
    XCTAssertEqual(app.draft, "Newer text")
    XCTAssertEqual(app.contextFiles, ["new.swift"])
  }

  @MainActor func testRestartRestoresDraftAndUIWithoutStartingExecution() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    addTeardownBlock { try? FileManager.default.removeItem(at: directory) }
    let app = workspace(store: WorkspaceRecoveryStore(directory: directory))
    app.selectJob("a-next")
    app.draft = "Unsent after restart"
    app.selectedFile = "deleted.swift"
    app.inspectorVisible = true
    app.fileDrafts["project\ndeleted.swift"] = FileEdit(
      original: "base", digest: "hash", text: "recovered")
    app.saveDraft()
    let destination = try XCTUnwrap(app.recoverySnapshot.lastDestination)
    let restarted = workspace(store: WorkspaceRecoveryStore(directory: directory))
    restarted.applyDestination(destination)
    XCTAssertEqual(restarted.selectedJob, "a-next")
    XCTAssertEqual(restarted.composerConversationID, "root-a")
    XCTAssertEqual(restarted.draft, "Unsent after restart")
    XCTAssertEqual(restarted.selectedFile, "deleted.swift")
    XCTAssertEqual(restarted.recoveredFilePaths, ["deleted.swift"])
    XCTAssertTrue(restarted.inspectorVisible)
    XCTAssertFalse(restarted.connected)
    XCTAssertFalse(restarted.busy)
    XCTAssertTrue(restarted.terminals.running.isEmpty)
  }

  @MainActor func testTranscriptPositionUsesOriginalProjectAfterNavigation() async {
    let app = workspace()
    app.setTranscriptPosition(
      TranscriptPosition(follow: false, anchor: "turn:old"), for: "a", project: "previous")
    XCTAssertTrue(app.transcriptPosition(for: "a").follow)
    let key = WorkspaceRecoverySnapshot.key(project: "previous", conversation: "a")
    XCTAssertEqual(app.recoverySnapshot.transcripts[key]?.anchor, "turn:old")
  }

  @MainActor func testUnknownConversationDoesNotOverwriteExistingDraftBeforeIdentityLoads() async {
    let app = workspace()
    app.selectJob("a")
    app.draft = "Keep this"
    app.selectJob("older-run-not-in-recents")
    XCTAssertTrue(app.loadingConversationDraft)
    app.saveDraft()
    app.selectJob("a")
    XCTAssertEqual(app.draft, "Keep this")
  }

  @MainActor func testProjectLoadingCannotAutosavePreviousDraftIntoNextProject() async {
    let app = workspace()
    app.draft = "Previous project text"
    app.saveDraft()
    let targetKey = WorkspaceRecoverySnapshot.key(project: "next-project", conversation: "")
    app.recoverySnapshot.composers[targetKey] = ComposerRecovery(text: "Existing target draft")
    app.openingProject = true
    app.project = ["id": "next-project", "path": "/tmp/next-project"]
    app.contextFiles = []
    app.saveDraft()
    XCTAssertEqual(app.recoverySnapshot.composers[targetKey]?.text, "Existing target draft")
    app.openingProject = false
    app.restoreComposer(conversationID: "")
    XCTAssertEqual(app.draft, "Existing target draft")
  }

  @MainActor private func reply(_ engine: Engine, id: Int, result: Any? = nil, error: String? = nil)
    async
  {
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while engine.pendingRequestCount == 0 && ContinuousClock.now < deadline { await Task.yield() }
    XCTAssertEqual(engine.pendingRequestCount, 1)
    if let error {
      engine.receive(["id": id, "error": error])
    } else {
      engine.receive(["id": id, "result": result ?? NSNull()])
    }
  }

  @MainActor func testProjectSetupFailureLeavesPreviousDestinationAndDraftIntact() async {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.selectJob("a", targetSection: "Files")
    app.draft = "Keep previous draft"
    app.selectedFile = "a.swift"
    let previous = app.currentDestination
    let opening = Task { try await app.open("/tmp/next") }
    await reply(engine, id: 1, result: ["id": "next", "path": "/tmp/next"])
    await reply(engine, id: 2, result: [["id": "next", "path": "/tmp/next"]])
    await reply(engine, id: 3, error: "Harness discovery unavailable")
    do {
      try await opening.value
      XCTFail("Opening should fail")
    } catch { XCTAssertTrue(error.localizedDescription.contains("Harness discovery unavailable")) }
    XCTAssertEqual(app.currentDestination, previous)
    XCTAssertEqual(app.draft, "Keep previous draft")
    XCTAssertFalse(app.openingProject)
  }

  @MainActor func testChangedProjectIdentityDoesNotReplaceVisibleProject() async {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.draft = "Keep current work"
    let previous = app.currentDestination
    let target = WorkspaceDestination(projectID: "expected", projectPath: "/tmp/replaced")
    let restoring = Task { try await app.restoreDestination(target) }
    await reply(engine, id: 1, result: ["id": "different", "path": "/tmp/replaced"])
    do {
      try await restoring.value
      XCTFail("Identity mismatch should fail")
    } catch { XCTAssertTrue(error.localizedDescription.contains("identity changed")) }
    XCTAssertEqual(app.currentDestination, previous)
    XCTAssertEqual(app.draft, "Keep current work")
    XCTAssertFalse(app.restoringNavigation)
  }

  @MainActor func testUnavailableHistoryDestinationReleasesNavigationLock() async {
    let app = workspace()
    let previous = app.currentDestination
    app.restoringNavigation = true
    do {
      try await app.restoreDestination(WorkspaceDestination(projectID: "missing", projectPath: ""))
      XCTFail("A missing path should fail")
    } catch { XCTAssertTrue(error.localizedDescription.contains("unavailable")) }
    XCTAssertFalse(app.restoringNavigation)
    XCTAssertEqual(app.currentDestination, previous)
  }

  #if canImport(Combine)
    @MainActor func testEditingExistingRecoveryDraftDoesNotInvalidateWholeWorkspace() async {
      let app = workspace()
      var changes = 0
      let observer = app.objectWillChange.sink { changes += 1 }
      app.fileDrafts["project\na.swift"] = FileEdit(original: "base", digest: "hash", text: "first")
      XCTAssertEqual(changes, 1)
      for index in 0..<100 {
        app.fileDrafts["project\na.swift"] = FileEdit(
          original: "base", digest: "hash", text: "edit \(index)")
      }
      XCTAssertEqual(changes, 1)
      XCTAssertEqual(app.fileDrafts["project\na.swift"]?.text, "edit 99")
      withExtendedLifetime(observer) {}
    }
  #endif

  @MainActor func testReviewDraftsAndSelectionStayWithTheirConversation() async {
    let app = workspace()
    app.selectJob("a")
    app.reviewSelection = ReviewSelection(
      scope: .turn, fileID: "file-a", baseRef: "release", hunkID: 2)
    app.reviewCommentStore.drafts["snapshot"] = ReviewCommentDraft(
      path: "a.swift", snapshotID: "snapshot",
      text: "Keep my review", selection: .init(hunkID: 2, start: 0, end: 1))
    app.selectJob("b")
    XCTAssertTrue(app.reviewCommentStore.drafts.isEmpty)
    XCTAssertEqual(app.reviewSelection.scope, .uncommitted)
    app.selectJob("a-next")
    XCTAssertEqual(app.reviewCommentStore.drafts["snapshot"]?.text, "Keep my review")
    XCTAssertEqual(app.reviewSelection.fileID, "file-a")
    XCTAssertEqual(app.reviewSelection.hunkID, 2)
  }

  @MainActor func testCompactionAndFollowupKeepTheSameComposerAndReviewDrafts() async {
    let app = workspace()
    app.jobs.append([
      "id": "compacted", "project": "project", "kind": "compaction", "conversation_id": "root-a",
    ])
    app.selectJob("a")
    app.draft = "Unsent follow-up"
    app.reviewCommentStore.drafts["snapshot"] = ReviewCommentDraft(
      path: "a.swift", snapshotID: "snapshot",
      text: "Pending review", selection: .init(hunkID: 0, start: 0, end: 1))
    app.selectJob("compacted")
    XCTAssertEqual(app.draft, "Unsent follow-up")
    XCTAssertEqual(app.composerConversationID, "root-a")
    XCTAssertEqual(app.reviewCommentStore.drafts["snapshot"]?.text, "Pending review")
    app.draft = "After compaction"
    app.selectJob("b")
    app.selectJob("a-next")
    XCTAssertEqual(app.draft, "After compaction")
    XCTAssertEqual(app.reviewCommentStore.drafts["snapshot"]?.text, "Pending review")
  }

  @MainActor func testReviewFeedbackAppendsToDraftWithoutSendingOrAffectingAnotherSession() async {
    let app = workspace()
    app.selectJob("a")
    app.section = "Review"
    app.draft = "Existing request"
    let key = app.composerKey
    XCTAssertTrue(
      app.appendReviewFeedback("Revision-bound feedback", project: app.projectID, conversation: key)
    )
    XCTAssertEqual(app.draft, "Existing request\n\nRevision-bound feedback")
    XCTAssertEqual(app.section, "Workspace")
    XCTAssertFalse(app.busy)
    app.selectJob("b")
    app.draft = "Keep B"
    XCTAssertFalse(
      app.appendReviewFeedback("Stale response", project: app.projectID, conversation: key))
    XCTAssertEqual(app.draft, "Keep B")
  }
}
