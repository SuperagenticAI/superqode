import Foundation
import XCTest
@testable import SuperQodeCompanion

private actor MemoryVault: DeviceCredentialVault {
  var credential: DeviceCredential?
  private(set) var reads = 0
  private(set) var removals = 0
  init(_ credential: DeviceCredential? = nil) { self.credential = credential }
  func load() -> DeviceCredential? { reads += 1; return credential }
  func save(_ value: DeviceCredential) { credential = value }
  func remove() { removals += 1; credential = nil }
}

private actor WorkflowTransport: CompanionTransport {
  var revoked = false
  var blockProjects = false
  var projectEntered = false
  var entryWaiters: [CheckedContinuation<Void, Never>] = []
  var projectRelease: CheckedContinuation<Void, Never>?
  private(set) var pairCalls = 0
  func setRevoked() { revoked = true }
  func holdProjects() { blockProjects = true }
  func waitForProject() async {
    if projectEntered { return }
    await withCheckedContinuation { entryWaiters.append($0) }
  }
  func releaseProjects() { projectRelease?.resume(); projectRelease = nil }
  func post(_ path: String, _ payload: [String: JSONValue], key: String?) -> JSONValue {
    if path == "v1/pair" {
      pairCalls += 1
      return .object(["id": .string("fixture"), "claim": .string("fixture-claim"), "expires": .number(Date().addingTimeInterval(60).timeIntervalSince1970)])
    }
    return .object(["state": .string("denied")])
  }
  func rpc(_ method: String, _ params: [String: JSONValue], key: String?) async throws -> JSONValue {
    if revoked { throw CompanionError("Device authorization expired or was revoked", status: 403) }
    if method == "projects.list", blockProjects {
      projectEntered = true
      entryWaiters.forEach { $0.resume() }; entryWaiters = []
      await withCheckedContinuation { projectRelease = $0 }
    }
    return try await ExploreTransport().rpc(method, params, key: key)
  }
}

