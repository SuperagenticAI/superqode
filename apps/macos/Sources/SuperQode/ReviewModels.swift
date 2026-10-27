import Foundation

enum ReviewScope: String, Codable, CaseIterable, Identifiable {
  case turn, uncommitted, branch
  var id: String { rawValue }
  var title: String {
    switch self {
    case .turn: return "This turn"
    case .uncommitted: return "Uncommitted"
    case .branch: return "Branch"
    }
  }
}

struct ReviewSelection: Codable, Equatable {
  var scope: ReviewScope = .uncommitted
  var fileID = ""
  var baseRef = "main"
  var hunkID = 0

  func parameters(project: String, job: String) -> [String: Any] {
    [
      "project": project, "scope": scope.rawValue, "job": job,
      "base_ref": baseRef, "file_id": fileID,
    ]
  }
}

struct ReviewFile: Decodable, Identifiable, Equatable {
  let id: String
  let path: String
  let layer: String
  let change: String
  var layerTitle: String {
    switch layer {
    case "staged": return "Staged"
    case "unstaged": return "Unstaged"
    case "untracked": return "Untracked"
    case "turn": return "Turn checkpoint"
    default: return "Committed"
    }
  }
}

struct ReviewListing: Decodable {
  let scope: ReviewScope
  let label: String
  let files: [ReviewFile]
  let excludedCount: Int
  let truncated: Bool
  enum CodingKeys: String, CodingKey {
    case scope, label, files, truncated
    case excludedCount = "excluded_count"
  }
}

struct ReviewLine: Decodable, Identifiable, Equatable {
  let id: Int
  let kind: String
  let text: String
  let oldLine: Int?
  let newLine: Int?
  let noNewline: Bool
  enum CodingKeys: String, CodingKey {
    case id, kind, text
    case oldLine = "old_line"
    case newLine = "new_line"
    case noNewline = "no_newline"
  }
  var numberLabel: String {
    "old \(oldLine.map(String.init) ?? "–"), new \(newLine.map(String.init) ?? "–")"
  }
  var marker: String { kind == "add" ? "+" : kind == "delete" ? "−" : " " }
}

struct ReviewHunk: Decodable, Identifiable, Equatable {
  let id: Int
  let header: String
  let lines: [ReviewLine]
}

struct ReviewDocument: Decodable {
  let id: String
  let path: String
  let layer: String
  let scope: ReviewScope
  let label: String
  let hunks: [ReviewHunk]
  let snapshotID: String?
  let baseRevision: String?
  let targetRevision: String?
  let revisions: [String: String]?
  let baseMode: String?
  let targetMode: String?
  let issue: String
  let truncated: Bool
  let canStage: Bool
  enum CodingKeys: String, CodingKey {
    case id, path, layer, scope, label, hunks, issue, truncated
    case snapshotID = "snapshot_id"
    case baseRevision = "base_revision"
    case targetRevision = "target_revision"
    case canStage = "can_stage"
    case revisions
    case baseMode = "base_mode"
    case targetMode = "target_mode"
  }

  var complete: Bool {
    issue.isEmpty && !truncated && snapshotID?.isEmpty == false
      && baseRevision != nil && targetRevision != nil
  }

  static func decode(_ value: Any) throws -> ReviewDocument {
    let document: ReviewDocument = try decodeReview(value)
    guard
      document.hunks.enumerated().allSatisfy({ offset, hunk in
        hunk.id == offset
          && hunk.lines.enumerated().allSatisfy { index, line in
            guard line.id == index, line.oldLine.map({ $0 > 0 }) ?? true,
              line.newLine.map({ $0 > 0 }) ?? true
            else { return false }
            switch line.kind {
            case "add": return line.oldLine == nil && line.newLine != nil
            case "delete": return line.oldLine != nil && line.newLine == nil
            case "context": return line.oldLine != nil && line.newLine != nil
            default: return false
            }
          }
      })
    else {
      throw EngineError(
        message: "The review contains invalid line coordinates. Refresh it before commenting.")
    }
    return document
  }
}

struct ReviewLineSelection: Codable, Equatable {
  var hunkID: Int?
  var start: Int?
  var end: Int?

  mutating func select(_ line: Int, in hunk: Int, extending: Bool) {
    if extending, hunkID == hunk, start != nil {
      end = line
    } else {
      hunkID = hunk
      start = line
      end = line
    }
  }

  func range(in hunk: ReviewHunk) -> ClosedRange<Int>? {
    guard hunkID == hunk.id, let start, let end,
      hunk.lines.indices.contains(start), hunk.lines.indices.contains(end)
    else { return nil }
    return min(start, end)...max(start, end)
  }
}

struct ReviewCommentDraft: Codable, Equatable {
  var path: String
  var snapshotID: String
  var text: String
  var selection: ReviewLineSelection
}

func decodeReview<T: Decodable>(_ value: Any) throws -> T {
  guard JSONSerialization.isValidJSONObject(value) else {
    throw EngineError(message: "The engine returned an invalid review response.")
  }
  return try JSONDecoder().decode(T.self, from: JSONSerialization.data(withJSONObject: value))
}
