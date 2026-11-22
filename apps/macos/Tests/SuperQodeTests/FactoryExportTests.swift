import XCTest
import CryptoKit
@testable import SuperQode

final class FactoryExportTests: XCTestCase {
  @MainActor func testArchiveCopyVerifiesBytesAndRefusesOverwrite() async throws {
    let folder = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
    try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
    defer { try? FileManager.default.removeItem(at: folder) }
    let source = folder.appendingPathComponent("source.zip"); let target = folder.appendingPathComponent("copy.zip")
    let data = Data("controlled export bytes".utf8); try data.write(to: source)
    let digest = "sha256:" + SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryExportLibrary(); library.enter("project")
    let preview = Task { await library.refresh(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["snapshot_digest": "reviewed"]]); await preview.value
    let create = Task { await library.create(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 2, "result": ["path": source.path, "sha256": digest, "manifest": ["snapshot_digest": "reviewed"]]])
    await create.value
    try library.copy(to: target); XCTAssertEqual(try Data(contentsOf: target), data)
    XCTAssertThrowsError(try library.copy(to: target))
    try Data("tampered".utf8).write(to: source)
    XCTAssertThrowsError(try library.copy(to: folder.appendingPathComponent("tampered-copy.zip")))
    XCTAssertEqual(try Data(contentsOf: target), data)
  }
  @MainActor func testExportPreviewAndReceiptCannotCrossProjects() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryExportLibrary(); library.enter("first")
    let reading = Task { await library.refresh(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["snapshot_digest": "snapshot"]]); await reading.value
    let exporting = Task { await library.create(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    library.enter("second")
    engine.receive(["id": 2, "result": ["path": "/foreign/private.zip", "manifest": ["snapshot_digest": "snapshot"]]])
    await exporting.value
    XCTAssertTrue(library.package.isEmpty); XCTAssertTrue(library.preview.isEmpty); XCTAssertFalse(library.busy)
  }
  @MainActor func testChangedSnapshotInvalidatesOldExportReceipt() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryExportLibrary(); library.enter("project")
    let reading = Task { await library.refresh(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["snapshot_digest": "first"]]); await reading.value
    let exporting = Task { await library.create(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 2, "result": ["path": "/old.zip", "manifest": ["snapshot_digest": "first"]]])
    await exporting.value; XCTAssertFalse(library.package.isEmpty)
    let refresh = Task { await library.refresh(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 3, "result": ["snapshot_digest": "second"]]); await refresh.value
    XCTAssertTrue(library.package.isEmpty)
  }
  @MainActor func testExportRefusesReceiptForDifferentSnapshot() async {
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting); defer { engine.stop() }
    let library = FactoryExportLibrary(); library.enter("project")
    let reading = Task { await library.refresh(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 1, "result": ["snapshot_digest": "expected"]]); await reading.value
    let exporting = Task { await library.create(engine) }
    while engine.pendingRequestCount < 1 { await Task.yield() }
    engine.receive(["id": 2, "result": ["manifest": ["snapshot_digest": "different"]]])
    await exporting.value
    XCTAssertTrue(library.package.isEmpty); XCTAssertTrue(library.failure.contains("differs"))
  }
}
