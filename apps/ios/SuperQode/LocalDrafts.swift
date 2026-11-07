import Foundation
import CryptoKit

struct SubmissionAttempt: Codable, Equatable, Sendable {
  let key: String
  let params: [String: JSONValue]
  var method: String? = nil
}

struct LocalDraft: Codable, Identifiable, Equatable, Sendable {
  var id = UUID().uuidString
  let project: String
  var origin = ""
  var parent: String?
  var profile = ""
  var prompt = ""
  var mode = "code"
  var contextFiles: [String]? = nil
  var images: [DraftImage]? = nil
  var fileEdit: SavedFileEdit? = nil
  var enqueue: Bool? = nil
  var updated = Date()
  var attempt: SubmissionAttempt?
  var isExperiment: Bool { ["evaluations.start", "optimizations.start"].contains(attempt?.method ?? "") }
}

/// Device-only unsent text. An interrupted submission keeps its original request ID.
actor DraftRepository {
  private let file: URL
  init(directory: URL? = nil) {
    let root = directory ?? FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
      .appendingPathComponent("SuperQode", isDirectory: true)
    file = root.appendingPathComponent("drafts.json")
  }
  func list() throws -> [LocalDraft] {
    guard FileManager.default.fileExists(atPath: file.path) else { return [] }
    let bytes = try Data(contentsOf: file)
    guard bytes.count <= 4 * 1024 * 1024 else { throw CompanionError("Draft storage is too large. Export or clear saved drafts in Settings.") }
    return try JSONDecoder().decode([LocalDraft].self, from: bytes).sorted { $0.updated > $1.updated }
  }
  func save(_ draft: LocalDraft) throws {
    if let edit = draft.fileEdit, !edit.create, draft.attempt == nil,
      SHA256.hash(data: Data(edit.text.utf8)).map({ String(format: "%02x", $0) }).joined() == edit.digest {
      try remove(draft.id); return
    }
    if draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draft.attempt == nil && (draft.images ?? []).isEmpty && draft.fileEdit == nil {
      try remove(draft.id)
      return
    }
    var drafts = try list().filter { $0.id != draft.id }
    guard drafts.count < 20 else { throw CompanionError("You have 20 saved drafts. Remove a draft before saving another.") }
    var snapshot = draft
    snapshot.updated = Date()
    drafts.append(snapshot)
    try write(drafts)
  }
  func remove(_ identity: String) throws {
    try write(list().filter { $0.id != identity })
    if UUID(uuidString: identity) != nil { try? FileManager.default.removeItem(at: imageDirectory(identity)) }
  }
  func clear() throws {
    try? FileManager.default.removeItem(at: file.deletingLastPathComponent().appendingPathComponent("draft-images"))
    if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
  }
  private func imageDirectory(_ draft: String) -> URL {
    file.deletingLastPathComponent().appendingPathComponent("draft-images", isDirectory: true).appendingPathComponent(draft, isDirectory: true)
  }
  func stageImage(draft: String, name: String, data: Data) throws -> DraftImage {
    guard UUID(uuidString: draft) != nil, !data.isEmpty, data.count <= 4 * 1024 * 1024 else { throw CompanionError("Choose an image no larger than 4 MB.") }
    let root = file.deletingLastPathComponent().appendingPathComponent("draft-images", isDirectory: true)
    let entries = (FileManager.default.enumerator(at: root, includingPropertiesForKeys: [.fileSizeKey, .isRegularFileKey])?.allObjects as? [URL]) ?? []
    let total = entries.reduce(0) { size, url in size + ((try? url.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey])).flatMap { $0.isRegularFile == true ? $0.fileSize : 0 } ?? 0) }
    guard total + data.count <= 64 * 1024 * 1024 else { throw CompanionError("Saved image drafts exceed 64 MB. Remove older drafts in Settings.") }
    let image = DraftImage(name: name, bytes: data.count)
    let directory = imageDirectory(draft)
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true, attributes: [.protectionKey: FileProtectionType.complete])
    var target = directory.appendingPathComponent(image.id)
    try data.write(to: target, options: [.atomic, .completeFileProtection])
    var flags = URLResourceValues(); flags.isExcludedFromBackup = true
    try target.setResourceValues(flags)
    // Atomic replacement and the backup-exclusion update can both drop the
    // protection class. Apply it to the final path after those writes.
    try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: target.path)
    return image
  }
  func imageData(draft: String, image: DraftImage) throws -> Data {
    guard UUID(uuidString: draft) != nil, UUID(uuidString: image.id) != nil else { throw CompanionError("The saved image reference is invalid. Attach it again.") }
    let bytes = try Data(contentsOf: imageDirectory(draft).appendingPathComponent(image.id))
    guard bytes.count == image.bytes, bytes.count <= 4 * 1024 * 1024 else { throw CompanionError("The saved image changed. Attach it again.") }
    return bytes
  }
  func removeImage(draft: String, image: DraftImage) throws {
    guard UUID(uuidString: draft) != nil, UUID(uuidString: image.id) != nil else { return }
    try FileManager.default.removeItem(at: imageDirectory(draft).appendingPathComponent(image.id))
  }
  private func write(_ drafts: [LocalDraft]) throws {
    let bytes = try JSONEncoder().encode(drafts)
    guard bytes.count <= 4 * 1024 * 1024 else { throw CompanionError("Saved drafts exceed the device storage limit. Remove an older draft first.") }
    let root = file.deletingLastPathComponent()
    try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true,
      attributes: [.protectionKey: FileProtectionType.complete])
    try bytes.write(to: file, options: [.atomic, .completeFileProtection])
    var url = file
    var flags = URLResourceValues()
    flags.isExcludedFromBackup = true
    try url.setResourceValues(flags)
    try FileManager.default.setAttributes([.protectionKey: FileProtectionType.complete], ofItemAtPath: file.path)
  }
}

struct SavedFileEdit: Codable, Equatable, Sendable {
  var path: String
  var digest: String
  var text: String
  var create: Bool
}

struct DraftImage: Codable, Identifiable, Equatable, Sendable {
  var id = UUID().uuidString
  let name: String
  let bytes: Int
  var macID: String? = nil
}

struct OpenedRun: Identifiable, Hashable { let id: String }
