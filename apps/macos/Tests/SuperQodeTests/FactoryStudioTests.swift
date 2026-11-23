import XCTest
import Security
import CryptoKit
@testable import SuperQode

final class FactoryStudioTests: XCTestCase {
  @MainActor func testExternalOptimizerImportCannotPublishIntoAnotherProject() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first"); studio.improvementPlan = ["id": "plan"]
    let pending = Task { await studio.importOptimizerCandidate(engine: engine, optimizer: "metaharness", path: ".superqode/external-optimizers/run") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second")
    engine.receive(["id": 1, "result": ["candidate": "foreign", "notice": "imported"]])
    await pending.value
    XCTAssertTrue(studio.improvementCandidate.isEmpty); XCTAssertTrue(studio.improvementPlan.isEmpty); XCTAssertFalse(studio.busy)
  }
  @MainActor func testOperationsRefreshCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryOperationsLibrary(); library.enter("first")
    let pending = Task { await library.refresh(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 1, "result": ["packages": [["id": "foreign"]], "readiness": ["worker_ready": true]]])
    await pending.value
    XCTAssertTrue(library.packages.isEmpty); XCTAssertTrue(library.readiness.isEmpty)
  }
  @MainActor func testOperationsRestoreReceiptCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryOperationsLibrary(); library.enter("first")
    let pending = Task { await library.perform(engine, "restore", ["id": "package"]) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 1, "result": ["restored": true]])
    await pending.value
    XCTAssertTrue(library.result.isEmpty); XCTAssertFalse(library.busy)
  }
  @MainActor func testLateBudgetRefreshCannotReplaceAnotherPlan() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project"); studio.improvementPlan = ["id": "first"]
    let pending = Task { await studio.refreshImprovementBudget(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.improvementPlan = ["id": "second"]
    engine.receive(["id": 1, "result": ["request_count": 99]])
    await pending.value
    XCTAssertEqual(string(studio.improvementPlan, "id"), "second"); XCTAssertNil(studio.improvementPlan["budget"])
  }
  @MainActor func testBudgetRefreshDoesNotCrossProjectBoundary() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first"); studio.improvementPlan = ["id": "plan"]
    let pending = Task { await studio.refreshImprovementBudget(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second")
    engine.receive(["id": 1, "result": ["request_count": 99]])
    await pending.value
    XCTAssertTrue(studio.improvementPlan.isEmpty)
  }
  @MainActor func testWorkflowExportPreservesNewerSuiteDraft() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project"); studio.review = ["snapshot_digest": "snapshot"]
    let pending = Task { await studio.workflowExperiment(engine, stage: "review", goal: "New review goal", workGoal: "Fix task") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.trialSuites.text = "newer suite draft"
    engine.receive(["id": 1, "result": ["suite_yaml": "old export", "suite_path": "old-path"]])
    let accepted = await pending.value
    XCTAssertFalse(accepted); XCTAssertEqual(studio.trialSuites.text, "newer suite draft"); XCTAssertFalse(studio.busy)
  }
  @MainActor func testWorkflowExportCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first")
    let pending = Task { await studio.workflowExperiment(engine, stage: "review", goal: "New review goal", workGoal: "Fix task") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second")
    engine.receive(["id": 1, "result": ["suite_yaml": "foreign export"]])
    let accepted = await pending.value
    XCTAssertFalse(accepted); XCTAssertEqual(studio.project, "second"); XCTAssertTrue(studio.trialSuites.text.isEmpty)
  }
  @MainActor func testFeedbackInspectionPreservesNewerReviewAndRejectsForeignProject() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryFeedbackLibrary(); library.enter("first"); library.selected = "issue"
    let pending = Task { await library.inspect(engine, restoreReview: true) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.notes = "newer review"; library.category = "unknown"
    engine.receive(["id": 1, "result": ["suggested_category": "model_protocol", "reviews": [["notes": "old review"]]]])
    await pending.value
    XCTAssertEqual(library.notes, "newer review"); XCTAssertEqual(library.category, "unknown")
    let foreign = Task { await library.inspect(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 2, "result": ["record": ["reason": "foreign source"]]])
    await foreign.value
    XCTAssertTrue(library.detail.isEmpty); XCTAssertTrue(library.notes.isEmpty)
  }
  @MainActor func testFeedbackProposalDoesNotReplaceNewerSuiteDraft() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let suites = FactoryTrialSuiteLibrary(); suites.enter("project")
    let library = suites.feedback; library.selected = "issue"; library.proposalID = "proposal"
    let pending = Task { await library.loadDraft(engine, into: suites) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    suites.text = "newer suite draft"
    engine.receive(["id": 1, "result": ["suite_yaml": "stale suite", "suite_path": "old-path"]])
    let loaded = await pending.value
    XCTAssertFalse(loaded); XCTAssertEqual(suites.text, "newer suite draft")
    XCTAssertTrue(suites.sourceDigest.isEmpty)
  }
  @MainActor func testSuiteSourceLoadPreservesNewerEdits() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let suites = FactoryTrialSuiteLibrary(); suites.enter("project")
    let pending = Task { await suites.loadSource(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    suites.text = "new draft"
    engine.receive(["id": 1, "result": ["yaml": "stale source", "expected_file_digest": "old"]])
    await pending.value
    XCTAssertEqual(suites.text, "new draft"); XCTAssertTrue(suites.sourceDigest.isEmpty)
  }
  @MainActor func testSuiteEntryResponseCannotCrossProjectBoundary() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first")
    let suites = studio.trialSuites; suites.selected = "suite"; suites.entry = "case--baseline"
    let pending = Task { await suites.inspectEntry(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second")
    engine.receive(["id": 1, "result": ["patch": "foreign source"]])
    await pending.value
    XCTAssertEqual(suites.project, "second"); XCTAssertTrue(suites.detail.isEmpty)
  }
  @MainActor func testSuiteJobFailureSurvivesScorecardRefresh() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let suites = FactoryTrialSuiteLibrary(); suites.enter("project"); suites.selected = "suite"
    let pending = Task { await suites.run(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["id": "job"]])
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 2, "result": ["id": "job", "status": "failed", "result": ["error": "worker stopped"]]])
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 3, "result": ["verdict": "hold"]])
    await pending.value
    XCTAssertTrue(suites.failure.contains("failed")); XCTAssertEqual(string(suites.board, "verdict"), "hold"); XCTAssertFalse(suites.busy)
  }
  @MainActor func testLateSkillCreationDoesNotReplaceEditedDraft() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project"); studio.text = "draft"
    let pending = Task { await studio.createBoundSkill(engine: engine, binding: "coder", id: "review", markdown: "instructions") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.text = "newer draft"
    engine.receive(["id": 1, "result": ["yaml": "bound draft"]])
    let accepted = await pending.value
    XCTAssertFalse(accepted); XCTAssertEqual(studio.text, "newer draft"); XCTAssertFalse(studio.busy)
  }
  @MainActor func testLateSkillCreationDoesNotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first"); studio.text = "draft"
    let pending = Task { await studio.createBoundSkill(engine: engine, binding: "coder", id: "review", markdown: "instructions") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second"); studio.text = "second draft"
    engine.receive(["id": 1, "result": ["yaml": "bound first draft"]])
    let accepted = await pending.value
    XCTAssertFalse(accepted); XCTAssertEqual(studio.text, "second draft"); XCTAssertTrue(studio.failure.isEmpty)
  }
  @MainActor func testLateValidationDoesNotReplaceEditedDraft() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project"); studio.text = "draft"
    let pending = Task { await studio.validate(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.text = "new draft"
    engine.receive(["id": 1, "result": ["yaml": "draft", "review": "stale"]])
    await pending.value
    XCTAssertEqual(studio.text, "new draft"); XCTAssertTrue(studio.review.isEmpty)
  }
  @MainActor func testProjectSwitchPreservesDraftsAndRejectsLateLoad() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first"); studio.text = "first draft"
    let loading = Task { await studio.load(engine: engine, template: "fix-and-verify") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second"); studio.text = "second draft"
    engine.receive(["id": 1, "result": ["yaml": "old response"]])
    await loading.value
    XCTAssertEqual(studio.text, "second draft")
    studio.enter("first"); XCTAssertEqual(studio.text, "first draft")
  }
  @MainActor func testLateRunInspectionDoesNotReplaceAnotherSelection() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project"); studio.run = "first"
    let loading = Task { await studio.inspect(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.run = "second"
    engine.receive(["id": 1, "result": ["candidate_id": "old candidate"]])
    await loading.value
    XCTAssertTrue(studio.detail.isEmpty)
  }
  @MainActor func testFactoryNavigationRequiresAProject() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil)); app.connected = true
    XCTAssertEqual(Sections.names.count, Sections.icons.count)
    XCTAssertNotNil(app.workspaceCommands.first { $0.action == .section("Factory Studio") }?.disabledReason)
    app.project = ["id": "project"]
    XCTAssertNil(app.workspaceCommands.first { $0.action == .section("Factory Studio") }?.disabledReason)
    var state = WorkbenchNavigationState(); state.select("Factory Studio")
    XCTAssertTrue(state.factoryMounted)
    XCTAssertFalse(WorkspaceNavigationGroup.usesCodingWorkspace("Factory Studio"))
  }
  @MainActor func testChoosingAHarnessFromFactoryStudioReturnsThere() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.section = "Factory Studio"
    app.selectedJob = "existing-thread"
    app.draft = "Keep this unsent conversation"
    app.openConnections(returningTo: "Factory Studio")
    XCTAssertTrue(app.showConnection)
    XCTAssertEqual(app.connectionStartPage, "menu:root")
    XCTAssertFalse(app.connectionSwitchesHarness)
    XCTAssertEqual(app.connectionReturnSection, "Factory Studio")
    app.chooseConnection(["id": "core", "name": "Core"])
    XCTAssertEqual(app.section, "Factory Studio")
    XCTAssertEqual(app.harness, "core")
    XCTAssertEqual(app.selectedJob, "existing-thread")
    XCTAssertEqual(app.draft, "Keep this unsent conversation")
    XCTAssertTrue(app.connectionReturnSection.isEmpty)
    app.connectionReturnSection = "Factory Studio"
    app.harnesses += [
      ["id": "apple-local", "name": "Apple on-device", "runtime": "builtin"],
    ]
    app.chooseAppleModel(development: true)
    XCTAssertEqual(app.section, "Factory Studio")
    XCTAssertEqual(app.provider, "apple-foundation")
    XCTAssertEqual(app.model, "system-on-device")
    XCTAssertEqual(app.selectedJob, "existing-thread")
    app.chooseConnection(["id": "core", "name": "Core"])
    XCTAssertEqual(app.section, "Workspace")
  }
  @MainActor func testSourceReviewRejectsPreviousProjectResponse() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first")
    let pending = Task { await studio.refreshSources(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second")
    engine.receive(["id": 1, "result": ["review": "stale", "digest": "old"]])
    await pending.value
    XCTAssertTrue(studio.sourceReview.isEmpty)
    XCTAssertTrue(studio.failure.isEmpty)
  }
  @MainActor func testLatestSourceRefreshWins() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project")
    let first = Task { await studio.refreshSources(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    let second = Task { await studio.refreshSources(engine: engine) }
    while engine.pendingRequestCount < 2 { await Task.yield() }
    engine.receive(["id": 2, "result": ["review": "latest"]])
    await second.value
    engine.receive(["id": 1, "result": ["review": "old"]])
    await first.value
    XCTAssertEqual(string(studio.sourceReview, "review"), "latest")
  }
  @MainActor func testCancelledSourceRefreshDoesNotPublishAnError() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project")
    let pending = Task { await studio.refreshSources(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    pending.cancel(); engine.receive(["id": 1, "result": ["review": "cancelled"]])
    await pending.value
    XCTAssertTrue(studio.sourceReview.isEmpty); XCTAssertTrue(studio.failure.isEmpty)
  }
  @MainActor func testSourceCommitUsesReviewedSavedSourcesAndExistingJobLifecycle() async throws {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project"); studio.text = "unsaved draft"
    studio.sourceReview = ["review": "saved-review", "digest": "saved-digest"]
    let operation = Task { await studio.commitSources(engine: engine, paths: [".superqode/factory.yaml"], message: "Version saved Factory") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    let request = try XCTUnwrap(JSONSerialization.jsonObject(with: pipe.fileHandleForReading.availableData) as? [String: Any])
    let params = try XCTUnwrap(request["params"] as? [String: Any])
    XCTAssertEqual(string(params, "source_review"), "saved-review")
    XCTAssertEqual(string(params, "source_digest"), "saved-digest")
    XCTAssertEqual(string(params, "factory_action"), "source-commit")
    XCTAssertNil(params["yaml"])
    engine.receive(["id": 1, "result": ["id": "job"]])
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 2, "result": ["id": "job", "status": "completed", "result": ["sha": "abc123"]]])
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 3, "result": ["review": "fresh-sources"]])
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 4, "result": ["revisions": [], "runs": []]])
    await operation.value
    XCTAssertEqual(studio.text, "unsaved draft")
    XCTAssertFalse(studio.busy)
    XCTAssertTrue(studio.message.contains("abc123"))
    XCTAssertEqual(string(studio.sourceReview, "review"), "fresh-sources")
  }
  @MainActor func testLateImprovementPlanDoesNotCrossProjectBoundary() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first")
    let pending = Task { await studio.openImprovement(engine: engine, id: "old-plan") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second")
    engine.receive(["id": 1, "result": ["id": "old-plan", "baseline_yaml": "old"]])
    await pending.value
    XCTAssertTrue(studio.improvementPlan.isEmpty); XCTAssertTrue(studio.improvementCandidate.isEmpty)
  }
  @MainActor func testChangingImprovementCandidateClearsPreviousAuthority() {
    let studio = FactoryStudioLibrary(); studio.enter("project")
    studio.improvementCandidate = "before"
    studio.improvementResult = ["eligible": true]; studio.improvementComparisonJob = "old-job"
    studio.improvementCandidate = "after"
    XCTAssertTrue(studio.improvementResult.isEmpty); XCTAssertTrue(studio.improvementComparisonJob.isEmpty)
  }
  @MainActor func testImprovementAdoptionPreservesEditsMadeDuringRequest() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project"); studio.text = "original draft"
    studio.improvementPlan = ["id": "plan"]; studio.improvementCandidate = "candidate"; studio.improvementComparisonJob = "comparison"
    let pending = Task { await studio.adoptImprovement(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.text = "later user edit"
    engine.receive(["id": 1, "result": ["yaml": "stale proposed factory"]])
    let adopted = await pending.value
    XCTAssertFalse(adopted)
    XCTAssertEqual(studio.text, "later user edit"); XCTAssertFalse(studio.busy)
  }
  @MainActor func testOpeningExperimentRestoresItsRecordedComparison() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project")
    let pending = Task { await studio.openImprovement(engine: engine, id: "plan") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["id": "plan", "baseline_yaml": "baseline", "comparison_job": "job",
      "comparison": ["candidate": "candidate", "eligible": true]]])
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 2, "result": ["diff": "reviewed diff"]])
    await pending.value
    XCTAssertEqual(studio.improvementCandidate, "candidate"); XCTAssertEqual(studio.improvementComparisonJob, "job")
    XCTAssertTrue(studio.improvementResult["eligible"] as? Bool == true)
  }
  func testReleaseSignatureUsesP256MessageSHA256AndRejectsChangedMessage() throws {
    // Ephemeral software key: this test never enrolls or accesses the Keychain.
    var error: Unmanaged<CFError>?
    let ephemeral = P256.Signing.PrivateKey()
    let key = try XCTUnwrap(SecKeyCreateWithData(ephemeral.x963Representation as CFData,
      [kSecAttrKeyType as String: kSecAttrKeyTypeECSECPrimeRandom,
       kSecAttrKeyClass as String: kSecAttrKeyClassPrivate, kSecAttrKeySizeInBits as String: 256] as CFDictionary, &error))
    let publicKey = try XCTUnwrap(SecKeyCopyPublicKey(key))
    let message = Data("exact candidate challenge".utf8)
    let signature = try FactoryReleaseSigner.signature(message: message, key: key)
    XCTAssertTrue(SecKeyVerifySignature(publicKey, .ecdsaSignatureMessageX962SHA256,
      message as CFData, signature as CFData, &error))
    XCTAssertFalse(SecKeyVerifySignature(publicKey, .ecdsaSignatureMessageX962SHA256,
      Data("changed candidate".utf8) as CFData, signature as CFData, &error))
    XCTAssertEqual((SecKeyCopyExternalRepresentation(publicKey, &error) as Data?)?.count, 65)
  }
}
