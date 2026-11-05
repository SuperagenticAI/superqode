import AppKit
import SwiftUI

@MainActor final class DraftStore: ObservableObject {
  @Published var text = ""
  @Published var cursorPrefix = ""
}

@MainActor final class ReviewCommentStore: ObservableObject {
  @Published var drafts: [String: ReviewCommentDraft] = [:]
}

@MainActor private final class DialogAuditState: ObservableObject {
  @Published var shown = false
  @Published var nested = false
  @Published var title = "Dialog check"
  @Published var content = AnyView(EmptyView())
}
private struct DialogAuditHost: View {
  @ObservedObject var state: DialogAuditState
  var body: some View {
    Color.clear.centeredDialog(isPresented: $state.shown, title: state.title) {
      state.content.centeredDialog(isPresented: $state.nested, title: "Nested dialog check") {
        Text("Nested dialog").frame(width: 320, height: 120)
      }
    }
  }
}

@MainActor final class Workspace: ObservableObject {
  let recoveryStore: WorkspaceRecoveryStore
  let preferences: UserDefaults
  lazy var threadNotifications: ThreadNotifications = {
    let alerts = ThreadNotifications(preferences: preferences)
    alerts.openThread = { [weak self] project, job in
      guard let self else { return }
      self.perform {
        let record = try await self.engine.call("jobs.get", ["id": job]) as? [String: Any] ?? [:]
        guard string(record, "project") == project,
          let destination = self.projects.first(where: { string($0, "id") == project }) else { return }
        if self.projectID != project { try await self.open(string(destination, "path"), expectedProjectID: project) }
        self.selectJob(job, targetSection: "Workspace")
        let title = Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "SuperQode"
        NSApp.windows.first(where: { $0.title == title })?.makeKeyAndOrderFront(nil)
        NSApp.activate(ignoringOtherApps: true)
      }
    }
    return alerts
  }()
  @Published var threadTabsByProject: [String: [String]] = [:]
  var recoverySnapshot: WorkspaceRecoverySnapshot
  @Published var restoringNavigation = false
  var restoringComposer = false
  var composerConversationID = ""
  private var draftSaveTask: Task<Void, Never>?
  var recoverySaveTask: Task<Void, Never>?
  var recoverySaveGeneration = 0
  @Published var recoveryIssue = ""
  @Published var loadingConversationDraft = false
  @Published var selectedFile = "" { didSet { persistDestination() } }
  @Published private(set) var navigationState = WorkbenchNavigationState()
  var workbenchDrawer: String {
    get { navigationState.drawer }
    set {
      var next = navigationState; next.drawer = newValue
      if newValue == "Files" { next.filesMounted = true }
      if newValue.isEmpty { next.expanded = false }
      if next != navigationState { navigationState = next }
    }
  }
  var drawerExpanded: Bool {
    get { navigationState.expanded }
    set {
      var next = navigationState; next.expanded = newValue && !next.drawer.isEmpty
      if next != navigationState { navigationState = next }
    }
  }
  var inspectorVisible: Bool {
    get { navigationState.inspector }
    set {
      var next = navigationState; next.inspector = newValue
      guard next != navigationState else { return }
      navigationState = next
      persistDestination()
    }
  }
  func toggleWorkbenchDrawer(_ name: String) {
    var next = navigationState
    next.drawer = next.drawer == name ? "" : name
    next.expanded = name == "Files" && !next.drawer.isEmpty
    if name == "Files" { next.filesMounted = true }
    if next != navigationState { navigationState = next }
  }
  func resetWorkbenchPanels() {
    var next = navigationState
    next.drawer = ""; next.expanded = false; next.inspector = false; next.filesMounted = false
    if next != navigationState { navigationState = next }
  }
  func toggleWorkbenchInspector() {
    var next = navigationState
    next.closeExpandedDrawer()
    next.inspector.toggle()
    navigationState = next
    persistDestination()
  }
  @Published var checkpointID = "" { didSet { persistDestination() } }
  @Published var checkpointPath = "" { didSet { persistDestination() } }
  @Published var reviewSelection = ReviewSelection() { didSet { persistDestination() } }

  init(recoveryStore: WorkspaceRecoveryStore? = nil, preferences: UserDefaults = .standard, engine: Engine? = nil) {
    let smokeRecovery = ProcessInfo.processInfo.environment["SUPERQODE_SMOKE_RECOVERY_DIRECTORY"].map { URL(fileURLWithPath: $0) }
    let store = recoveryStore ?? (ProcessInfo.processInfo.arguments.contains("--smoke-test")
      ? WorkspaceRecoveryStore(directory: smokeRecovery) : .applicationStore())
    self.recoveryStore = store
    self.preferences = preferences
    self.engine = engine ?? Engine()
    self.recoverySnapshot = store.load()
    self.fileDrafts = recoverySnapshot.editors
    self.recoveryIssue = store.loadIssue
    self.accentChoice = (NativeAccent(rawValue: preferences.string(forKey: NativeAccent.preferenceKey) ?? "") ?? .graphite).rawValue
    self.customAccentHex = preferences.string(forKey: NativeAccent.customKey) ?? "#777777"
    self.threadTabsByProject = preferences.dictionary(forKey: "nativeOpenThreadTabs") as? [String: [String]] ?? [:]
  }
  let engine: Engine
  let harnessStudio = HarnessStudioLibrary()
  let terminals = ProjectTerminals()
  let credentialStore = CredentialStore()
  @Published var providers: [[String: Any]] = []
  @Published var savedCredentialProviders: [String] = []
  @Published var routeStatus: [String: Any] = [:]
  @Published var openingProject = false
  @Published var showWelcome = true { didSet { persistDestination() } }
  @Published var starterTourRequested = false
  @Published var showLearningGuide = false
  @Published var showFeatureBrowser = false
  @Published var showCommandPalette = false
  private weak var commandPaletteWindow: NSWindow?
  private weak var commandPaletteHostWindow: NSWindow?
  private weak var commandPaletteResponder: NSResponder?
  private var pendingPaletteAction: WorkspaceCommandAction?
  @Published var learningTopic = "Start coding"
  @Published var showConnection = false
  @Published var showConnectionInspector = false
  @Published var connectionStartPage = "menu:root"

  func openConnections(_ page: String = "menu:root") {
    connectionStartPage = page
    showConnection = true
  }
  @Published var agentModel = ""
  @Published var agentMode = ""
  @Published var agentConfig: [String: String] = [:]
  @Published var connectionMetadata: [String: [String: Any]] = [:]
  @Published var forkWorkspaces: [[String: Any]] = []
  @Published var checkingConnection = false
  private var connectionGeneration = 0
  var agentSession: [String: Any] {
    let currentEvents = string(detail["request"] as? [String: Any] ?? [:], "harness") == harness ? events : []
    let event = currentEvents.last {
      string($0, "type") == "harness_event"
        && string($0["data"] as? [String: Any] ?? [:], "event") == "acp_session"
    }
    return (event?["data"] as? [String: Any])?["payload"] as? [String: Any]
      ?? connectionMetadata[harness]?["session"] as? [String: Any] ?? [:]
  }
  var acpConnections: [[String: Any]] {
    var seen = Set<String>()
    return harnesses.filter { string($0, "desktop_kind") == "acp" }
      .sorted { string($0, "id").hasPrefix("acp:") && !string($1, "id").hasPrefix("acp:") }
      .filter { route in
        var semantics: [String: Any] = [
          "command": string(route, "command", string(route, "id")),
          "vendor": string(route, "subscription_vendor"), "env": route["extra_env"] ?? [:],
        ]
        if route["custom"] as? Bool == true { semantics["custom"] = string(route, "id") }
        if string(route, "command").isEmpty { semantics["unavailable"] = string(route, "id") }
        let key = (try? JSONSerialization.data(withJSONObject: semantics, options: .sortedKeys))
          .map { String(decoding: $0, as: UTF8.self) } ?? string(route, "id")
        return seen.insert(key).inserted
      }
  }
  var agentModels: [[String: Any]] {
    let state = agentSession["models"] as? [String: Any] ?? [:]
    let live = state["availableModels"] as? [[String: Any]] ?? []
    let cached = (connectionMetadata[harness]?["session"] as? [String: Any])?["models"] as? [String: Any] ?? [:]
    let catalog = cached["availableModels"] as? [[String: Any]] ?? []
    let byID = catalog.reduce(into: [String: [String: Any]]()) { $0[$1.agentModelID] = $1 }
    return (live.isEmpty ? catalog : live).map { row in
      guard let metadata = byID[row.agentModelID] else { return row }
      return metadata.merging(row) { _, current in current }
    }.sorted {
      if ($0["free"] as? Bool == true) != ($1["free"] as? Bool == true) { return $0["free"] as? Bool == true }
      return string($0, "name", $0.agentModelID) < string($1, "name", $1.agentModelID)
    }
  }
  var agentCommands: [[String: Any]] {
    let currentEvents = string(detail["request"] as? [String: Any] ?? [:], "harness") == harness ? events : []
    let event = currentEvents.last {
      string($0, "type") == "harness_event"
        && string($0["data"] as? [String: Any] ?? [:], "event") == "commands"
    }
    let data = (event?["data"] as? [String: Any])?["payload"] as? [String: Any] ?? [:]
    return data["commands"] as? [[String: Any]] ?? []
  }
  private var verifiedRoute = ""
  private var connectionTestJob = ""
  private var connectionTestRoute = ""
  private var credentialGeneration = 0
  private var connectionTestGeneration = 0
  @Published var connected = false
  @Published var error: String?
  @Published var notice = ""
  @Published var navigationHistory: [WorkspaceDestination] = []
  @Published var forwardHistory: [WorkspaceDestination] = []
  var section: String {
    get { navigationState.section }
    set {
      let previous = currentDestination
      var next = navigationState; next.select(newValue)
      guard next != navigationState else { return }
      let changedSection = newValue != section
      navigationState = next
      if changedSection && !restoringNavigation { recordNavigation(previous) }
      persistDestination()
    }
  }
  func goBack() {
    if showWelcome && !project.isEmpty {
      showWelcome = false
      return
    }
    travelHistory(forward: false)
  }
  func registerCommandPaletteWindow(_ window: NSWindow?) {
    commandPaletteHostWindow = window
  }
  func presentCommandPalette() {
    guard !showCommandPalette else { return }
    guard let window = commandPaletteHostWindow else { return }
    guard window.sheetParent == nil, window.attachedSheet == nil else {
      notice = "Close the current dialog before opening the command palette."
      return
    }
    window.makeKeyAndOrderFront(nil)
    commandPaletteWindow = window
    commandPaletteResponder = window.firstResponder
    pendingPaletteAction = nil
    showCommandPalette = true
  }
  func choosePaletteCommand(_ action: WorkspaceCommandAction) {
    guard workspaceCommand(action)?.isEnabled == true else { return }
    pendingPaletteAction = action
    showCommandPalette = false
  }
  func finishCommandPalette() {
    let action = pendingPaletteAction
    pendingPaletteAction = nil
    let window = commandPaletteWindow
    let responder = commandPaletteResponder
    commandPaletteWindow = nil
    commandPaletteResponder = nil
    // Present choosers and connection sheets only after the palette has closed.
    if let action { runWorkspaceCommand(action) }
    else if let window, let responder, window.isVisible { window.makeFirstResponder(responder) }
  }
  @Published var projects: [[String: Any]] = []
  @Published var project: [String: Any] = [:]
  @Published var harnesses: [[String: Any]] = []
  @Published var hub: [[String: Any]] = []
  @Published var models: [[String: Any]] = []
  @Published var hardware: [String: Any] = [:]
  @Published var packs: [[String: Any]] = []
  @Published var jobs: [[String: Any]] = []
  @Published var executionRecovery: [String: Any] = [:]
  private var threadLibraries: [String: ThreadLibrary] = [:]
  func threadLibrary(for project: String) -> ThreadLibrary {
    if let library = threadLibraries[project] { return library }
    let library = ThreadLibrary()
    threadLibraries[project] = library
    return library
  }
  @Published var selectedJob = ""
  @Published var detail: [String: Any] = [:]
  @Published var events: [[String: Any]] = []
  @Published private(set) var hasMoreRunEvents = false
  @Published private(set) var omittedRunEvents = 0
  @Published private(set) var eventStreamOpen = false
  @Published private(set) var activityLoadError = ""
  @Published var workSource = "app"
  @Published var backgroundEngineMode = false
  @Published var switchingBackgroundEngine = false
  private var eventCursor = 0
  @Published var git: [String: Any] = [:]
  @Published var files: [String] = []
  var fileDrafts: [String: FileEdit] = [:] {
    didSet {
      // Source text stays local to the editor; publish only changes to the draft list.
      if Set(oldValue.keys) != Set(fileDrafts.keys) { objectWillChange.send() }
      scheduleRecoverySave()
    }
  }
  @Published var capabilities: [String: Any] = [:]
  @Published var provider = "openai"
  @Published var model = ""
  @Published var harness = "superqode"
  let draftStore = DraftStore()
  let reviewCommentStore = ReviewCommentStore()
  var draft: String {
    get { draftStore.text }
    set {
      guard draftStore.text != newValue else { return }
      draftStore.text = newValue
      scheduleDraftSave()
    }
  }
  @Published var interactionMode = "code" { didSet { scheduleDraftSave() } }
  @Published var permissionMode = "ask" {
    didSet {
      guard !restoringComposer, !projectID.isEmpty else { return }
      guard PermissionMemory.modes.contains(permissionMode) else {
        permissionMode = "ask"
        return
      }
      PermissionMemory.store(permissionMode, composerKey: composerKey, defaults: preferences)
    }
  }
  @Published var repositoryPanels: [String] = []
  @Published var repositoryLayoutName = ""
  // Cursor notifications arrive for every keystroke and selection movement.
  // Keep them local to the composer rather than invalidating the workspace.
  var mentionPrefix: String {
    get { draftStore.cursorPrefix }
    set {
      guard draftStore.cursorPrefix != newValue else { return }
      draftStore.cursorPrefix = newValue
    }
  }
  @Published var contextWindow = "" { didSet { scheduleDraftSave() } }
  @Published var summarizeContext = false { didSet { scheduleDraftSave() } }
  @Published var contextFiles: [String] = [] { didSet { scheduleDraftSave() } }
  @Published var imageAttachments: [[String: Any]] = [] { didSet { scheduleDraftSave() } }
  @Published var taskQueue: [String: Any] = [:]
  private var lastQueueJob = ""
  @Published var accentChoice = NativeAccent.graphite.rawValue {
    didSet { preferences.set(accentChoice, forKey: NativeAccent.preferenceKey) }
  }
  @Published var customAccentHex = "#777777" {
    didSet { preferences.set(customAccentHex, forKey: NativeAccent.customKey) }
  }
  @Published var theme = "dark"
  @Published var busy = false
  @Published var candidate: [String: Any] = [:]
  private var poller: Task<Void, Never>?
  private var detailGeneration = 0
  private var detailRequests = Set<String>()
  private var pendingPreferences: [(String, String)]?
  private var writingPreferences = false
  private var projectGeneration = 0
  private var gitGeneration = 0
  private var filesGeneration = 0
  private var projectRefresh: Task<Void, Never>?
  var isACP: Bool {
    harnesses.first(where: { string($0, "id") == harness })?["desktop_kind"] as? String == "acp"
  }
  var isRemote: Bool {
    let kind = string(harnesses.first(where: { string($0, "id") == harness }) ?? [:], "kind")
    return kind == "uhp" || kind == "a2a"
  }
  var canContinueConversation: Bool {
    if string(detail, "kind") == "compaction" { return canContinue }
    let task = string(detail, "kind") == "task"
    let finished = ["completed", "failed", "cancelled", "interrupted"].contains(string(detail, "status"))
    return task && finished
  }
  var canContinue: Bool {
    let result = detail["result"] as? [String: Any] ?? [:]
    return string(detail, "status") == "completed"
      && (result["native_continuity"] as? Bool == true || result["acp_continuity"] as? Bool == true
        || result["remote_continuity"] as? Bool == true || result["vendor_continuity"] as? Bool == true)
  }
  @Published var conversationHistory: [[String: Any]] = []
  @Published var earlierHistory = ""
  @Published var loadingHistory = false
  private var restoreSelectedConnection = false
  func loadConversationHistory(earlier: Bool = false) async {
    let id = selectedJob
    let generation = detailGeneration
    guard !id.isEmpty, !loadingHistory else { return }
    loadingHistory = true
    defer { if generation == detailGeneration { loadingHistory = false } }
    do {
      var params: [String: Any] = ["id": id]
      if earlier { params["before"] = earlierHistory }
      let result = try await engine.call("conversations.get", params) as? [String: Any] ?? [:]
      guard id == selectedJob, generation == detailGeneration else { return }
      if loadingConversationDraft, let identity = result["conversation_id"] as? String, !identity.isEmpty {
        loadingConversationDraft = false
        restoreComposer(conversationID: identity)
        restoreSessionDestination()
      }
      let turns = result["turns"] as? [[String: Any]] ?? []
      conversationHistory = earlier ? turns + conversationHistory : turns
      earlierHistory = string(result, "earlier")
    } catch {
      if id == selectedJob, generation == detailGeneration { self.error = error.localizedDescription }
    }
  }
  var isManaged: Bool {
    isACP
      || harnesses.first(where: { string($0, "id") == harness })?["desktop_kind"] as? String
        == "connection"
  }
  /// Ask, Plan, and Full are enforceable only when this backend pauses for them.
  var enforcesSessionControls: Bool {
    guard !isManaged, !connectionDisconnected else { return false }
    let row = harnesses.first { string($0, "id") == harness } ?? [:]
    return row["enforces_session_controls"] as? Bool == true
  }
  /// The route already chosen in the app, for a reviewed Super Agent draft.
  var reviewedModelRoute: [String: Any]? {
    let selected = model.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !selected.isEmpty, !isManaged, !connectionDisconnected else { return nil }
    switch provider {
    case "ollama", "lmstudio", "mlx", "llama.cpp":
      return ["source": "local", "engine": provider, "model": selected]
    case "llamacpp":
      return ["source": "local", "engine": "llama.cpp", "model": selected]
    case "", "agent":
      return nil
    default:
      return ["source": "provider", "provider": provider, "model": selected]
    }
  }
  var connectionDisconnected: Bool { harness == "disconnected" }
  /// Detach the selected route without logging out of vendor-owned accounts or deleting history.
  func disconnectConnection() {
    guard !anyActive, !busy else { return }
    chooseHarness("disconnected")
    provider = ""
    model = ""
    agentModel = ""
    agentMode = ""
    agentConfig = [:]
    connectionMetadata = [:]
    routeStatus = [:]
    savePreferences()
  }
  func chooseConnection(_ route: [String: Any], verified: [String: Any]? = nil) {
    guard !active, !busy else { notice = "Finish or stop the current response before switching agents."; return }
    let id = string(route, "id")
    if let index = harnesses.firstIndex(where: { string($0, "id") == id }) {
      harnesses[index] = route
    } else {
      harnesses.append(route)
    }
    chooseHarness(id)
    interactionMode = "code"
    section = "Workspace"
    if let verified, verifiedACPConnection(route: route, metadata: verified) {
      connectionMetadata[id] = verified
      routeStatus = ["state": "connected", "message": string(verified, "message")]
    } else { perform { await self.checkManagedConnection() } }
  }
  func checkManagedConnection() async {
    guard isManaged, !projectID.isEmpty else { return }
    if isRemote || harness.hasPrefix("vendor-key:") {
      await checkRoute()
      return
    }
    let reference = harness
    let checkedProject = projectID
    connectionGeneration += 1
    let generation = connectionGeneration
    checkingConnection = true
    routeStatus = ["state": "checking", "message": "Checking agent connection…"]
    var operation = ""
    defer { if generation == connectionGeneration { checkingConnection = false } }
    do {
      let response = try await engine.call("connect.auth.start", [
        "action": "probe", "project": projectID, "reference": reference,
      ]) as? [String: Any] ?? [:]
      operation = string(response, "id")
      guard !operation.isEmpty else { throw EngineError(message: "Connection check could not start.") }
      for _ in 0..<200 {
        guard generation == connectionGeneration, reference == harness else {
          _ = try? await engine.call("connect.auth.cancel", ["id": operation])
          return
        }
        let result = try await engine.call("connect.auth.poll", ["id": operation]) as? [String: Any] ?? [:]
        guard generation == connectionGeneration, reference == harness, checkedProject == projectID else {
          _ = try? await engine.call("connect.auth.cancel", ["id": operation])
          return
        }
        if string(result, "state") == "completed" {
          let metadata = result["result"] as? [String: Any] ?? [:]
          connectionMetadata[reference] = metadata
          routeStatus = ["state": metadata["connected"] as? Bool == true ? "connected" : string(metadata, "state", "configured"),
                         "message": string(metadata, "message")]
          return
        }
        if string(result, "state") != "running" {
          throw EngineError(message: (result["messages"] as? [String] ?? []).last ?? "Connection check failed.")
        }
        try await Task.sleep(for: .milliseconds(250))
      }
      _ = try? await engine.call("connect.auth.cancel", ["id": operation])
      throw EngineError(message: "Connection check timed out. Check the agent's sign-in and try again.")
    } catch {
      if generation == connectionGeneration && reference == harness && checkedProject == projectID {
        var metadata = connectionMetadata[reference] ?? [:]
        metadata["last_check_error"] = error.localizedDescription
        connectionMetadata[reference] = metadata
        routeStatus = ["state": "connection-failed", "ready": false, "message": error.localizedDescription]
      }
    }
  }
  func cancelConnectionCheck() {
    guard checkingConnection else { return }
    connectionGeneration += 1
    checkingConnection = false
    routeStatus = ["state": "check-cancelled", "message": "Connection check cancelled. You can check again when ready."]
  }
  var projectID: String { string(project, "id") }
  var projectJobs: [[String: Any]] { jobs.filter { string($0, "project") == projectID } }
  var recentConversations: [[String: Any]] { groupedRecentRuns(projectJobs) }
  var selectedConversationID: String {
    if !composerConversationID.isEmpty { return composerConversationID }
    let selected = jobs.first { string($0, "id") == selectedJob } ?? [:]
    return string(selected, "conversation_id", selectedJob)
  }
  var active: Bool {
    ["running", "needs_approval", "queued", "cancelling"].contains(string(detail, "status"))
  }
  var anyActive: Bool {
    jobs.contains {
      ["running", "needs_approval", "queued", "cancelling"].contains(string($0, "status"))
    }
  }
  func hasActiveWork(project: String) -> Bool {
    jobs.contains { string($0, "project") == project && ["running", "needs_approval", "queued", "cancelling"].contains(string($0, "status")) }
  }