final class CompanionWorkflowTests: XCTestCase {
  private var credential: DeviceCredential {
    DeviceCredential(address: ExploreWorkspace.address, token: "fixture-only", device: "fixture-device")
  }
  @MainActor func testDisconnectedRequestsCannotRepopulateAnOldSession() async {
    let vault = MemoryVault(credential)
    let api = WorkflowTransport()
    await api.holdProjects()
    let store = CompanionStore(vault: vault, makeTransport: { _, _ in api })
    let pending = Task { await store.restore() }
    await api.waitForProject()
    await store.disconnect()
    await api.releaseProjects()
    await pending.value
    XCTAssertFalse(store.paired)
    XCTAssertTrue(store.projects.isEmpty)
    XCTAssertTrue(store.jobs.isEmpty)
    XCTAssertEqual(store.phase, .unpaired)
  }
  @MainActor func testRevokedDeviceDisablesActionsWithoutDiscardingAuthorizationSilently() async {
    let vault = MemoryVault(credential)
    let api = WorkflowTransport()
    await api.setRevoked()
    let store = CompanionStore(vault: vault, makeTransport: { _, _ in api })
    await store.restore()
    XCTAssertEqual(store.phase, .authorizationExpired)
    XCTAssertFalse(store.canMutate)
    let removals = await vault.removals
    XCTAssertEqual(removals, 0)
  }
  @MainActor func testPairingDoubleTapCreatesOneRequest() async throws {
    let api = WorkflowTransport()
    let store = CompanionStore(vault: MemoryVault(), makeTransport: { _, _ in api })
    store.address = ExploreWorkspace.address
    store.pairingCode = "fixture-code"
    store.beginPairing()
    store.beginPairing()
    for _ in 0..<100 {
      if !store.connecting { break }
      try await Task.sleep(for: .milliseconds(5))
    }
    let calls = await api.pairCalls
    XCTAssertEqual(calls, 1)
    XCTAssertFalse(store.paired)
  }
  @MainActor func testExploreModeNeverReadsOrDeletesRealCredentials() async {
    let vault = MemoryVault(credential)
    let store = CompanionStore(vault: vault)
    store.enterExploreMode()
    await store.restore()
    XCTAssertTrue(store.isPreview)
    XCTAssertFalse(store.canMutate)
    XCTAssertEqual(store.profiles.first?.text("model"), "qwen3-coder:30b")
    await store.disconnect()
    let reads = await vault.reads
    let removals = await vault.removals
    XCTAssertEqual(reads, 0)
    XCTAssertEqual(removals, 0)
    XCTAssertFalse(store.paired)
  }
  func testExploreTransportCannotExecuteActions() async {
    for method in ["tasks.start", "jobs.approve", "threads.update", "remote.start", "optimizations.start"] {
      do { _ = try await ExploreTransport().rpc(method, [:], key: "fixture"); XCTFail("Explore mode accepted a write") }
      catch { XCTAssertTrue(error.localizedDescription.contains("read-only")) }
    }
  }
  func testDraftSurvivesRelaunchWithOriginalRequestIdentityAndBackupExclusion() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    defer { try? FileManager.default.removeItem(at: directory) }
    let repository = DraftRepository(directory: directory)
    var draft = LocalDraft(project: "project")
    XCTAssertEqual(draft.profile, "")
    XCTAssertEqual(draft.prompt, "")
    draft.origin = ExploreWorkspace.address
    draft.prompt = "Resume safely"
    draft.attempt = SubmissionAttempt(key: "original-request", params: ["prompt": .string(draft.prompt)])
    try await repository.save(draft)
    let restored = try await DraftRepository(directory: directory).list()
    XCTAssertEqual(restored.first?.attempt?.key, "original-request")
    XCTAssertEqual(restored.first?.attempt?.params["prompt"], .string("Resume safely"))
    let file = directory.appendingPathComponent("drafts.json")
    XCTAssertEqual(try file.resourceValues(forKeys: [.isExcludedFromBackupKey]).isExcludedFromBackup, true)
    try await repository.remove(draft.id)
    let remaining = try await repository.list()
    XCTAssertTrue(remaining.isEmpty)
  }
  func testMalformedDraftStorageIsNotOverwritten() async throws {
    let directory = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: directory) }
    let file = directory.appendingPathComponent("drafts.json")
    let original = Data("broken-storage".utf8)
    try original.write(to: file)
    var draft = LocalDraft(project: "project"); draft.prompt = "Preserve my earlier text"
    do { try await DraftRepository(directory: directory).save(draft); XCTFail("Corrupt storage was overwritten") }
    catch { XCTAssertEqual(try Data(contentsOf: file), original) }
  }
  func testNativeMarkupPreservesCodeListsAndTables() {
    let source = "## Result\n\n```swift\nlet value = 1\n```\n\n- Safe by default\n\n| Check | Result |\n| --- | --- |\n| Queue | Passed |"
    let blocks = responseBlocks(source)
    XCTAssertTrue(blocks.contains(.code("swift", "let value = 1")))
    XCTAssertTrue(blocks.contains(.heading(2, "Result")))
    XCTAssertTrue(blocks.contains(.item("•", "Safe by default")))
    XCTAssertTrue(blocks.contains(.table([["Check", "Result"], ["Queue", "Passed"]])))
  }
  func testHighlightingKeepsUnicodeAndDiffRangesValid() {
    let code = "let name = \"模型 🌍\" // Local only"
    let spans = mobileSourceSpans(code)
    XCTAssertTrue(spans.contains { $0.kind == .string && (code as NSString).substring(with: $0.range).contains("模型") })
    XCTAssertTrue(spans.contains { $0.kind == .comment })
    let diff = mobileSourceSpans("--- old\n+++ new\n-old\n+new\n", language: "diff")
    XCTAssertEqual(diff.map(\.kind), [.header, .header, .deletion, .addition])
  }
}
