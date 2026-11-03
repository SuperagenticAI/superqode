import Foundation

/// @mentions, permission memory, repository pins, and the compact change line.
/// These stay free of the engine so the desktop loop can be tested without a model.
enum ComposerMentions {
  static func query(in prefix: String) -> String? {
    guard let range = tokenRange(in: prefix) else { return nil }
    let token = prefix[range]
    guard token.hasPrefix("@"), !token.dropFirst().contains("@") else { return nil }
    return String(token.dropFirst())
  }

  static func isComplete(text: String, prefix: String, paths: [String]) -> Bool {
    guard text.hasPrefix(prefix), query(in: prefix) != nil else { return false }
    let suffix = text.dropFirst(prefix.count).prefix { !$0.isWhitespace }
    guard let token = query(in: prefix + suffix) else { return false }
    return paths.contains(token)
  }

  static func insert(text: String, prefix: String, path: String) -> String {
    guard !path.isEmpty, !path.contains("\n"), !path.contains("\u{0000}"),
      text.hasPrefix(prefix), let range = tokenRange(in: prefix), prefix[range].hasPrefix("@")
    else { return text }
    let suffix = String(text.dropFirst(prefix.count))
    let gap = suffix.first?.isWhitespace == true ? "" : " "
    return prefix.replacingCharacters(in: range, with: "@" + path + gap) + suffix
  }

  private static func tokenRange(in prefix: String) -> Range<String.Index>? {
    var index = prefix.endIndex
    while index > prefix.startIndex {
      let previous = prefix.index(before: index)
      if prefix[previous].isWhitespace { break }
      index = previous
    }
    guard index < prefix.endIndex else { return nil }
    return index..<prefix.endIndex
  }
}

enum PermissionMemory {
  static let storageKey = "nativePermissionModes"
  static let modes = ["ask", "auto-edit", "full"]

  static func mode(for composerKey: String, defaults: UserDefaults = .standard) -> String {
    let stored = defaults.dictionary(forKey: storageKey) as? [String: String]
    let value = stored?[composerKey] ?? "ask"
    return modes.contains(value) ? value : "ask"
  }

  static func store(_ mode: String, composerKey: String, defaults: UserDefaults = .standard) {
    guard modes.contains(mode), !composerKey.isEmpty else { return }
    var stored = defaults.dictionary(forKey: storageKey) as? [String: String] ?? [:]
    stored[composerKey] = mode
    defaults.set(stored, forKey: storageKey)
  }

  /// Remember the mode on the conversation that was just created, and put the
  /// shared new-conversation draft back on Ask.
  static func commitNewConversation(
    _ mode: String, project: String, conversation: String, defaults: UserDefaults = .standard
  ) {
    let created = WorkspaceRecoverySnapshot.key(project: project, conversation: conversation)
    store(mode, composerKey: created, defaults: defaults)
    let draft = WorkspaceRecoverySnapshot.key(project: project, conversation: "")
    if created != draft { store("ask", composerKey: draft, defaults: defaults) }
  }
}

enum RepositoryLayout {
  static let panels = [
    "Workspace", "Review", "Files", "Terminal", "Threads", "Tools",
    "Evaluations", "Optimization", "Checkpoints", "Harness Studio",
  ]

  static func pinned(_ names: [String]) -> [String] {
    var seen = Set<String>()
    return names.filter { panels.contains($0) && seen.insert($0).inserted }
  }
}

enum TaskIsolation {
  /// Keep project-relative files that exist in the opened worktree. The prompt moves either way.
  static func handoff(files: [String], present: (String) -> Bool) -> (files: [String], dropped: [String]) {
    var kept: [String] = []
    var dropped: [String] = []
    for file in files {
      let path = file.trimmingCharacters(in: .whitespacesAndNewlines)
      if path.isEmpty || path.hasPrefix("/") || path.split(separator: "/").contains("..") || !present(path) {
        dropped.append(file)
      } else {
        kept.append(path)
      }
    }
    return (kept, dropped)
  }

  static func title(from draft: String) -> String {
    let raw = draft.split(whereSeparator: \.isNewline).first.map(String.init) ?? ""
    let cleaned = raw.unicodeScalars.filter { $0.value >= 32 }.map(String.init).joined()
    let trimmed = cleaned.trimmingCharacters(in: .whitespacesAndNewlines)
    if trimmed.isEmpty { return "Isolated task" }
    return String(trimmed.prefix(120))
  }
}

enum ChangeSummary {
  static func line(stat: String, status: String, diff: String, error: String) -> String? {
    let statLines = nonempty(stat)
    if let summary = statLines.last { return summary }
    let statusLines = nonempty(status)
    if statusLines.count > 1 { return "\(statusLines.count) changed files" }
    if let only = statusLines.first { return only }
    if !diff.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return "Uncommitted changes" }
    let issue = error.trimmingCharacters(in: .whitespacesAndNewlines)
    return issue.isEmpty ? nil : issue
  }

  private static func nonempty(_ text: String) -> [String] {
    text.split(whereSeparator: \.isNewline).map {
      $0.trimmingCharacters(in: .whitespaces)
    }.filter { !$0.isEmpty }
  }
}