  func perform(_ action: @escaping @MainActor () async throws -> Void) {
    Task { do { try await action() } catch { self.error = error.localizedDescription } }
  }
  func boot() async {
    guard !connected else { return }
    do {
      engine.onExit = { [weak self] in self?.connected = false }
      try engine.start()
      backgroundEngineMode = engine.backgroundMode
      _ = try await engine.call("hello")
      connected = true
      capabilities = try await engine.call("capabilities") as? [String: Any] ?? [:]
      let settings = try await engine.call("settings.get") as? [String: Any] ?? [:]
      // A fresh blank thread always starts without a remembered account.
      resetThreadConnection()
      theme = string(settings, "theme", "dark")
      savedCredentialProviders = settings["credential_providers"] as? [String] ?? []
      for provider in savedCredentialProviders {
        do {
          let store = credentialStore
          if let key = try await Task.detached(operation: { try store.read(provider) }).value {
            _ = try await engine.call(
              "providers.credentials.set", ["provider": provider, "key": key])
          }
        } catch {
          notice =
            "A saved provider key could not be loaded. Open Connect model to reconnect. "
            + error.localizedDescription
        }
      }
      await refreshProviders()
      projects = try await engine.call("projects.list") as? [[String: Any]] ?? []
      packs = try await engine.call("evals.packs") as? [[String: Any]] ?? []
      let args = ProcessInfo.processInfo.arguments
      try await openStartupProject(arguments: args)
      // Welcome must not inventory model caches or probe a remembered account.
      // Local AI / connection setup performs discovery on explicit navigation.
      await refreshJobs()
      poller = Task { [weak self] in
        var nextJobs = ContinuousClock.now
        while !Task.isCancelled {
          guard let self, self.connected else { return }
          do { try await Task.sleep(for: self.active ? .milliseconds(100) : .seconds(1)) }
          catch { return }
          guard !Task.isCancelled else { return }
          if ContinuousClock.now >= nextJobs {
            await self.refreshJobs()
            nextJobs = ContinuousClock.now.advanced(by: self.anyActive ? .seconds(1) : .seconds(3))
          }
          if self.activityLoadError.isEmpty && (self.active || self.hasMoreRunEvents || self.eventStreamOpen) {
            await self.refreshDetail()
          }
        }
      }
      if args.contains("--smoke-test") {
        if args.contains("--welcome-only") { await smokeWelcomeStartup() }
        else { await smokeTest() }
      }
    } catch { self.error = error.localizedDescription }
  }
  func openStartupProject(arguments: [String]) async throws {
    // Loading recovery and recents must not navigate away from Welcome.
    // Explicit launch targets (including the smoke fixture) remain supported.
    guard let index = arguments.firstIndex(of: "--project"), arguments.count > index + 1,
      !arguments[index + 1].hasPrefix("--"), !arguments[index + 1].isEmpty else { return }
    try await open(arguments[index + 1])
  }
  func chooseProject() {
    guard !openingProject, !restoringNavigation else { return }
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.allowsMultipleSelection = false
    panel.prompt = "Open project"
    if panel.runModal() == .OK, let url = panel.url { perform { try await self.open(url.path) } }
  }
  func open(_ path: String, recordHistory: Bool = true, expectedProjectID: String? = nil) async throws {
    guard !openingProject else { throw EngineError(message: "Wait for the current project to finish opening.") }
    saveDraft(flush: false)
    let previous = currentDestination
    let savedDestinations = recoverySnapshot.projectDestinations
    projectGeneration += 1
    detailGeneration += 1
    connectionGeneration += 1
    checkingConnection = false
    let generation = projectGeneration
    openingProject = true
    defer {
      if generation == projectGeneration {
        openingProject = false
        loadingHistory = false
        persistDestination()
      }
    }
    // Load everything before replacing the visible project. A failed request
    // must leave the previous destination and both projects' drafts intact.
    let opened = try await engine.call("projects.open", ["path": path]) as? [String: Any] ?? [:]
    let openedID = string(opened, "id")
    guard !openedID.isEmpty else { throw EngineError(message: "The engine did not return a project identity.") }
    if let expectedProjectID, openedID != expectedProjectID {
      throw EngineError(message: "The project identity changed. Open it manually to inspect saved drafts.")
    }
    let nextProjects = try await engine.call("projects.list") as? [[String: Any]] ?? []
    let params: [String: Any] = ["project": openedID]
    let definitions = try await engine.call("harnesses.list", params) as? [[String: Any]] ?? []
    let index = try await engine.call("hub.list", params) as? [String: Any] ?? [:]
    let routes = try await engine.call("routes.list", params) as? [[String: Any]] ?? []
    let nextForks = try await engine.call("threads.fork.list", params) as? [[String: Any]] ?? []
    var nextHarnesses = definitions + routes
    for entry in UserDefaults.standard.stringArray(forKey: "nativeVendorKeys") ?? [] {
      if let key = try? credentialStore.read("vendor:" + entry),
        let route = try? await engine.call("connect.vendor.key", ["project": openedID, "entry": entry, "key": key]) as? [String: Any] {
        nextHarnesses.append(route)
      }
    }
    if UserDefaults.standard.bool(forKey: "nativeSystemOneKey"),
      let key = try? credentialStore.read("systemone") {
      _ = try? await engine.call("connect.systemone.key", ["key": key])
    }
    let settings = try await engine.call("settings.get") as? [String: Any] ?? [:]
    guard generation == projectGeneration else { return }
    if recordHistory { recordNavigation(previous) }
    let wasRestoring = restoringNavigation
    restoringNavigation = true
    defer { restoringNavigation = wasRestoring }
    project = opened
    forkWorkspaces = nextForks
    selectedJob = ""
    composerConversationID = ""
    loadingConversationDraft = false
    selectedFile = ""
    resetWorkbenchPanels()
    checkpointID = ""
    checkpointPath = ""
    reviewSelection = ReviewSelection()
    conversationHistory = []
    earlierHistory = ""
    loadingHistory = false
    contextFiles = []
    imageAttachments = []
    taskQueue = [:]
    executionRecovery = [:]
    lastQueueJob = ""
    detail = [:]
    events = []
    eventCursor = 0
    hasMoreRunEvents = false
    omittedRunEvents = 0
    eventStreamOpen = false
    activityLoadError = ""
    candidate = [:]
    git = [:]
    files = []
    repositoryPanels = []
    repositoryLayoutName = ""
    mentionPrefix = ""
    connectionMetadata = [:]
    projects = nextProjects
    harnesses = nextHarnesses
    hub = index["items"] as? [[String: Any]] ?? []
    if !connectionDisconnected, !harnesses.contains(where: { string($0, "id") == harness }), let first = definitions.first {
      harness = string(first, "id")
    }
    migrateLegacyDraft(settings: settings)
    restoreComposer(conversationID: "")
    section = "Workspace"
    if recordHistory, let saved = savedDestinations[projectID] { applyDestination(saved) }
    // Explicit project opens must enter the workspace, even when its saved
    // destination was Welcome. History/restart restoration can apply Welcome
    // separately after open returns.
    showWelcome = false
    if selectedJob.isEmpty { resetThreadConnection() }
    perform {
      await self.refreshGit()
      await self.loadRepositoryLayout()
    }
    if isManaged && recordHistory { perform { await self.checkManagedConnection() } }
  }
  func chooseHarness(_ id: String) {
    let previousACP = isManaged
    let changed = harness != id
    if changed {
      let key = "nativeRouteChoices:" + projectID
      var choices = UserDefaults.standard.dictionary(forKey: key) ?? [:]
      choices[harness] = ["provider": provider, "model": model,
        "agentModel": agentModel, "agentMode": agentMode, "agentConfig": agentConfig]
      UserDefaults.standard.set(choices, forKey: key)
      connectionGeneration += 1
      checkingConnection = false
      routeStatus = [:]
      agentModel = ""
      agentMode = ""
      agentConfig = [:]
    }
    harness = id
    if interactionMode == "plan" && !enforcesSessionControls { interactionMode = "code" }
    if changed && isManaged {
      provider = "agent"
      model = ""
    } else if changed && previousACP {
      provider = "openai"
      model = ""
    }
    if changed, let choices = UserDefaults.standard.dictionary(forKey: "nativeRouteChoices:" + projectID),
      let choice = choices[id] as? [String: Any] {
      provider = string(choice, "provider", provider)
      model = string(choice, "model", model)
      agentModel = string(choice, "agentModel")
      agentMode = string(choice, "agentMode")
      agentConfig = choice["agentConfig"] as? [String: String] ?? [:]
    }
    savePreferences()
  }
  func chooseModelRoute(_ provider: String, _ model: String) {
    if isManaged || connectionDisconnected {
      chooseHarness(
        harnesses.first(where: { string($0, "id") == "core" })?.projectRowID
          ?? harnesses.first(where: { string($0, "desktop_kind").isEmpty })?.projectRowID ?? "core")
    }
    self.provider = provider
    self.model = model
    savePreferences()
  }
  func clearLocalModelBinding() async throws {
    _ = try await engine.call("local.models.clear_binding", ["project": projectID, "provider": provider, "model": model])
    verifiedRoute = ""
    await checkRoute()
    notice = "Local endpoint binding cleared. Future requests use the provider configuration."
  }
  func savePreferences() {
    pendingPreferences = [("provider", provider), ("model", model), ("harness", harness), ("theme", theme)]
    guard !writingPreferences else { return }
    writingPreferences = true
    perform {
      defer { self.writingPreferences = false }
      while let snapshot = self.pendingPreferences {
        self.pendingPreferences = nil
        for (key, value) in snapshot {
          _ = try await self.engine.call("settings.set", ["key": key, "value": value])
        }
      }
    }
  }
  func scheduleDraftSave() {
    guard !restoringComposer, !loadingConversationDraft, !openingProject, !restoringNavigation else { return }
    draftSaveTask?.cancel()
    draftSaveTask = Task {
      do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
      self.saveDraft(flush: false)
    }
  }
  func saveDraft(flush: Bool = true) {
    draftSaveTask?.cancel()
    guard !projectID.isEmpty, !loadingConversationDraft, !restoringComposer,
      !openingProject, !restoringNavigation else { return }
    recoverySnapshot.composers[composerKey] = composerRecovery
    persistDestination()
    if flush { flushRecovery() }
  }

