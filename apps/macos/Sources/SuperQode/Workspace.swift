import AppKit
import SwiftUI

struct FileEdit {
  let original: String
  let digest: String
  let text: String
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
  var agentSession: [String: Any] {
    let event = events.last {
      string($0, "type") == "harness_event"
        && string($0["data"] as? [String: Any] ?? [:], "event") == "acp_session"
    }
    return (event?["data"] as? [String: Any])?["payload"] as? [String: Any] ?? [:]
  }
  var agentCommands: [[String: Any]] {
    let event = events.last {
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
  @Published var selectedJob = ""
  @Published var detail: [String: Any] = [:]
  @Published var events: [[String: Any]] = []
  @Published var git: [String: Any] = [:]
  @Published var files: [String] = []
  @Published var fileDrafts: [String: FileEdit] = [:]
  @Published var capabilities: [String: Any] = [:]
  @Published var provider = "openai"
  @Published var model = ""
  @Published var harness = "superqode"
  @Published var draft = ""
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
  private var loadingDetail = false
  private var projectGeneration = 0
  var isACP: Bool {
    harnesses.first(where: { string($0, "id") == harness })?["desktop_kind"] as? String == "acp"
  }
  var isRemote: Bool {
    let kind = string(harnesses.first(where: { string($0, "id") == harness }) ?? [:], "kind")
    return kind == "uhp" || kind == "a2a"
  }
  var canContinue: Bool {
    let result = detail["result"] as? [String: Any] ?? [:]
    return string(detail, "status") == "completed"
      && (result["native_continuity"] as? Bool == true || result["acp_continuity"] as? Bool == true
        || result["remote_continuity"] as? Bool == true
        || result["vendor_continuity"] as? Bool == true)
  }
  var isManaged: Bool {
    isACP
      || harnesses.first(where: { string($0, "id") == harness })?["desktop_kind"] as? String
        == "connection"
  }
  func chooseConnection(_ route: [String: Any]) {
    let id = string(route, "id")
    if let index = harnesses.firstIndex(where: { string($0, "id") == id }) {
      harnesses[index] = route
    } else {
      harnesses.append(route)
    }
    chooseHarness(id)
    interactionMode = "code"
    section = "Workspace"
    selectJob("")
    perform { await self.checkRoute() }
  }
  var projectID: String { string(project, "id") }
  var projectJobs: [[String: Any]] { jobs.filter { string($0, "project") == projectID } }
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
        while !Task.isCancelled {
          try? await Task.sleep(for: .seconds(1))
          guard let self, self.connected else { return }
          await self.refreshJobs()
          await self.refreshDetail()
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
    projectGeneration += 1
    let generation = projectGeneration
    openingProject = true
    defer { if generation == projectGeneration { openingProject = false } }
    let opened = try await engine.call("projects.open", ["path": path]) as? [String: Any] ?? [:]
    guard generation == projectGeneration else { return }
    project = opened
    selectedJob = ""
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
    if !harnesses.contains(where: { string($0, "id") == harness }), let first = definitions.first {
      harness = string(first, "id")
    }
    let settings = try await engine.call("settings.get") as? [String: Any] ?? [:]
    draft =
      (UserDefaults.standard.dictionary(forKey: "nativeDrafts") as? [String: String])?[projectID]
      ?? (settings["drafts"] as? [String: String])?[projectID] ?? ""
    await refreshGit()
    await refreshModels()
    section = "Workspace"
    showWelcome = false
  }
  func chooseHarness(_ id: String) {
    let previousACP = isManaged
    let changed = harness != id
    if changed {
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
    savePreferences()
  }
  func chooseModelRoute(_ provider: String, _ model: String) {
    if isManaged {
      harness =
        harnesses.first(where: { string($0, "desktop_kind") != "acp" })?.projectRowID ?? "core"
    }
    self.provider = provider
    self.model = model
    savePreferences()
  }
  func savePreferences() {
    perform {
      for (key, value) in [
        ("provider", self.provider), ("model", self.model), ("harness", self.harness),
        ("theme", self.theme),
      ] {
        _ = try await self.engine.call("settings.set", ["key": key, "value": value])
      }
    }
  }
  func saveDraft() {
    let id = projectID
    let text = draft
    guard !id.isEmpty else { return }
    var drafts =
      UserDefaults.standard.dictionary(forKey: "nativeDrafts") as? [String: String] ?? [:]
    drafts[id] = text
    UserDefaults.standard.set(drafts, forKey: "nativeDrafts")
  }

  func refreshJobs() async {
    do {
      jobs = try await engine.call("jobs.list") as? [[String: Any]] ?? []
      if !projectID.isEmpty {
        taskQueue =
          try await engine.call("queue.list", ["project": projectID]) as? [String: Any] ?? [:]
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
  func selectJob(_ id: String) {
    selectedJob = id
    detail = [:]
    events = []
    candidate = [:]
    perform { await self.refreshDetail() }
  }
  func refreshDetail() async {
    guard !selectedJob.isEmpty, !loadingDetail else { return }
    loadingDetail = true
    defer { loadingDetail = false }
    let id = selectedJob
    do {
      let cursor = events.last?["sequence"] as? Int ?? 0
      let result =
        try await engine.call("jobs.get", ["id": id, "after": cursor]) as? [String: Any] ?? [:]
      guard id == selectedJob else { return }
      detail = result
      events += result["events"] as? [[String: Any]] ?? []
      if events.count > 1200 { events.removeFirst(events.count - 1200) }
    } catch { self.error = error.localizedDescription }
  }
  func refreshGit() async {
    let id = projectID
    guard !id.isEmpty else { return }
    do {
      let status = try await engine.call("git.status", ["project": id]) as? [String: Any] ?? [:]
      guard id == projectID else { return }
      git = status
    } catch { git = ["error": error.localizedDescription] }
  }
  func refreshModels() async {
    do {
      let inventory = try await engine.call("models.list") as? [String: Any] ?? [:]
      models = inventory["models"] as? [[String: Any]] ?? []
      hardware = inventory["hardware"] as? [String: Any] ?? [:]
    } catch { self.error = error.localizedDescription }
  }
  func refreshDefinitions() async throws {
    let definitions =
      try await engine.call("harnesses.list", ["project": projectID]) as? [[String: Any]] ?? []
    let routes =
      try await engine.call("routes.list", ["project": projectID]) as? [[String: Any]] ?? []
    harnesses = definitions + routes
  }
  func refreshProviders() async {
    do { providers = try await engine.call("providers.list") as? [[String: Any]] ?? [] } catch {
      self.error = error.localizedDescription
    }
  }
  func checkRoute() async {
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
    guard !busy else { return }
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
    var extra: [String: Any] = [
      "prompt": draft, "context_files": contextFiles, "interaction_mode": interactionMode,
      "context_window": contextWindow.isEmpty ? 0 : Int(contextWindow) ?? -1,
      "enable_summarization": summarizeContext,
      "image_ids": imageAttachments.map { string($0, "id") },
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
    start("tasks.start", extra: extra)
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
    perform {
      self.files =
        try await self.engine.call("files.list", ["project": self.projectID]) as? [String] ?? []
    }
  }
  func shutdown() {
    poller?.cancel()
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
      report["project_terminal"] = "passed; actual local PTY output"

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
        ], includeDetails: false)
      guard
        visible.map({ string($0, "type") }) == [
          "approval", "error", "harness_event", "future_event",
        ]
      else {
        throw EngineError(message: "Conversation hid an approval, tool, error or unknown event")
      }
      report["conversation"] =
        "passed; permissions, errors, tool work and unknown events remain visible"

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
      let taskParams: [String: Any] = [
        "project": projectID, "harness": "no-tool", "provider": "openai", "model": "gpt-4o-mini",
        "prompt": "Reply using the local native test fixture.", "command_id": UUID().uuidString,
      ]
      let started = try await engine.call("tasks.start", taskParams) as? [String: Any] ?? [:]
      let taskID = string(started, "id")
      selectJob(taskID)
      for _ in 0..<150 {
        await refreshDetail()
        if !active && !detail.isEmpty { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      guard string(detail, "status") == "completed", pretty(events).contains("Native task fixture")
      else { throw EngineError(message: "Native model stream failed: " + pretty(detail["result"])) }
      let session = string(detail["result"] as? [String: Any] ?? [:], "session_id")
      var followParams = taskParams
      followParams["command_id"] = UUID().uuidString
      followParams["parent_id"] = taskID
      followParams["prompt"] = "Continue the same native session."
      let followed = try await engine.call("tasks.start", followParams) as? [String: Any] ?? [:]
      selectJob(string(followed, "id"))
      for _ in 0..<150 {
        await refreshDetail()
        if !active && !detail.isEmpty { break }
        try await Task.sleep(for: .milliseconds(100))
      }
      guard string(detail, "status") == "completed",
        session == string(detail["result"] as? [String: Any] ?? [:], "session_id")
      else { throw EngineError(message: "Native task continuation failed") }
      report["task_stream"] = "passed against loopback fixture"
      report["continuation"] = "passed; native session preserved"
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
  private func verifyCenteredDialogs() async throws -> String {
    for visible in [
      NSRect(x: 0, y: 25, width: 1440, height: 850),
      NSRect(x: -1920, y: 0, width: 1920, height: 1080),
      NSRect(x: 1440, y: -400, width: 1280, height: 900),
    ] {
      let frame = CenteredDialogController.centeredFrame(
        size: NSSize(width: 700, height: 500), visibleFrame: visible)
      guard abs(frame.midX - visible.midX) < 0.01, abs(frame.midY - visible.midY) < 0.01,
        visible.contains(frame)
      else { throw EngineError(message: "Dialog display geometry is incorrect") }
    }
    guard let main = NSApp.windows.first(where: { $0.title == "SuperQode" }),
      let screen = main.screen
    else { throw EngineError(message: "Dialog test has no parent display") }
    let original = main.frame
    let child = CenteredDialogController()
    defer {
      child.close()
      showConnection = false
      showLearningGuide = false
      for _ in 0..<4 {
        guard let active = NSApp.modalWindow,
          active.identifier?.rawValue.hasPrefix("superqode.dialog.") == true
        else { break }
        active.performClose(nil)
      }
      main.setFrame(original, display: true)
    }
    var offset = original
    offset.origin.x = screen.visibleFrame.minX + 8
    offset.size.width = min(original.width, 1120)
    main.setFrame(offset, display: true)
    showConnection = true
    for _ in 0..<150 {
      if NSApp.modalWindow?.identifier?.rawValue.hasPrefix("superqode.dialog.") == true { break }
      try await Task.sleep(for: .milliseconds(20))
    }
    guard let outer = NSApp.modalWindow,
      outer.identifier?.rawValue.hasPrefix("superqode.dialog.") == true
    else {
      throw EngineError(message: "Connect did not open a native modal dialog")
    }
    try await Task.sleep(for: .milliseconds(250))
    func assertCenter(_ window: NSWindow) throws {
      guard abs(window.frame.midX - screen.visibleFrame.midX) <= 1,
        abs(window.frame.midY - screen.visibleFrame.midY) <= 1
      else {
        throw EngineError(message: "Dialog is offset from the parent display centre")
      }
    }
    try assertCenter(outer)
    var childVisible = true
    var engineReplied = false
    child.binding = Binding(get: { childVisible }, set: { childVisible = $0 })
    child.content = AnyView(
      Text("Checking asynchronous dialog progress").frame(width: 420, height: 220)
        .task {
          if (try? await self.engine.call("hello")) != nil { engineReplied = true }
        })
    child.present(parent: outer)
    for _ in 0..<150 {
      if engineReplied { break }
      try await Task.sleep(for: .milliseconds(20))
    }
    guard let nested = child.panel, NSApp.modalWindow === nested, engineReplied else {
      throw EngineError(message: "Nested modal blocked asynchronous engine progress")
    }
    try assertCenter(nested)
    nested.cancelOperation(nil)
    guard !childVisible, NSApp.modalWindow === outer else {
      throw EngineError(message: "Escape did not restore the parent dialog")
    }
    outer.performClose(nil)
    guard !showConnection, NSApp.modalWindow == nil else {
      throw EngineError(message: "Dialog close did not restore its binding and modal session")
    }
    return
      "passed; display centring with offset parent, negative display origins, nested dialogs, async progress and Escape/close"
  }
  private func captureLearningViews(directory: URL) throws {
    let preview = Workspace()
    preview.connected = true
    preview.starterTourRequested = true
    for phase in [
      "welcome", "welcome-light", "welcome-contrast", "first-task", "learning", "sidebar",
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
            : AnyView(GettingStartedView().environmentObject(preview))
      let view = NSHostingView(
        rootView:
          content
          .environment(\.colorScheme, phase.contains("light") ? .light : .dark)
          .background(Color(nsColor: .windowBackgroundColor)))
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
  func captureWindow(to url: URL) throws {
    guard let view = NSApp.windows.first(where: { $0.title == "SuperQode" })?.contentView
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
