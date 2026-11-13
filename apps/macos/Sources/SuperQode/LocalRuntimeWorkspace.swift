import AppKit
import SwiftUI

/// Keep URL edits in a stable native field, including across hidden-page updates.
struct LocalRuntimeEndpointField: NSViewRepresentable {
  @Binding var value: String
  @Environment(\.isEnabled) private var enabled

  final class Coordinator: NSObject, NSTextFieldDelegate {
    var parent: LocalRuntimeEndpointField
    init(_ parent: LocalRuntimeEndpointField) { self.parent = parent }

    func controlTextDidChange(_ notification: Notification) {
      guard let field = notification.object as? NSTextField, field.isEnabled else { return }
      parent.value = field.stringValue
    }

    func update(_ field: NSTextField, parent: LocalRuntimeEndpointField, enabled: Bool) {
      self.parent = parent
      if field.stringValue != parent.value { field.stringValue = parent.value }
      if field.isEnabled != enabled { field.isEnabled = enabled }
      if !enabled && field.currentEditor() != nil { field.window?.makeFirstResponder(nil) }
    }
  }

  func makeCoordinator() -> Coordinator { Coordinator(self) }
  func makeNSView(context: Context) -> NSTextField {
    let field = NSTextField()
    field.identifier = NSUserInterfaceItemIdentifier("local.runtime.endpoint")
    field.setAccessibilityIdentifier("local.runtime.endpoint")
    field.placeholderString = "Local base URL, e.g. http://127.0.0.1:8000/v1"
    field.isEditable = true
    field.isSelectable = true
    field.isBezeled = true
    field.drawsBackground = true
    field.bezelStyle = .roundedBezel
    field.setContentHuggingPriority(.defaultLow, for: .horizontal)
    field.setAccessibilityLabel("Local base URL")
    field.delegate = context.coordinator
    context.coordinator.update(field, parent: self, enabled: enabled)
    return field
  }
  func updateNSView(_ field: NSTextField, context: Context) {
    context.coordinator.update(field, parent: self, enabled: enabled)
  }
}