  /// Move an unsent prompt into the workspace just opened by Isolate draft.
  func moveDraftToOpenedWorkspace(
    text: String, files: [String], images: [[String: Any]], fromProject: String,
    fromComposerKey: String
  ) {
    guard !projectID.isEmpty, projectID != fromProject else { return }
    let root = URL(fileURLWithPath: string(project, "path")).resolvingSymlinksInPath()
    let split = TaskIsolation.handoff(files: files) { relative in
      let target = root.appendingPathComponent(relative).resolvingSymlinksInPath()
      return target.path.hasPrefix(root.path + "/") && FileManager.default.fileExists(atPath: target.path)
    }
    restoringComposer = true
    draft = text
    contextFiles = split.files
    imageAttachments = images
    restoringComposer = false
    saveDraft()
    let sourceKey = fromComposerKey
    if var source = recoverySnapshot.composers[sourceKey] {
      if source.text == text { source.text = "" }
      if source.files == files { source.files = split.dropped }
      let carried = images.map { string($0, "id") }
      if source.images.map({ $0["id"] ?? "" }) == carried { source.images = [] }
      recoverySnapshot.composers[sourceKey] = source
      flushRecovery()
    }
    notice = split.dropped.isEmpty
      ? "Isolated workspace opened. The unsent draft is here."
      : "Isolated workspace opened. The unsent draft is here. Files that are not in this worktree stayed behind."
  }

  func refreshJobs() async {
    do {
      let nextJobs = try await engine.call("jobs.list") as? [[String: Any]] ?? []
      if !NSArray(array: jobs).isEqual(to: nextJobs) { jobs = nextJobs }
      let alerts = try await engine.call("notifications.poll", ["after": threadNotifications.cursor]) as? [String: Any] ?? [:]
      threadNotifications.consume(alerts, selected: selectedJob)
      if !projectID.isEmpty {
        let queuedProject = projectID
        let nextQueue = try await engine.call("queue.list", ["project": queuedProject]) as? [String: Any] ?? [:]
        guard queuedProject == projectID else { return }
        if !NSDictionary(dictionary: taskQueue).isEqual(to: nextQueue) { taskQueue = nextQueue }
        let recovery = try await engine.call("execution.recovery", ["project": queuedProject]) as? [String: Any] ?? [:]
        guard queuedProject == projectID else { return }
        if !NSDictionary(dictionary: executionRecovery).isEqual(to: recovery) { executionRecovery = recovery }
        let forks = try await engine.call("threads.fork.list", ["project": queuedProject]) as? [[String: Any]] ?? []
        guard queuedProject == projectID else { return }
        if !NSArray(array: forkWorkspaces).isEqual(to: forks) { forkWorkspaces = forks }
        if let queued = (taskQueue["items"] as? [[String: Any]] ?? []).first(where: {
          string($0, "state") == "running"
        }) {
          let job = string(queued, "job")
          if !job.isEmpty && job != lastQueueJob {
            lastQueueJob = job
            selectJob(job)
          }
        }
      }
      if !connectionTestJob.isEmpty,
        let test = jobs.first(where: { string($0, "id") == connectionTestJob }),
        !["running", "needs_approval", "queued", "cancelling"].contains(string(test, "status"))
      {
        let passed = string(test, "status") == "completed"
        if connectionTestRoute == provider + "\n" + model
          && connectionTestGeneration == credentialGeneration
        {
          verifiedRoute = passed ? connectionTestRoute : ""
          routeStatus = [
            "ready": passed, "state": passed ? "execution-verified" : "test-failed",
            "message": passed
              ? "Model test passed on this Mac."
              : "Model test did not complete successfully. Inspect the recorded run for details.",
          ]
        }
        connectionTestJob = ""
      }
    } catch {
      self.error = error.localizedDescription
    }
  }
  /// Reset composer routing only; running jobs retain their own connections.
  func resetThreadConnection() {
    connectionGeneration += 1
    connectionTestGeneration += 1
    checkingConnection = false
    restoreSelectedConnection = false
    harness = "disconnected"
    provider = ""
    model = ""
    agentModel = ""
    agentMode = ""
    agentConfig = [:]
    connectionMetadata = [:]
    routeStatus = [:]
    verifiedRoute = ""
  }

  func selectJob(_ id: String, restoreConnection: Bool = true,
    conversationID: String? = nil, recordHistory: Bool = true, targetSection: String? = nil) {
    // Reselecting the current recorded turn is navigation, not a reload. Keep
    // its transcript, connection and draft mounted. New-thread actions and
    // explicit restoration still perform the complete reset below.
    if !id.isEmpty, id == selectedJob, restoreConnection, recordHistory,
      !loadingConversationDraft, conversationID == nil || conversationID == composerConversationID {
      if let targetSection { section = targetSection }
      if showWelcome { showWelcome = false }
      return
    }
    saveDraft(flush: false)
    if recordHistory, id != selectedJob || targetSection.map({ $0 != section }) == true {
      recordNavigation(currentDestination)
    }
    let wasRestoring = restoringNavigation
    restoringNavigation = true
    defer { restoringNavigation = wasRestoring; persistDestination() }
    var nextNavigation = navigationState
    nextNavigation.closeExpandedDrawer()
    if nextNavigation != navigationState { navigationState = nextNavigation }
    detailGeneration += 1
    restoreSelectedConnection = restoreConnection
    conversationHistory = []
    earlierHistory = ""
    loadingHistory = false
    selectedJob = id
    let summary = projectJobs.first { string($0, "id") == id }
    let identity = conversationID ?? summary.map { string($0, "conversation_id", id) }
    loadingConversationDraft = !id.isEmpty && identity == nil
    restoreComposer(conversationID: identity ?? id)
    if let summary { rememberThreadTab(summary) }
    restoreSessionDestination()
    if let targetSection { section = targetSection }
    detail = [:]
    events = []
    eventCursor = 0
    hasMoreRunEvents = !id.isEmpty
    omittedRunEvents = 0
    eventStreamOpen = false
    activityLoadError = ""
    candidate = [:]
    if id.isEmpty && restoreConnection {
      resetThreadConnection()
    }
    if !id.isEmpty && connected { perform { await self.refreshDetail() } }
  }
  func refreshDetail() async {
    guard !selectedJob.isEmpty else { return }
    let id = selectedJob
    let generation = detailGeneration
    let requestKey = "\(generation):\(id)"
    guard detailRequests.insert(requestKey).inserted else { return }
    defer { detailRequests.remove(requestKey) }
    activityLoadError = ""
    do {
      // Bound work per refresh so selection, cancellation and typing stay responsive.
      // The poller continues draining even after the run becomes terminal.
      for _ in 0..<4 {
        try Task.checkCancellation()
        let cursor = eventCursor
        let result =
          try await engine.call("jobs.get", ["id": id, "after": cursor]) as? [String: Any] ?? [:]
        guard id == selectedJob, generation == detailGeneration else { return }
        guard string(result, "project") == projectID else {
          throw EngineError(message: "This run belongs to a different project. Choose a run in the current project.")
        }
        let page = try JobEventPage(result, after: cursor)
        let firstLoad = detail.isEmpty
        if firstLoad { rememberThreadTab(result) }
        if firstLoad, loadingConversationDraft, let identity = result["conversation_id"] as? String, !identity.isEmpty {
          loadingConversationDraft = false
          restoreComposer(conversationID: identity)
          restoreSessionDestination()
        }
        if firstLoad && restoreSelectedConnection,
          string(result, "kind") == "task", let request = result["request"] as? [String: Any] {
          restoreSelectedConnection = false
          chooseHarness(string(request, "harness", harness))
          provider = string(request, "provider", provider)
          model = string(request, "model", model)
          interactionMode = recoverySnapshot.composers[composerKey]?.mode ?? string(request, "interaction_mode", "code")
          let options = request["acp_options"] as? [String: Any] ?? [:]
          agentModel = string(options, "model")
          agentMode = string(options, "mode")
          agentConfig = options["config"] as? [String: String] ?? [:]
          savePreferences()
        }
        let previousStatus = string(detail, "status")
        var metadata = result
        metadata.removeValue(forKey: "events")
        if !NSDictionary(dictionary: detail).isEqual(to: metadata) { detail = metadata }
        eventCursor = page.nextSequence
        hasMoreRunEvents = page.hasMore
        eventStreamOpen = page.streamOpen
        if !page.events.isEmpty { events += page.events }
        if firstLoad && string(metadata, "kind") == "task" {
          await loadConversationHistory()
          guard id == selectedJob, generation == detailGeneration else { return }
        }
        if events.count > 1200 {
          omittedRunEvents += events.count - 1200
          events.removeFirst(events.count - 1200)
        }
        let status = string(metadata, "status")
        if status != previousStatus, ["completed", "failed", "cancelled"].contains(status) {
          scheduleProjectRefresh()
        }
        if !hasMoreRunEvents { break }
      }
    } catch {
      if id == selectedJob, generation == detailGeneration {
        // Keep the unread cursor and continuation state so Retry resumes here.
        activityLoadError = error.localizedDescription
      }
    }
  }
  private func scheduleProjectRefresh() {
    projectRefresh?.cancel()
    projectRefresh = Task {
      do { try await Task.sleep(for: .milliseconds(150)) } catch { return }
      await self.refreshGit()
      guard !Task.isCancelled else { return }
      self.loadFiles()
    }
  }
  func refreshGit() async {
    gitGeneration += 1
    let generation = gitGeneration
    let id = projectID
    guard !id.isEmpty else { return }
    do {
      let status = try await engine.call("git.status", ["project": id]) as? [String: Any] ?? [:]
      guard id == projectID, generation == gitGeneration, !Task.isCancelled else { return }
      if !NSDictionary(dictionary: git).isEqual(to: status) { git = status }
    } catch { if id == projectID, generation == gitGeneration, !Task.isCancelled { git = ["error": error.localizedDescription] } }
  }
  func refreshModels() async {
    do {
      let inventory = try await engine.call("models.list") as? [String: Any] ?? [:]
      models = inventory["models"] as? [[String: Any]] ?? []
      hardware = inventory["hardware"] as? [String: Any] ?? [:]
    } catch { self.error = error.localizedDescription }
  }
  func refreshDefinitions() async throws {
    let id = projectID
    guard !id.isEmpty else { return }
    let definitions =
      try await engine.call("harnesses.list", ["project": id]) as? [[String: Any]] ?? []
    let routes = try await engine.call("routes.list", ["project": id]) as? [[String: Any]] ?? []
    guard id == projectID else { return }
    harnesses = definitions + routes
  }
  func refreshProviders() async {
    do { providers = try await engine.call("providers.list") as? [[String: Any]] ?? [] } catch {
      self.error = error.localizedDescription
    }
  }
  func checkRoute() async {
    guard !connectionDisconnected else { routeStatus = [:]; return }
    if isManaged {
      let selected = harnesses.first(where: { string($0, "id") == harness }) ?? [:]
      routeStatus = [
        "state": "agent-managed",
        "message": selected["available"] as? Bool == true
          ? (isACP
            ? "ACP launcher detected. Sign-in is checked by the agent."
            : "Agent or server owns the model and tools. Access is checked when coding starts.")
          : string(selected, "issue", "Set up this agent before coding."),
      ]
      return
    }
    let route = provider + "\n" + model
    guard route != verifiedRoute else { return }
    let currentProvider = provider
    let currentModel = model
    do {
      let result =
        try await engine.call(
          "providers.check", ["provider": currentProvider, "model": currentModel, "project": projectID, "harness": harness]) as? [String: Any]
        ?? [:]
      if route == provider + "\n" + model { routeStatus = result }
    } catch {
      if route == provider + "\n" + model {
        routeStatus = ["ready": false, "message": error.localizedDescription]
      }
    }
  }
  func configureConnection(
    provider selectedProvider: String, model selectedModel: String, key: String, remember: Bool
  ) async throws {
    if !key.isEmpty {
      try await storeProviderCredential(selectedProvider, key: key, remember: remember)
    }
    chooseModelRoute(
      selectedProvider, selectedModel.trimmingCharacters(in: .whitespacesAndNewlines))
    await refreshProviders()
    await checkRoute()
  }
  func storeProviderCredential(_ selectedProvider: String, key: String, remember: Bool) async throws {
      _ = try await engine.call(
        "providers.credentials.set", ["provider": selectedProvider, "key": key])
      verifiedRoute = ""
      credentialGeneration += 1
      if remember {
        let store = credentialStore
        do {
          try await Task.detached {
            try store.save(
              selectedProvider, key: key.trimmingCharacters(in: .whitespacesAndNewlines))
          }.value
        } catch {
          await refreshProviders()
          throw EngineError(
            message:
              "The key is available for this session, but could not be remembered. Turn off Remember and retry. "
              + error.localizedDescription)
        }
        if !savedCredentialProviders.contains(selectedProvider) {
          savedCredentialProviders.append(selectedProvider)
        }
        _ = try await engine.call(
          "settings.set", ["key": "credential_providers", "value": savedCredentialProviders])
      } else if savedCredentialProviders.contains(selectedProvider) {
        let store = credentialStore
        try await Task.detached { try store.remove(selectedProvider) }.value
        savedCredentialProviders.removeAll { $0 == selectedProvider }
        _ = try await engine.call("settings.set", ["key": "credential_providers", "value": savedCredentialProviders])
      }
    await refreshProviders()
  }
  func forgetCredential(_ provider: String) async throws {
    let store = credentialStore
    try await Task.detached { try store.remove(provider) }.value
    _ = try await engine.call("providers.credentials.set", ["provider": provider, "key": NSNull()])
    credentialGeneration += 1
    savedCredentialProviders.removeAll { $0 == provider }
    _ = try await engine.call(
      "settings.set", ["key": "credential_providers", "value": savedCredentialProviders])
    verifiedRoute = ""
    await refreshProviders()
    await checkRoute()
  }
  func testConnection() {
    guard !busy, !anyActive, !projectID.isEmpty else { return }
    guard
      confirm(
        "Test this model?",
        "Send a short prompt through the no-tool harness using \(provider) / \(model). Your provider may charge for this request. This test uses the selected project’s engine context.",
        button: "Test model")
    else { return }
    busy = true
    let selectedProvider = provider
    let selectedModel = model
    let generation = credentialGeneration
    perform {
      defer { self.busy = false }
      let response =
        try await self.engine.call(
          "tasks.start",
          [
            "project": self.projectID, "harness": "no-tool", "provider": selectedProvider,
            "model": selectedModel, "prompt": "Reply with: SuperQode connection ready.",
            "command_id": UUID().uuidString,
          ]) as? [String: Any] ?? [:]
      self.connectionTestJob = string(response, "id")
      self.connectionTestRoute = selectedProvider + "\n" + selectedModel
      self.connectionTestGeneration = generation
      self.verifiedRoute = ""
      self.routeStatus = ["state": "testing", "message": "Testing model execution…"]
      self.selectJob(self.connectionTestJob)
      await self.refreshJobs()
    }
  }
  func start(_ method: String, extra: [String: Any] = [:]) {
    guard !busy, method == "tuning.start" || !connectionDisconnected else { return }
    busy = true
    perform {
      defer { self.busy = false }
      var params: [String: Any] = [
        "project": self.projectID, "harness": self.harness, "provider": self.provider,
        "model": self.model, "command_id": UUID().uuidString,
      ]
      for (key, value) in extra { params[key] = value }
      let result = try await self.engine.call(method, params) as? [String: Any] ?? [:]
      self.selectJob(string(result, "id"))
      await self.refreshJobs()
      self.savePreferences()
    }
  }
  var canSubmitDraft: Bool {
    connected && !loadingConversationDraft && !connectionDisconnected && !busy && !active
      && !checkingConnection && !projectID.isEmpty && (isManaged || !model.isEmpty)
      && detail["archived"] as? Bool != true
      && !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
  }
  func send(continueSession: Bool) {
    guard connected else { notice = "The local engine is offline. Your draft is kept; reconnect before sending."; return }

    guard detail["archived"] as? Bool != true else { notice = "Restore this archived thread before continuing."; return }
    guard !loadingConversationDraft, !connectionDisconnected, !busy, !active, !checkingConnection, !projectID.isEmpty,
      (isManaged || !model.isEmpty), !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
    if interactionMode == "plan" && !enforcesSessionControls {
      notice = "Plan mode applies to a SuperQode harness that can enforce it. This agent uses its own tools and permissions."
      return
    }
    let submittedDraft = draft
    let submittedKey = composerKey
    let submittedConversation = composerConversationID
    let submittedRecord = composerRecovery
    let submittedFiles = contextFiles
    let submittedImages = imageAttachments.map { string($0, "id") }
    let submittedPermission = permissionMode
    var extra: [String: Any] = [
      "prompt": submittedDraft, "context_files": submittedFiles, "interaction_mode": interactionMode,
      "context_window": contextWindow.isEmpty ? 0 : Int(contextWindow) ?? -1,
      "enable_summarization": summarizeContext,
      "image_ids": submittedImages,
    ]
    if enforcesSessionControls { extra["permission_mode"] = submittedPermission }
    if isACP {
      extra["acp_options"] = [
        "model": agentModel, "mode": agentMode, "config": agentConfig.filter { !$0.value.isEmpty },
      ]
    }
    if continueSession {
      extra["parent_id"] =
        string(detail, "kind") == "compaction"
        ? string(detail["result"] as? [String: Any] ?? [:], "source_job") : selectedJob
    }
    let submittedProject = projectID
    var params: [String: Any] = [
      "project": submittedProject, "harness": harness, "provider": provider,
      "model": model, "command_id": UUID().uuidString,
    ]
    params.merge(extra) { _, value in value }
    busy = true
    perform {
      defer { self.busy = false }
      let result = try await self.engine.call("tasks.start", params) as? [String: Any] ?? [:]
      let id = string(result, "id")
      guard !id.isEmpty else { throw EngineError(message: "The engine did not accept this message.") }
      self.clearAcceptedSubmission(key: submittedKey, submitted: submittedRecord)
      // Acceptance belongs to the submitted conversation even if navigation changed.
      let destination = continueSession ? submittedConversation : id
      if !continueSession {
        PermissionMemory.commitNewConversation(
          submittedPermission, project: submittedProject, conversation: destination,
          defaults: self.preferences)
      } else {
        PermissionMemory.store(
          submittedPermission,
          composerKey: WorkspaceRecoverySnapshot.key(
            project: submittedProject, conversation: destination),
          defaults: self.preferences)
      }
      guard self.projectID == submittedProject, self.composerKey == submittedKey else {
        await self.refreshJobs()
        return
      }
      // Clear only the accepted submission, preserving edits typed while starting.
      if self.draft == submittedDraft { self.draft = ""; self.saveDraft() }
      if self.contextFiles == submittedFiles { self.contextFiles = [] }
      if self.imageAttachments.map({ string($0, "id") }) == submittedImages {
        self.imageAttachments = []
      }
      let keptNewerDraft = !continueSession && !self.draft.isEmpty && self.draft != submittedDraft
      // Keep a newer new-task draft visible if the user typed while acceptance was pending.
      if keptNewerDraft {
        self.permissionMode = "ask"
        self.notice = "Task started. Your newer draft is still in New conversation."
        await self.refreshJobs()
        return
      }
      self.selectJob(id, restoreConnection: false, conversationID: continueSession ? submittedConversation : id)
      await self.refreshDetail()
      await self.refreshJobs()
      self.savePreferences()
    }
  }
  func queueAction(_ method: String, extra: [String: Any] = [:]) {
    perform {
      var params = extra
      params["project"] = self.projectID
      _ = try await self.engine.call(method, params)
      await self.refreshJobs()
    }
  }
  func enqueueDraft() {
    guard !connectionDisconnected else { notice = "Connect an agent before adding a task."; return }
    guard !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
    if interactionMode == "plan" && !enforcesSessionControls {
      notice = "Plan mode applies to a SuperQode harness that can enforce it. This agent uses its own tools and permissions."
      return
    }
    var extra: [String: Any] = [
      "prompt": draft, "harness": harness, "provider": provider, "model": model,
      "interaction_mode": interactionMode,
      "context_files": contextFiles, "image_ids": imageAttachments.map { string($0, "id") },
      "context_window": contextWindow.isEmpty ? 0 : Int(contextWindow) ?? -1,
      "enable_summarization": summarizeContext,
      "acp_options": ["model": agentModel, "mode": agentMode, "config": agentConfig],
    ]
    if enforcesSessionControls { extra["permission_mode"] = permissionMode }
    queueAction("queue.add", extra: extra)
    notice = "Adding task to the project queue"
  }
  func attachImages() {
    let panel = NSOpenPanel()
    panel.allowedContentTypes = [.image]
    panel.allowsMultipleSelection = true
    panel.prompt = "Attach images"
    guard panel.runModal() == .OK else { return }
    let paths = panel.urls.map(\.path)
    let sourceComposerKey = composerKey
    perform {
      for path in paths { try await self.stageImage(path, for: sourceComposerKey) }
    }
  }
  func stageImage(_ path: String, for sourceComposerKey: String) async throws {
    guard composerKey == sourceComposerKey else {
      notice = "The draft changed while loading the image. Attach it again in the intended thread."
      return
    }
    guard imageAttachments.count < 4 else { throw EngineError(message: "Attach up to four images.") }
    let item = try await engine.call("images.stage", ["path": path]) as? [String: Any] ?? [:]
    guard composerKey == sourceComposerKey else {
      notice = "The draft changed while loading the image. Attach it again in the intended thread."
      return
    }
    guard imageAttachments.count < 4 else { throw EngineError(message: "Attach up to four images.") }
    imageAttachments.append(item)
  }

