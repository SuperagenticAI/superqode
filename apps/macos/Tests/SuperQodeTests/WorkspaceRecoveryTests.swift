import Foundation
import XCTest

@testable import SuperQode

final class WorkspaceRecoveryTests: XCTestCase {
  private func directory() throws -> URL {
    let url = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: url, withIntermediateDirectories: true)
    addTeardownBlock { try? FileManager.default.removeItem(at: url) }
    return url
  }

  func testRestartRestoresDistinctComposerAndEditorDrafts() throws {
    let directory = try directory()
    let first = WorkspaceRecoverySnapshot.key(project: "project", conversation: "first")
    let second = WorkspaceRecoverySnapshot.key(project: "project", conversation: "second")
    var snapshot = WorkspaceRecoverySnapshot()
    snapshot.composers[first] = ComposerRecovery(
      text: "First unfinished message", files: ["a.swift"],
      images: [["id": "image-id", "name": "design.png"]])
    snapshot.composers[second] = ComposerRecovery(text: "Second unfinished message")
    snapshot.editors["project\na.swift"] = FileEdit(
      original: "before", digest: "base-digest", text: "after")
    snapshot.lastDestination = WorkspaceDestination(
      projectID: "project", projectPath: "/project",
      conversationID: "first", jobID: "latest-turn", section: "Files", filePath: "a.swift",
      inspectorVisible: true, checkpointID: "checkpoint", checkpointPath: "a.swift")
    snapshot.transcripts[first] = TranscriptPosition(follow: false, anchor: "turn:earlier")
    try WorkspaceRecoveryStore(directory: directory).save(snapshot)

    let restarted = WorkspaceRecoveryStore(directory: directory).load()
    XCTAssertEqual(restarted.composers[first], snapshot.composers[first])
    XCTAssertEqual(restarted.composers[second]?.text, "Second unfinished message")
    XCTAssertEqual(restarted.editors["project\na.swift"]?.digest, "base-digest")
    XCTAssertEqual(restarted.editors["project\na.swift"]?.text, "after")
    XCTAssertEqual(restarted.lastDestination, snapshot.lastDestination)
    XCTAssertEqual(restarted.transcripts[first]?.anchor, "turn:earlier")
    XCTAssertFalse(restarted.transcripts[first]?.follow ?? true)
  }

  func testNewTaskAndProjectsCannotShareDraftKeys() {
    let keys = [
      WorkspaceRecoverySnapshot.key(project: "a", conversation: ""),
      WorkspaceRecoverySnapshot.key(project: "a", conversation: "run"),
      WorkspaceRecoverySnapshot.key(project: "a\nb", conversation: "c"),
      WorkspaceRecoverySnapshot.key(project: "a", conversation: "b\nc"),
      WorkspaceRecoverySnapshot.key(project: "é", conversation: "run"),
    ]
    XCTAssertEqual(Set(keys).count, keys.count)
  }

  func testUnreadableRecoveryIsPreservedAndCannotBeOverwritten() throws {
    let directory = try directory()
    let file = directory.appendingPathComponent("workspace-v1.json")
    let original = Data("{truncated".utf8)
    try original.write(to: file)
    let store = WorkspaceRecoveryStore(directory: directory)
    XCTAssertTrue(store.load().composers.isEmpty)
    XCTAssertFalse(store.loadIssue.isEmpty)
    XCTAssertThrowsError(try store.save(.init()))
    XCTAssertEqual(try Data(contentsOf: file), original)
  }

  func testFutureVersionIsPreserved() throws {
    let directory = try directory()
    let file = directory.appendingPathComponent("workspace-v1.json")
    var future = WorkspaceRecoverySnapshot()
    future.version = 2
    let original = try JSONEncoder().encode(future)
    try original.write(to: file)
    let store = WorkspaceRecoveryStore(directory: directory)
    _ = store.load()
    XCTAssertFalse(store.loadIssue.isEmpty)
    XCTAssertThrowsError(try store.save(.init()))
    XCTAssertEqual(try Data(contentsOf: file), original)
  }

  func testOversizedSaveKeepsPreviousGoodSnapshot() throws {
    let directory = try directory()
    let store = WorkspaceRecoveryStore(directory: directory)
    var snapshot = WorkspaceRecoverySnapshot()
    snapshot.composers["draft"] = ComposerRecovery(text: "safe")
    try store.save(snapshot)
    snapshot.composers["draft"] = ComposerRecovery(
      text: String(repeating: "x", count: WorkspaceRecoveryStore.maximumBytes))
    XCTAssertThrowsError(try store.save(snapshot))
    XCTAssertEqual(
      WorkspaceRecoveryStore(directory: directory).load().composers["draft"]?.text, "safe")
  }

  func testSymlinkedRecoveryFileDoesNotReadOrOverwriteTarget() throws {
    let directory = try directory()
    let target = directory.appendingPathComponent("original")
    let original = try JSONEncoder().encode(WorkspaceRecoverySnapshot())
    try original.write(to: target)
    try FileManager.default.createSymbolicLink(
      at: directory.appendingPathComponent("workspace-v1.json"), withDestinationURL: target)
    let store = WorkspaceRecoveryStore(directory: directory)
    _ = store.load()
    XCTAssertFalse(store.loadIssue.isEmpty)
    XCTAssertThrowsError(try store.save(.init()))
    XCTAssertEqual(try Data(contentsOf: target), original)
  }

  func testSymlinkedDirectoryIsRejected() throws {
    let parent = try directory()
    let target = parent.appendingPathComponent("actual")
    try FileManager.default.createDirectory(at: target, withIntermediateDirectories: true)
    let link = parent.appendingPathComponent("link")
    try FileManager.default.createSymbolicLink(at: link, withDestinationURL: target)
    let store = WorkspaceRecoveryStore(directory: link)
    _ = store.load()
    XCTAssertFalse(store.loadIssue.isEmpty)
    XCTAssertThrowsError(try store.save(.init()))
    XCTAssertTrue(try FileManager.default.contentsOfDirectory(atPath: target.path).isEmpty)
  }

  func testRecoveryFilesArePrivateToTheLocalUser() throws {
    let directory = try directory()
    try WorkspaceRecoveryStore(directory: directory).save(.init())
    let attributes = try FileManager.default.attributesOfItem(
      atPath: directory.appendingPathComponent("workspace-v1.json").path)
    XCTAssertEqual((attributes[.posixPermissions] as? NSNumber)?.intValue, 0o600)
    let directoryAttributes = try FileManager.default.attributesOfItem(atPath: directory.path)
    XCTAssertEqual((directoryAttributes[.posixPermissions] as? NSNumber)?.intValue, 0o700)
  }

  func testUnwritableLocationReportsFailureInsteadOfClaimingRecovery() throws {
    let directory = try directory()
    let file = directory.appendingPathComponent("not-a-directory")
    try Data().write(to: file)
    XCTAssertThrowsError(try WorkspaceRecoveryStore(directory: file).save(.init()))
  }

  func testResetPreservesUnreadableBytesBeforeWritingCurrentDrafts() throws {
    let directory = try directory()
    let file = directory.appendingPathComponent("workspace-v1.json")
    let original = Data("unreadable recovery".utf8)
    try original.write(to: file)
    let store = WorkspaceRecoveryStore(directory: directory)
    _ = store.load()
    let archive = try XCTUnwrap(store.resetPreservingSavedFile())
    XCTAssertEqual(try Data(contentsOf: archive), original)
    var current = WorkspaceRecoverySnapshot()
    current.composers["draft"] = ComposerRecovery(text: "current work")
    try store.save(current)
    XCTAssertEqual(
      WorkspaceRecoveryStore(directory: directory).load().composers["draft"]?.text, "current work")
  }

  func testFinalSynchronousSaveCannotBeOverwrittenByEarlierBackgroundSave() throws {
    let directory = try directory()
    let store = WorkspaceRecoveryStore(directory: directory)
    var older = WorkspaceRecoverySnapshot()
    older.composers["draft"] = ComposerRecovery(text: "older")
    let completed = expectation(description: "background completion")
    store.saveInBackground(older) { error in
      XCTAssertNil(error)
      completed.fulfill()
    }
    var finalSnapshot = older
    finalSnapshot.composers["draft"] = ComposerRecovery(text: "final")
    try store.save(finalSnapshot)
    wait(for: [completed], timeout: 5)
    XCTAssertEqual(
      WorkspaceRecoveryStore(directory: directory).load().composers["draft"]?.text, "final")
  }
}
