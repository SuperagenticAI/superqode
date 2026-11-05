import XCTest

@testable import SuperQode

#if canImport(Combine)
  import Combine
#endif

final class WorkspaceSessionTests: XCTestCase {
  @MainActor func testNewThreadDropsConnectionWithoutStoppingOtherWork() {
    let app = workspace()
    app.selectJob("a")
    app.draft = "Keep this draft"
    app.harness = "acp:qwen"
    app.provider = "agent"
    app.model = "last-model"
    app.agentModel = "last-agent-model"
    app.agentMode = "edit"
    app.agentConfig = ["effort": "high"]
    app.connectionMetadata = ["acp:qwen": ["connected": true]]
    app.routeStatus = ["ready": true]
    app.jobs.append(["id": "working", "project": "project", "status": "running"])
    app.selectJob("", targetSection: "Workspace")
    XCTAssertTrue(app.connectionDisconnected)
    XCTAssertNil(app.composerHarnessIdentity)
    XCTAssertTrue(app.provider.isEmpty)
    XCTAssertTrue(app.model.isEmpty)
    XCTAssertTrue(app.agentModel.isEmpty)
    XCTAssertTrue(app.agentMode.isEmpty)
    XCTAssertTrue(app.agentConfig.isEmpty)
    XCTAssertTrue(app.connectionMetadata.isEmpty)
    XCTAssertTrue(app.routeStatus.isEmpty)
    XCTAssertFalse(app.canSubmitDraft)
    XCTAssertEqual(app.jobs.last?["status"] as? String, "running")
    app.selectJob("a")
    XCTAssertEqual(app.draft, "Keep this draft")
  }

  @MainActor func testStartupRouteResetDoesNotPersistOrContactAnAgent() {
    let app = workspace()
    app.harness = "connection:codex"
    app.provider = "agent"
    app.model = "remembered-model"
    app.resetThreadConnection()
    XCTAssertTrue(app.connectionDisconnected)
    XCTAssertEqual(app.engine.pendingRequestCount, 0)
    XCTAssertFalse(app.checkingConnection)
    XCTAssertTrue(app.model.isEmpty)
  }

  @MainActor func testRepeatedNewThreadActionsNeverReuseAChosenDraftConnection() {
    let app = workspace()
    app.connected = true
    app.harnesses = [["id": "acp:opencode", "name": "OpenCode", "agent_id": "opencode"]]
    app.harness = "acp:opencode"
    app.provider = "agent"
    app.model = "last-model"
    XCTAssertEqual(app.composerHarnessIdentity?.name, "OpenCode")
    app.runWorkspaceCommand(.newTask)
    XCTAssertTrue(app.selectedJob.isEmpty)
    XCTAssertTrue(app.connectionDisconnected)
    XCTAssertNil(app.composerHarnessIdentity)
    XCTAssertTrue(app.model.isEmpty)
    XCTAssertTrue(app.conversationHistory.isEmpty)
    XCTAssertEqual(app.engine.pendingRequestCount, 0)
    // A manually chosen route can have a colourful badge in an unsent draft.
    app.harness = "acp:opencode"
    XCTAssertNotNil(app.composerHarnessIdentity)
    // Pressing New again clears that draft's route too.
    app.selectJob("", targetSection: "Workspace")
    XCTAssertNil(app.composerHarnessIdentity)
  }

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

  @MainActor func testThreadTabsGroupTurnsAndClosingKeepsDrafts() {
    let app = workspace()
    app.selectJob("a")
    app.draft = "Keep A"
    app.selectJob("b")
    app.draft = "Keep B"
    app.selectJob("a-next")
    XCTAssertEqual(app.openThreadTabs.count, 2)
    XCTAssertEqual(app.threadTabsByProject["project"], ["root-a", "root-b"])
    XCTAssertEqual(app.draft, "Keep A")
    app.closeThreadTab("root-a")
    XCTAssertEqual(app.selectedConversationID, "root-b")
    XCTAssertEqual(app.draft, "Keep B")
    XCTAssertEqual(app.jobs.count, 3, "Closing a tab must not delete or cancel a job")
    app.selectJob("a")
    XCTAssertEqual(app.draft, "Keep A")
    app.closeThreadTab("root-b")
    XCTAssertEqual(app.selectedConversationID, "root-a")
    app.closeThreadTab("root-a")
    XCTAssertTrue(app.selectedJob.isEmpty)
    XCTAssertTrue(app.openThreadTabs.isEmpty)
    app.selectJob("b")
    XCTAssertEqual(app.draft, "Keep B")
  }

