import XCTest
@testable import SuperQode

final class FactoryModelSetupTests: XCTestCase {
  @MainActor func testFirstRunChecklistCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("first")
    let pending = Task { await studio.inspectGettingStarted(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.enter("second")
    engine.receive(["id": 1, "result": ["verified_trial": true]])
    await pending.value
    XCTAssertTrue(studio.gettingStarted.isEmpty)
    XCTAssertFalse(studio.setupChecking)
  }

  @MainActor func testDraftEditsRejectStaleFirstRunChecklist() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project")
    let pending = Task { await studio.inspectGettingStarted(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.text = "Changed definition"
    engine.receive(["id": 1, "result": ["verified_trial": true]])
    await pending.value
    XCTAssertTrue(studio.gettingStarted.isEmpty)
    XCTAssertFalse(studio.setupChecking)
  }

  @MainActor func testModelChangeRejectsStaleFirstRunChecklist() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project")
    let pending = Task { await studio.inspectGettingStarted(engine: engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.modelSetup.draftingReference = "ollama/changed"
    engine.receive(["id": 1, "result": ["models": ["drafting": ["eligible": true]]]])
    await pending.value
    XCTAssertTrue(studio.gettingStarted.isEmpty)
    XCTAssertFalse(studio.setupChecking)
  }

  @MainActor func testHistoricalDatasetCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryTrialSuiteLibrary(); library.enter("first")
    let pending = Task { await library.history(engine, action: "draft") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 1, "result": ["yaml": "foreign tasks", "digest": "old"]])
    await pending.value
    XCTAssertTrue(library.historyProposal.isEmpty)
    XCTAssertFalse(library.busy)
  }

  @MainActor func testChangingDatasetSplitInvalidatesPendingProposal() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryTrialSuiteLibrary(); library.enter("project")
    let pending = Task { await library.history(engine, action: "draft") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.historySplits = ["changed": "held-out"]
    engine.receive(["id": 1, "result": ["yaml": "old tasks", "digest": "old"]])
    await pending.value
    XCTAssertTrue(library.historyProposal.isEmpty)
    XCTAssertFalse(library.busy)
  }
  @MainActor func testDraftingSelectionIsExplicitAndScopedToProject() {
    let library = FactoryModelSetupLibrary()
    library.enter("first")
    XCTAssertTrue(library.draftingReference.isEmpty)
    library.useConnected(provider: "huggingface", model: "team/coder", harness: "core")
    XCTAssertEqual(library.provider, "huggingface")
    XCTAssertEqual(library.model, "team/coder")
    library.enter("second")
    XCTAssertTrue(library.draftingReference.isEmpty)
    library.enter("first")
    XCTAssertEqual(library.draftingReference, "huggingface/team/coder")
    XCTAssertEqual(library.draftingHarness, "core")
  }

  @MainActor func testAgentConnectionCannotReplaceDirectDraftingModel() {
    let library = FactoryModelSetupLibrary()
    library.useConnected(provider: "ollama", model: "coder", harness: "core")
    library.useConnected(provider: "acp", model: "agent", harness: "external")
    XCTAssertEqual(library.draftingReference, "ollama/coder")
  }

  @MainActor func testCheckCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryModelSetupLibrary(); library.enter("first")
    let pending = Task { await library.inspect(engine: engine, yaml: "draft", checkConnections: true) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 1, "result": ["drafting": ["state": "model-discovered"]]])
    await pending.value
    XCTAssertTrue(library.report.isEmpty)
    XCTAssertFalse(library.checking)
  }

  @MainActor func testChangingModelRejectsOlderConnectionResult() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryModelSetupLibrary(); library.enter("project")
    library.useConnected(provider: "ollama", model: "first", harness: "core")
    let pending = Task { await library.inspect(engine: engine, yaml: "draft") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.useConnected(provider: "openai", model: "second", harness: "core")
    engine.receive(["id": 1, "result": ["drafting": ["eligible": true]]])
    await pending.value
    XCTAssertTrue(library.report.isEmpty)
    XCTAssertFalse(library.checking)
  }

  @MainActor func testDraftEditsInvalidatePendingConnectionEvidence() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let studio = FactoryStudioLibrary(); studio.enter("project")
    let pending = Task { await studio.modelSetup.inspect(engine: engine, yaml: studio.text) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    studio.text = "Changed policy"
    engine.receive(["id": 1, "result": ["drafting": ["eligible": true]]])
    await pending.value
    XCTAssertTrue(studio.modelSetup.report.isEmpty)
  }

  @MainActor func testPrivacyFailureBlocksDraftingAndStarterSelectionClearsIt() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryModelSetupLibrary(); library.enter("project")
    library.useConnected(provider: "openai", model: "frontier", harness: "core")
    let pending = Task { await library.inspect(engine: engine, yaml: "draft") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["drafting": ["eligible": false, "state": "privacy-blocked"]]])
    await pending.value
    XCTAssertTrue(library.draftingBlocked)
    library.draftingReference = ""
    XCTAssertFalse(library.draftingBlocked)
    XCTAssertTrue(library.report.isEmpty)
  }
}
