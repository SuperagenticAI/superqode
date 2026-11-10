import AppKit
import SwiftUI

struct ConnectionSourcesView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  @State private var mode = "Local model"
  @State private var selectedProvider = "openai"
  @State private var selectedModel = ""
  @State private var key = ""
  @State private var remember = true
  @State private var saving = false
  @State private var message = ""
  init(mode: String) { _mode = State(initialValue: mode) }
  private var cloudProviders: [[String: Any]] {
    app.providers.filter { provider in
      guard provider["key_supported"] as? Bool == true else { return false }
      let selected = app.harnesses.first { string($0, "id") == app.harness } ?? [:]
      if let allowed = selected["byok_providers"] as? [String] {
        return allowed.contains(string(provider, "id"))
      }
      return true
    }
  }
  private var featuredProviders: [[String: Any]] {
    cloudProviders.filter { ["deepseek", "qwen-cn", "qwen-intl", "alibaba", "moonshot", "zai", "zhipu", "minimax", "doubao", "siliconflow", "openrouter"].contains(string($0, "id")) }
  }
  private var cloud: [String: Any] {
    cloudProviders.first { string($0, "id") == selectedProvider } ?? [:]
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Picker("Model source", selection: $mode) {
        Text("Local model").tag("Local model")
        Text("Provider API key").tag("Provider API key")
      }.pickerStyle(.segmented)
      if mode == "Local model" {
        localContent.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
      } else {
        ScrollView {
          VStack(alignment: .leading, spacing: 20) {
            PageTitle(
              eyebrow: "Connect a model",
              title: "Use your API key",
              subtitle: "For "
                + string(
                  app.harnesses.first { string($0, "id") == app.harness } ?? [:], "name", app.harness))
            if cloudProviders.isEmpty {
              EmptyState(
                icon: "info.circle", title: "This model source needs different setup",
                detail:
                  "This harness does not declare an API provider supported by this picker. Go Back to choose another source, or use its terminal setup workflow."
              ).frame(height: 200)
            } else {
              cloudContent
            }
            if !message.isEmpty {
              Label(message, systemImage: "info.circle").font(.callout).foregroundStyle(.secondary)
                .textSelection(.enabled)
            }
            if saving { ProgressView().controlSize(.small) }
          }.frame(maxWidth: .infinity, alignment: .topLeading)
        }.defaultScrollAnchor(.top)
      }
    }.padding(28).frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
      .task(id: mode) {
        if mode == "Local model" { await app.refreshModels() }
      }
      .onAppear {
        if !cloudProviders.contains(where: { string($0, "id") == selectedProvider }),
          let first = cloudProviders.first
        {
          selectedProvider = string(first, "id")
        }
      }
      .onChange(of: mode) { _, _ in
        key = ""
        message = ""
      }
      .onChange(of: selectedProvider) { _, _ in
        key = ""
        selectedModel = selectedProvider == app.provider ? app.model : ""
        message = ""
      }
  }

  private var localContent: some View {
    InstalledLocalModelPicker(project: app.projectID, dismissOnUse: true)
      .id(app.projectID)
      .environmentObject(app)
  }

  private var cloudContent: some View {
    VStack(alignment: .leading, spacing: 16) {
      if !featuredProviders.isEmpty {
        Text("Chinese models and aggregators").font(.headline)
        Text("Choose a provider to see its key type, model examples and official setup guide. API keys and coding-plan subscriptions use different routes.")
          .font(.caption).foregroundStyle(.secondary)
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], alignment: .leading) {
          ForEach(featuredProviders, id: \.projectRowID) { provider in
            Button(string(provider, "name")) {
              selectedProvider = string(provider, "id")
            }.disabled(saving)
          }
        }
      }
      Picker("Provider", selection: $selectedProvider) {
        ForEach(cloudProviders, id: \.projectRowID) { row in
          Text(string(row, "name")).tag(string(row, "id"))
        }
      }
      if !string(cloud, "notes").isEmpty { Text(string(cloud, "notes")).font(.callout).foregroundStyle(.secondary) }
      if !string(cloud, "default_base_url").isEmpty {
        Text("Default endpoint: " + string(cloud, "default_base_url")).font(.caption.monospaced()).textSelection(.enabled)
      }
      Text("Key environment variable: " + (cloud["credential_variables"] as? [String] ?? []).joined(separator: " or "))
        .font(.caption).foregroundStyle(.secondary)
      if let url = URL(string: string(cloud, "docs_url")), url.scheme == "https", url.user == nil, url.password == nil {
        Link("Official provider setup and pricing", destination: url)
      }
      HStack {
        TextField("Model ID", text: $selectedModel).textFieldStyle(.roundedBorder)
        Menu("Catalog examples") {
          ForEach(cloud["example_models"] as? [String] ?? [], id: \.self) { model in
            Button(model) { selectedModel = model }
          }
        }
      }
      Text(
        "Examples come from the installed engine catalog. You can enter another model ID supported by this provider."
      ).font(.caption).foregroundStyle(.secondary)
      SecureField(
        cloud["credential_configured"] as? Bool == true
          ? "Credential configured · enter a key to replace it" : "API key", text: $key
      ).textFieldStyle(.roundedBorder)
      Toggle("Remember new key in macOS Keychain", isOn: $remember).disabled(key.isEmpty)
      Text(
        "Saved keys stay in this Mac’s Keychain. Session-only keys are discarded when the local engine exits. Saving a key does not verify it or send a model request."
      ).font(.caption).foregroundStyle(.secondary)
      if cloud["credential_configured"] as? Bool == true {
        Pill(title: "CREDENTIAL CONFIGURED · NOT VERIFIED", color: .orange)
      }
      HStack {
        Spacer()
        if app.savedCredentialProviders.contains(selectedProvider) {
          Button("Forget saved key", role: .destructive) {
            guard
              app.confirm(
                "Forget this provider key?",
                "Remove only the key saved by the native SuperQode app. Existing terminal credentials remain available.",
                button: "Forget key")
            else { return }
            saving = true
            Task {
              do {
                try await app.forgetCredential(selectedProvider)
                message = "App-owned key removed."
              } catch { message = error.localizedDescription }
              saving = false
            }
          }.disabled(saving)
        }
        Button("Use provider") { connect() }.buttonStyle(BrandButtonStyle())
          .disabled(
            saving || cloudProviders.isEmpty
              || selectedModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              || (key.isEmpty && cloud["credential_configured"] as? Bool != true))
      }
    }
  }

  private func connect() {
    saving = true
    message = ""
    let supplied = key
    Task {
      defer {
        key = ""
        saving = false
      }
      do {
        try await app.configureConnection(
          provider: selectedProvider, model: selectedModel, key: supplied, remember: remember)
        app.section = "Workspace"
        app.notice =
          "Provider selected. Credentials are configured; use Test model to verify execution."
        dismiss()
      } catch { message = error.localizedDescription }
    }
  }
}

