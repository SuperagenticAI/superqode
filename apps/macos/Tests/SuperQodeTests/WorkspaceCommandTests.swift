import XCTest

@testable import SuperQode

final class WorkspaceCommandTests: XCTestCase {
  private let terminal = WorkspaceCommand(action: .section("Terminal"), title: "Terminal",
    detail: "Project shell", symbol: "terminal", keywords: "console commands")
  private let refresh = WorkspaceCommand(action: .refreshChanges, title: "Refresh Changes",
    detail: "Git status", symbol: "arrow.clockwise", keywords: "diff review")

  func testSearchCombinesTermsAcrossTitleAndAliases() {
    XCTAssertEqual(WorkspaceCommand.search([terminal, refresh], query: "GIT review").map(\.id), [refresh.id])
    XCTAssertEqual(WorkspaceCommand.search([terminal, refresh], query: "terminal console").map(\.id), [terminal.id])
    XCTAssertTrue(WorkspaceCommand.search([terminal, refresh], query: "terminal git").isEmpty)
  }

  func testSearchIgnoresAccentsAndExtraWhitespace() {
    let project = WorkspaceCommand(action: .project("/tmp/café"), title: "Café",
      detail: "Recent project", symbol: "folder")
    XCTAssertEqual(WorkspaceCommand.search([project], query: "  CAFE  ").map(\.id), [project.id])
    XCTAssertEqual(WorkspaceCommand.search([terminal, refresh], query: " \n ").map(\.id), [terminal.id, refresh.id])
  }

  func testExactTitleRanksAbovePrefixAndKeywordMatches() {
    let prefix = WorkspaceCommand(action: .run("one"), title: "Terminal investigation",
      detail: "Recent run", symbol: "bubble.left")
    let keyword = WorkspaceCommand(action: .newTask, title: "New Task", detail: "Compose",
      symbol: "square.and.pencil", keywords: "terminal")
    XCTAssertEqual(WorkspaceCommand.search([keyword, prefix, terminal], query: "terminal").map(\.id),
      [terminal.id, prefix.id, keyword.id])
  }

  func testEqualMatchesKeepCatalogOrderAndDisabledReason() {
    var unavailable = refresh
    unavailable.disabledReason = "Open a project first."
    let results = WorkspaceCommand.search([unavailable, terminal], query: "")
    XCTAssertEqual(results.map(\.id), [refresh.id, terminal.id])
    XCTAssertEqual(results.first?.disabledReason, "Open a project first.")
    XCTAssertEqual(WorkspaceCommand.initialSelection(results), terminal.id)
  }

  func testKeyboardSelectionClampsAndHandlesEmptySearch() {
    let commands = [terminal, refresh]
    XCTAssertEqual(WorkspaceCommand.moveSelection(terminal.id, by: 1, in: commands), refresh.id)
    XCTAssertEqual(WorkspaceCommand.moveSelection(refresh.id, by: 1, in: commands), refresh.id)
    XCTAssertEqual(WorkspaceCommand.moveSelection(terminal.id, by: -1, in: commands), terminal.id)
    XCTAssertEqual(WorkspaceCommand.moveSelection("stale", by: 1, in: commands), terminal.id)
    XCTAssertNil(WorkspaceCommand.moveSelection(nil, by: 1, in: []))
    XCTAssertNil(WorkspaceCommand.initialSelection([]))
  }

  @MainActor func testCatalogHasUniqueIDsAndSingleCharacterShortcuts() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.connected = true
    app.project = ["id": "project", "path": "/tmp/project"]
    app.projects = [["id": "other", "path": "/tmp/other"]]
    app.jobs = [["id": "run", "project": "project", "title": "Fix tests", "kind": "task"]]
    let commands = app.workspaceCommands
    XCTAssertEqual(Set(commands.map(\.id)).count, commands.count)
    let shortcuts = commands.compactMap(\.key)
    XCTAssertTrue(shortcuts.allSatisfy { $0.count == 1 })
    XCTAssertEqual(Set(shortcuts).count, shortcuts.count)
    XCTAssertNotNil(app.workspaceCommand(.run("run")))
    XCTAssertNotNil(app.workspaceCommand(.project("/tmp/other")))
  }

  @MainActor func testUnavailableActionsDoNotNavigateAndAreRevalidated() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    XCTAssertFalse(app.workspaceCommand(.section("Terminal"))?.isEnabled ?? true)
    app.runWorkspaceCommand(.section("Terminal"))
    XCTAssertEqual(app.section, "Workspace")
    app.connected = true
    app.project = ["id": "project", "path": "/tmp/project"]
    XCTAssertTrue(app.workspaceCommand(.section("Terminal"))?.isEnabled ?? false)
    app.runWorkspaceCommand(.section("Terminal"))
    XCTAssertEqual(app.section, "Terminal")
    XCTAssertFalse(app.showWelcome)
    app.connected = false
    app.runWorkspaceCommand(.section("Files"))
    XCTAssertEqual(app.section, "Terminal")
  }

  @MainActor func testRecentRunsAreScopedToCurrentProject() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.connected = true
    app.project = ["id": "a"]
    app.jobs = [
      ["id": "local", "project": "a", "kind": "task", "title": "Local"],
      ["id": "foreign", "project": "b", "kind": "task", "title": "Other project"],
    ]
    XCTAssertNotNil(app.workspaceCommand(.run("local")))
    XCTAssertNil(app.workspaceCommand(.run("foreign")))
    XCTAssertNil(app.workspaceCommand(.run("missing")))
  }

  @MainActor func testBusyOperationsDisableProjectChangesAndExportNeedsSelection() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.connected = true
    app.project = ["id": "project"]
    app.busy = true
    XCTAssertFalse(app.workspaceCommand(.openProject)?.isEnabled ?? true)
    XCTAssertFalse(app.workspaceCommand(.newTask)?.isEnabled ?? true)
    app.busy = false
    XCTAssertFalse(app.workspaceCommand(.exportEvidence)?.isEnabled ?? true)
    app.selectedJob = "run"
    XCTAssertTrue(app.workspaceCommand(.exportEvidence)?.isEnabled ?? false)
  }

  @MainActor func testProjectLoadingBlocksOverlappingNavigation() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.connected = true
    app.project = ["id": "project"]
    app.projects = [["id": "other", "path": "/tmp/other"]]
    app.openingProject = true
    let actions: [WorkspaceCommandAction] = [.openProject, .newTask, .section("Files"), .project("/tmp/other")]
    for action in actions {
      XCTAssertFalse(app.workspaceCommand(action)?.isEnabled ?? true)
    }
    app.runWorkspaceCommand(.section("Files"))
    XCTAssertEqual(app.section, "Workspace")
  }

  @MainActor func testMenuActionDefersUntilPaletteDismissalAndRunsOnce() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.connected = true
    app.project = ["id": "project"]
    app.showCommandPalette = true
    app.runWorkspaceCommand(.section("Terminal"))
    XCTAssertFalse(app.showCommandPalette)
    XCTAssertEqual(app.section, "Workspace")
    app.finishCommandPalette()
    XCTAssertEqual(app.section, "Terminal")
    let history = app.navigationHistory
    app.finishCommandPalette()
    XCTAssertEqual(app.navigationHistory, history)
  }
}