  func pasteImage() {
    guard let image = NSImage(pasteboard: .general), let data = image.tiffRepresentation,
      let bitmap = NSBitmapImageRep(data: data),
      let png = bitmap.representation(using: .png, properties: [:])
    else {
      error = "No image is available on the clipboard."
      return
    }
    let path = FileManager.default.temporaryDirectory.appendingPathComponent(
      UUID().uuidString + ".png")
    let sourceComposerKey = composerKey
    perform {
      try png.write(to: path, options: .atomic)
      defer { try? FileManager.default.removeItem(at: path) }
      try await self.stageImage(path.path, for: sourceComposerKey)
    }
  }
  func attachFiles() {
    let panel = NSOpenPanel()
    panel.directoryURL = URL(fileURLWithPath: string(project, "path"))
    panel.canChooseDirectories = false
    panel.allowsMultipleSelection = true
    panel.prompt = "Attach project files"
    guard panel.runModal() == .OK else { return }
    let root = URL(fileURLWithPath: string(project, "path")).resolvingSymlinksInPath().path + "/"
    for url in panel.urls {
      let path = url.resolvingSymlinksInPath().path
      guard path.hasPrefix(root) else {
        error = "Attach files from the current project."
        continue
      }
      let relative = String(path.dropFirst(root.count))
      if !contextFiles.contains(relative) { contextFiles.append(relative) }
    }
  }
  func consumeFileDrop(_ providers: [NSItemProvider]) -> Bool {
    guard !projectID.isEmpty else { return false }
    let urls = providers.filter { $0.canLoadObject(ofClass: URL.self) }
    guard !urls.isEmpty else { return false }
    let sourceComposerKey = composerKey
    for provider in urls {
      _ = provider.loadObject(ofClass: URL.self) { object, _ in
        guard let url = object, url.isFileURL else { return }
        DispatchQueue.main.async {
          guard self.composerKey == sourceComposerKey else {
            self.notice = "The draft changed while loading the drop. Attach it again in the intended thread."
            return
          }
          self.attachDroppedFile(url.path)
        }
      }
    }
    return true
  }
  func attachDroppedFile(_ path: String) {
    var directory: ObjCBool = false
    guard FileManager.default.fileExists(atPath: path, isDirectory: &directory), !directory.boolValue else { return }
    let kind = (path as NSString).pathExtension.lowercased()
    if ["png", "jpg", "jpeg", "gif", "webp", "tif", "tiff", "heic"].contains(kind) {
      let sourceComposerKey = composerKey
      perform { try await self.stageImage(path, for: sourceComposerKey) }
      return
    }
    let root = URL(fileURLWithPath: string(project, "path")).resolvingSymlinksInPath().path + "/"
    let resolved = URL(fileURLWithPath: path).resolvingSymlinksInPath().path
    guard resolved.hasPrefix(root) else {
      error = "Attach files from the current project."
      return
    }
    let relative = String(resolved.dropFirst(root.count))
    if !contextFiles.contains(relative) { contextFiles.append(relative) }
  }
  var canSteer: Bool {
    guard string(detail, "status") == "running",
      let event = events.last(where: { string($0, "type") == "control_capabilities" }),
      let data = event["data"] as? [String: Any]
    else { return false }
    return data["steer"] as? Bool == true
  }
  func steerDraft() {
    let id = selectedJob
    let text = draft
    perform {
      _ = try await self.engine.call("jobs.steer", ["id": id, "text": text])
      self.notice = "Steering instruction sent. Check the stream for runtime acknowledgement."
    }
  }
  func approve(_ requestID: String, allow: Bool, always: Bool = false) {
    let id = selectedJob
    perform {
      _ = try await self.engine.call(
        "jobs.approve",
        ["id": id, "request_id": requestID, "allow": allow, "scope": always ? "always" : "once"])
      await self.refreshDetail()
    }
  }
  func cancel() {
    let id = selectedJob
    perform {
      _ = try await self.engine.call("jobs.cancel", ["id": id])
      await self.refreshDetail()
    }
  }
  func confirm(_ title: String, _ message: String, button: String = "Continue") -> Bool {
    let alert = NSAlert()
    alert.messageText = title
    alert.informativeText = message
    alert.addButton(withTitle: button)
    alert.addButton(withTitle: "Cancel")
    return alert.runModal() == .alertFirstButtonReturn
  }
  func gitAction(_ method: String, message: String = "") {
    guard
      confirm(
        method == "git.stage" ? "Stage tracked changes?" : "Create local commit?",
        method == "git.stage"
          ? "Stage modifications and deletions of tracked files in this project." : message)
    else { return }
    perform {
      _ = try await self.engine.call(method, ["project": self.projectID, "message": message])
      await self.refreshGit()
    }
  }
  func inspectCandidate() {
    let id = selectedJob
    perform {
      let result =
        try await self.engine.call("optimizations.inspect", ["id": id]) as? [String: Any] ?? [:]
      if id == self.selectedJob { self.candidate = result }
    }
  }
  func saveCandidate() {
    let id = selectedJob
    let digest = string(candidate, "digest")
    guard
      confirm(
        "Save candidate harness?",
        "Create a new project harness from the validated candidate. Review the diff before continuing.",
        button: "Save harness")
    else { return }
    perform {
      let result =
        try await self.engine.call("harnesses.save_candidate", ["id": id, "digest": digest])
        as? [String: Any] ?? [:]
      self.notice = string(result, "message")
      self.harnesses =
        try await self.engine.call("harnesses.list", ["project": self.projectID])
        as? [[String: Any]] ?? []
      let routes =
        try await self.engine.call("routes.list", ["project": self.projectID]) as? [[String: Any]]
        ?? []
      self.harnesses += routes
    }
  }
  func exportEvidence() {
    guard !selectedJob.isEmpty else { return }
    let id = selectedJob
    perform {
      var after = 0
      var all: [[String: Any]] = []
      var record: [String: Any] = [:]
      while true {
        record =
          try await self.engine.call("jobs.get", ["id": id, "after": after]) as? [String: Any]
          ?? [:]
        let page = try JobEventPage(record, after: after)
        all += page.events
        after = page.nextSequence
        if !page.hasMore { break }
      }
      record["events"] = all
      let panel = NSSavePanel()
      panel.nameFieldStringValue = "superqode-\(id.prefix(12)).json"
      panel.allowedContentTypes = [.json]
      if panel.runModal() == .OK, let url = panel.url {
        try JSONSerialization.data(withJSONObject: record, options: [.prettyPrinted, .sortedKeys])
          .write(to: url, options: .atomic)
        self.notice =
          "Evidence exported. Review it before sharing; task output can contain project content."
      }
    }
  }
  var mentionQuery: String? { ComposerMentions.query(in: mentionPrefix) }
  var mentionMatches: [String] {
    guard let query = mentionQuery?.lowercased() else { return [] }
    var matches: [String] = []
    for path in files where query.isEmpty || path.lowercased().contains(query) {
      matches.append(path)
      if matches.count == 8 { break }
    }
    return matches
  }
  func noteComposerCursor(_ prefix: String) {
    guard prefix != mentionPrefix else { return }
    mentionPrefix = prefix
  }
  func acceptTopMentionIfNeeded() -> Bool {
    guard !ComposerMentions.isComplete(text: draft, prefix: mentionPrefix, paths: files),
      let path = mentionMatches.first else { return false }
    acceptMention(path)
    return true
  }
  func acceptMention(_ path: String) {
    let next = ComposerMentions.insert(text: draft, prefix: mentionPrefix, path: path)
    guard next != draft else { return }
    draft = next
    if !contextFiles.contains(path) { contextFiles.append(path) }
    mentionPrefix = ""
  }
  func loadRepositoryLayout() async {
    let id = projectID
    guard !id.isEmpty else {
      repositoryPanels = []
      repositoryLayoutName = ""
      return
    }
    do {
      let layout = try await engine.call("creator.layout", ["project": id]) as? [String: Any] ?? [:]
      guard id == projectID else { return }
      let raw = layout["panels"] as? [String]
        ?? (layout["panels"] as? [Any])?.compactMap { $0 as? String } ?? []
      repositoryLayoutName = string(layout, "name")
      repositoryPanels = RepositoryLayout.pinned(raw)
    } catch {
      guard id == projectID else { return }
      repositoryPanels = []
      repositoryLayoutName = ""
    }
  }
  func loadFiles() {
    filesGeneration += 1
    let generation = filesGeneration
    let id = projectID
    guard !id.isEmpty else { return }
    perform {
      let files = try await self.engine.call("files.list", ["project": id]) as? [String] ?? []
      guard id == self.projectID, generation == self.filesGeneration else { return }
      if self.files != files { self.files = files }
    }
  }
  func shutdown() {
    saveDraft()
    flushRecovery()
    poller?.cancel()
    projectRefresh?.cancel()
    terminals.stopAll()
    engine.stop()
  }