func codingModel(_ identifier: String) -> Bool {
  !identifier.localizedCaseInsensitiveContains("embed")
    && !identifier.localizedCaseInsensitiveContains("rerank")
}
func modelName(_ identifier: String) -> String {
  if let range = identifier.range(of: #"^(ollama|lmstudio):"#, options: .regularExpression) {
    return String(identifier[range.upperBound...])
  }
  return identifier
}

/// Pick one installed local model and one harness, then start coding.
struct InstalledLocalModelPicker: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  var dismissOnUse = false
  /// Local AI keeps a prompt on this page. The connect sheet stays harness, model, then start.
  var showsPrompt = false
  @State private var models: [[String: Any]] = []
  @State private var engines: [[String: Any]] = []
  @State private var harnesses: [[String: Any]] = []
  @State private var harness = ""
  @State private var selected = ""
  @State private var failure = ""
  @State private var busy = false
  @State private var progress = ""
  @State private var showDownload = false
  @State private var step = "harness"
  @State private var prompt = ""
  @State private var serverRequest: [String: Any]?

  private var selectable: [[String: Any]] {
    harnesses.filter { $0["selectable"] as? Bool == true }
  }
  private var harnessRow: [String: Any]? {
    harnesses.first { string($0, "id") == harness }
  }
  private var needsInstall: Bool {
    guard let row = harnessRow else { return false }
    return row["selectable"] as? Bool != true && !string(row, "install_extra").isEmpty
  }
  private var visibleModels: [[String: Any]] {
    models.filter { row in
      let name = string(row, "model") + " " + string(row, "name")
      return !name.localizedCaseInsensitiveContains("mmproj")
    }
  }
  private var selectedRow: [String: Any]? {
    visibleModels.first { string($0, "id") == selected }
  }
  /// A local server job must not block coding. Agent runs still do.
  private var agentBusy: Bool {
    app.jobs.contains {
      string($0, "kind") != "local"
        && ["running", "needs_approval", "queued", "cancelling"].contains(string($0, "status"))
    }
  }
  private var canStart: Bool {
    guard !busy, !project.isEmpty, !harness.isEmpty, let row = selectedRow, !agentBusy else { return false }
    return row["advertised"] as? Bool == true || engineReady(string(row, "engine"))
  }
  private var outgoingPrompt: String {
    showsPrompt ? prompt.trimmingCharacters(in: .whitespacesAndNewlines) : ""
  }
  private var actionTitle: String {
    if !outgoingPrompt.isEmpty { return "Send" }
    guard let row = selectedRow else { return "Start coding" }
    if row["advertised"] as? Bool == true { return "Start coding" }
    return "Start and code"
  }

  private var preparing: Bool { busy && !progress.isEmpty }
  private var warmupSubject: String {
    if progress.localizedCaseInsensitiveContains("install") {
      return string(harnessRow ?? [:], "name")
    }
    return string(selectedRow ?? [:], "name", string(selectedRow ?? [:], "model"))
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      if preparing {
        ModelWarmupCard(message: progress, subject: warmupSubject)
      } else {
        Text(step == "harness" ? "Choose a harness" : "Choose a model").font(.title2.weight(.semibold))
        Text(step == "harness"
          ? "Step 1 of 2. Pick who writes the code. The models on this Mac come next."
          : "Step 2 of 2. Pick an Ollama or LM Studio model, then start coding.")
          .foregroundStyle(.secondary)
        if project.isEmpty {
          Text("Open a project first.").font(.callout).foregroundStyle(.secondary)
        } else if step == "harness" {
          harnessStep
        } else {
          modelStep
        }
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      if showsPrompt && step == "model" && !needsInstall && !preparing {
        TextField("Describe a change", text: $prompt, axis: .vertical)
          .lineLimit(2...5)
          .textFieldStyle(.roundedBorder)
          .disabled(busy)
          .accessibilityIdentifier("local.prompt")
      }
      if !preparing {
      HStack {
        if step == "model" {
          Button("Back") { step = "harness" }.disabled(busy)
            .accessibilityIdentifier("local.back")
        }
        Button("Refresh") { Task { await load() } }.disabled(busy)
        Spacer()
        if step == "model" && needsInstall {
          Button("Install and continue") { Task { await installSelected() } }
            .buttonStyle(BrandButtonStyle())
            .disabled(busy || project.isEmpty)
            .accessibilityIdentifier("local.install")
        } else if step == "model" {
          Button("Download a model…") { showDownload = true }.disabled(busy)
          if !needsInstall && !serverEngine.isEmpty {
            Button("Context and server…") { serverRequest = ["action": "serve", "engine": serverEngine] }
              .disabled(busy || agentBusy)
              .help("Set the context window and cache, then start the server. A server that is already running keeps its settings until you start it again.")
          }
          Button(actionTitle) { Task { await startCoding() } }
            .buttonStyle(BrandButtonStyle())
            .disabled(!canStart)
            .accessibilityIdentifier("local.startCoding")
        }
      }
      }
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .task(id: project) { await load() }
    .centeredDialog(isPresented: $showDownload, title: "Download a local model") {
      LocalQuickStartView(project: project, showInstalled: false).environmentObject(app)
    }
    .centeredDialog(
      isPresented: Binding(get: { serverRequest != nil }, set: { if !$0 { serverRequest = nil } }),
      title: "Review local operation"
    ) {
      if let serverRequest { LocalModelActionView(request: serverRequest).environmentObject(app) }
    }
  }

  /// The selected model's server, or the first installed runtime.
  private var serverEngine: String {
    if let row = selectedRow, !string(row, "engine").isEmpty { return string(row, "engine") }
    if let row = engines.first(where: { $0["installed"] as? Bool == true || $0["running"] as? Bool == true }) {
      return string(row, "id")
    }
    return ""
  }

  private var harnessStep: some View {
    Group {
      if harnesses.isEmpty && busy {
        ProgressView("Loading harnesses…").controlSize(.small)
      } else if harnesses.isEmpty && !busy {
        Text("No harness here can run an Ollama or LM Studio model yet.")
          .foregroundStyle(.secondary)
      } else {
        ScrollView {
          harnessGrid(harnesses)
        }.frame(maxHeight: 460)
      }
    }
  }

  private var modelStep: some View {
    VStack(alignment: .leading, spacing: 10) {
      if let row = harnessRow {
        Text(string(row, "name")).font(.headline)
        Text(string(row, "note")).font(.callout).foregroundStyle(.secondary)
      }
      if needsInstall {
        Text("SuperQode installs this harness in the app. You do not need to install SuperQode or uv yourself.")
          .foregroundStyle(.secondary)
      } else if visibleModels.isEmpty && !busy {
        Text("No installed Ollama or LM Studio chat models were found.")
          .foregroundStyle(.secondary)
      } else if !needsInstall {
        ScrollView {
          VStack(spacing: 8) {
            ForEach(visibleModels, id: \.projectRowID) { row in
              let active = selected == string(row, "id")
              Button {
                selected = string(row, "id")
                failure = ""
              } label: {
                HStack(spacing: 12) {
                  Image(systemName: active ? "largecircle.fill.circle" : "circle")
                    .foregroundStyle(active ? Color.qAccent : .secondary)
                  VStack(alignment: .leading, spacing: 2) {
                    Text(string(row, "name", string(row, "model"))).font(.headline).lineLimit(2)
                      .foregroundStyle(.primary)
                    Text(modelCaption(row)).font(.caption).foregroundStyle(.secondary)
                  }
                  Spacer(minLength: 0)
                }
                .padding(12)
                .background(.primary.opacity(active ? 0.08 : 0.04), in: RoundedRectangle(cornerRadius: 9))
                .overlay(
                  RoundedRectangle(cornerRadius: 9).stroke(active ? Color.qAccent : .clear, lineWidth: 1.5)
                )
              }
              .buttonStyle(.plain)
              .disabled(busy)
              .accessibilityAddTraits(active ? .isSelected : [])
            }
          }
        }.frame(maxHeight: 360)
        if let row = selectedRow { Text(readiness(row)).font(.callout).foregroundStyle(.secondary) }
      }
    }
  }

  private func harnessGrid(_ rows: [[String: Any]]) -> some View {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 168), spacing: 8)], spacing: 8) {
      ForEach(rows, id: \.projectRowID) { row in
        let id = string(row, "id")
        let active = harness == id
        Button {
          choose(id)
        } label: {
          VStack(alignment: .leading, spacing: 4) {
            Text(string(row, "name")).font(.system(size: 13, weight: .semibold)).lineLimit(2)
              .foregroundStyle(Color.primary)
            Text(string(row, "note")).font(.caption2).foregroundStyle(.secondary).lineLimit(3)
          }
          .padding(10)
          .frame(maxWidth: .infinity, minHeight: 72, alignment: .topLeading)
          .background(.primary.opacity(active ? 0.08 : 0.04), in: RoundedRectangle(cornerRadius: 9))
          .overlay(
            RoundedRectangle(cornerRadius: 9).stroke(active ? Color.qAccent : Color.secondary.opacity(0.35), lineWidth: active ? 1.5 : 1)
          )
        }
        .buttonStyle(.plain)
        .disabled(busy)
        .accessibilityIdentifier("local.harness." + id)
        .accessibilityAddTraits(active ? .isSelected : [])
      }
    }
  }

  private func choose(_ id: String) {
    harness = id
    failure = ""
    if !visibleModels.contains(where: { string($0, "id") == selected }) {
      selected = string(visibleModels.first ?? [:], "id")
    }
    step = "model"
  }

  private func modelCaption(_ row: [String: Any]) -> String {
    let engine = string(row, "engine") == "lmstudio" ? "LM Studio" : "Ollama"
    guard let size = row["size_gb"] as? Double, size > 0 else { return engine }
    return engine + " · " + String(format: "%.1f GB", size)
  }

  private func readiness(_ row: [String: Any]) -> String {
    let engine = string(row, "engine") == "lmstudio" ? "LM Studio" : "Ollama"
    if row["advertised"] as? Bool == true { return "\(engine) is ready. Start coding connects this model." }
    if engineReady(string(row, "engine")) {
      if row["server_running"] as? Bool == true && string(row, "engine") == "lmstudio" {
        return "LM Studio is open. Start and code will load this model, then connect it."
      }
      return "\(engine) is installed and stopped. Start and code will launch it, then connect this model."
    }
    return "Install \(engine) to use this model."
  }

  private func engineReady(_ id: String) -> Bool {
    guard let row = engines.first(where: { string($0, "id") == id }) else { return false }
    return row["installed"] as? Bool == true || row["running"] as? Bool == true
  }

  private func load() async {
    busy = true
    defer { busy = false }
    do {
      try await reloadModels()
      guard !Task.isCancelled else { return }
      if !project.isEmpty {
        harnesses = try await app.engine.call("local.models.harnesses", ["project": project]) as? [[String: Any]] ?? []
      }
      if !harness.isEmpty && !harnesses.contains(where: { string($0, "id") == harness }) {
        harness = ""
        step = "harness"
      }
      if step == "model" && !visibleModels.contains(where: { string($0, "id") == selected }) {
        selected = string(visibleModels.first ?? [:], "id")
      }
      failure = ""
    } catch { failure = error.localizedDescription }
  }

  private func installSelected() async {
    guard !project.isEmpty, needsInstall else { return }
    let name = string(harnessRow ?? [:], "name", "this harness")
    busy = true
    progress = "Installing \(name)…"
    defer { busy = false; progress = "" }
    do {
      let started = try await app.engine.call("local.models.install", [
        "project": project, "harness": harness,
      ]) as? [String: Any] ?? [:]
      if string(started, "status") == "completed" {
        await load()
        return
      }
      let id = string(started, "id")
      guard !id.isEmpty else { throw EngineError(message: "Could not start the install.") }
      for _ in 0..<600 {
        try await Task.sleep(for: .seconds(1))
        guard !Task.isCancelled else { throw CancellationError() }
        let status = try await app.engine.call(
          "local.models.install.status", ["id": id]
        ) as? [String: Any] ?? [:]
        if !string(status, "progress").isEmpty { progress = string(status, "progress") }
        let state = string(status, "status")
        if state == "completed" {
          await load()
          return
        }
        if state == "failed" {
          failure = string(status, "error", "The install did not finish.")
          return
        }
      }
      failure = "The install is still running. Press Install and continue again in a moment."
    } catch is CancellationError {
      return
    } catch {
      failure = error.localizedDescription
    }
  }

  private func reloadModels() async throws {
    let result = try await app.engine.call("local.models.installed") as? [String: Any] ?? [:]
    guard !Task.isCancelled else { return }
    models = result["models"] as? [[String: Any]] ?? []
    engines = result["engines"] as? [[String: Any]] ?? []
  }

  private func startCoding() async {
    guard !project.isEmpty, !harness.isEmpty, let row = selectedRow else { return }
    let outgoing = outgoingPrompt
    busy = true
    progress = "Connecting…"
    var deliver = false
    defer {
      busy = false
      progress = ""
      if deliver { app.send(continueSession: false) }
    }
    do {
      let ready = try await bringOnline(row)
      await app.refreshJobs()
      guard app.projectID == project, !Task.isCancelled else { return }
      let otherWork = app.jobs.contains {
        string($0, "kind") != "local"
          && ["running", "needs_approval", "queued", "cancelling"].contains(string($0, "status"))
      }
      guard !otherWork else {
        failure = "Finish the current run, then connect this model."
        return
      }
      let result = try await app.engine.call("local.models.use", [
        "project": project,
        "engine": string(ready, "engine"),
        "model": string(ready, "model"),
        "harness": harness,
      ]) as? [String: Any] ?? [:]
      guard app.projectID == project else { return }
      let harnessID = string(result, "harness", harness)
      let providerID = string(result, "provider")
      let modelID = string(result, "model")
      guard !harnessID.isEmpty, !modelID.isEmpty else {
        failure = "The model connected, but Agent Space did not receive it. Choose the harness and model again."
        return
      }
      progress = "Warming the model so your first question is ready…"
      try await app.warmLocalModel(
        endpoint: string(result, "endpoint"),
        model: modelID,
        server: string(ready, "engine")
      )
      guard app.projectID == project, !Task.isCancelled else { return }
      // Leave the old thread first. Opening it restores that thread's route and
      // leaves Send disabled when this Mac has no connection yet.
      app.selectJob("", restoreConnection: false)
      app.checkingConnection = false
      if let route = result["route"] as? [String: Any] {
        app.chooseConnection(route)
        guard app.harness == string(route, "id") else { return }
        app.provider = providerID
        app.model = modelID
        app.savePreferences()
      } else {
        app.chooseHarness(harnessID)
        app.chooseModelRoute(providerID, modelID)
      }
      guard !app.connectionDisconnected, !app.model.isEmpty else {
        failure = "The model connected, but Agent Space did not keep it. Choose the harness and model again."
        return
      }
      app.section = "Workspace"
      app.showWelcome = false
      let model = modelID
      let harnessName = selectable.first { string($0, "id") == harnessID }
        .map { string($0, "name") } ?? harnessID
      if outgoing.isEmpty {
        app.notice = "Connected \(model) with \(harnessName). Type your request, then press Send."
      } else {
        prompt = ""
        app.draft = outgoing
        deliver = true
      }
      if dismissOnUse { dismiss() }
    } catch is CancellationError {
      return
    } catch {
      failure = error.localizedDescription
    }
  }

  /// Start a stopped server, or load an LM Studio weight, then return the advertised model.
  private func bringOnline(_ row: [String: Any]) async throws -> [String: Any] {
    if row["advertised"] as? Bool == true { return row }
    let engine = string(row, "engine")
    let name = engine == "lmstudio" ? "LM Studio" : "Ollama"
    guard engineReady(engine) else {
      throw EngineError(message: "Install \(name) to use this model.")
    }
    if row["server_running"] as? Bool != true {
      progress = "Starting \(name)…"
      try await startServer(engine, model: string(row, "model"))
    }
    if let match = try await waitForAdvertised(row) { return match }
    if engine == "lmstudio" {
      progress = "Loading the model in LM Studio…"
      try await runLocal([
        "action": "load", "engine": "lmstudio", "model": string(row, "model"), "context": 8192,
      ])
      if let match = try await waitForAdvertised(row) { return match }
    }
    throw EngineError(message: "\(name) started, but this model is not available yet. Refresh and try again.")
  }

  private func startServer(_ engine: String, model: String) async throws {
    if engine == "lmstudio" || model.isEmpty {
      try await runLocal(["action": "serve", "engine": engine, "kv_cache": "auto", "context": 8192, "model": ""])
      return
    }
    do {
      _ = try await app.engine.call("local.models.prepare", [
        "action": "serve", "engine": engine, "kv_cache": "auto", "context": 8192, "model": model,
      ])
    } catch {
      try await runLocal(["action": "serve", "engine": engine, "kv_cache": "auto", "context": 8192, "model": ""])
      return
    }
    try await runLocal(["action": "serve", "engine": engine, "kv_cache": "auto", "context": 8192, "model": model])
  }

  private func runLocal(_ request: [String: Any]) async throws {
    let plan = try await app.engine.call("local.models.prepare", request) as? [String: Any] ?? [:]
    guard !string(plan, "id").isEmpty else { throw EngineError(message: "Could not prepare the local server.") }
    let job = try await app.engine.call("local.models.start", [
      "plan": string(plan, "id"),
      "expected_digest": string(plan, "digest"),
      "command_id": UUID().uuidString,
    ]) as? [String: Any] ?? [:]
    let id = string(job, "id")
    guard !id.isEmpty else { throw EngineError(message: "Could not start the local server.") }
    for _ in 0..<180 {
      try await Task.sleep(for: .seconds(1))
      guard !Task.isCancelled else { throw CancellationError() }
      let row = try await app.engine.call("jobs.get", ["id": id]) as? [String: Any] ?? [:]
      let state = string(row, "status")
      if state == "completed" { return }
      if ["failed", "cancelled", "needs_approval"].contains(state) {
        let result = row["result"] as? [String: Any] ?? [:]
        throw EngineError(message: string(result, "error", "Could not finish starting the local server."))
      }
    }
    throw EngineError(message: "The local server is still starting. Wait a moment, then press Start coding again.")
  }

  private func waitForAdvertised(_ row: [String: Any]) async throws -> [String: Any]? {
    let engine = string(row, "engine")
    let model = string(row, "model")
    let needle = model.split(separator: "/").last.map(String.init)?.lowercased() ?? model.lowercased()
    for _ in 0..<20 {
      try await reloadModels()
      guard !Task.isCancelled else { throw CancellationError() }
      let advertised = models.filter { string($0, "engine") == engine && $0["advertised"] as? Bool == true }
      if let exact = advertised.first(where: { string($0, "model") == model }) { return exact }
      let matches = advertised.filter { string($0, "model").lowercased().contains(needle) && !needle.isEmpty }
      if matches.count == 1 { return matches[0] }
      try await Task.sleep(for: .seconds(1))
    }
    return nil
  }
}

struct RouteReadiness: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    HStack(spacing: 10) {
      Image(
        systemName: app.routeStatus["ready"] as? Bool == true ? "checkmark.circle" : "info.circle"
      ).foregroundStyle(app.routeStatus["ready"] as? Bool == true ? Color.green : .secondary)
      Text(string(app.routeStatus, "message", "Choose a model to get started.")).font(.caption)
        .foregroundStyle(.secondary)
      Spacer()
      Button("Choose connection…") { app.showConnection = true }.font(.caption)
    }.task(id: app.provider + "\n" + app.model + "\n" + app.harness) {
      try? await Task.sleep(for: .milliseconds(350))
      guard !Task.isCancelled else { return }
      await app.checkRoute()
    }
  }
}