@MainActor final class LocalRuntimeLibrary: ObservableObject {
  @Published var profiles: [[String: Any]] = []
  @Published var templates: [[String: Any]] = []
  @Published var performance: [String: Any] = [:]
  @Published var failure = ""
  func load(_ engine: Engine) async {
    do {
      let result = try await engine.call("local.runtimes.catalog") as? [String: Any] ?? [:]
      guard !Task.isCancelled else { return }
      profiles = result["profiles"] as? [[String: Any]] ?? []
      templates = result["templates"] as? [[String: Any]] ?? []
    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
  }
  func refreshPerformance(_ engine: Engine) async {
    do {
      let value = try await engine.call("local.execution.status") as? [String: Any] ?? [:]
      guard !Task.isCancelled else { return }
      if !NSDictionary(dictionary: performance).isEqual(to: value) { performance = value }
    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
  }
}

struct LocalRuntimeWorkspace: View {
  @EnvironmentObject var app: Workspace
  var active = true
  @StateObject private var library = LocalRuntimeLibrary()
  @State private var restoringProfile = false
  @State private var template = "vllm-metal"
  @State private var identity = UUID().uuidString.lowercased()
  @State private var name = "vLLM Metal"
  @State private var endpoint = "http://127.0.0.1:8000/v1"
  @State private var context = 8192
  @State private var capability = "unknown"
  @State private var apiKey = ""
  @State private var rememberKey = false
  @State private var includeUsage = true
  @State private var models: [[String: Any]] = []
  @State private var model = ""
  @State private var coding = false
  @State private var harness = "core"
  @State private var harnesses: [[String: Any]] = []
  @State private var busy = false
  @State private var message = ""
  @State private var setup: [String: Any] = [:]
  @State private var showSetup = false
  @State private var servers: [[String: Any]] = []
  @State private var serverAction: [String: Any]?
  @State private var serverConnection: String?
  @State private var operation = ""
  @State private var operationDetail: [String: Any] = [:]
  @State private var operationAfter = 0
  @State private var pollingOperation = false

  private var selected: [String: Any] { library.profiles.first { string($0, "id") == identity } ?? [:] }
  private var jobRunning: Bool { ["queued", "running", "cancelling", "needs_approval"].contains(string(operationDetail, "status")) }
  private var projectReady: Bool { !app.projectID.isEmpty && !app.openingProject }

  var body: some View {
    content
    .task(id: String(active) + "\n" + String(app.connected)) {
      guard active, app.connected else { return }
      await library.load(app.engine)
      await refreshServers()
      if projectReady { await loadHarnesses() }
      await restoreOperation()
      while !Task.isCancelled {
        await library.refreshPerformance(app.engine)
        await pollOperation()
        do { try await Task.sleep(for: .seconds(2)) } catch { return }
      }
    }
    .onChange(of: app.projectID) { _, _ in models = []; model = ""; Task { await loadHarnesses() } }
    .onChange(of: active) { _, visible in
      if !visible { serverAction = nil; serverConnection = nil; showSetup = false; benchmark = false }
    }
    .centeredDialog(isPresented: Binding(get: { serverAction != nil }, set: { if !$0 { serverAction = nil } }),
      title: "Review local operation", onDismiss: { Task { await refreshServers() } }) {
      if let serverAction { LocalModelActionView(request: serverAction).environmentObject(app) }
    }
    .centeredDialog(isPresented: Binding(get: { serverConnection != nil }, set: { if !$0 { serverConnection = nil } }),
      title: "Use a local model") {
      if let serverConnection { LocalModelConnectionView(engine: serverConnection, project: app.projectID).environmentObject(app) }
    }
    .centeredDialog(isPresented: $showSetup, title: "Review runtime installation") {
      VStack(alignment: .leading, spacing: 16) {
        Text("Install " + string(setup, "name")).font(.title2)
        Text(string(setup, "guidance"))
        ForEach(setup["commands"] as? [String] ?? [], id: \.self) { command in
          Text(command).font(.caption.monospaced()).textSelection(.enabled)
        }
        Text("Homebrew changes its managed installation. Stopping can leave partial packages; retry the reviewed install to finish. No model weights or provider keys are used.").font(.caption).foregroundStyle(.secondary)
        HStack {
          Button("Cancel") { showSetup = false }
          Spacer()
          Button("Install runtime") { startInstall() }.buttonStyle(BrandButtonStyle())
            .disabled(setup["automatic"] as? Bool != true || busy || app.anyActive)
        }
      }.padding(24).frame(width: 650)
    }
    .centeredDialog(isPresented: $benchmark, title: "Local benchmarks") {
      ToolsView(workflow: "local bench").environmentObject(app).frame(width: 920, height: 680)
    }
  }
  @State private var benchmark = false

  private var content: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Text("Runtimes & performance").font(.title2.weight(.semibold))
        Spacer()
        Button("Refresh runtimes") { Task { await refreshServers() } }
      }
      LocalExecutionPanel(value: library.performance) { limit in
        app.perform {
          _ = try await app.engine.call("local.execution.configure", ["concurrency": limit])
          await library.refreshPerformance(app.engine)
        }
      }
      LazyVGrid(columns: [GridItem(.adaptive(minimum: 230), spacing: 10)], spacing: 10) {
        ForEach(servers, id: \.projectRowID) { row in
          LocalServerCard(row: row, onOperation: { serverAction = $0 }, onConnect: { serverConnection = $0 })
        }
      }
      runtimePanel
      if !operation.isEmpty { operationPanel }
      if !message.isEmpty { Text(message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled) }
      if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.orange).textSelection(.enabled) }
      HStack {
        Button("Harness evaluations") { app.section = "Evaluations" }.disabled(!projectReady)
        Button("Local benchmarks") { benchmark = true }.disabled(!projectReady)
      }
    }
  }

  private func refreshServers() async {
    do {
      let result = try await app.engine.call("local.models.servers") as? [[String: Any]] ?? []
      if !Task.isCancelled { servers = result }
    } catch { if !Task.isCancelled { library.failure = error.localizedDescription } }
  }

  private var runtimePanel: some View {
    VStack(alignment: .leading, spacing: 14) {
      HStack {
        Text("Other local inference servers").font(.title3.weight(.semibold))
        Spacer()
        Button("New profile") { reset() }.disabled(busy)
      }
      Text("Keep your existing server. Profiles connect only to this Mac's loopback addresses; redirects and remote hosts are refused.")
        .font(.caption).foregroundStyle(.secondary)
      if !library.profiles.isEmpty {
        ScrollView(.horizontal) {
          HStack {
            ForEach(library.profiles, id: \.projectRowID) { row in
              Button(string(row, "name")) { select(row) }.buttonStyle(.bordered)
                .tint(identity == string(row, "id") ? Color.qAccent : .secondary)
            }
          }
        }
      }
      HStack {
        CatalogPopup(label: "Setup template", options: [
          CatalogPopupOption(id: "vllm-metal", title: "vLLM Metal"),
          CatalogPopupOption(id: "omlx", title: "oMLX"),
          CatalogPopupOption(id: "jan", title: "Jan"),
          CatalogPopupOption(id: "gpt4all", title: "GPT4All"),
          CatalogPopupOption(id: "custom", title: "Other compatible server"),
        ], selection: $template, placeholder: "Choose a setup template")
        .onChange(of: template) { _, next in
          if restoringProfile { restoringProfile = false; return }
          if let row = library.templates.first(where: { string($0, "id") == next }) {
            identity = UUID().uuidString.lowercased(); name = string(row, "name"); endpoint = string(row, "endpoint")
            capability = next == "gpt4all" ? "no" : "unknown"; apiKey = ""; rememberKey = false; models = []; model = ""; setup = [:]
          }
        }
        TextField("Profile name", text: $name).textFieldStyle(.roundedBorder)
      }
      LocalRuntimeEndpointField(value: $endpoint).frame(maxWidth: .infinity).frame(height: 24)
      HStack {
        SecureField("Local API key (optional)", text: $apiKey).textFieldStyle(.roundedBorder)
        Toggle("Save in Keychain", isOn: $rememberKey).toggleStyle(.checkbox)
      }
      if selected["key_configured"] as? Bool == true {
        HStack {
          Text("A key is configured for this app session.").font(.caption).foregroundStyle(.secondary)
          Button("Remove key") { removeKey() }.font(.caption).disabled(busy)
        }
      }
      HStack {
        Text("Context cap").font(.caption)
        CatalogPopup(label: "Context cap", options: [2048, 4096, 8192, 16384, 32768, 65536].map {
          CatalogPopupOption(id: String($0), title: $0.formatted())
        }, selection: Binding(get: { String(context) }, set: { if let value = Int($0) { context = value } }), placeholder: "Choose a context cap")
        Text("Tool support").font(.caption)
        CatalogPopup(label: "Tool capability", options: [
          CatalogPopupOption(id: "unknown", title: "Unknown · check first"),
          CatalogPopupOption(id: "yes", title: "Declared supported"),
          CatalogPopupOption(id: "no", title: "Chat only"),
        ], selection: $capability, placeholder: "Choose tool support")
      }
      Toggle("Request token usage from this server", isOn: $includeUsage).font(.caption)
      Text("Disable usage reporting only if an older server rejects stream_options. Missing token counts are shown as unknown.")
        .font(.caption2).foregroundStyle(.secondary)
      Text("Set the context to what the server actually loaded. A model's advertised maximum is not its loaded memory allocation. Keys stay in this session or your Mac Keychain.")
        .font(.caption).foregroundStyle(.secondary)
      HStack {
        Button("Save profile") { saveProfile() }.buttonStyle(BrandButtonStyle()).disabled(busy || jobRunning)
        Button("Check server & models") { probe() }.disabled(busy || !savedReady || jobRunning)
        Button("Installation & setup…") { reviewInstall() }.disabled(busy || !savedReady || app.anyActive)
        if let guide = guideURL { Link("Vendor guide", destination: guide) }
      }
      if !models.isEmpty {
        Divider()
        CatalogPopup(label: "Advertised model", options: models.map {
          CatalogPopupOption(id: string($0, "id"), title: string($0, "id"))
        }, selection: $model, placeholder: "Choose a model")
        if let row = models.first(where: { string($0, "id") == model }) {
          Text("Context cap: \(row["context"] ?? context) · " + string(row, "context_source")).font(.caption).foregroundStyle(.secondary)
        }
        Toggle("Use a coding harness", isOn: $coding)
        if coding {
          Picker("Harness", selection: $harness) {
            ForEach(harnesses.filter { $0["selectable"] as? Bool == true }, id: \.projectRowID) { row in Text(string(row, "name")).tag(string(row, "id")) }
          }
          Text("Run the read-only tool check first. It inspects generated-data arguments without executing tools or reading project files.").font(.caption).foregroundStyle(.secondary)
        }
        HStack {
          Button("Warm model") { startWarmup() }.disabled(busy || !savedReady || !projectReady || model.isEmpty || app.anyActive)
          Button("Run tool check") { startCheck() }.disabled(busy || !savedReady || !projectReady || model.isEmpty || app.anyActive || capability == "no")
          Spacer()
          Button(coding ? "Use for coding" : "Use for chat") { connect() }.buttonStyle(BrandButtonStyle())
            .disabled(busy || !savedReady || !projectReady || model.isEmpty || app.anyActive || (coding && !toolCheckPassed))
        }
        if !projectReady { Text("Open a project to run a check or start a conversation.").font(.caption).foregroundStyle(.secondary) }
      }
      if busy { ProgressView("Working with local runtime…").controlSize(.small) }
    }.padding(18).brandSurface().disabled(busy)
  }

  private var guideURL: URL? {
    let row = library.templates.first { string($0, "id") == template } ?? [:]
    guard let url = URL(string: string(row, "docs_url")), url.scheme == "https" else { return nil }
    return url
  }
  private var toolCheckPassed: Bool {
    let checks = selected["checks"] as? [String: [String: Any]] ?? [:]
    return checks[model]?["tool_call_success"] as? Bool == true
  }
  private var operationPanel: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        if jobRunning { ProgressView().controlSize(.small) }
        Text(string(operationDetail, "title", "Local operation") + " · " + string(operationDetail, "status"))
        Spacer()
        if jobRunning { Button("Stop") { app.perform { _ = try await app.engine.call("jobs.cancel", ["id": operation]) } } }
      }
      let result = operationDetail["result"] as? [String: Any] ?? [:]
      if let check = result["verification"] as? [String: Any] {
        Text(check["tool_call_success"] as? Bool == true ? "Tool shape check passed. Coding quality still needs evaluation." : "The model did not produce the expected tool call. Use chat or review its parser/model setup.")
          .font(.callout)
        if !string(result, "verification_stale").isEmpty { Text(string(result, "verification_stale")).foregroundStyle(.orange) }
      }
      DisclosureGroup("Operation output") {
        Text((operationDetail["events"] as? [[String: Any]] ?? []).suffix(40).compactMap { row -> String? in
          let data = row["data"] as? [String: Any] ?? [:]
          return data["text"] as? String ?? data["message"] as? String
        }.joined(separator: "\n")).font(.caption.monospaced()).textSelection(.enabled)
      }
    }.padding(16).brandSurface()
  }
  private func action(_ work: @escaping @MainActor () async throws -> Void) {
    busy = true; library.failure = ""
    Task { defer { busy = false }; do { try await work() } catch { library.failure = error.localizedDescription } }
  }
  private func reset() {
    identity = UUID().uuidString.lowercased(); name = "Local server"; template = "custom"
    endpoint = "http://127.0.0.1:8000/v1"; context = 8192; capability = "unknown"
    apiKey = ""; rememberKey = false; includeUsage = true; models = []; model = ""; coding = false; setup = [:]
    setOperation("")
  }
  private func select(_ row: [String: Any]) {
    let next = string(row, "template", "custom")
    restoringProfile = template != next; template = next
    identity = string(row, "id"); name = string(row, "name"); endpoint = string(row, "endpoint")
    context = row["context"] as? Int ?? 8192; includeUsage = row["include_usage"] as? Bool ?? true; rememberKey = row["remember_key"] as? Bool == true
    capability = row["tools"] as? Bool == true ? "yes" : row["tools"] as? Bool == false ? "no" : "unknown"
    models = []; model = ""; apiKey = ""; setup = [:]
    Task { await restoreOperation() }
  }
  private var savedReady: Bool {
    let savedCapability = selected["tools"] as? Bool == true ? "yes" : selected["tools"] as? Bool == false ? "no" : "unknown"
    return !selected.isEmpty && name == string(selected, "name") && endpoint == string(selected, "endpoint")
      && context == (selected["context"] as? Int) && template == string(selected, "template", "custom")
      && capability == savedCapability && includeUsage == (selected["include_usage"] as? Bool ?? true) && apiKey.isEmpty && rememberKey == (selected["remember_key"] as? Bool == true)
  }
  private func saveProfile() {
    action {
      let keyValue = apiKey
      var params: [String: Any] = ["id": identity, "name": name, "template": template, "endpoint": endpoint, "context": context, "remember_key": rememberKey, "include_usage": includeUsage]
      if capability == "unknown" { params["tools"] = NSNull() }
      else { params["tools"] = capability == "yes" }
      if rememberKey && keyValue.isEmpty && selected["key_configured"] as? Bool == true && selected["remember_key"] as? Bool != true {
        throw EngineError(message: "Reenter the local key to save it in Keychain. It can stay in the current session without saving.")
      }
      let saved = try await app.engine.call("local.runtimes.save", params) as? [String: Any] ?? [:]
      endpoint = string(saved, "endpoint", endpoint)
      if !rememberKey && keyValue.isEmpty {
        let store = app.credentialStore; let account = "local-runtime:" + identity
        try await Task.detached { try store.remove(account) }.value
      }
      if !keyValue.isEmpty {
        let store = app.credentialStore; let account = "local-runtime:" + identity
        if rememberKey { try await Task.detached { try store.save(account, key: keyValue) }.value }
        else { try await Task.detached { try store.remove(account) }.value }
        _ = try await app.engine.call("local.runtimes.key", ["id": identity, "key": keyValue])
        apiKey = ""
      }
      await library.load(app.engine); await loadHarnesses(); message = "Profile saved. Check the server to choose a model."
    }
  }
  private func removeKey() {
    action {
      let store = app.credentialStore; let account = "local-runtime:" + identity
      try await Task.detached { try store.remove(account) }.value
      _ = try await app.engine.call("local.runtimes.key", ["id": identity, "key": NSNull()])
      apiKey = ""; await library.load(app.engine)
    }
  }
  private func probe() {
    action {
      let result = try await app.engine.call("local.runtimes.probe", ["id": identity]) as? [String: Any] ?? [:]
      models = result["models"] as? [[String: Any]] ?? []; model = models.first.map { string($0, "id") } ?? ""
      message = models.isEmpty ? "Server answered but advertised no chat models. Load a model in the vendor app, then check again." : "Server models found. No model prompt was sent."
    }
  }
  private func connect() {
    action {
      let project = app.projectID
      let profileID = identity
      let selectedModel = model
      let useCoding = coding
      let result = try await app.engine.call("local.runtimes.use", ["id": profileID, "project": project, "model": selectedModel, "harness": useCoding ? harness : "no-tool"]) as? [String: Any] ?? [:]
      guard project == app.projectID, !app.openingProject, profileID == identity, selectedModel == model, !app.anyActive else {
        message = "The selection changed while connecting. Choose the model again for this project."
        return
      }
      app.chooseHarness(string(result, "harness")); app.chooseModelRoute(string(result, "provider"), string(result, "model"))
      app.interactionMode = useCoding ? "code" : "chat"; app.section = "Workspace"
    }
  }
  private func startWarmup() {
    action {
      let job = try await app.engine.call("local.runtimes.warm", ["id": identity, "project": app.projectID, "model": model, "command_id": UUID().uuidString]) as? [String: Any] ?? [:]
      setOperation(string(job, "id")); await pollOperation()
    }
  }
  private func startCheck() {
    action {
      let job = try await app.engine.call("local.runtimes.test", ["id": identity, "project": app.projectID, "model": model, "command_id": UUID().uuidString]) as? [String: Any] ?? [:]
      setOperation(string(job, "id")); await pollOperation()
    }
  }
  private func reviewInstall() {
    action {
      setup = try await app.engine.call("local.runtimes.setup.plan", ["id": identity]) as? [String: Any] ?? [:]
      if setup["automatic"] as? Bool == true { showSetup = true }
      else { message = string(setup, "guidance") }
    }
  }
  private func startInstall() {
    showSetup = false
    action {
      let job = try await app.engine.call("local.runtimes.setup.start", ["id": identity, "project": app.projectID, "expected_digest": string(setup, "digest"), "command_id": UUID().uuidString]) as? [String: Any] ?? [:]
      setOperation(string(job, "id")); await pollOperation()
    }
  }
  private func loadHarnesses() async {
    guard projectReady else { harnesses = []; return }
    let project = app.projectID
    do {
      let rows = try await app.engine.call("local.runtimes.harnesses", ["id": identity, "project": project]) as? [[String: Any]] ?? []
      guard project == app.projectID, !Task.isCancelled else { return }
      harnesses = rows
    }
    catch { /* A new, unsaved profile can still be edited. */ }
  }
  private func restoreOperation() async {
    setOperation(string(selected, "last_operation_job", string(selected, "last_check_job")))
    await pollOperation()
  }
  private func setOperation(_ id: String) {
    guard operation != id else { return }
    operation = id; operationAfter = 0; operationDetail = [:]
  }
  private func pollOperation() async {
    guard !operation.isEmpty, !pollingOperation else { return }
    pollingOperation = true
    defer { pollingOperation = false }
    let id = operation
    do {
      var next = try await app.engine.call("jobs.get", ["id": id, "after": operationAfter]) as? [String: Any] ?? [:]
      guard id == operation, !Task.isCancelled else { return }
      let page = try JobEventPage(next, after: operationAfter)
      operationAfter = page.nextSequence
      let previous = operationDetail["events"] as? [[String: Any]] ?? []
      next["events"] = Array((previous + page.events).suffix(40))
      let finished = (operationDetail.isEmpty || jobRunning) && !["queued", "running", "cancelling", "needs_approval"].contains(string(next, "status"))
      if !NSDictionary(dictionary: operationDetail).isEqual(to: next) { operationDetail = next }
      if finished { await library.load(app.engine) }
    } catch { if !Task.isCancelled { library.failure = error.localizedDescription } }
  }
}

