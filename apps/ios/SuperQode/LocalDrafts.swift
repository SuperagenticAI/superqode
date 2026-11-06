import Foundation

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
    if draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draft.attempt == nil {
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
  func remove(_ identity: String) throws { try write(list().filter { $0.id != identity }) }
  func clear() throws {
    if FileManager.default.fileExists(atPath: file.path) { try FileManager.default.removeItem(at: file) }
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
  }
}

struct OpenedRun: Identifiable, Hashable { let id: String }
