import AppKit
import SwiftUI

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
  @State private var models: [[String: Any]] = []
  @State private var model = ""
  @State private var coding = false
  @State private var harness = "core"
  @State private var harnesses: [[String: Any]] = []
  @State private var busy = false
  @State private var message = ""
  @State private var apple: [String: Any] = [:]
  @State private var appleUtility = false
  @State private var setup: [String: Any] = [:]
  @State private var showSetup = false
  @State private var operation = ""
  @State private var operationDetail: [String: Any] = [:]

  private var selected: [String: Any] { library.profiles.first { string($0, "id") == identity } ?? [:] }
  private var jobRunning: Bool { ["queued", "running", "cancelling", "needs_approval"].contains(string(operationDetail, "status")) }
  private var projectReady: Bool { !app.projectID.isEmpty && !app.openingProject }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        PageTitle(eyebrow: "Local AI", title: "Runtimes & performance",
          subtitle: "Connect a local server, check its tools and see where your Mac spends time.")
        LocalExecutionPanel(value: library.performance) { limit in
          app.perform {
            _ = try await app.engine.call("local.execution.configure", ["concurrency": limit])
            await library.refreshPerformance(app.engine)
          }
        }
        applePanel
        runtimePanel
        if !operation.isEmpty { operationPanel }
        if !message.isEmpty { Text(message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled) }
        if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.orange).textSelection(.enabled) }
        HStack {
          Text("Compare real coding outcomes").font(.headline)
          Spacer()
          Button("Harness evaluations") { app.section = "Evaluations" }.disabled(!projectReady)
          Button("Local benchmarks") { app.section = "Models"; benchmark = true }.disabled(!projectReady)
        }
        Text("A tool-shape check does not certify coding quality. Compare identical tasks, model artifacts, context and cold/warm cache state before choosing a default.")
          .font(.caption).foregroundStyle(.secondary)
      }.padding(24)
    }
    .task(id: active) {
      guard active else { return }
      await library.load(app.engine)
      if projectReady { await loadHarnesses() }
      await restoreOperation()
      while !Task.isCancelled && active {
        await library.refreshPerformance(app.engine)
        await pollOperation()
        do { try await Task.sleep(for: .seconds(2)) } catch { return }
      }
    }
    .onChange(of: app.projectID) { _, _ in models = []; model = ""; Task { await loadHarnesses() } }
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

  private var applePanel: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Image(systemName: "apple.logo").font(.title).foregroundStyle(Color.qAccent)
        VStack(alignment: .leading, spacing: 3) {
          Text("Apple on-device model").font(.headline)
          Text("Chat, summaries and lightweight tasks. No subscription or API key.").font(.caption).foregroundStyle(.secondary)
        }
        Spacer()
        Button("Check availability") {
          action {
            apple = try await app.engine.call("local.apple.status") as? [String: Any] ?? [:]
            appleUtility = apple["utility_enabled"] as? Bool == true
          }
        }.disabled(busy)
      }
      Text(string(apple, "guidance", "Requires a supported Mac, macOS 26+ and Apple Intelligence enabled. Apple's system model is separate from downloaded Qwen, GLM or Gemma weights."))
        .font(.callout).foregroundStyle(.secondary)
      Toggle("Use for optional summaries and utility tasks", isOn: Binding(get: { appleUtility }, set: { enabled in
        action {
          let result = try await app.engine.call("local.apple.utility", ["enabled": enabled]) as? [String: Any] ?? [:]
          appleUtility = result["utility_enabled"] as? Bool == true
        }
      })).disabled(busy || (apple["available"] as? Bool != true && !appleUtility))
      Text("Utility hooks include summaries and rubric grading. Validate grading quality before using scores as a release gate. If this native model becomes unavailable, its utility input is not silently sent to a cloud model.")
        .font(.caption).foregroundStyle(.secondary)
      HStack {
        Link("Apple setup guide", destination: URL(string: "https://support.apple.com/en-us/121115")!)
        Spacer()
        Button("Use for chat") {
          app.chooseHarness("no-tool")
          app.chooseModelRoute("apple-foundation", "system-on-device")
          app.interactionMode = "chat"; app.section = "Workspace"
          app.notice = "Apple on-device chat selected. Coding harnesses need a tool-capable model."
        }.buttonStyle(BrandButtonStyle())
          .disabled(apple["available"] as? Bool != true || !projectReady || app.anyActive)
      }
    }.padding(18).brandSurface()
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
        Picker("Setup template", selection: $template) {
          Text("vLLM Metal").tag("vllm-metal"); Text("oMLX").tag("omlx")
          Text("Jan").tag("jan"); Text("GPT4All").tag("gpt4all"); Text("Other compatible server").tag("custom")
        }.onChange(of: template) { _, next in
          if restoringProfile { restoringProfile = false; return }
          if let row = library.templates.first(where: { string($0, "id") == next }) {
            identity = UUID().uuidString.lowercased(); name = string(row, "name"); endpoint = string(row, "endpoint")
            capability = next == "gpt4all" ? "no" : "unknown"; apiKey = ""; rememberKey = false; models = []; model = ""; setup = [:]
          }
        }
        TextField("Profile name", text: $name).textFieldStyle(.roundedBorder)
      }
      TextField("Local base URL, e.g. http://127.0.0.1:8000/v1", text: $endpoint).textFieldStyle(.roundedBorder)
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
        Picker("Context cap", selection: $context) {
          ForEach([2048, 4096, 8192, 16384, 32768, 65536], id: \.self) { Text($0.formatted()).tag($0) }
        }
        Picker("Tool capability", selection: $capability) {
          Text("Unknown · check first").tag("unknown"); Text("Declared supported").tag("yes"); Text("Chat only").tag("no")
        }
      }
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
        Picker("Advertised model", selection: $model) {
          Text("Choose a model").tag("")
          ForEach(models, id: \.projectRowID) { row in Text(string(row, "id")).tag(string(row, "id")) }
        }
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
    }.padding(18).brandSurface()
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
    apiKey = ""; rememberKey = false; models = []; model = ""; coding = false; setup = [:]
  }
  private func select(_ row: [String: Any]) {
    let next = string(row, "template", "custom")
    restoringProfile = template != next; template = next
    identity = string(row, "id"); name = string(row, "name"); endpoint = string(row, "endpoint")
    context = row["context"] as? Int ?? 8192; rememberKey = row["remember_key"] as? Bool == true
    capability = row["tools"] as? Bool == true ? "yes" : row["tools"] as? Bool == false ? "no" : "unknown"
    models = []; model = ""; apiKey = ""; setup = [:]
    Task { await restoreOperation() }
  }
  private var savedReady: Bool {
    let savedCapability = selected["tools"] as? Bool == true ? "yes" : selected["tools"] as? Bool == false ? "no" : "unknown"
    return !selected.isEmpty && name == string(selected, "name") && endpoint == string(selected, "endpoint")
      && context == (selected["context"] as? Int) && template == string(selected, "template", "custom")
      && capability == savedCapability && apiKey.isEmpty && rememberKey == (selected["remember_key"] as? Bool == true)
  }
  private func saveProfile() {
    action {
      let keyValue = apiKey
      var params: [String: Any] = ["id": identity, "name": name, "template": template, "endpoint": endpoint, "context": context, "remember_key": rememberKey]
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
      let result = try await app.engine.call("local.runtimes.use", ["id": identity, "project": app.projectID, "model": model, "harness": coding ? harness : "no-tool"]) as? [String: Any] ?? [:]
      app.chooseHarness(string(result, "harness")); app.chooseModelRoute(string(result, "provider"), string(result, "model"))
      app.interactionMode = coding ? "code" : "chat"; app.section = "Workspace"
    }
  }
  private func startWarmup() {
    action {
      let job = try await app.engine.call("local.runtimes.warm", ["id": identity, "project": app.projectID, "model": model, "command_id": UUID().uuidString]) as? [String: Any] ?? [:]
      operation = string(job, "id"); await pollOperation()
    }
  }
  private func startCheck() {
    action {
      let job = try await app.engine.call("local.runtimes.test", ["id": identity, "project": app.projectID, "model": model, "command_id": UUID().uuidString]) as? [String: Any] ?? [:]
      operation = string(job, "id"); await pollOperation()
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
      operation = string(job, "id"); await pollOperation()
    }
  }
  private func loadHarnesses() async {
    guard projectReady else { harnesses = []; return }
    do { harnesses = try await app.engine.call("local.runtimes.harnesses", ["id": identity, "project": app.projectID]) as? [[String: Any]] ?? [] }
    catch { /* A new, unsaved profile can still be edited. */ }
  }
  private func restoreOperation() async {
    if !string(selected, "last_check_job").isEmpty { operation = string(selected, "last_check_job"); await pollOperation() }
  }
  private func pollOperation() async {
    guard !operation.isEmpty else { return }
    do {
      let next = try await app.engine.call("jobs.get", ["id": operation]) as? [String: Any] ?? [:]
      let finished = jobRunning && !["queued", "running", "cancelling", "needs_approval"].contains(string(next, "status"))
      if !NSDictionary(dictionary: operationDetail).isEqual(to: next) { operationDetail = next }
      if finished { await library.load(app.engine) }
    } catch { if !Task.isCancelled { library.failure = error.localizedDescription } }
  }
}
