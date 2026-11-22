import XCTest
@testable import SuperQode

final class FactoryAcceptanceTests: XCTestCase {
  @MainActor func testTraceResponseCannotCrossRunOrProject() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryAcceptanceLibrary(); library.enter("first"); library.selectRun("run-a")
    let first = Task { await library.refreshTrace(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.selectRun("run-b")
    engine.receive(["id": 1, "result": ["run": "run-a", "covered": 1]])
    await first.value; XCTAssertTrue(library.trace.isEmpty)
    let second = Task { await library.refreshTrace(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 2, "result": ["run": "run-b", "covered": 1]])
    await second.value; XCTAssertTrue(library.trace.isEmpty); XCTAssertTrue(library.run.isEmpty)
  }
  @MainActor func testLatestReceiptReadWinsAndCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryAcceptanceLibrary(); library.enter("first")
    let first = Task { await library.refreshReceipts(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    let second = Task { await library.refreshReceipts(engine) }
    while engine.pendingRequestCount < 2 { await Task.yield() }
    engine.receive(["id": 2, "result": ["decisions": [["reason": "new"]]]]); await second.value
    engine.receive(["id": 1, "result": ["decisions": [["reason": "old"]]]]); await first.value
    XCTAssertEqual(string(library.receipts.first ?? [:], "reason"), "new")
    let third = Task { await library.refreshReceipts(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 3, "result": ["decisions": [["reason": "foreign"]]]]); await third.value
    XCTAssertTrue(library.receipts.isEmpty)
  }
  @MainActor func testVerifierDraftRejectsResponseAfterInputsChange() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryAcceptanceLibrary(); library.enter("project"); library.sourceChanged("saved definition")
    let pending = Task { await library.draft(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.checksText = "{\"newer\": {}}"
    engine.receive(["id": 1, "result": ["digest": "stale", "yaml": "stale definition"]])
    await pending.value
    XCTAssertTrue(library.proposal.isEmpty); XCTAssertEqual(library.checksText, "{\"newer\": {}}")
    XCTAssertTrue(library.message.contains("Inputs changed")); XCTAssertFalse(library.busy)
  }
  @MainActor func testVerifierSavePreservesSourceEditedDuringRequest() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryAcceptanceLibrary(); library.enter("project"); library.sourceChanged("saved")
    let draft = Task { await library.draft(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["digest": "reviewed", "yaml": "proposal"]]); await draft.value
    let saving = Task { await library.install(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.sourceChanged("newer draft")
    engine.receive(["id": 2, "result": ["saved": true]])
    let reloadAllowed = await saving.value
    XCTAssertFalse(reloadAllowed); XCTAssertTrue(library.proposal.isEmpty)
    XCTAssertTrue(library.message.contains("Newer draft edits are preserved"))
  }
  @MainActor func testGenerationDisplaysUnsupportedCapabilityWithoutAnInstallableProposal() async throws {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryAcceptanceLibrary(); library.enter("project"); library.sourceChanged("saved"); library.description = "Database health"
    let pending = Task { await library.generate(engine, provider: "ollama", model: "local") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    let frame = try XCTUnwrap(JSONSerialization.jsonObject(with: pipe.fileHandleForReading.availableData) as? [String: Any])
    let params = try XCTUnwrap(frame["params"] as? [String: Any])
    XCTAssertEqual(string(params, "factory_action"), "verifier-generate")
    XCTAssertEqual(string(params, "yaml"), "saved"); XCTAssertTrue(params["confirmed"] as? Bool == true)
    engine.receive(["id": 1, "result": ["id": "draft-job"]])
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 2, "result": ["status": "completed", "result": ["proposal": NSNull(), "missing_capabilities": ["External service access unavailable"]]]])
    await pending.value
    XCTAssertTrue(library.proposal.isEmpty)
    XCTAssertEqual(library.generationResult["missing_capabilities"] as? [String], ["External service access unavailable"])
    XCTAssertEqual(engine.pendingRequestCount, 0); XCTAssertFalse(library.busy)
  }
  @MainActor func testOutcomeReadCannotCrossProjectsAndObservationDraftsSurviveRunSelection() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryAcceptanceLibrary(); library.enter("first"); library.selectRun("run")
    library.observation = "pilot-1"; library.outcome = "met"; library.humanMinutes = "12.5"
    library.selectRun("other"); library.selectRun("run")
    XCTAssertEqual(library.observation, "pilot-1"); XCTAssertEqual(library.humanMinutes, "12.5")
    let pending = Task { await library.refreshOutcomes(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 1, "result": ["revisions": [["cost_usd": 0]]]])
    await pending.value; XCTAssertTrue(library.outcomes.isEmpty); XCTAssertTrue(library.observation.isEmpty)
  }
  @MainActor func testInvalidHumanEffortDoesNotSendAnObservation() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryAcceptanceLibrary(); library.enter("project"); library.selectRun("run")
    library.observation = "pilot"; library.humanMinutes = "nan"
    await library.recordOutcome(engine)
    XCTAssertEqual(engine.pendingRequestCount, 0); XCTAssertTrue(library.failure.contains("finite"))
  }
  @MainActor func testUnknownMeasurementsAreDistinctFromZero() {
    XCTAssertEqual(FactoryAcceptanceLibrary.measurement(nil), "Unknown")
    XCTAssertEqual(FactoryAcceptanceLibrary.measurement(NSNull()), "Unknown")
    XCTAssertEqual(FactoryAcceptanceLibrary.measurement(Double.nan), "Unknown")
    XCTAssertEqual(FactoryAcceptanceLibrary.measurement(0, decimals: 2), "0.00")
    XCTAssertEqual(FactoryAcceptanceLibrary.measurement(12.5, decimals: 1), "12.5")
  }
  @MainActor func testParentDraftChangesInvalidateVerifierProposalAndKeepDescriptionAcrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first"); studio.text = "same draft"
    studio.acceptance.description = "Keep this input"
    let pending = Task { await studio.acceptance.draft(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.text = "new draft"
    engine.receive(["id": 1, "result": ["digest": "old"]]); await pending.value
    XCTAssertTrue(studio.acceptance.proposal.isEmpty)
    studio.enter("second"); studio.text = "new draft"; studio.enter("first")
    XCTAssertEqual(studio.acceptance.description, "Keep this input")
    XCTAssertEqual(studio.text, "new draft")
  }
}