struct AppleLocalModelPanel: View {
  @EnvironmentObject var app: Workspace
  let project: String
  var active = true
  let onUse: () -> Void
  @State private var status: [String: Any] = [:]
  @State private var checking = false
  @State private var failure = ""

  private var available: Bool { status["available"] as? Bool == true }
  private var utility: Bool { status["utility_enabled"] as? Bool == true }
  private var canUse: Bool {
    available && !project.isEmpty && project == app.projectID && !app.openingProject && !app.anyActive
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Label("Apple on-device model", systemImage: "apple.logo").font(.headline)
        Spacer()
        Button(checking ? "Checking…" : "Check availability") { Task { await refresh() } }
          .disabled(checking || !app.connected)
      }
      Text(string(status, "guidance", "Requires macOS 26 or later and Apple Intelligence on a supported Mac."))
        .font(.callout).foregroundStyle(.secondary)
      if !failure.isEmpty { Text(failure).font(.caption).foregroundStyle(.orange) }
      HStack {
        if let url = URL(string: string(status, "docs_url")), url.scheme == "https" {
          Link("Apple setup guide", destination: url).font(.caption)
        }
        Spacer()
        Button("Use for chat") { use(development: false) }.disabled(!canUse)
        Button("Use for development") { use(development: true) }
          .buttonStyle(BrandButtonStyle()).disabled(!canUse)
      }
      DisclosureGroup("Apple model settings") {
        Text("Development uses the Apple on-device harness and your project’s file permissions. Use it for small read, write and edit tasks.")
          .font(.caption).foregroundStyle(.secondary)
        Toggle("Use for optional summaries and utility tasks", isOn: Binding(get: { utility }, set: { enabled in
          app.perform {
            let result = try await app.engine.call("local.apple.utility", ["enabled": enabled]) as? [String: Any] ?? [:]
            status["utility_enabled"] = result["utility_enabled"] as? Bool == true
          }
        })).disabled(checking || (!available && !utility))
      }
    }.padding(16).brandSurface()
      .accessibilityIdentifier("local.appleModel")
      .task(id: String(active) + "\n" + String(app.connected)) {
        if active && app.connected { await refresh() }
      }
  }

  private func use(development: Bool) {
    guard canUse else { return }
    app.chooseAppleModel(development: development)
    onUse()
  }

  private func refresh() async {
    guard !checking else { return }
    checking = true
    defer { checking = false }
    do {
      let result = try await app.engine.call("local.apple.status") as? [String: Any] ?? [:]
      guard !Task.isCancelled else { return }
      status = result; failure = ""
    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
  }
}