  @MainActor func testKeyboardTabCyclingWrapsAndPreservesEachDraft() {
    let app = workspace()
    app.selectJob("a"); app.draft = "Draft A"
    app.selectJob("b"); app.draft = "Draft B"
    app.cycleThreadTab(by: 1)
    XCTAssertEqual(app.selectedConversationID, "root-a")
    XCTAssertEqual(app.draft, "Draft A")
    app.cycleThreadTab(by: -1)
    XCTAssertEqual(app.selectedConversationID, "root-b")
    XCTAssertEqual(app.draft, "Draft B")
    app.openingProject = true
    app.cycleThreadTab(by: 1)
    XCTAssertEqual(app.selectedConversationID, "root-b")
  }

  @MainActor func testThreadTabsPersistAndStayWithinTheirProject() {
    let app = workspace()
    app.selectJob("a")
    let restored = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: app.preferences)
    restored.project = app.project
    restored.jobs = app.jobs
    XCTAssertEqual(restored.openThreadTabs.count, 1)
    restored.project = ["id": "other"]
    XCTAssertTrue(restored.openThreadTabs.isEmpty)
    restored.rememberThreadTab(["id": "foreign", "project": "project", "kind": "task"])
    restored.rememberThreadTab(["id": "check", "project": "other", "kind": "check"])
    XCTAssertNil(restored.threadTabsByProject["other"])
  }

  @MainActor func testStagedImagesDoNotAttachToAnotherConversation() async throws {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.selectJob("a")
    let key = app.composerKey
    let staging = Task { try await app.stageImage("/tmp/paste.png", for: key) }
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while engine.pendingRequestCount == 0 && ContinuousClock.now < deadline { await Task.yield() }
    XCTAssertEqual(engine.pendingRequestCount, 1)
    app.selectJob("b")
    app.imageAttachments = [["id": "b-image", "name": "keep.png"]]
    await reply(engine, id: 1, result: ["id": "pasted", "name": "paste.png"])
    try await staging.value
    XCTAssertEqual(app.imageAttachments.first?["id"] as? String, "b-image")
    XCTAssertEqual(app.imageAttachments.count, 1)
    app.selectJob("a")
    XCTAssertTrue(app.imageAttachments.isEmpty)
  }

  @MainActor func testStagedImagesAttachToTheOriginalDraftAndRespectTheLimit() async throws {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    let key = app.composerKey
    let staging = Task { try await app.stageImage("/tmp/paste.png", for: key) }
    await reply(engine, id: 1, result: ["id": "pasted", "name": "paste.png"])
    try await staging.value
    XCTAssertEqual(app.imageAttachments.first?["id"] as? String, "pasted")
    let second = Task { try await app.stageImage("/tmp/other.png", for: key) }
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while engine.pendingRequestCount == 0 && ContinuousClock.now < deadline { await Task.yield() }
    app.imageAttachments = (0..<4).map { ["id": "image-\($0)"] }
    await reply(engine, id: 2, result: ["id": "extra"])
    do { try await second.value; XCTFail("A delayed image must not exceed the attachment limit") }
    catch { XCTAssertEqual(error.localizedDescription, "Attach up to four images.") }
    XCTAssertEqual(app.imageAttachments.count, 4)
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

  @MainActor private func finishAcceptedSend(_ app: Workspace, engine: Engine) async {
    await reply(engine, id: 2, result: app.jobs)
    await reply(engine, id: 3, result: [:])
    await reply(engine, id: 4, result: ["items": []])
    await reply(engine, id: 5, result: [:])
    await reply(engine, id: 6, result: [])
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while app.busy && ContinuousClock.now < deadline { await Task.yield() }
    XCTAssertFalse(app.busy)
  }

  @MainActor func testAcceptedFullResetsOriginalDraftAfterThreadNavigation() async {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.harnesses = [["id": app.harness, "enforces_session_controls": true]]
    app.model = "fixture-model"
    app.draft = "Submitted task"
    app.permissionMode = "full"
    app.connected = true
    app.send(continueSession: false)
    app.connected = false
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while engine.pendingRequestCount == 0 && ContinuousClock.now < deadline { await Task.yield() }
    app.selectJob("b")
    app.draft = "Keep the other thread"
    app.permissionMode = "auto-edit"
    await reply(engine, id: 1, result: ["id": "accepted"])
    await finishAcceptedSend(app, engine: engine)

    XCTAssertEqual(app.draft, "Keep the other thread")
    XCTAssertEqual(app.permissionMode, "auto-edit")
    let createdKey = WorkspaceRecoverySnapshot.key(project: "project", conversation: "accepted")
    XCTAssertEqual(PermissionMemory.mode(for: createdKey, defaults: app.preferences), "full")
    app.selectJob("")
    XCTAssertEqual(app.permissionMode, "ask")
    XCTAssertEqual(app.draft, "")
  }

  @MainActor func testAcceptedFullKeepsNewerTextButResetsItsPermission() async {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.harnesses = [["id": app.harness, "enforces_session_controls": true]]
    app.model = "fixture-model"
    app.draft = "Submitted task"
    app.permissionMode = "full"
    app.connected = true
    app.send(continueSession: false)
    app.connected = false
    app.draft = "Next task typed while sending"
    await reply(engine, id: 1, result: ["id": "accepted"])
    await finishAcceptedSend(app, engine: engine)

    XCTAssertEqual(app.composerConversationID, "")
    XCTAssertEqual(app.draft, "Next task typed while sending")
    XCTAssertEqual(app.permissionMode, "ask")
    XCTAssertEqual(PermissionMemory.mode(for: app.composerKey, defaults: app.preferences), "ask")
  }

  @MainActor func testRejectedSendDoesNotResetPermissionOrDiscardDraft() async {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.harnesses = [["id": app.harness, "enforces_session_controls": true]]
    app.model = "fixture-model"
    app.draft = "Keep the rejected task"
    app.permissionMode = "full"
    app.connected = true
    app.send(continueSession: false)
    app.connected = false
    await reply(engine, id: 1, error: "Connection unavailable")
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while app.busy && ContinuousClock.now < deadline { await Task.yield() }

    XCTAssertFalse(app.busy)
    XCTAssertEqual(app.draft, "Keep the rejected task")
    XCTAssertEqual(app.permissionMode, "full")
    XCTAssertEqual(PermissionMemory.mode(for: app.composerKey, defaults: app.preferences), "full")
  }

  @MainActor func testIsolationMovesExistingThreadDraftAndLeavesNewConversationAlone() throws {
    let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: root) }
    try Data("committed".utf8).write(to: root.appendingPathComponent("tracked.txt"))
    let app = workspace()
    let images: [[String: Any]] = [["id": "staged-image", "name": "example.png"]]
    app.draft = "Same goal"
    app.contextFiles = ["tracked.txt", "uncommitted.txt"]
    app.imageAttachments = images
    app.saveDraft()
    let unrelatedKey = app.composerKey
    let unrelatedDraft = app.composerRecovery
    app.selectJob("a")
    app.draft = "Same goal"
    app.contextFiles = ["tracked.txt", "uncommitted.txt"]
    app.imageAttachments = images
    app.permissionMode = "full"
    app.saveDraft()
    let sourceKey = app.composerKey
    app.project = ["id": "isolated", "path": root.path]
    app.restoreComposer(conversationID: "")
    app.moveDraftToOpenedWorkspace(
      text: "Same goal", files: ["tracked.txt", "uncommitted.txt"], images: images,
      fromProject: "project", fromComposerKey: sourceKey)

    XCTAssertEqual(app.draft, "Same goal")
    XCTAssertEqual(app.contextFiles, ["tracked.txt"])
    XCTAssertEqual(app.imageAttachments.first?["id"] as? String, "staged-image")
    XCTAssertEqual(app.permissionMode, "ask")
    XCTAssertEqual(app.recoverySnapshot.composers[sourceKey]?.text, "")
    XCTAssertEqual(app.recoverySnapshot.composers[sourceKey]?.files, ["uncommitted.txt"])
    XCTAssertEqual(app.recoverySnapshot.composers[sourceKey]?.images, [])
    XCTAssertEqual(app.recoverySnapshot.composers[unrelatedKey], unrelatedDraft)
  }

  @MainActor func testIsolationPreservesLaterEditsToTheSourceThread() throws {
    let app = workspace()
    app.selectJob("a")
    let sourceKey = app.composerKey
    app.draft = "Later edit"
    app.contextFiles = ["later.txt"]
    app.imageAttachments = [["id": "later-image", "name": "later.png"]]
    app.saveDraft()
    let latest = app.composerRecovery
    app.project = ["id": "isolated", "path": NSTemporaryDirectory()]
    app.restoreComposer(conversationID: "")
    app.moveDraftToOpenedWorkspace(
      text: "Original task", files: [], images: [], fromProject: "project",
      fromComposerKey: sourceKey)
    XCTAssertEqual(app.recoverySnapshot.composers[sourceKey], latest)
    XCTAssertEqual(app.draft, "Original task")
  }

  @MainActor func testDroppedImageCannotAttachToAnotherThreadWhileStaging() async throws {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    let image = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".png")
    try Data([0]).write(to: image)
    defer { try? FileManager.default.removeItem(at: image) }
    app.attachDroppedFile(image.path)
    let deadline = ContinuousClock.now.advanced(by: .seconds(2))
    while engine.pendingRequestCount == 0 && ContinuousClock.now < deadline { await Task.yield() }
    app.selectJob("b")
    app.draft = "Keep this thread"
    app.imageAttachments = [["id": "other-image", "name": "other.png"]]
    await reply(engine, id: 1, result: ["id": "late-image", "name": "late.png"])
    while !app.notice.contains("draft changed") && ContinuousClock.now < deadline { await Task.yield() }
    XCTAssertEqual(app.draft, "Keep this thread")
    XCTAssertEqual(app.imageAttachments.map { string($0, "id") }, ["other-image"])
    XCTAssertTrue(app.notice.contains("draft changed"))
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

  @MainActor private func completeProjectOpen(_ app: Workspace, engine: Engine,
    projectID: String, path: String, startup: Bool = false) async throws {
    let opening = Task {
      if startup { try await app.openStartupProject(arguments: ["SuperQode", "--project", path]) }
      else { try await app.open(path) }
    }
    await reply(engine, id: 1, result: ["id": projectID, "path": path])
    await reply(engine, id: 2, result: [["id": projectID, "path": path]])
    await reply(engine, id: 3, result: [])
    await reply(engine, id: 4, result: ["items": []])
    await reply(engine, id: 5, result: [])
    await reply(engine, id: 6, result: [])
    await reply(engine, id: 7, result: [:])
    try await opening.value
  }

  @MainActor func testOpeningCurrentProjectFromWelcomeEntersWorkspaceAndKeepsDraft() async throws {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.section = "Files"
    app.selectedFile = "pending.swift"
    app.draft = "Unsent work"
    app.showWelcome = true
    XCTAssertTrue(try XCTUnwrap(app.recoverySnapshot.projectDestinations["project"]).showWelcome)
    try await completeProjectOpen(app, engine: engine, projectID: "project", path: "/tmp/project")
    XCTAssertFalse(app.showWelcome)
    XCTAssertFalse(app.openingProject)
    XCTAssertEqual(app.section, "Files")
    XCTAssertEqual(app.selectedFile, "pending.swift")
    XCTAssertEqual(app.draft, "Unsent work")
    XCTAssertFalse(try XCTUnwrap(app.recoverySnapshot.lastDestination).showWelcome)
  }

  @MainActor func testOpeningRecentProjectIgnoresItsSavedWelcomeDestination() async throws {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.draft = "Keep previous project"
    app.showWelcome = true
    app.recoverySnapshot.projectDestinations["next"] = WorkspaceDestination(
      projectID: "next", projectPath: "/tmp/next", section: "Review", showWelcome: true)
    let key = WorkspaceRecoverySnapshot.key(project: "next", conversation: "")
    app.recoverySnapshot.composers[key] = ComposerRecovery(text: "Restore recent project")
    try await completeProjectOpen(app, engine: engine, projectID: "next", path: "/tmp/next")
    XCTAssertEqual(app.projectID, "next")
    XCTAssertFalse(app.showWelcome)
    XCTAssertEqual(app.section, "Review")
    XCTAssertEqual(app.draft, "Restore recent project")
    let previousKey = WorkspaceRecoverySnapshot.key(project: "project", conversation: "")
    XCTAssertEqual(app.recoverySnapshot.composers[previousKey]?.text, "Keep previous project")
  }

  @MainActor func testOpeningFirstProjectFromWelcomeEntersWorkspace() async throws {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.project = [:]
    app.recoverySnapshot = WorkspaceRecoverySnapshot()
    app.showWelcome = true
    try await completeProjectOpen(app, engine: engine, projectID: "first", path: "/tmp/first", startup: true)
    XCTAssertEqual(app.projectID, "first")
    XCTAssertFalse(app.showWelcome)
    XCTAssertFalse(app.openingProject)
    XCTAssertEqual(app.section, "Workspace")
  }

  @MainActor func testStartupKeepsWelcomeEvenWithRecoveredEditorAndRecentProjects() async throws {
    let pipe = Pipe()
    let engine = Engine(requestTimeout: .seconds(2), input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = workspace(engine: engine)
    app.project = [:]; app.showWelcome = true
    let previous = WorkspaceDestination(projectID: "previous", projectPath: "/tmp/previous", section: "Files", filePath: "main.py")
    app.recoverySnapshot.lastDestination = previous
    app.projects = [["id": "previous", "path": "/tmp/previous"]]
    let key = WorkspaceRecoverySnapshot.key(project: "previous", conversation: "")
    app.recoverySnapshot.composers[key] = ComposerRecovery(text: "Keep my draft")
    try await app.openStartupProject(arguments: ["SuperQode"])
    try await app.openStartupProject(arguments: ["SuperQode", "-psn_0_123"])
    XCTAssertTrue(app.showWelcome)
    XCTAssertTrue(app.projectID.isEmpty)
    XCTAssertEqual(engine.pendingRequestCount, 0)
    XCTAssertEqual(app.recoverySnapshot.lastDestination, previous)
    XCTAssertEqual(app.recoverySnapshot.composers[key]?.text, "Keep my draft")
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
