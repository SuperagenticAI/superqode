import Foundation

struct FileEdit: Codable, Equatable {
  let original: String
  let digest: String
  let text: String
}

struct WorkspaceDestination: Codable, Equatable {
  var projectID: String
  var projectPath: String
  var conversationID: String = ""
  var jobID: String = ""
  var section: String = "Workspace"
  var filePath: String = ""
  var inspectorVisible: Bool = false
  var checkpointID: String = ""
  var checkpointPath: String = ""
  var showWelcome: Bool = false
  var review: ReviewSelection? = nil
}

struct ComposerRecovery: Codable, Equatable {
  var text: String = ""
  var files: [String] = []
  var images: [[String: String]] = []
  var mode: String = "code"
  var contextWindow: String = ""
  var summarize: Bool = false
  var reviewComments: [String: ReviewCommentDraft]? = nil
}

struct TranscriptPosition: Codable, Equatable {
  var follow: Bool = true
  var anchor: String? = nil
}

struct WorkspaceRecoverySnapshot: Codable {
  var version = 1
  var lastDestination: WorkspaceDestination? = nil
  var destinations: [String: WorkspaceDestination] = [:]
  var projectDestinations: [String: WorkspaceDestination] = [:]
  var composers: [String: ComposerRecovery] = [:]
  var editors: [String: FileEdit] = [:]
  var transcripts: [String: TranscriptPosition] = [:]
  var migratedProjects: Set<String> = []

  static func key(project: String, conversation: String) -> String {
    // Length-prefixing keeps arbitrary project/conversation IDs unambiguous.
    "\(project.utf8.count):\(project)\(conversation)"
  }
}

/// Local UI recovery only. Opening a snapshot never starts execution.
final class WorkspaceRecoveryStore {
  static let maximumBytes = 32 * 1024 * 1024
  private let directory: URL?
  private let writer = DispatchQueue(label: "ai.superqode.workspace-recovery")
  private(set) var loadIssue = ""
  private var blocked = false

  init(directory: URL?) { self.directory = directory }

  static func applicationStore() -> WorkspaceRecoveryStore {
    let base = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)
      .first!
    return WorkspaceRecoveryStore(
      directory: base.appendingPathComponent("SuperQode/Recovery", isDirectory: true))
  }

  private var file: URL? { directory?.appendingPathComponent("workspace-v1.json") }

  func resetPreservingSavedFile() throws -> URL? {
    try writer.sync {
      guard let directory, let file else { return nil }
      let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
      guard attributes[.type] as? FileAttributeType == .typeDirectory else {
        throw RecoveryError.invalidFile
      }
      let archive = directory.appendingPathComponent(
        "workspace-preserved-\(UUID().uuidString).json")
      let exists = (try? FileManager.default.attributesOfItem(atPath: file.path)) != nil
      if exists { try FileManager.default.moveItem(at: file, to: archive) }
      blocked = false
      loadIssue = ""
      return exists ? archive : nil
    }
  }

  func load() -> WorkspaceRecoverySnapshot {
    guard let file, let directory else { return .init() }
    do {
      if let attributes = try? FileManager.default.attributesOfItem(atPath: directory.path),
        attributes[.type] as? FileAttributeType != .typeDirectory
      {
        throw RecoveryError.invalidFile
      }
      guard FileManager.default.fileExists(atPath: file.path) else { return .init() }
      let attributes = try FileManager.default.attributesOfItem(atPath: file.path)
      guard attributes[.type] as? FileAttributeType == .typeRegular,
        ((attributes[.size] as? NSNumber)?.intValue ?? Int.max) <= Self.maximumBytes
      else {
        throw RecoveryError.invalidFile
      }
      let snapshot = try JSONDecoder().decode(
        WorkspaceRecoverySnapshot.self, from: Data(contentsOf: file))
      guard snapshot.version == 1 else { throw RecoveryError.unsupportedVersion }
      return snapshot
    } catch {
      // Preserve unreadable/future data. Do not overwrite it with a fresh snapshot.
      blocked = true
      loadIssue =
        "Recovery could not be loaded. The saved file is preserved at \(file.path). "
        + "Copy any current drafts before quitting. " + error.localizedDescription
      return .init()
    }
  }

  func save(_ snapshot: WorkspaceRecoverySnapshot) throws {
    try writer.sync { try write(snapshot) }
  }

  func saveInBackground(
    _ snapshot: WorkspaceRecoverySnapshot, completion: @escaping @MainActor (Error?) -> Void
  ) {
    writer.async {
      let failure: Error?
      do {
        try self.write(snapshot)
        failure = nil
      } catch { failure = error }
      DispatchQueue.main.async { completion(failure) }
    }
  }

  private func write(_ snapshot: WorkspaceRecoverySnapshot) throws {
    guard let directory, let file else { return }
    guard !blocked else { throw RecoveryError.blocked }
    let data = try JSONEncoder().encode(snapshot)
    guard data.count <= Self.maximumBytes else { throw RecoveryError.storageLimit }
    try FileManager.default.createDirectory(
      at: directory, withIntermediateDirectories: true,
      attributes: [.posixPermissions: 0o700])
    let attributes = try FileManager.default.attributesOfItem(atPath: directory.path)
    guard attributes[.type] as? FileAttributeType == .typeDirectory else {
      throw RecoveryError.invalidFile
    }
    try FileManager.default.setAttributes([.posixPermissions: 0o700], ofItemAtPath: directory.path)
    try data.write(to: file, options: [.atomic, .completeFileProtectionUnlessOpen])
    try FileManager.default.setAttributes([.posixPermissions: 0o600], ofItemAtPath: file.path)
  }

  enum RecoveryError: LocalizedError {
    case invalidFile, unsupportedVersion, blocked, storageLimit
    var errorDescription: String? {
      switch self {
      case .invalidFile: return "The recovery file or directory is invalid or too large."
      case .unsupportedVersion: return "This recovery file needs a different app version."
      case .blocked:
        return "The existing recovery file needs attention before new drafts can be saved."
      case .storageLimit:
        return "Recovery storage is full. Save or discard recovered file drafts, then retry."
      }
    }
  }
}
