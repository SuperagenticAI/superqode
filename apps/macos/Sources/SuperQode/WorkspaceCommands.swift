import AppKit

@MainActor extension Workspace {
  var workspaceCommands: [WorkspaceCommand] {
    let engineReason = connected ? nil : "Wait for the local engine to connect."
    let projectReason = project.isEmpty ? "Open a project first." : engineReason
    let idleReason = openingProject || restoringNavigation ? "Wait for navigation to finish."
      : busy ? "Wait for the current operation to finish." : nil
    var commands: [WorkspaceCommand] = [
      .init(action: .openProject, title: "Open Project…", detail: "Choose a local repository",
        symbol: "folder.badge.plus", keywords: "repository folder", key: "o",
        disabledReason: engineReason ?? idleReason),
      .init(action: .newTask, title: "New Task", detail: "Start composing a task",
        symbol: "square.and.pencil", keywords: "new chat conversation", key: "n",
        disabledReason: projectReason ?? idleReason),
      .init(action: .connect, title: "Connect…", detail: "Choose an agent or model connection",
        symbol: "link", keywords: "provider harness model agent",
        disabledReason: projectReason ?? idleReason),
      .init(action: .back, title: "Back", detail: "Restore the previous session and page",
        symbol: "chevron.left", key: "[",
        disabledReason: openingProject || restoringNavigation || busy ? idleReason : navigationHistory.isEmpty && !(showWelcome && !project.isEmpty)
          ? "No previous page to return to." : nil),
      .init(action: .forward, title: "Forward", detail: "Restore the next session and page",
        symbol: "chevron.right", key: "]",
        disabledReason: openingProject || restoringNavigation || busy ? idleReason
          : forwardHistory.isEmpty ? "No next page to return to." : nil),
      .init(action: .refreshChanges, title: "Refresh Changes", detail: "Refresh project Git status",
        symbol: "arrow.clockwise", keywords: "git diff review", key: "r",
        disabledReason: projectReason ?? idleReason),
      .init(action: .exportEvidence, title: "Export Run Evidence…", detail: "Save recorded run activity locally",
        symbol: "square.and.arrow.up", keywords: "history transcript json",
        disabledReason: selectedJob.isEmpty ? "Select a run first." : engineReason ?? idleReason),
      .init(action: .welcome, title: "Welcome to SuperQode", detail: "Return to Welcome",
        symbol: "house", keywords: "home start", disabledReason: openingProject ? idleReason : nil),
      .init(action: .learning, title: "Getting Started & Learning", detail: "Open the local learning guide",
        symbol: "book", keywords: "help documentation guide", key: "?"),
    ]
    commands += Sections.names.enumerated().map { index, name in
      WorkspaceCommand(action: .section(name), title: Sections.title(for: name),
        detail: "Navigate to " + Sections.title(for: name), symbol: Sections.icons[index],
        keywords: name == "Workspace" ? "chat conversation coding" : name.lowercased(),
        key: index < 9 ? String(index + 1) : nil, disabledReason: projectReason ?? idleReason)
    }
    commands += recentConversations.prefix(12).map { run in
      WorkspaceCommand(action: .run(string(run, "id")),
        title: string(run, "conversation_title", string(run, "title", "Untitled run")),
        detail: "Recent run · " + string(run, "status"), symbol: "bubble.left.and.bubble.right",
        keywords: "session conversation " + string(run, "kind"), disabledReason: engineReason ?? idleReason)
    }
    commands += projects.prefix(8).map { row in
      let path = string(row, "path")
      return WorkspaceCommand(action: .project(path),
        title: URL(fileURLWithPath: path).lastPathComponent,
        detail: "Recent project · " + path, symbol: "folder", keywords: "repository",
        disabledReason: engineReason ?? idleReason)
    }
    return commands
  }

  func workspaceCommand(_ action: WorkspaceCommandAction) -> WorkspaceCommand? {
    workspaceCommands.first { $0.action == action }
  }

  /// Resolve again at execution time: availability may have changed since search.
  func runWorkspaceCommand(_ action: WorkspaceCommandAction) {
    guard let command = workspaceCommand(action) else { return }
    guard command.isEnabled else { notice = command.disabledReason ?? "Action unavailable."; return }
    if showCommandPalette {
      choosePaletteCommand(action)
      return
    }
    switch action {
    case .openProject: chooseProject()
    case .newTask:
      selectJob("", targetSection: "Workspace")
      showWelcome = false
    case .connect: showConnection = true
    case .back: goBack()
    case .forward: goForward()
    case .refreshChanges: perform { await self.refreshGit() }
    case .exportEvidence: exportEvidence()
    case .welcome: showWelcome = true
    case .learning: showLearningGuide = true
    case .section(let name):
      showWelcome = false
      section = name
    case .run(let id):
      guard let run = projectJobs.first(where: { string($0, "id") == id }) else { return }
      showWelcome = false
      let destinationSection: String
      switch string(run, "kind") {
      case "tool": destinationSection = "Tools"
      case "optimization": destinationSection = "Optimization"
      case "evaluation": destinationSection = "Evaluations"
      default: destinationSection = "Workspace"
      }
      selectJob(id, targetSection: destinationSection)
    case .project(let path): perform { try await self.open(path) }
    }
  }
}
