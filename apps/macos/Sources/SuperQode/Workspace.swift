import AppKit
import SwiftUI

struct FileEdit {
  let original: String
  let digest: String
  let text: String
}

@MainActor final class DraftStore: ObservableObject {
  @Published var text = ""
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
  let engine = Engine()
  let terminals = ProjectTerminals()
  let credentialStore = CredentialStore()
  @Published var providers: [[String: Any]] = []
  @Published var savedCredentialProviders: [String] = []
  @Published var routeStatus: [String: Any] = [:]
  @Published var openingProject = false
  @Published var showWelcome = true
  @Published var starterTourRequested = false
  @Published var showLearningGuide = false
  @Published var learningTopic = "Start coding"
  @Published var showConnection = false
  @Published var agentModel = ""
  @Published var agentMode = ""
  @Published var agentConfig: [String: String] = [:]
  @Published var connectionMetadata: [String: [String: Any]] = [:]
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
        let semantics: [String: Any] = [
          "command": string(route, "command", string(route, "id")),
          "vendor": string(route, "subscription_vendor"), "env": route["extra_env"] ?? [:],
        ]
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
  @Published var navigationHistory: [String] = []
  private var restoringNavigation = false
  @Published var section = "Workspace" {
    didSet {
      if oldValue != section && !restoringNavigation { navigationHistory.append(oldValue) }
    }
  }
  func goBack() {
    if showWelcome && !project.isEmpty {
      showWelcome = false
      return
    }
    guard let previous = navigationHistory.popLast() else { return }
    restoringNavigation = true
    section = previous
    restoringNavigation = false
  }
  @Published var projects: [[String: Any]] = []
  @Published var project: [String: Any] = [:]
  @Published var harnesses: [[String: Any]] = []
  @Published var hub: [[String: Any]] = []
  @Published var models: [[String: Any]] = []
  @Published var hardware: [String: Any] = [:]
  @Published var packs: [[String: Any]] = []
  @Published var jobs: [[String: Any]] = []
  @Published var showReview = false
  @Published var showConnectionHealth = false
  @Published var requestedFile = ""
  var connectionSetupRequested = false
  var projectActive: Bool {
    let root = string(project, "path")
    return jobs.contains { job in
      guard ["running", "needs_approval", "queued", "cancelling"].contains(string(job, "status")) else { return false }
      if string(job, "project") == projectID { return true }
      let other = string(projects.first { string($0, "id") == string(job, "project") } ?? [:], "path")
      return !root.isEmpty && !other.isEmpty && (root.hasPrefix(other + "/") || other.hasPrefix(root + "/"))
    }
  }
  func openConnectionAfterHealth() { connectionSetupRequested = true }
  @Published var selectedJob = ""
  @Published var detail: [String: Any] = [:]
  @Published var events: [[String: Any]] = []
  @Published var git: [String: Any] = [:]
  @Published var files: [String] = []
  var fileDrafts: [String: FileEdit] = [:]
  @Published var capabilities: [String: Any] = [:]
  @Published var provider = "openai"
  @Published var model = ""
  @Published var harness = "superqode"
  let draftStore = DraftStore()
  private var draftSaveTask: Task<Void, Never>?
  var draft: String {
    get { draftStore.text }
    set {
      guard draftStore.text != newValue else { return }
      draftStore.text = newValue
      scheduleDraftSave()
    }
  }
  @Published var interactionMode = "code"
  @Published var contextWindow = ""
  @Published var summarizeContext = false
  @Published var contextFiles: [String] = []
  @Published var imageAttachments: [[String: Any]] = []
  @Published var taskQueue: [String: Any] = [:]
  private var lastQueueJob = ""
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
  func chooseConnection(_ route: [String: Any]) {
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
    perform { await self.checkManagedConnection() }
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
          routeStatus = ["state": metadata["connected"] as? Bool == true ? "connected" : "configured",
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
      if generation == connectionGeneration && reference == harness {
        routeStatus = ["state": "connection-failed", "ready": false, "message": error.localizedDescription]
      }
    }
  }
  var projectID: String { string(project, "id") }
  var projectJobs: [[String: Any]] { jobs.filter { string($0, "project") == projectID } }
  var recentConversations: [[String: Any]] { groupedRecentRuns(projectJobs) }
  var selectedConversationID: String {
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

  func perform(_ action: @escaping @MainActor () async throws -> Void) {
    Task { do { try await action() } catch { self.error = error.localizedDescription } }
  }
  func boot() async {
    guard !connected else { return }
    do {
      engine.onExit = { [weak self] in self?.connected = false }
      try engine.start()
      _ = try await engine.call("hello")
      connected = true
      capabilities = try await engine.call("capabilities") as? [String: Any] ?? [:]
      let settings = try await engine.call("settings.get") as? [String: Any] ?? [:]
      provider = string(settings, "provider", "openai")
      model = string(settings, "model")
      harness = string(settings, "harness", "superqode")
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
      if let index = args.firstIndex(of: "--project"), args.count > index + 1 {
        try await open(args[index + 1])
      }
      if project.isEmpty { await refreshModels() }
      await checkRoute()
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
          if self.active { await self.refreshDetail() }
        }
      }
      if args.contains("--smoke-test") { await smokeTest() }
    } catch { self.error = error.localizedDescription }
  }
  func chooseProject() {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.allowsMultipleSelection = false
    panel.prompt = "Open project"
    if panel.runModal() == .OK, let url = panel.url { perform { try await self.open(url.path) } }
  }
  func open(_ path: String) async throws {
    saveDraft()
    projectGeneration += 1
    detailGeneration += 1
    connectionGeneration += 1
    checkingConnection = false
    connectionMetadata = [:]
    let generation = projectGeneration
    openingProject = true
    defer { if generation == projectGeneration { openingProject = false } }
    let opened = try await engine.call("projects.open", ["path": path]) as? [String: Any] ?? [:]
    guard generation == projectGeneration else { return }
    project = opened
    selectedJob = ""
    conversationHistory = []
    earlierHistory = ""
    loadingHistory = false
    contextFiles = []
    imageAttachments = []
    taskQueue = [:]
    lastQueueJob = ""
    detail = [:]
    events = []
    candidate = [:]
    git = [:]
    files = []
    hub = []
    harnesses = []
    projects = try await engine.call("projects.list") as? [[String: Any]] ?? []
    let params: [String: Any] = ["project": projectID]
    let definitions = try await engine.call("harnesses.list", params) as? [[String: Any]] ?? []
    let index = try await engine.call("hub.list", params) as? [String: Any] ?? [:]
    guard generation == projectGeneration else { return }
    let routes = try await engine.call("routes.list", params) as? [[String: Any]] ?? []
    guard generation == projectGeneration else { return }
    harnesses = definitions + routes
    for entry in UserDefaults.standard.stringArray(forKey: "nativeVendorKeys") ?? [] {
      if let key = try? credentialStore.read("vendor:" + entry) {
        if let route = try? await engine.call(
          "connect.vendor.key", ["project": projectID, "entry": entry, "key": key])
          as? [String: Any]
        {
          harnesses.append(route)
        }
      }
    }
    if UserDefaults.standard.bool(forKey: "nativeSystemOneKey"),
      let key = try? credentialStore.read("systemone")
    {
      _ = try? await engine.call("connect.systemone.key", ["key": key])
    }
    hub = index["items"] as? [[String: Any]] ?? []
    if !connectionDisconnected, !harnesses.contains(where: { string($0, "id") == harness }), let first = definitions.first {
      harness = string(first, "id")
    }
    let settings = try await engine.call("settings.get") as? [String: Any] ?? [:]
    draft =
      (UserDefaults.standard.dictionary(forKey: "nativeDrafts") as? [String: String])?[projectID]
      ?? (settings["drafts"] as? [String: String])?[projectID] ?? ""
    section = "Workspace"
    showWelcome = false
    perform {
      await self.refreshGit()
      await self.refreshModels()
    }
    if isManaged { perform { await self.checkManagedConnection() } }
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
    draftSaveTask?.cancel()
    let id = projectID
    let text = draft
    guard !id.isEmpty else { return }
    draftSaveTask = Task {
      do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
      self.writeDraft(text, for: id)
    }
  }
  func saveDraft() {
    draftSaveTask?.cancel()
    writeDraft(draft, for: projectID)
  }
  private func writeDraft(_ text: String, for id: String) {
    guard !id.isEmpty else { return }
    var drafts = UserDefaults.standard.dictionary(forKey: "nativeDrafts") as? [String: String] ?? [:]
    guard drafts[id] != text else { return }
    drafts[id] = text
    UserDefaults.standard.set(drafts, forKey: "nativeDrafts")
  }

  func refreshJobs() async {
    do {
      let nextJobs = try await engine.call("jobs.list") as? [[String: Any]] ?? []
      if !NSArray(array: jobs).isEqual(to: nextJobs) { jobs = nextJobs }
      if !projectID.isEmpty {
        let queuedProject = projectID
        let nextQueue = try await engine.call("queue.list", ["project": queuedProject]) as? [String: Any] ?? [:]
        guard queuedProject == projectID else { return }
        if !NSDictionary(dictionary: taskQueue).isEqual(to: nextQueue) { taskQueue = nextQueue }
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
  func selectJob(_ id: String, restoreConnection: Bool = true) {
    detailGeneration += 1
    restoreSelectedConnection = restoreConnection
    conversationHistory = []
    earlierHistory = ""
    loadingHistory = false
    selectedJob = id
    detail = [:]
    events = []
    candidate = [:]
    perform { await self.refreshDetail() }
  }
  func refreshDetail() async {
    guard !selectedJob.isEmpty else { return }
    let id = selectedJob
    let generation = detailGeneration
    let requestKey = "\(generation):\(id)"
    guard detailRequests.insert(requestKey).inserted else { return }
    defer { detailRequests.remove(requestKey) }
    do {
      let cursor = events.last?["sequence"] as? Int ?? 0
      let result =
        try await engine.call("jobs.get", ["id": id, "after": cursor]) as? [String: Any] ?? [:]
      guard id == selectedJob, generation == detailGeneration else { return }
      let firstLoad = detail.isEmpty
      if firstLoad && restoreSelectedConnection,
        string(result, "kind") == "task", let request = result["request"] as? [String: Any] {
        restoreSelectedConnection = false
        chooseHarness(string(request, "harness", harness))
        provider = string(request, "provider", provider)
        model = string(request, "model", model)
        interactionMode = string(request, "interaction_mode", "code")
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
      let incoming = result["events"] as? [[String: Any]] ?? []
      if !incoming.isEmpty { events += incoming }
      if firstLoad && string(metadata, "kind") == "task" {
        await loadConversationHistory()
        guard id == selectedJob, generation == detailGeneration else { return }
      }
      if events.count > 1200 { events.removeFirst(events.count - 1200) }
      let status = string(metadata, "status")
      if status != previousStatus, ["completed", "failed", "cancelled"].contains(status) {
        scheduleProjectRefresh()
      }
    } catch {
      if id == selectedJob, generation == detailGeneration { self.error = error.localizedDescription }
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
      git = status
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
          "providers.check", ["provider": currentProvider, "model": currentModel]) as? [String: Any]
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
      }
    }
    chooseModelRoute(
      selectedProvider, selectedModel.trimmingCharacters(in: .whitespacesAndNewlines))
    await refreshProviders()
    await checkRoute()
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
    guard !busy, (!connectionDisconnected || method == "checks.start") else { return }
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
  func send(continueSession: Bool) {
    guard !connectionDisconnected, !busy, !active, !checkingConnection, !projectID.isEmpty,
      (isManaged || !model.isEmpty), !draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else { return }
    let submittedDraft = draft
    let submittedFiles = contextFiles
    let submittedImages = imageAttachments.map { string($0, "id") }
    var extra: [String: Any] = [
      "prompt": submittedDraft, "context_files": submittedFiles, "interaction_mode": interactionMode,
      "context_window": contextWindow.isEmpty ? 0 : Int(contextWindow) ?? -1,
      "enable_summarization": summarizeContext,
      "image_ids": submittedImages,
    ]
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
      guard self.projectID == submittedProject else { return }
      // Clear only the accepted submission, preserving edits typed while starting.
      if self.draft == submittedDraft { self.draft = ""; self.saveDraft() }
      if self.contextFiles == submittedFiles { self.contextFiles = [] }
      if self.imageAttachments.map({ string($0, "id") }) == submittedImages {
        self.imageAttachments = []
      }
      self.selectJob(id, restoreConnection: false)
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
    queueAction(
      "queue.add",
      extra: [
        "prompt": draft, "harness": harness, "provider": provider, "model": model,
        "interaction_mode": interactionMode,
        "context_files": contextFiles, "image_ids": imageAttachments.map { string($0, "id") },
        "context_window": contextWindow.isEmpty ? 0 : Int(contextWindow) ?? -1,
        "enable_summarization": summarizeContext,
        "acp_options": ["model": agentModel, "mode": agentMode, "config": agentConfig],
      ])
    notice = "Adding task to the project queue"
  }
  func attachImages() {
    let panel = NSOpenPanel()
    panel.allowedContentTypes = [.image]
    panel.allowsMultipleSelection = true
    panel.prompt = "Attach images"
    guard panel.runModal() == .OK else { return }
    let paths = panel.urls.map(\.path)
    perform {
      for path in paths {
        guard self.imageAttachments.count < 4 else {
          throw EngineError(message: "Attach up to four images.")
        }
        let item =
          try await self.engine.call("images.stage", ["path": path]) as? [String: Any] ?? [:]
        self.imageAttachments.append(item)
      }
    }
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
    perform {
      guard self.imageAttachments.count < 4 else {
        throw EngineError(message: "Attach up to four images.")
      }
      try png.write(to: path, options: .atomic)
      defer { try? FileManager.default.removeItem(at: path) }
      let item =
        try await self.engine.call("images.stage", ["path": path.path]) as? [String: Any] ?? [:]
      self.imageAttachments.append(item)
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
        let page = record["events"] as? [[String: Any]] ?? []
        all += page
        guard page.count == 500, let seq = page.last?["sequence"] as? Int else { break }
        after = seq
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
  func loadFiles() {
    filesGeneration += 1
    let generation = filesGeneration
    let id = projectID
    guard !id.isEmpty else { return }
    perform {
      let files = try await self.engine.call("files.list", ["project": id]) as? [String] ?? []
      guard id == self.projectID, generation == self.filesGeneration else { return }
      self.files = files
    }
  }
  func shutdown() {
    saveDraft()
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
      report["performance"] = try await verifyResponsiveness()
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
      showWelcome = false
      guard draft == existingDraft else {
        throw EngineError(message: "Welcome navigation lost a draft")
      }
      report["welcome_navigation"] = "passed; project entry and draft-preserving return"
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
      guard currentAgentActivity(live).isEmpty, recents.count == 2,
        string(recents[0], "id") == "follow-up", string(recents[0], "conversation_title") == "Original request"
      else { throw EngineError(message: "Completed commands remained live or follow-ups duplicated recent rows") }
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
            AgentWorkingCard(status: "running", progress: agentProgress([
              toolEvent("plan", ["entries": [["content": "Inspect the project", "status": "completed"], ["content": "Run the test suite", "status": "in_progress"]]]),
              toolEvent("tool_call", ["toolCallId": "preview", "title": "Shell", "rawInput": ["command": "python -m unittest -v"]]),
            ]), startedAt: Date().addingTimeInterval(-42))
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
        ] {
          try await captureConnectionPage(page, directory: destination)
        }
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
            "project": projectID, "harness": harness, "provider": "ollama",
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
      do {
        _ = try await engine.call("files.read", ["project": projectID, "path": "../outside.txt"])
        throw EngineError(message: "File boundary was not enforced")
      } catch let failure as EngineError {
        guard failure.message != "File boundary was not enforced" else { throw failure }
        report["file_boundary"] = "passed"
      }
      chooseHarness("no-tool")
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
      let review = try await engine.call("git.review", ["project": projectID]) as? [String: Any] ?? [:]
      guard (review["files"] as? [[String: Any]] ?? []).contains(where: { string($0, "path") == "Sources/New.swift" }) else {
        throw EngineError(message: "Change review omitted an untracked source file")
      }
      let fileReview = try await engine.call("git.review", ["project": projectID, "path": "Sources/New.swift"]) as? [String: Any] ?? [:]
      guard string(fileReview, "diff").contains("+let ready = true") else { throw EngineError(message: "Change review did not show new source content") }
      let completion = try await engine.call("jobs.summary", ["id": taskID]) as? [String: Any] ?? [:]
      guard string(completion, "id") == taskID, completion["changes_recorded"] as? Bool == true else {
        throw EngineError(message: "Task completion did not load recorded checkpoint evidence")
      }
      report["change_review_completion"] = "passed; untracked source diff and sealed task checkpoint evidence"

      await refreshJobs()
      let args = ProcessInfo.processInfo.arguments
      for tab in [
        "Workspace", "Harness Hub", "Models", "Evaluations", "Optimization", "Files", "Tools",
        "Terminal", "Checkpoints",
      ] {
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
        try await captureDeveloperViews(directory: URL(fileURLWithPath: args[index + 1]))
        report["developer_views"] = "passed; native change review, connection health and task completion render in light and dark"
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
    for index in 0..<1000 { preview.draftStore.text = "Draft \(index)" }
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
      throw EngineError(message: "Engine I/O blocked the UI heartbeat for more than 250 ms")
    }
    return ["draft_edits": 1000, "workspace_invalidations": workspaceChanges,
            "stream_characters": 614400, "stream_projection_ms": renderMS,
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
    func press(_ identifier: String) async throws {
      for _ in 0..<150 {
        var active = main.attachedSheet
        while let nested = active?.attachedSheet { active = nested }
        let sheet = active ?? main
        if let surface = sheet.contentView,
          let button = control(identifier, in: surface) {
          guard button.isEnabled, button.bounds.width > 0, button.bounds.height > 0,
            let hit = surface.hitTest(button.convert(
              NSPoint(x: button.bounds.midX, y: button.bounds.midY), to: surface.superview)),
            hit === button || hit.isDescendant(of: button)
              || (hit as? NSButton)?.identifier == button.identifier
          else { throw EngineError(message: "Connect control cannot receive clicks: " + identifier) }
          // Deliver a click through this test window's normal event dispatch,
          // rather than invoking the button action directly. No global mouse
          // input, accessibility permission or other app is involved.
          let point = button.convert(NSPoint(x: button.bounds.midX, y: button.bounds.midY), to: nil)
          let timestamp = ProcessInfo.processInfo.systemUptime
          guard let down = NSEvent.mouseEvent(
            with: .leftMouseDown, location: point, modifierFlags: [], timestamp: timestamp,
            windowNumber: sheet.windowNumber, context: nil, eventNumber: 1, clickCount: 1, pressure: 1),
            let up = NSEvent.mouseEvent(
              with: .leftMouseUp, location: point, modifierFlags: [], timestamp: timestamp + 0.01,
              windowNumber: sheet.windowNumber, context: nil, eventNumber: 2, clickCount: 1, pressure: 0)
          else { throw EngineError(message: "Could not construct the native click test") }
          NSApp.postEvent(up, atStart: true)
          sheet.sendEvent(down)
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
    ])
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
    try await press("notice.close")
    try await press("attachment.file.fixture-a.txt")
    try await press("attachment.image.ui-image")
    guard notice.isEmpty, contextFiles == ["fixture-b.txt"], imageAttachments.isEmpty else {
      throw EngineError(message: "Attachment or notification X removed the wrong item")
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
    let view = NSHostingView(
      rootView: ConnectionView(initialPage: page).environmentObject(self).preferredColorScheme(
        .dark))
    panel.contentView = view
    panel.orderFront(nil)
    defer { panel.close() }
    try await Task.sleep(for: .milliseconds(450))
    view.layoutSubtreeIfNeeded()
    guard let bitmap = view.bitmapImageRepForCachingDisplay(in: view.bounds) else {
      throw EngineError(message: "Connect view could not render")
    }
    view.cacheDisplay(in: view.bounds, to: bitmap)
    guard let png = bitmap.representation(using: .png, properties: [:]) else {
      throw EngineError(message: "Connect view render failed")
    }
    try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
    try png.write(
      to: directory.appendingPathComponent(
        "connect-" + page.replacingOccurrences(of: ":", with: "-") + ".png"))
  }
  private func captureDeveloperViews(directory: URL) async throws {
    for dark in [false, true] {
      let views: [(String, AnyView, CGFloat, CGFloat)] = [
        ("change-review", AnyView(ChangeReviewView().environmentObject(self)), 1020, 650),
        ("connection-health", AnyView(ConnectionHealthView().environmentObject(self)), 670, 520),
        ("task-completion", AnyView(TaskCompletionView().environmentObject(self).padding(20)), 800, 260),
      ]
      for (name, view, width, height) in views {
        let host = NSHostingView(rootView: view.frame(width: width, height: height, alignment: .topLeading)
          .background(Color.qPanel).environment(\.colorScheme, dark ? .dark : .light))
        host.appearance = NSAppearance(named: dark ? .darkAqua : .aqua)
        let panel = NSWindow(contentRect: NSRect(x: 0, y: 0, width: width, height: height), styleMask: [.borderless], backing: .buffered, defer: false)
        panel.appearance = host.appearance; panel.contentView = host; panel.orderFront(nil)
        defer { panel.orderOut(nil); panel.contentView = nil }
        try await Task.sleep(for: .milliseconds(500))
        host.layoutSubtreeIfNeeded(); host.displayIfNeeded()
        guard let bitmap = host.bitmapImageRepForCachingDisplay(in: host.bounds) else { throw EngineError(message: "Developer view did not render") }
        host.cacheDisplay(in: host.bounds, to: bitmap)
        guard let png = bitmap.representation(using: .png, properties: [:]) else { throw EngineError(message: "Developer view capture failed") }
        try png.write(to: directory.appendingPathComponent(name + (dark ? "-dark.png" : "-light.png")))
      }
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