  /// Runs actual pipe commands against a disposable project, without calling a model.
  func smokeTest() async {
    var report: [String: Any] = ["native": true, "ui": "SwiftUI", "project": projectID]
    do {
      guard !projectID.isEmpty else { throw EngineError(message: "Smoke test requires --project") }
      let store = credentialStore
      defer { try? store.remove("openai") }
      try await configureConnection(
        provider: "openai", model: "gpt-4o-mini", key: "native-keychain-smoke-initial",
        remember: true)
      guard try store.read("openai") == "native-keychain-smoke-initial",
        savedCredentialProviders.contains("openai")
      else { throw EngineError(message: "Native Keychain save/read failed") }
      try await configureConnection(
        provider: "openai", model: "gpt-4o-mini", key: "native-keychain-smoke-updated",
        remember: true)
      guard try store.read("openai") == "native-keychain-smoke-updated" else {
        throw EngineError(message: "Native Keychain update failed")
      }
      try await forgetCredential("openai")
      guard try store.read("openai") == nil, !savedCredentialProviders.contains("openai") else {
        throw EngineError(message: "Native Keychain deletion failed")
      }
      try await configureConnection(
        provider: "openai", model: "gpt-4o-mini", key: "native-keychain-smoke-session",
        remember: false)
      guard try store.read("openai") == nil else {
        throw EngineError(message: "Session-only credential was persisted")
      }
      report["keychain"] = "passed; save/read/update/delete; isolated test item removed"
      report["session_credential"] = "configured without Keychain persistence"
      let openedFile =
        try await engine.call("files.read", ["project": projectID, "path": "README.md"])
        as? [String: Any] ?? [:]
      _ = try await engine.call(
        "files.write",
        [
          "project": projectID, "path": "README.md", "digest": string(openedFile, "digest"),
          "text": "# Native desktop smoke project\nEdited through the native file protocol.\n",
        ])
      let readBack =
        try await engine.call("files.read", ["project": projectID, "path": "README.md"])
        as? [String: Any] ?? [:]
      guard string(readBack, "text").contains("Edited through the native file protocol") else {
        throw EngineError(message: "Native file save failed")
      }
      report["file_edit"] = "passed; revision-guarded save and read-back"
      _ = try await engine.call(
        "files.create",
        ["project": projectID, "path": "Sources/New.swift", "text": "let ready = true\n"])
      _ = try await engine.call(
        "git.stage_file", ["project": projectID, "path": "Sources/New.swift"])
      _ = try await engine.call(
        "git.unstage_file", ["project": projectID, "path": "Sources/New.swift"])
      report["file_create_unstage"] = "passed; source file retained"
      let tools = try await engine.call("tools.catalog") as? [[String: Any]] ?? []
      guard tools.count > 100 else {
        throw EngineError(message: "Advanced workflow catalog missing")
      }
      report["native_tools"] = tools.count
      terminals.start(projectID, path: string(project, "path"), smoke: true)
      for _ in 0..<100 {
        if terminals.output(projectID).contains("native-project-pty") { break }
        try await Task.sleep(for: .milliseconds(50))
      }
      guard terminals.output(projectID).contains("native-project-pty") else {
        throw EngineError(message: "Native terminal PTY failed")
      }
      guard let terminalBackground = terminals.view(projectID)?.nativeBackgroundColor.usingColorSpace(.sRGB),
        terminalBackground.redComponent == 0, terminalBackground.greenComponent == 0,
        terminalBackground.blueComponent == 0 else { throw EngineError(message: "Terminal background is not pure black") }
      report["project_terminal"] = "passed; actual local PTY output on pure-black background"

      let queued =
        try await engine.call(
          "queue.add",
          [
            "project": projectID, "prompt": "Queued smoke draft", "harness": "core",
            "provider": "ollama", "model": "not-called",
          ]) as? [String: Any] ?? [:]
      let queue =
        try await engine.call("queue.list", ["project": projectID]) as? [String: Any] ?? [:]
      guard (queue["items"] as? [[String: Any]] ?? []).count == 1,
        queue["running"] as? Bool == false
      else { throw EngineError(message: "Task queue started without consent") }
      _ = try await engine.call("queue.remove", ["project": projectID, "id": string(queued, "id")])
      report["task_queue"] = "passed; durable draft waits for explicit start"

      guard NSImage(named: "BrandMark") != nil else {
        throw EngineError(message: "Bundled SuperQode brand asset is missing")
      }
      report["branding"] = "passed; native asset catalog brand mark loaded"
      for name in Set(BundledAgentIcons.assets.values) {
        guard NSImage(named: name) != nil else { throw EngineError(message: "Bundled agent icon missing: " + name) }
      }
      report["agent_icons"] = "passed; all \(Set(BundledAgentIcons.assets.values).count) bundled ACP glyphs loaded"
      report["performance"] = try await verifyResponsiveness()
      let coldNavigation = try await smokeNavigationResponsiveness()
      report["navigation_cold_performance"] = coldNavigation
      try requireResponsiveNavigation(coldNavigation)
      report["coding_inputs"] = try verifyCodingInputs()
      report["source_editor"] = try await verifySourceEditor()
      report["centered_dialogs"] = try await verifyCenteredDialogs()
      if let index = ProcessInfo.processInfo.arguments.firstIndex(of: "--snapshot-dir"),
        ProcessInfo.processInfo.arguments.count > index + 1
      {
        let destination = URL(fileURLWithPath: ProcessInfo.processInfo.arguments[index + 1])
        try captureLearningViews(directory: destination)
      }
      report["getting_started"] =
        "passed; native welcome, project steps and learning guide rendered"

      guard Sections.names.count == Sections.icons.count, Sections.names.contains("Checkpoints"),
        Sections.names.contains("Terminal")
      else { throw EngineError(message: "Native destination mapping is incomplete") }

      guard !showWelcome else {
        throw EngineError(message: "Opening a project did not enter its workspace")
      }
      let existingDraft = draft
      showWelcome = true
      try await openStartupProject(arguments: ["SuperQode"])
      try await Task.sleep(for: .milliseconds(350))
      guard showWelcome, draft == existingDraft else {
        throw EngineError(message: "Loading startup recovery navigated away from Welcome")
      }
      try await open(string(project, "path"))
      guard !showWelcome, draft == existingDraft else {
        throw EngineError(message: "Reopening a project from Welcome did not enter its workspace with its draft")
      }
      report["welcome_navigation"] = "passed; startup navigation stays on Welcome until an explicit project open, which enters the workspace and preserves its draft"
      let visible = conversationEvents(
        [
          ["type": "stage"], ["type": "approval"], ["type": "error"],
          ["type": "harness_event", "data": ["event": "tool_call"]],
          ["type": "harness_event", "data": ["event": "model_request"]],
          ["type": "future_event"],
          ["type": "output", "data": ["text": "command stdout"]],
        ], includeDetails: false)
      guard visible.map({ string($0, "type") }) == ["approval", "error", "activity_group"],
        let activity = (visible.last?["data"] as? [String: Any])?["events"] as? [[String: Any]],
        activity.count == 5
      else { throw EngineError(message: "Conversation activity grouping lost events or hid an approval/error") }
      let coloured = NSAttributedString(highlightedSource("def greet():\n    return 'hello' # note", language: "python", dark: true, highContrast: false))
      var syntaxColours = Set<String>()
      coloured.enumerateAttribute(.foregroundColor, in: NSRange(location: 0, length: coloured.length)) { value, _, _ in
        if let color = value as? NSColor { syntaxColours.insert(color.description) }
      }
      let ordered = conversationEvents([
        ["type": "harness_event", "data": ["event": "tool_call"]],
        ["type": "answer", "data": ["text": "# Final response"]],
        ["type": "output", "data": ["text": "tool stdout"]],
      ], includeDetails: false)
      guard syntaxColours.count >= 4,
        ordered.map({ string($0, "type") }) == ["output", "activity_group"]
      else { throw EngineError(message: "Code colouring or activity footer order failed") }
      report["response_presentation"] = "passed; code has distinct token colours; activity stays after responses with raw tool logs preserved"
      let recents = groupedRecentRuns([
        ["id": "root", "kind": "task", "conversation_id": "root", "updated": 1.0],
        ["id": "follow-up", "kind": "task", "conversation_id": "root", "conversation_title": "Original request", "updated": 3.0],
        ["id": "other", "kind": "task", "conversation_id": "other", "updated": 2.0],
      ])
      func toolEvent(_ name: String, _ payload: [String: Any]) -> [String: Any] {
        ["type": "harness_event", "data": ["event": name, "payload": payload]]
      }
      var live = [toolEvent("tool_call", ["toolCallId": "a", "title": "Shell", "rawInput": ["command": "pytest -q"], "status": "in_progress"])]
      guard currentAgentActivity(live) == "pytest -q" else { throw EngineError(message: "Live command was not shown") }
      live.append(toolEvent("tool_update", ["toolCallId": "a", "status": "in_progress"]))
      live.append(toolEvent("tool_call", ["tool_call_id": "b", "arguments": ["command": "git diff"]]))
      guard currentAgentActivity(live) == "git diff" else { throw EngineError(message: "Latest command did not replace the previous line") }
      live.append(toolEvent("tool_result", ["tool_call_id": "b"]))
      guard currentAgentActivity(live) == "pytest -q" else { throw EngineError(message: "Pending command was lost after another tool finished") }
      live.append(toolEvent("tool_update", ["toolCallId": "a", "status": "completed"]))
      guard currentAgentActivity(live) == "Finished · pytest -q", recents.count == 2,
        string(recents[0], "id") == "follow-up", string(recents[0], "conversation_title") == "Original request"
      else { throw EngineError(message: "Completed commands were mislabeled or follow-ups duplicated recent rows") }
      report["conversation_recents_live_activity"] = "passed; one latest turn per parent conversation; single current command handles sparse ACP updates and completed tools"
      let installFixture: [String: Any] = ["route": ["id": "acp:install-check", "available": false],
        "install": ["command": "example install", "reference": "fixture"]]
      guard connectionInstallPlan(installFixture, routes: []) != nil,
        connectionInstallPlan(installFixture, routes: [["id": "acp:install-check", "available": true]]) == nil,
        connectionInstallPlan(["route": ["id": "acp:installed", "available": true], "install": ["command": "unused"]], routes: []) == nil
      else { throw EngineError(message: "Installed agents still show installation instructions") }
      report["installation_visibility"] = "passed; missing agent has setup instructions; installed and freshly installed agents hide them"
      let blocks = responseBlocks("# Heading\n\nA **bold** paragraph.\n\n- First\n\n```python\nprint('hello')\n```\n\n| A | B |\n| --- | --- |\n| 1 | 2 |")
      guard blocks == [.heading(1, "Heading"), .paragraph("A **bold** paragraph."), .item("•", "First"), .code("python", "print('hello')"), .table([["A", "B"], ["1", "2"]])],
        responseBlocks("```swift\nlet x = 1") == [.code("swift", "let x = 1")],
        String(responseInline("**Bold** and `code`").characters) == "Bold and code"
      else { throw EngineError(message: "Response Markdown rendering failed") }
      let selectedHarness = harness
      let selectedProvider = provider
      let selectedModel = model
      disconnectConnection()
      guard connectionDisconnected, model.isEmpty, agentModel.isEmpty else {
        throw EngineError(message: "Disconnect retained an active model selection")
      }
      chooseHarness(selectedHarness)
      provider = selectedProvider
      model = selectedModel
      savePreferences()
      report["conversation"] = "passed; rendered Markdown blocks and unfinished code fences; grouped activity preserves all events; approvals/errors visible; disconnect/reconnect clears selection"

      if let index = ProcessInfo.processInfo.arguments.firstIndex(of: "--snapshot-dir"),
        ProcessInfo.processInfo.arguments.count > index + 1 {
        let sample = "# Ready to build\n\nThe response now uses **readable formatting**, `inline code`, and [useful links](https://superqode.dev).\n\n## What changed\n\n- One clear conversation\n- Selectable, highlighted source code\n- Tool activity stays in one expandable section\n\n```python\ndef greet(name: str) -> str:\n    # Keep the greeting simple\n    return f\"Hello, {name}!\"\n\nassert greet('Ada') == 'Hello, Ada!'\n```\n\n> Review changes before committing them.\n\n| Check | Result |\n| --- | --- |\n| Formatting | Ready |\n| Code selection | Available |"
        for dark in [false, true] {
          let host = NSHostingView(rootView: VStack(alignment: .leading, spacing: 14) {
            AgentResponseView(text: sample)
            AgentWorkingCard(status: "running", activity: currentAgentActivity([toolEvent("tool_call", ["tool_name": "bash", "args": ["command": "uv run pytest -q tests/test_desktop_studio_execution.py --disable-warnings"]])]))
          }.padding(24)
            .background(Color.qPanel).environment(\.colorScheme, dark ? .dark : .light))
          host.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
          host.frame = NSRect(x: 0, y: 0, width: 780, height: 1050)
          let previewWindow = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
          previewWindow.appearance = host.appearance
          previewWindow.contentView = host
          previewWindow.orderFront(nil)
          defer { previewWindow.orderOut(nil); previewWindow.contentView = nil }
          host.layoutSubtreeIfNeeded()
          try await Task.sleep(for: .milliseconds(250))
          host.displayIfNeeded()
          guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
            throw EngineError(message: "Response renderer could not produce a native preview")
          }
          host.cacheDisplay(in: host.bounds, to: bitmap)
          try bitmap.representation(using: .png, properties: [:])?.write(to:
            URL(fileURLWithPath: ProcessInfo.processInfo.arguments[index + 1])
              .appendingPathComponent(dark ? "response-dark.png" : "response-light.png"))
        }
      }
      let originalSection = section
      section = "Models"
      section = "Harness Hub"
      goBack()
      guard section == "Models" else { throw EngineError(message: "Back navigation failed") }
      section = originalSection
      navigationHistory = []
      report["navigation"] = "passed; previous section restored"
      for menu in ["root", "vendors", "protocols", "harness", "models", "build"] {
        let result =
          try await engine.call("connect.menu", ["project": projectID, "menu": menu])
          as? [String: Any] ?? [:]
        guard !(result["rows"] as? [[String: Any]] ?? []).isEmpty else {
          throw EngineError(message: "Connect menu is empty: " + menu)
        }
      }
      report["connect_menus"] =
        "passed; shared root, subscriptions, protocols, harness, model and build menus"
      if let index = ProcessInfo.processInfo.arguments.firstIndex(of: "--snapshot-dir"),
        ProcessInfo.processInfo.arguments.count > index + 1
      {
        let destination = URL(fileURLWithPath: ProcessInfo.processInfo.arguments[index + 1])
        for page in [
          "menu:root", "menu:vendors", "menu:protocols", "source:key", "configure:wizard",
          "configure:rlm", "configure:rlm-routing", "systemone",
          "runtimes", "acp", "acp-clients", "custom-acp", "acp-setup-preview", "thread-identities-preview", "thread-identities-preview-light",
        ] {
          try await captureConnectionPage(page, directory: destination)
        }
        try await captureConnectionInspector(directory: destination)
      }
      report["harnesses"] = harnesses.count
      report["hub"] = hub.count
      report["packs"] = packs.count
      guard !harnesses.isEmpty, !hub.isEmpty, !packs.isEmpty else {
        throw EngineError(message: "Missing engine catalogs")
      }
      let result =
        try await engine.call(
          "checks.start",
          [
            "project": projectID, "command": "printf native-swift-smoke",
            "command_id": UUID().uuidString,
          ]) as? [String: Any] ?? [:]
      let id = string(result, "id")
      selectJob(id)
      for _ in 0..<100 {
        await refreshDetail()
        if string(detail, "status") == "completed" { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      guard string(detail, "status") == "completed", pretty(events).contains("native-swift-smoke")
      else { throw EngineError(message: "Native command stream failed") }
      report["check"] = "passed"
      let setup =
        try await engine.call(
          "evaluations.start",
          [
            // Project opening now intentionally clears the composer route.
            // This setup-only check chooses its fixture harness explicitly.
            "project": projectID, "harness": "no-tool", "provider": "ollama",
            "model": "native-setup-only", "tasks": string(packs[0], "path"), "live": false,
            "command_id": UUID().uuidString,
          ]) as? [String: Any] ?? [:]
      let evaluationID = string(setup, "id")
      selectJob(evaluationID)
      for _ in 0..<100 {
        await refreshDetail()
        if string(detail, "status") == "completed" { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      let evaluation = detail["result"] as? [String: Any] ?? [:]
      guard string(detail, "status") == "completed", evaluation["live"] as? Bool == false,
        !(evaluation["variants"] as? [[String: Any]] ?? []).isEmpty
      else { throw EngineError(message: "Native setup evaluation failed") }
      report["evaluation"] = "passed; model execution skipped"
      let diagnostics = try await engine.call("evals.inspect", [
        "project": projectID, "tasks": string(packs[0], "path"), "split": "all",
      ]) as? [String: Any] ?? [:]
      let experiments = try await engine.call("experiments.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard (diagnostics["task_count"] as? Int ?? 0) > 0,
        !string(diagnostics, "tasks_hash").isEmpty,
        experiments.contains(where: { string($0, "id") == evaluationID })
      else { throw EngineError(message: "Native experiment diagnostics or history failed") }
      report["experiment_workflow"] = "passed; diagnostics and durable project history"
      let practice = try await engine.call("tuning.prepare", [
        "project": projectID, "practice": true,
      ]) as? [String: Any] ?? [:]
      let practiceID = string(practice, "id")
      let practiceRows = practice["review"] as? [[String: Any]] ?? []
      let practiceLabels = practice["labels"] as? [String] ?? []
      guard practice["synthetic_practice"] as? Bool == true,
        !practiceID.isEmpty, let firstExample = practiceRows.first,
        let firstLabel = practiceLabels.first else {
        throw EngineError(message: "Offline tuning practice did not prepare a review batch")
      }
      let judged = try await engine.call("tuning.label", [
        "project": projectID, "id": practiceID, "revision": string(practice, "revision"),
        "example": string(firstExample, "id"), "label": firstLabel,
        "rationale": "Local native release fixture",
      ]) as? [String: Any] ?? [:]
      guard (judged["review"] as? [[String: Any]] ?? []).count == practiceRows.count - 1 else {
        throw EngineError(message: "Offline tuning judgment was not saved")
      }
      do {
        _ = try await engine.call("tuning.start", [
          "project": projectID, "id": practiceID, "revision": string(judged, "revision"),
          "stage": "optimize", "live": true,
        ])
        throw EngineError(message: "Practice unexpectedly authorized a live optimizer")
      } catch let failure as EngineError {
        guard failure.message.contains("Practice is offline only") else { throw failure }
      }
      report["tuning_practice"] = "passed; credential-free prepare, saved judgment, live execution rejected"
      if let index = ProcessInfo.processInfo.arguments.firstIndex(of: "--snapshot-dir"),
        ProcessInfo.processInfo.arguments.count > index + 1 {
        let host = NSHostingView(rootView: TuningView(experimentID: practiceID)
          .environmentObject(self).environment(\.colorScheme, .dark).background(Color.black))
        host.frame = NSRect(x: 0, y: 0, width: 1000, height: 1000)
        let window = NSWindow(contentRect: host.frame, styleMask: [.borderless], backing: .buffered, defer: false)
        window.appearance = NSAppearance(named: .darkAqua)
        window.contentView = host
        window.orderFront(nil)
        defer { window.orderOut(nil); window.contentView = nil }
        try await Task.sleep(for: .seconds(1))
        host.layoutSubtreeIfNeeded()
        host.displayIfNeeded()
        guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else {
          throw EngineError(message: "Native tuning screen could not render")
        }
        host.cacheDisplay(in: host.bounds, to: bitmap)
        guard let png = bitmap.representation(using: .png, properties: [:]) else {
          throw EngineError(message: "Native tuning screen could not encode")
        }
        try png.write(to: URL(fileURLWithPath: ProcessInfo.processInfo.arguments[index + 1])
          .appendingPathComponent("tuning-practice.png"))
      }
      do {
        _ = try await engine.call("files.read", ["project": projectID, "path": "../outside.txt"])
        throw EngineError(message: "File boundary was not enforced")
      } catch let failure as EngineError {
        guard failure.message != "File boundary was not enforced" else { throw failure }
        report["file_boundary"] = "passed"
      }
      chooseHarness(ProcessInfo.processInfo.environment["SUPERQODE_SMOKE_HARNESS"] ?? "no-tool")
      provider = "openai"
      model = "gpt-4o-mini"
      draft = "Reply using the local native test fixture."
      let previousJob = selectedJob
      send(continueSession: false)
      for _ in 0..<150 {
        if !busy && selectedJob != previousJob { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      guard draft.isEmpty, selectedJob != previousJob else {
        throw EngineError(message: "Sending did not clear the submitted composer and select its conversation")
      }
      let taskID = selectedJob
      for _ in 0..<150 {
        await refreshDetail()
        if !active && !detail.isEmpty { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      guard string(detail, "status") == "completed", pretty(events).contains("Native task fixture")
      else { throw EngineError(message: "Native model stream failed: " + pretty(detail["result"])) }
      let session = string(detail["result"] as? [String: Any] ?? [:], "session_id")
      draft = "Continue the same native session."
      send(continueSession: true)
      for _ in 0..<150 {
        if !busy && selectedJob != taskID { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      guard draft.isEmpty, selectedJob != taskID else {
        throw EngineError(message: "Follow-up message did not leave the composer")
      }
      for _ in 0..<150 {
        await refreshDetail()
        if !active && !detail.isEmpty { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      guard string(detail, "status") == "completed",
        session == string(detail["result"] as? [String: Any] ?? [:], "session_id")
      else { throw EngineError(message: "Native task continuation failed") }
      report["task_stream"] = "passed against loopback fixture"
      for _ in 0..<100 where loadingHistory {
        try await Task.sleep(for: .milliseconds(10))
      }
      guard conversationHistory.count == 1,
        string(conversationHistory.first ?? [:], "id") == taskID,
        string(conversationHistory.first ?? [:], "response").contains("Native task fixture") else {
        throw EngineError(message: "Earlier conversation turns were not loaded into the native UI")
      }
      report["continuation"] = "passed; native session preserved and earlier turns displayed"
      report["composer"] = "passed; submitted messages clear and follow-ups use the same session"
      for index in 0..<12 {
        selectJob(index.isMultiple(of: 2) ? evaluationID : taskID)
        await Task.yield()
      }
      selectJob(taskID)
      for _ in 0..<150 {
        await refreshDetail()
        if string(detail, "id") == taskID { break }
        try await Task.sleep(for: .milliseconds(20))
      }
      guard string(detail, "id") == taskID, string(detail, "status") == "completed" else {
        throw EngineError(message: "Rapid conversation switching lost the selected run")
      }
      let sequences = events.compactMap { $0["sequence"] as? Int }
      guard Set(sequences).count == sequences.count else {
        throw EngineError(message: "Stale conversation responses duplicated events")
      }
      for index in 0..<12 {
        model = "temporary-model-\(index)"
        savePreferences()
        await Task.yield()
      }
      model = "gpt-4o-mini"
      savePreferences()
      for _ in 0..<200 {
        if !writingPreferences { break }
        try await Task.sleep(for: .milliseconds(10))
      }
      let persisted = try await engine.call("settings.get") as? [String: Any] ?? [:]
      guard string(persisted, "model") == model, string(persisted, "harness") == harness,
        string(persisted, "provider") == provider else {
        throw EngineError(message: "Rapid route changes saved inconsistent preferences")
      }
      for _ in 0..<150 {
        if files.contains("Sources/New.swift") { break }
        try await Task.sleep(for: .milliseconds(20))
      }
      guard files.contains("Sources/New.swift") else {
        throw EngineError(message: "Completed task did not refresh the project file list")
      }
      report["rapid_switching"] = "passed; selected conversation, unique events and latest saved connection survive rapid changes"
      report["changes_refresh"] = "passed; task completion refreshes Git status and project files"
      let sourceProject = projectID
      let sourceRun = selectedJob
      let sourceDraft = draft
      let forkParameters: [String: Any] = ["project": sourceProject, "id": sourceRun,
        "title": "Alternative implementation", "branch": "superqode/native-fork"]
      let forkPlan = try await engine.call("threads.fork.preview", forkParameters) as? [String: Any] ?? [:]
      let fork = try await engine.call("threads.fork.create", forkParameters.merging([
        "fork_id": string(forkPlan, "fork_id"), "expected_digest": string(forkPlan, "digest")]) { _, value in value }) as? [String: Any] ?? [:]
      try await openForkWorkspace(fork, includeContext: true)
      guard projectID == string(fork, "project"), draft.contains("Shared thread context"),
        selectedJob.isEmpty, string(project, "name") == "Alternative implementation" else {
        throw EngineError(message: "Fork workspace did not retain its reviewed draft and destination")
      }
      let forkArguments = ProcessInfo.processInfo.arguments
      if let index = forkArguments.firstIndex(of: "--snapshot-dir"), forkArguments.count > index + 1 {
        try await Task.sleep(for: .milliseconds(250))
        try captureWindow(to: URL(fileURLWithPath: forkArguments[index + 1]).appendingPathComponent("fork-workspace.png"))
      }
      try await openForkSource(fork)
      guard projectID == sourceProject, selectedJob == sourceRun, draft == sourceDraft else {
        throw EngineError(message: "Returning from a fork changed the source destination or draft")
      }
      report["thread_forks"] = "passed; real isolated Git worktree, bounded draft context, source navigation and no automatic task execution"
      await refreshJobs()
      let args = ProcessInfo.processInfo.arguments
      report["harness_studio"] = try await smokeHarnessStudio()
      for tab in Sections.names {
        section = tab
        selectJob(tab == "Evaluations" ? evaluationID : taskID)
        await refreshDetail()
        try await Task.sleep(for: .milliseconds(350))
        if let index = args.firstIndex(of: "--snapshot-dir"), args.count > index + 1 {
          try captureWindow(
            to: URL(fileURLWithPath: args[index + 1]).appendingPathComponent(
              tab.lowercased().replacingOccurrences(of: " ", with: "-") + ".png"))
        }
      }
      report["native_workspace_screens"] = Sections.names
      let library = try await engine.call("threads.list", ["project": projectID]) as? [String: Any] ?? [:]
      guard let thread = (library["items"] as? [[String: Any]])?.first else {
        throw EngineError(message: "Recorded tasks are missing from the thread library")
      }
      let threadID = string(thread, "id")
      _ = try await engine.call("threads.update", ["project": projectID, "id": threadID, "title": "Native thread organization fixture", "pinned": true])
      let pinned = try await engine.call("threads.list", ["project": projectID, "view": "pinned"]) as? [String: Any] ?? [:]
      guard (pinned["items"] as? [[String: Any]])?.contains(where: { string($0, "conversation_title") == "Native thread organization fixture" }) == true else {
        throw EngineError(message: "Thread rename and pin did not persist through the native pipe")
      }
      _ = try await engine.call("threads.update", ["project": projectID, "id": threadID, "archived": true])
      let archived = try await engine.call("threads.get", ["project": projectID, "id": threadID]) as? [String: Any] ?? [:]
      guard archived["archived"] as? Bool == true else { throw EngineError(message: "Thread archive failed") }
      _ = try await engine.call("threads.update", ["project": projectID, "id": threadID, "archived": false])
      report["thread_library"] = "passed; full thread library, rename, pin, archive and restore over the native engine pipe"
      let snapshotIndex = args.firstIndex(of: "--snapshot-dir")
      let externalSnapshots = snapshotIndex.flatMap { args.count > $0 + 1 ? URL(fileURLWithPath: args[$0 + 1]) : nil }
      report["external_sessions"] = try await smokeExternalSessions(snapshotDirectory: externalSnapshots)
      report["local_model_workbench"] = try await smokeLocalModelWorkbench()
      if let externalSnapshots {
        try await captureConnectionPage("local-storage-hub", directory: externalSnapshots)
        try await captureConnectionPage("local-harness-compatibility", directory: externalSnapshots)
      }
      report["background_engine"] = try await smokeBackgroundEngine()
      let navigation = try await smokeNavigationResponsiveness()
      report["navigation_performance"] = navigation
      try requireResponsiveNavigation(navigation)
      if let index = args.firstIndex(of: "--snapshot-dir"), args.count > index + 1 {
        section = "Workspace"
        selectJob(taskID)
        await refreshDetail()
        let originalTheme = theme
        for appearance in ["light", "dark"] {
          theme = appearance
          try await Task.sleep(for: .milliseconds(350))
          let target = URL(fileURLWithPath: args[index + 1]).appendingPathComponent("workspace-" + appearance + ".png")
          try captureWindow(to: target)
          guard let bitmap = NSBitmapImageRep(data: try Data(contentsOf: target)),
            let pixel = bitmap.colorAt(x: 12, y: bitmap.pixelsHigh / 2)?.usingColorSpace(.sRGB) else {
            throw EngineError(message: "Theme background could not be inspected")
          }
          let channels = [pixel.redComponent, pixel.greenComponent, pixel.blueComponent]
          guard channels.allSatisfy({ appearance == "dark" ? $0 < 0.01 : $0 > 0.99 }) else {
            throw EngineError(message: "Workspace background is not pure black/white in " + appearance)
          }
        }
        theme = originalTheme
        report["pure_theme_surfaces"] = "passed; native workspace background pixels are pure white in light mode and pure black in dark mode"
      }
      report["passed"] = true
    } catch {
      report["passed"] = false
      report["error"] = error.localizedDescription
    }
    let output =
      ProcessInfo.processInfo.environment["SUPERQODE_SMOKE_REPORT"]
      ?? "/tmp/superqode-native-smoke.json"
    try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
      .write(to: URL(fileURLWithPath: output))
    shutdown()
    NSApp.terminate(nil)
  }
  private func verifyResponsiveness() async throws -> [String: Any] {
    let preview = Workspace()
    var workspaceChanges = 0
    let subscription = preview.objectWillChange.sink { workspaceChanges += 1 }
    for index in 0..<1000 {
      preview.draftStore.text = "Draft \(index)"
      preview.noteComposerCursor(preview.draftStore.text)
    }
    subscription.cancel()
    guard workspaceChanges == 0 else {
      throw EngineError(message: "Typing still invalidates the entire workspace")
    }
    let chunk = String(repeating: "x", count: 512)
    let deltas: [[String: Any]] = (0..<1200).map { _ in
      ["type": "harness_event", "data": ["event": "delta", "payload": ["text": chunk]]]
    }
    let start = ProcessInfo.processInfo.systemUptime
    let rows = displayEvents(deltas)
    let renderMS = (ProcessInfo.processInfo.systemUptime - start) * 1000
    guard rows.count == 1, string(rows[0]["data"] as? [String: Any] ?? [:], "text").count == 614400 else {
      throw EngineError(message: "Large streaming projection lost response text")
    }
    var worstTick = 0.0
    let heartbeat = Task {
      while !Task.isCancelled {
        let started = ProcessInfo.processInfo.systemUptime
        do { try await Task.sleep(for: .milliseconds(10)) } catch { return }
        worstTick = max(worstTick, ProcessInfo.processInfo.systemUptime - started)
      }
    }
    defer { heartbeat.cancel() }
    let richText = String(repeating: "## Result\n\nHello **world** with `code`.\n\n```swift\nlet value = 42\n```\n\n", count: 2500)
    let richStart = ProcessInfo.processInfo.systemUptime
    guard let prepared = await prepareResponseDocument(richText), prepared.blocks.count == 7500,
      let coloured = await prepareHighlightedSource(SourceHighlightKey(
        code: String(repeating: "let value = 42\n", count: 5000), language: "swift", highContrast: false)),
      coloured.characters.count == 75000 else {
      throw EngineError(message: "Background response formatting lost content")
    }
    let formattingMS = (ProcessInfo.processInfo.systemUptime - richStart) * 1000
    let reviewLines: [[String: Any]] = (0..<20_000).map { index in
      ["id": index, "kind": "add", "text": "A changed line with Chinese text 你好", "new_line": index + 1, "old_line": NSNull(), "no_newline": false]
    }
    let revision: [String: Any] = [
      "id": "performance-file", "path": "large.swift", "scope": "uncommitted", "layer": "unstaged", "label": "Large revision",
      "hunks": [["id": 0, "header": "@@ -0,0 +1,20000 @@", "lines": reviewLines]],
      "issue": "", "truncated": false, "can_stage": false,
    ]
    let reviewStart = ProcessInfo.processInfo.systemUptime
    let review = try await prepareReview(revision, decode: ReviewDocument.decode)
    guard review.hunks.first?.lines.count == 20_000 else {
      throw EngineError(message: "Background review preparation lost diff lines")
    }
    let reviewMS = (ProcessInfo.processInfo.systemUptime - reviewStart) * 1000
    let payload = String(repeating: "p", count: 512000)
    let saved = try await engine.call("settings.get") as? [String: Any] ?? [:]
    let previousDrafts = saved["drafts"] ?? [:]
    _ = try await engine.call("settings.set", ["key": "drafts", "value": ["performance-fixture": payload]])
    do {
      try await withThrowingTaskGroup(of: Void.self) { group in
        for _ in 0..<8 {
          group.addTask { _ = try await self.engine.call("settings.get", ["padding": payload]) }
        }
        try await group.waitForAll()
      }
    } catch {
      _ = try? await engine.call("settings.set", ["key": "drafts", "value": previousDrafts])
      throw error
    }
    _ = try await engine.call("settings.set", ["key": "drafts", "value": previousDrafts])
    heartbeat.cancel()
    await heartbeat.value
    guard worstTick < 0.25 else {
      throw EngineError(message: "Response formatting or engine I/O blocked the UI heartbeat for more than 250 ms")
    }
    return ["draft_edits": 1000, "workspace_invalidations": workspaceChanges,
            "stream_characters": 614400, "stream_projection_ms": renderMS,
            "formatted_response_bytes": richText.utf8.count, "response_formatting_ms": formattingMS,
            "review_lines": 20000, "review_preparation_ms": reviewMS,
            "engine_roundtrips": 8, "payload_bytes_each_way": 512000,
            "worst_ui_heartbeat_ms": worstTick * 1000]
  }
  private func verifySourceEditor() async throws -> String {
    var buffer = "def greet(name):\n    return 'Hello, ' + name\n"
    let initial = buffer
    let binding = Binding<String>(get: { buffer }, set: { buffer = $0 })
    let host = NSHostingView(rootView: SourceEditor(text: binding, path: "greet.py", editable: true))
    host.frame = NSRect(x: 0, y: 0, width: 700, height: 320)
    let window = NSWindow(contentRect: host.frame, styleMask: [.titled], backing: .buffered, defer: false)
    window.contentView = host
    window.orderFront(nil)
    defer { window.orderOut(nil); window.contentView = nil }
    host.layoutSubtreeIfNeeded()
    func findEditor(_ view: NSView) -> SourceEditor.Editor? {
      if let editor = view as? SourceEditor.Editor { return editor }
      return view.subviews.lazy.compactMap { findEditor($0) }.first
    }
    try await Task.sleep(for: .milliseconds(250))
    guard let editor = findEditor(host), editor.string == initial,
      let storage = editor.textStorage else { throw EngineError(message: "Native source editor failed to load") }
    var colours = Set<String>()
    storage.enumerateAttribute(.foregroundColor, in: NSRange(location: 0, length: storage.length)) { value, _, _ in
      if let color = value as? NSColor { colours.insert(color.description) }
    }
    guard colours.count >= 4, editor.backgroundColor.usingColorSpace(.sRGB)?.redComponent == 0 else {
      throw EngineError(message: "File source was not coloured on a black background")
    }
    window.makeFirstResponder(editor)
    editor.setSelectedRange(NSRange(location: (editor.string as NSString).length, length: 0))
    editor.insertText("# edited\n", replacementRange: editor.selectedRange())
    let selection = editor.selectedRange()
    try await Task.sleep(for: .milliseconds(250))
    guard buffer == initial + "# edited\n", editor.string == buffer,
      editor.selectedRange() == selection, editor.undoManager?.canUndo == true else {
      throw EngineError(message: "Source colouring changed the buffer, caret or undo history")
    }
    editor.undoManager?.undo()
    guard buffer == initial, editor.string == initial else {
      throw EngineError(message: "Native source editing could not be undone")
    }
    if let index = ProcessInfo.processInfo.arguments.firstIndex(of: "--snapshot-dir"), ProcessInfo.processInfo.arguments.count > index + 1 {
      editor.setSelectedRange(NSRange(location: 4, length: 0))
      editor.needsDisplay = true
      host.displayIfNeeded()
      if let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) {
        host.cacheDisplay(in: host.bounds, to: bitmap)
        try bitmap.representation(using: .png, properties: [:])?.write(to:
          URL(fileURLWithPath: ProcessInfo.processInfo.arguments[index + 1]).appendingPathComponent("source-editor.png"))
      }
    }
    editor.insertText("# second edit", replacementRange: editor.selectedRange())
    editor.replaceBuffer("let otherFile = true\n")
    guard editor.undoManager?.canUndo != true else {
      throw EngineError(message: "Switching source buffers retained another file's undo history")
    }
    return "passed; Python syntax colours, pure-black file surface, native edits and undo; caret survives colouring; switching files clears old undo history"
  }
  private func verifyCodingInputs() throws -> String {
    let preview = Workspace()
    preview.harnesses = [
      ["id": "acp:opencode", "desktop_kind": "acp", "command": "opencode acp"],
      ["id": "connection:alias", "desktop_kind": "acp", "command": "opencode acp", "extra_env": [:]],
      ["id": "connection:subscription", "desktop_kind": "acp", "command": "opencode acp", "subscription_vendor": "vendor"],
    ]
    guard preview.acpConnections.count == 2,
      string(preview.acpConnections.first ?? [:], "id") == "acp:opencode" else {
      throw EngineError(message: "ACP alias deduplication lost canonical or distinct-auth routes")
    }
    preview.harness = "acp:opencode"
    preview.connectionMetadata[preview.harness] = ["session": ["models": ["availableModels": [
      ["modelId": "paid", "name": "A paid model", "free": false],
      ["modelId": "free", "name": "Z free model", "free": true],
    ]]]]
    preview.detail = ["request": ["harness": "acp:another-agent"]]
    preview.events = [["type": "harness_event", "data": ["event": "acp_session", "payload": ["models": ["availableModels": [["modelId": "wrong-agent"]]]]]]]
    guard preview.agentModels.first?.agentModelID == "free" else {
      throw EngineError(message: "Agent model picker lost free models or their ordering")
    }
    preview.selectedJob = "local-conversation"
    preview.detail = ["kind": "task", "status": "completed", "request": ["harness": "acp:opencode"]]
    preview.draft = "Keep this unsent draft"
    preview.agentModel = "free"
    preview.agentMode = "code"
    preview.chooseConnection(["id": "acp:second", "desktop_kind": "acp"])
    guard preview.selectedJob == "local-conversation", preview.canContinueConversation,
      preview.draft == "Keep this unsent draft" else {
      throw EngineError(message: "Switching connections discarded the conversation or draft")
    }
    preview.chooseHarness("acp:opencode")
    guard preview.agentModel == "free", preview.agentMode == "code" else {
      throw EngineError(message: "Returning to an agent lost its model and mode choices")
    }
    let editor = PromptEditor.Editor(frame: NSRect(x: 0, y: 0, width: 400, height: 80))
    editor.isRichText = false
    editor.string = "Test message"
    editor.setSelectedRange(NSRange(location: editor.string.utf16.count, length: 0))
    var submissions = 0
    editor.submit = { submissions += 1 }
    func key(_ modifiers: NSEvent.ModifierFlags) throws -> NSEvent {
      guard let event = NSEvent.keyEvent(
        with: .keyDown, location: .zero, modifierFlags: modifiers, timestamp: 0,
        windowNumber: 0, context: nil, characters: "\r", charactersIgnoringModifiers: "\r",
        isARepeat: false, keyCode: 36) else { throw EngineError(message: "Could not build keyboard fixture") }
      return event
    }
    editor.keyDown(with: try key([]))
    guard submissions == 1, editor.string == "Test message" else {
      throw EngineError(message: "Enter did not submit without inserting a newline")
    }
    editor.keyDown(with: try key(.shift))
    guard submissions == 1, editor.string.contains("\n") else {
      throw EngineError(message: "Shift+Enter did not insert a newline")
    }
    return "passed; Enter and Shift+Enter; ACP aliases and free models; switching agents preserves conversation, draft, model and mode choices"
  }
  private func verifyCenteredDialogs() async throws -> String {
    guard let main = NSApp.windows.first(where: { $0.title == (Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "SuperQode") }) else {
      throw EngineError(message: "Connection test has no main window")
    }
    let previousHarness = harness
    let previousProvider = provider
    let previousModel = model
    defer {
      showConnection = false
      chooseHarness(previousHarness)
      provider = previousProvider
      model = previousModel
      harnesses.removeAll { string($0, "id") == "acp:desktop-ui-check" }
    }
    func control(_ identifier: String, in node: NSView) -> NSButton? {
      if let button = node as? NSButton, button.identifier?.rawValue == identifier { return button }
      for child in node.subviews {
        if let found = control(identifier, in: child) { return found }
      }
      return nil
    }
    func waitForSheet() async throws -> NSWindow {
      for _ in 0..<150 {
        if let sheet = main.attachedSheet, sheet.isVisible {
          // Native sheet presentation is asynchronous; wait for its opening
          // transition before delivering test clicks into a reopened sheet.
          try await Task.sleep(for: .milliseconds(450))
          return sheet
        }
        try await Task.sleep(for: .milliseconds(20))
      }
      throw EngineError(message: "Connect did not open a system sheet")
    }
    func press(_ identifier: String, verify: (() -> Bool)? = nil) async throws {
      for _ in 0..<150 {
        var active = main.attachedSheet
        while let nested = active?.attachedSheet { active = nested }
        let sheet = active ?? main
        if let surface = sheet.contentView,
          let button = control(identifier, in: surface) {
          // Closing a notice or removing a chip relayouts the next control.
          // Do not deliver a click into a frame that is still moving.
          let frame = button.convert(button.bounds, to: nil)
          try await Task.sleep(for: .milliseconds(100))
          guard button.window === sheet,
            button.identifier?.rawValue == identifier,
            button.convert(button.bounds, to: nil) == frame else { continue }
          guard button.isEnabled, button.bounds.width > 0, button.bounds.height > 0,
            let hit = surface.hitTest(button.convert(
              NSPoint(x: button.bounds.midX, y: button.bounds.midY), to: surface.superview)),
            hit === button || hit.isDescendant(of: button)
              || (hit as? NSButton)?.identifier == button.identifier
          else { throw EngineError(message: "Connect control cannot receive clicks: " + identifier) }
          // Exercise the actual NSButton target/action after the hierarchy and
          // hit-test checks above. A headless runner can lose a queued mouse-up
          // to application activation, especially on a second app launch.
          // AppKit activation keeps this binding check independent of runner
          // focus without global input, accessibility or another application.
          button.performClick(nil)
          // Observe the control's effect after SwiftUI has applied its state.
          if let verify {
            for _ in 0..<150 {
              if verify() { break }
              try await Task.sleep(for: .milliseconds(20))
            }
            guard verify() else {
              throw EngineError(message: "Native control action did not apply: \(identifier); noticeEmpty=\(self.notice.isEmpty), fixtureNoticeVisible=\(self.notice == "Dismissal check"), files=\(self.contextFiles), images=\(self.imageAttachments.count)")
            }
          }
          try await Task.sleep(for: .milliseconds(250))
          return
        }
        try await Task.sleep(for: .milliseconds(20))
      }
      func identifiers(_ node: NSView) -> [String] {
        (node.identifier.map { [$0.rawValue] } ?? []) + node.subviews.flatMap { identifiers($0) }
      }
      let visible = main.attachedSheet?.contentView.map { identifiers($0) } ?? []
      throw EngineError(message: "Missing Connect control: \(identifier); present=\(visible)")
    }
    var dismissalPhase = "Connect Close"
    func assertClosed() async throws {
      for _ in 0..<150 {
        if !showConnection && main.attachedSheet == nil { return }
        try await Task.sleep(for: .milliseconds(20))
      }
      throw EngineError(message: "Dialog did not dismiss: " + dismissalPhase)
    }
    showConnection = true
    _ = try await waitForSheet()
    try await press("connect.subscriptions")
    try await press("connect.row.codex")
    try await press("connect.back")
    try await press("connect.back")
    try await press("connect.acp")
    try await press("connect.back")
    try await press("connect.close")
    try await assertClosed()

    // Exercise the ACP selection and Use action independently of installed or
    // signed-in agents. Backend ACP initialization has separate fixture tests.
    // This route cannot run a model or any coding tool.
    harnesses.append([
      "id": "acp:desktop-ui-check", "name": "AAA Local UI check",
      "desktop_kind": "acp", "available": true, "description": "UI-only connection check",
      "digest": "ui-fixture", "command": "ui-only-not-an-executable",
    ])
    connectionMetadata["acp:desktop-ui-check"] = ["connected": true, "route_digest": "ui-fixture", "message": "Verified UI fixture"]
    showConnection = true
    _ = try await waitForSheet()
    try await press("connect.acp")
    try await press("connect.row.acp:desktop-ui-check")
    try await press("connect.use")
    dismissalPhase = "ACP Use"
    try await assertClosed()
    guard harness == "acp:desktop-ui-check", section == "Workspace" else {
      throw EngineError(message: "ACP selection did not return to the coding workspace")
    }
    showConnection = true
    _ = try await waitForSheet()
    try await press("connect.disconnect")
    dismissalPhase = "Connect Disconnect"
    try await assertClosed()
    guard connectionDisconnected else { throw EngineError(message: "Native Disconnect button did not detach the route") }
    chooseModelRoute("openai", "gpt-4o-mini")
    guard !connectionDisconnected else { throw EngineError(message: "Model connection did not recover after Disconnect") }
    chooseHarness(previousHarness)
    provider = previousProvider
    model = previousModel
    showConnection = true
    let sheet = try await waitForSheet()
    sheet.cancelOperation(nil)
    dismissalPhase = "Connect Escape"
    try await assertClosed()
    // Exercise the shared X against actual product dialog contents, not only Connect.
    let audit = DialogAuditState()
    let host = NSHostingView(rootView: DialogAuditHost(state: audit))
    host.frame = NSRect(x: 0, y: 0, width: 1, height: 1)
    main.contentView?.addSubview(host)
    defer { host.removeFromSuperview() }
    let dialogs: [(String, AnyView)] = [
      ("Beta guide", AnyView(BetaGuideView())),
      ("Getting started", AnyView(LearningGuideView().environmentObject(self))),
      ("Task queue", AnyView(TaskQueueView().environmentObject(self))),
      ("Context", AnyView(ContextPreviewView().environmentObject(self))),
      ("WorkOrders", AnyView(WorkOrderBoardView().environmentObject(self))),
      ("Terminal sign-in", AnyView(TerminalLoginView(terminals: terminals, arguments: [], complete: {}).environmentObject(self))),
      ("Authentication", AnyView(AuthenticationProgressView(request: ["action": "invalid-ui-fixture"], complete: { _ in }).environmentObject(self))),
    ]
    for (title, content) in dialogs {
      dismissalPhase = title
      audit.title = title
      audit.content = content
      audit.shown = true
      _ = try await waitForSheet()
      let done = title == "Beta guide" ? "dialog.done.default" : title == "Authentication" ? "dialog.cancel" : "dialog.done"
      try await press(done)
      try await assertClosed()
      guard !audit.shown else { throw EngineError(message: title + " Done/Cancel failed") }
      audit.shown = true
      _ = try await waitForSheet()
      try await press("dialog.close")
      try await assertClosed()
      guard !audit.shown else { throw EngineError(message: title + " X failed to reset presentation state") }
    }
    audit.content = AnyView(Text("Parent dialog").frame(width: 400, height: 200))
    audit.shown = true
    let parent = try await waitForSheet()
    audit.nested = true
    for _ in 0..<150 {
      if parent.attachedSheet != nil { break }
      try await Task.sleep(for: .milliseconds(20))
    }
    try await Task.sleep(for: .milliseconds(450))
    guard parent.attachedSheet != nil else { throw EngineError(message: "Nested sheet did not open") }
    try await press("dialog.close")
    guard !audit.nested, audit.shown else {
      throw EngineError(message: "Nested X closed the wrong dialog")
    }
    for _ in 0..<150 {
      if parent.attachedSheet == nil { break }
      try await Task.sleep(for: .milliseconds(20))
    }
    try await press("dialog.close")
    dismissalPhase = "Nested parent"
    try await assertClosed()
    let savedNotice = notice
    let savedFiles = contextFiles
    let savedImages = imageAttachments
    defer { notice = savedNotice; contextFiles = savedFiles; imageAttachments = savedImages }
    notice = "Dismissal check"
    contextFiles = ["fixture-a.txt", "fixture-b.txt"]
    imageAttachments = [["id": "ui-image", "name": "fixture.png"]]
    try await Task.sleep(for: .milliseconds(250))
    try await press("notice.close", verify: {
      self.notice.isEmpty && self.contextFiles == ["fixture-a.txt", "fixture-b.txt"]
        && self.imageAttachments.count == 1
    })
    try await press("attachment.file.fixture-a.txt", verify: {
      self.contextFiles == ["fixture-b.txt"] && self.imageAttachments.count == 1
    })
    try await press("attachment.image.ui-image", verify: {
      self.contextFiles == ["fixture-b.txt"] && self.imageAttachments.isEmpty
    })
    guard contextFiles == ["fixture-b.txt"], imageAttachments.isEmpty else {
      throw EngineError(message: "Attachment removal was overwritten after layout")
    }
    return "passed; Connect Back/Close, ACP Use, Escape, Done/Cancel and X in seven product sheets, nested X ownership, notification X, attachment X and reopen"


  }
  private func captureLearningViews(directory: URL) throws {
    let preview = Workspace()
    preview.connected = true
    preview.starterTourRequested = true
    for phase in [
      "welcome", "welcome-light", "welcome-contrast", "first-task", "learning", "sidebar",
      "sidebar-light",
      "sidebar-contrast",
    ] {
      let welcome = phase.hasPrefix("welcome")
      let sidebar = phase.hasPrefix("sidebar")
      preview.project = welcome ? [:] : project
      let content: AnyView =
        phase == "learning"
        ? AnyView(LearningGuideView().environmentObject(preview))
        : welcome
          ? AnyView(WelcomeView().environmentObject(preview))
          : sidebar
            ? AnyView(SidebarView().environmentObject(preview))
            : AnyView(GettingStartedView(draftStore: preview.draftStore).environmentObject(preview))
      let view = NSHostingView(
        rootView:
          content
          .environment(\.colorScheme, phase.contains("light") ? .light : .dark)
          .background(Color.qPanel))
      view.appearance = NSAppearance(
        named: phase.contains("contrast")
          ? .accessibilityHighContrastDarkAqua : phase.contains("light") ? .aqua : .darkAqua)
      view.frame =
        welcome
        ? NSRect(x: 0, y: 0, width: 1120, height: 740)
        : sidebar
          ? NSRect(x: 0, y: 0, width: 236, height: 740)
          : NSRect(x: 0, y: 0, width: 760, height: 640)
      view.layoutSubtreeIfNeeded()
      guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
        throw EngineError(message: "Getting started view could not render")
      }
      view.effectiveAppearance.performAsCurrentDrawingAppearance {
        view.cacheDisplay(in: view.bounds, to: bitmap)
      }
      guard let data = bitmap.representation(using: .png, properties: [:]) else {
        throw EngineError(message: "Getting started capture failed")
      }
      try data.write(to: directory.appendingPathComponent("getting-started-" + phase + ".png"))
    }
  }
  private func captureConnectionPage(_ page: String, directory: URL) async throws {
    let panel = NSWindow(
      contentRect: NSRect(x: 0, y: 0, width: 860, height: 740), styleMask: [.titled],
      backing: .buffered, defer: false)
    panel.isReleasedWhenClosed = false
    let content: AnyView
    let lightPreview = page == "thread-identities-preview-light"
    if page.hasPrefix("thread-identities-preview") {
      let examples: [[String: Any]] = [
        ["id": "preview-codex", "title": "Investigate the authentication flow", "harness": "acp:codex", "harnesses_used": [
          ["id": "acp:codex", "name": "Codex", "icon_key": "codex"]]],
        ["id": "preview-opencode", "title": "Build with an open-source coding harness", "harness": "acp:opencode", "harnesses_used": [
          ["id": "acp:opencode", "name": "OpenCode", "icon_key": "opencode"]]],
        ["id": "preview-mixed", "title": "Review API contracts across agents", "harness": "acp:claude", "harnesses_used": [
          ["id": "acp:codex", "name": "Codex", "icon_key": "codex"],
          ["id": "acp:claude", "name": "Claude", "icon_key": "claude"],
          ["id": "acp:gemini", "name": "Gemini CLI", "icon_key": "gemini"]]],
        ["id": "preview-custom", "title": "Compare the research harness", "harness": "custom", "harnesses_used": [
          ["id": "custom", "name": "Research harness", "icon_key": ""],
          ["id": "core", "name": "Core", "icon_key": "superqode"]]],
      ]
      content = AnyView(VStack(alignment: .leading, spacing: 24) {
        PageTitle(eyebrow: "Thread identity preview", title: "Know which agents did the work",
          subtitle: "Example threads · colour accents identify the harness; a blank conversation stays disconnected.")
        HStack(spacing: 10) {
          Image(systemName: "bubble.left.and.bubble.right").foregroundStyle(.secondary)
          Text("New conversation").font(.headline)
          Spacer()
          Text("No connection").font(.callout).foregroundStyle(.secondary)
        }.padding(14).brandSurface()
        ForEach(examples, id: \.projectRowID) { row in
          HStack(spacing: 18) {
            HarnessIconStack(row: row, size: 38)
            VStack(alignment: .leading, spacing: 8) {
              Text(string(row, "title")).font(.headline)
              Text(HarnessIdentity.used(in: row).map(\.name).joined(separator: " · "))
                .font(.callout).foregroundStyle(HarnessIdentity.current(in: row)?.accent ?? Color.secondary)
            }
            Spacer()
          }.padding(16).brandSurface()
        }
        Text("Colour is a harness identity accent, not connection status. Custom harnesses get a stable colour and a generic symbol.")
          .font(.caption).foregroundStyle(.secondary)
        Spacer()
      }.padding(28).frame(width: 860, height: 740).background(Color.qPanel).preferredColorScheme(lightPreview ? .light : .dark))
    } else if page == "acp-setup-preview" {
      let route: [String: Any] = ["id": "acp:setup-preview", "name": "ACP setup preview", "desktop_kind": "acp",
        "available": true, "digest": "preview", "command": "example-agent --acp", "registry_source": "Setup preview"]
      connectionMetadata["acp:setup-preview"] = ["connected": false,
        "message": "Choose a sign-in method offered by this agent, then verify the connection.",
        "auth_methods": [["id": "browser", "name": "Browser sign-in", "type": "agent"], ["id": "terminal", "name": "Terminal sign-in", "type": "terminal"]]]
      content = AnyView(ScrollView {
        VStack(alignment: .leading, spacing: 20) {
          Text("Set up your ACP agent").font(.title)
          ACPSetupView(initialRoute: route, project: projectID, use: { _, _ in })
        }.padding(28)
      }.frame(width: 860, height: 740).background(Color.qPanel).environmentObject(self).preferredColorScheme(.dark))
    } else if page == "local-storage-hub" {
      content = AnyView(LocalModelSetupView().environmentObject(self).preferredColorScheme(.dark))
    } else if page == "local-harness-compatibility" {
      content = AnyView(LocalModelCompatibilityView(project: projectID).environmentObject(self).preferredColorScheme(.dark))
    } else {
      content = AnyView(ConnectionView(initialPage: page).environmentObject(self).preferredColorScheme(.dark))
    }
    let styled = page.hasPrefix("local-") ? AnyView(content.foregroundStyle(Color.white).environment(\.colorScheme, .dark)) : AnyView(content.foregroundStyle(lightPreview ? Color.black : Color.white).environment(\.colorScheme, lightPreview ? .light : .dark))
    let view = NSHostingView(rootView: styled)
    view.appearance = NSAppearance(named: lightPreview ? .aqua : .darkAqua)
    panel.contentView = view
    panel.appearance = NSAppearance(named: lightPreview ? .aqua : .darkAqua)
    if page == "local-storage-hub" { panel.setContentSize(NSSize(width: 780, height: 620)) }
    if page == "local-harness-compatibility" { panel.setContentSize(NSSize(width: 920, height: 680)) }
    panel.orderFront(nil)
    defer { panel.close() }
    try await Task.sleep(for: .milliseconds(450))
    view.layoutSubtreeIfNeeded()
    guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
      throw EngineError(message: "Connect view could not render")
    }
    view.effectiveAppearance.performAsCurrentDrawingAppearance {
      view.cacheDisplay(in: view.bounds, to: bitmap)
    }
    guard let png = bitmap.representation(using: .png, properties: [:]) else {
      throw EngineError(message: "Connect view render failed")
    }
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    try png.write(
      to: directory.appendingPathComponent(
        "connect-" + page.replacingOccurrences(of: ":", with: "-") + ".png"))
  }
  private func captureConnectionInspector(directory: URL) async throws {
    let preview = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    preview.project = project
    preview.harness = "acp:preview"
    preview.harnesses = [["id": preview.harness, "name": "ACP connection preview", "desktop_kind": "acp", "digest": "preview"]]
    preview.routeStatus = ["state": "connected", "message": "ACP connection checked. The agent owns model access and billing."]
    preview.connectionMetadata[preview.harness] = ["connected": true, "checked_at": Date().timeIntervalSince1970,
      "route_digest": "preview", "initialization": ["protocol_version": 1, "agent": ["name": "preview", "version": "1.0"]],
      "session": ["capabilities": ["loadSession": true, "promptCapabilities": ["image": true]], "models": ["availableModels": [["modelId": "example"]]]]]
    for dark in [true, false] {
      let host = NSHostingView(rootView: ConnectionInspectorView().environmentObject(preview)
        .environment(\.colorScheme, dark ? .dark : .light))
      host.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
      let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 720, height: 650), styleMask: [.borderless], backing: .buffered, defer: false)
      panel.isReleasedWhenClosed = false
      panel.contentView = host
      panel.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
      panel.orderFront(nil)
      defer { panel.close() }
      try await Task.sleep(for: .milliseconds(250))
      host.layoutSubtreeIfNeeded()
      guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { throw EngineError(message: "Connection inspector could not render") }
      host.effectiveAppearance.performAsCurrentDrawingAppearance {
        host.cacheDisplay(in: host.bounds, to: bitmap)
      }
      guard let png = bitmap.representation(using: .png, properties: [:]) else { throw EngineError(message: "Connection inspector render failed") }
      try png.write(to: directory.appendingPathComponent(dark ? "connection-inspector-dark.png" : "connection-inspector-light.png"))
    }
  }
  func captureWindow(to url: URL) throws {
    guard let view = NSApp.windows.first(where: { $0.title == (Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "SuperQode") })?.contentView
    else { throw EngineError(message: "Native window is unavailable") }
    view.layoutSubtreeIfNeeded()
    view.displayIfNeeded()
    func dimensions(_ value: NSRect) -> [String: Double] {
      ["x": value.origin.x, "y": value.origin.y, "width": value.width, "height": value.height]
    }
    let layout: [String: Any] = [
      "bounds": dimensions(view.bounds), "frame": dimensions(view.frame),
      "fitting_width": view.fittingSize.width, "fitting_height": view.fittingSize.height,
      "window_content": dimensions(view.window?.contentLayoutRect ?? .zero),
      "children": view.subviews.map { child in
        ["type": String(describing: type(of: child)), "frame": dimensions(child.frame)]
          as [String: Any]
      },
    ]
    try JSONSerialization.data(withJSONObject: layout, options: [.prettyPrinted, .sortedKeys])
      .write(to: url.deletingPathExtension().appendingPathExtension("layout.json"))
    guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
      throw EngineError(message: "Native window could not render")
    }
    view.effectiveAppearance.performAsCurrentDrawingAppearance {
      view.cacheDisplay(in: view.bounds, to: bitmap)
    }
    guard let png = bitmap.representation(using: .png, properties: [:]) else {
      throw EngineError(message: "Could not render native window")
    }

    try FileManager.default.createDirectory(
      at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try png.write(to: url)
  }
}
