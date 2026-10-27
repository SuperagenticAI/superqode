import Foundation

enum WorkspaceCommandAction: Equatable {
  case openProject, newTask, connect, back, forward, refreshChanges, exportEvidence, welcome, learning
  case section(String), run(String), project(String)

  var id: String {
    switch self {
    case .openProject: return "open-project"
    case .newTask: return "new-task"
    case .connect: return "connect"
    case .back: return "back"
    case .forward: return "forward"
    case .refreshChanges: return "refresh-changes"
    case .exportEvidence: return "export-evidence"
    case .welcome: return "welcome"
    case .learning: return "learning"
    case .section(let name): return "section:" + name
    case .run(let id): return "run:" + id
    case .project(let path): return "project:" + path
    }
  }
}

struct WorkspaceCommand: Identifiable {
  let action: WorkspaceCommandAction
  let title: String
  let detail: String
  let symbol: String
  var keywords: String = ""
  var key: String? = nil
  var disabledReason: String? = nil
  var id: String { action.id }
  var isEnabled: Bool { disabledReason == nil }

  /// Every query term must match, including aliases; equal scores keep catalog order.
  static func search(_ commands: [WorkspaceCommand], query: String) -> [WorkspaceCommand] {
    func normalized(_ text: String) -> String {
      text.folding(options: [.caseInsensitive, .diacriticInsensitive], locale: .current)
    }
    let terms = normalized(query).split(whereSeparator: { $0.isWhitespace }).map(String.init)
    guard !terms.isEmpty else { return commands }
    return commands.enumerated().compactMap { index, command -> (Int, Int, WorkspaceCommand)? in
      let title = normalized(command.title)
      let text = normalized(command.title + " " + command.detail + " " + command.keywords)
      guard terms.allSatisfy({ text.contains($0) }) else { return nil }
      let phrase = terms.joined(separator: " ")
      let rank = title == phrase ? 0 : title.hasPrefix(phrase) ? 1 : title.contains(phrase) ? 2 : 3
      return (rank, index, command)
    }.sorted { $0.0 == $1.0 ? $0.1 < $1.1 : $0.0 < $1.0 }.map { $0.2 }
  }

  static func initialSelection(_ commands: [WorkspaceCommand]) -> String? {
    commands.first(where: \.isEnabled)?.id ?? commands.first?.id
  }

  static func moveSelection(_ current: String?, by offset: Int, in commands: [WorkspaceCommand]) -> String? {
    guard !commands.isEmpty else { return nil }
    guard let index = commands.firstIndex(where: { $0.id == current }) else {
      return initialSelection(commands)
    }
    return commands[min(max(index + offset, 0), commands.count - 1)].id
  }
}
