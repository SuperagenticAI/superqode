import AppKit

@MainActor extension Workspace {
  private var workspaceCommandIdleReason: String? {
    openingProject || restoringNavigation || switchingBackgroundEngine ? "Wait for navigation or engine reconnection to finish."
      : busy ? "Wait for the current operation to finish." : nil
  }
  private var workspaceBaseCommands: [WorkspaceCommand] {
    let engineReason = connected ? nil : "Wait for the local engine to connect."
    let projectReason = project.isEmpty ? "Open a project first." : engineReason
    let idleReason = workspaceCommandIdleReason
    var commands: [WorkspaceCommand] = [
      .init(action: .openProject, title: "Open Project…", detail: "Choose a local repository",
        symbol: "folder.badge.plus", keywords: "repository folder", key: "o",
        disabledReason: engineReason ?? idleReason),
      .init(action: .newTask, title: "New Task", detail: "Start composing a task",
        symbol: "square.and.pencil", keywords: "new chat conversation", key: "n",
        disabledReason: projectReason ?? idleReason),
      .init(action: .section("Agent activity"), title: "All Work",
        detail: "See project threads and connect external session history",
        symbol: "square.stack.3d.up", keywords: "fleet agents activity threads all projects working blocked needs attention external codex history sessions",
        disabledReason: engineReason ?? idleReason),
      .init(action: .connect, title: "Connect…", detail: "Choose an agent or model connection",
        symbol: "link", keywords: "provider harness model agent",
        disabledReason: projectReason ?? idleReason),
      .init(action: .section("Models"), title: "Local AI", detail: "Search, download and serve models on this Mac",
        symbol: "cpu", keywords: "ollama hugging face lm studio mlx gguf kv cache models local inference", disabledReason: engineReason ?? idleReason),
      .init(action: .connectionPage("builder"), title: "Build Your Own Harness…",
        detail: "Create or import a project HarnessSpec", symbol: "hammer", keywords: "custom harness yaml preset",
        disabledReason: projectReason ?? idleReason),
      .init(action: .connectionPage("runtimes"), title: "Agent Runtimes…",
        detail: "Browse all agent runtimes and harness backends", symbol: "cpu",
        keywords: "framework sdk backend adk pydanticai strands codex copilot claude antigravity deepagents muse grok devin tau rlm pipy codegem prime systemone uhp",
        disabledReason: projectReason ?? idleReason),
      .init(action: .connectionPage("acp"), title: "Connect ACP Agent…",
        detail: "Browse agents and review installation", symbol: "link", keywords: "agent client protocol setup",
        disabledReason: projectReason ?? idleReason),
      .init(action: .connectionDiagnostics, title: "Connection Diagnostics…",
        detail: "Inspect startup evidence, session capabilities and connection failures", symbol: "checkmark.shield",
        keywords: "agent acp resume images models modes retry health",
        disabledReason: projectReason ?? idleReason ?? (isManaged ? nil : "Choose an agent-managed connection first.")),
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
    commands += Sections.names.enumerated().filter { !["Agent activity", "Models"].contains($0.element) }.map { index, name in
      WorkspaceCommand(action: .section(name), title: Sections.title(for: name),
        detail: "Navigate to " + Sections.title(for: name), symbol: Sections.icons[index],
        keywords: name == "Workspace" ? "chat conversation coding" : name.lowercased(),
        key: index < 9 ? String(index + 1) : nil, disabledReason: projectReason ?? idleReason)
    }
    return commands
  }

  var workspaceCommands: [WorkspaceCommand] {
    var commands = workspaceBaseCommands
    let disabledReason = connected ? workspaceCommandIdleReason : "Wait for the local engine to connect."
    commands += recentConversations.prefix(12).map { run in
      WorkspaceCommand(action: .run(string(run, "id")),
        title: string(run, "conversation_title", string(run, "title", "Untitled run")),
        detail: "Recent run · " + string(run, "status"), symbol: "bubble.left.and.bubble.right",
        keywords: "session conversation " + string(run, "kind"), disabledReason: disabledReason)
    }
    commands += projects.prefix(8).map { row in
      let path = string(row, "path")
      return WorkspaceCommand(action: .project(path),
        title: string(row, "name", URL(fileURLWithPath: path).lastPathComponent),
        detail: "Recent project · " + path, symbol: "folder", keywords: "repository",
        disabledReason: disabledReason)
    }
    return commands
  }

  func workspaceCommand(_ action: WorkspaceCommandAction) -> WorkspaceCommand? {
    // Every native menu item observes the workspace. Resolving a fixed action
    // must not regroup recent conversations and rebuild all dynamic commands.
    switch action {
    case .run, .project: return workspaceCommands.first { $0.action == action }
    default: return workspaceBaseCommands.first { $0.action == action }
    }
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
    case .connect: openConnections()
    case .connectionPage(let page): openConnections(page)
    case .connectionDiagnostics: showConnectionInspector = true
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
      case "optimization", "tuning": destinationSection = "Optimization"
      case "evaluation": destinationSection = "Evaluations"
      default: destinationSection = "Workspace"
      }
      selectJob(id, targetSection: destinationSection)
    case .project(let path): perform { try await self.open(path) }
    }
  }
}
