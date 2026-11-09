import XCTest
@testable import SuperQode

final class LocalModelTests: XCTestCase {
  @MainActor func testLocalAINoticeAndResponsibilityGuidance() {
    XCTAssertEqual(LocalAINotice.copy, "Local AI runs on your Mac. No subscription needed. Pick a model that fits your Mac and use it responsibly.")
    XCTAssertTrue(LocalAILearnMoreView.points.contains { $0.0 == "Your responsibility" })
    XCTAssertTrue(LocalAILearnMoreView.points.contains { $0.0 == "Privacy" && $0.1.contains("network") })
    XCTAssertTrue(LocalAILearnMoreView.points.contains { $0.0 == "When you are done" && $0.1.contains("Unload") })
  }

  @MainActor func testHubCredentialDoesNotChangeTheCodingRoute() async throws {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), engine: engine)
    app.provider = "ollama"; app.model = "my-local-model"; app.harness = "core"
    let save = Task { try await app.storeProviderCredential("huggingface", key: "hf_fixture_session_only", remember: false) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["ok": true]])
    await Task.yield()
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 2, "result": [["id": "huggingface", "credential_configured": true]]])
    try await save.value
    XCTAssertEqual(app.provider, "ollama")
    XCTAssertEqual(app.model, "my-local-model")
    XCTAssertEqual(app.harness, "core")
    XCTAssertFalse(app.savedCredentialProviders.contains("huggingface"))
  }

  @MainActor func testRejectedHubCredentialPreservesTheCodingRoute() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), engine: engine)
    app.provider = "ollama"; app.model = "my-local-model"
    let save = Task { try await app.storeProviderCredential("huggingface", key: "bad", remember: false) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "error": ["message": "Rejected token"]])
    do { try await save.value; XCTFail("Rejected credential must fail") } catch {}
    XCTAssertEqual(app.provider, "ollama")
    XCTAssertEqual(app.model, "my-local-model")
    XCTAssertEqual(engine.pendingRequestCount, 0)
  }

  @MainActor func testSearchIgnoresLateResultsFromPreviousSource() async {
    let pipe = Pipe()
    let engine = Engine(input: pipe.fileHandleForWriting)
    defer { engine.stop() }
    let library = LocalModelLibrary()
    let first = Task { await library.search(engine: engine, query: "old", source: "recommended", format: "gguf") }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    let second = Task { await library.search(engine: engine, query: "new", source: "hf", format: "mlx") }
    while engine.pendingRequestCount < 2 { await Task.yield() }
    engine.receive(["id": 2, "result": [["id": "new-model"]]])
    await second.value
    engine.receive(["id": 1, "result": [["id": "stale-model"]]])
    await first.value
    XCTAssertEqual(library.hits.map { string($0, "id") }, ["new-model"])
    XCTAssertFalse(library.searching)
  }

  @MainActor func testLocalAIIsAccessibleWithoutOpeningAProject() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.connected = true
    let command = app.workspaceCommands.first { $0.action == .section("Models") }
    XCTAssertNotNil(command)
    XCTAssertNil(command?.disabledReason)
    XCTAssertEqual(Sections.title(for: "Models"), "Local AI")
    XCTAssertEqual(localBytes(nil), "Unknown")
    XCTAssertEqual(localBytes(NSNull()), "Unknown")
    XCTAssertNotEqual(localBytes(NSNumber(value: 0)), "Unknown")
  }

  @MainActor func testEngineModeCannotBeChangedDuringActiveWork() async {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.busy = true
    do {
      try await app.changeBackgroundEngine(true)
      XCTFail("Changing mode must not stop active operations")
    } catch { XCTAssertTrue(error.localizedDescription.contains("Finish or stop")) }
    XCTAssertEqual(app.engine.pendingRequestCount, 0)
    XCTAssertFalse(app.switchingBackgroundEngine)
  }
}
