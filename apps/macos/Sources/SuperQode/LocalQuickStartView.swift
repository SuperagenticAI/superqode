import SwiftUI

/// Each action uses an engine-reviewed plan; reopening observes existing jobs.
struct LocalQuickStartView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  var embedded = false
  var active = true
  var showInstalled = true
  @State private var hardware: [String: Any] = [:]
  @State private var engines: [[String: Any]] = []
  @State private var warnings: [String] = []
  @State private var learnMore = false
  @State private var advanced = false
  @State private var operation: [String: Any]?
  @State private var operationJob = ""
  @State private var operationStatus = ""
  @State private var showOperationLog = false
  @State private var choices: [[String: Any]] = []
  @State private var presets: [[String: Any]] = []
  @State private var selection = ""
  @State private var step: [String: Any] = [:]
  @State private var failure = ""
  @State private var busy = false
  @State private var progress: [String: Any] = [:]
  @State private var output = ""
  @State private var command = UUID().uuidString
  @State private var closed = false
  @State private var showSetup = false
  private var state: String { string(step, "step") }
  private var plan: [String: Any] { step["plan"] as? [String: Any] ?? [:] }
  private var validProject: Bool { app.projectID == project && !closed && !app.openingProject }

  var body: some View {
    ScrollView {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Text("Local AI").font(.title2.weight(.semibold))
        Spacer()
        if !embedded { Button("Advanced…") { advanced = true } }
      }
      if showInstalled {
        InstalledLocalModelPicker(project: project, dismissOnUse: !embedded, active: active)
          .id(project)
        if embedded { LocalRuntimeWorkspace(active: active) }
        DisclosureGroup(isExpanded: $showSetup) {
          VStack(alignment: .leading, spacing: 16) {
            LocalAINotice(learnMore: $learnMore)
            setupGuide
          }.padding(.top, 8)
        } label: {
          Text("Download or set up a model").font(.headline)
        }
      } else {
        LocalAINotice(learnMore: $learnMore)
        setupGuide
      }
    }
    }.padding(24).frame(width: embedded ? nil : 780, height: embedded ? nil : 760)
      .centeredDialog(isPresented: $learnMore, title: "About Local AI") {
        LocalAILearnMoreView()
      }
      .centeredDialog(isPresented: $showOperationLog, title: "Local operation progress") {
        LocalModelOperationView(job: operationJob).environmentObject(app)
      }
      .centeredDialog(isPresented: $advanced, title: "Advanced Local AI") {
        AdvancedLocalAIView().environmentObject(app).frame(width: 1080, height: 780)
      }
      .centeredDialog(isPresented: Binding(get: { operation != nil }, set: { if !$0 { operation = nil } }), title: "Review local operation", onDismiss: {
        Task { await load(); await observeOperations() }
      }) {
        if let operation { LocalModelActionView(request: operation).environmentObject(app) }
      }
      .task(id: active) {
        guard active else { return }
        if choices.isEmpty { await load() }
      }
      .task(id: String(active) + "\n" + string(step, "job")) {
        guard active, state == "working" else { return }
        while !Task.isCancelled && validProject && state == "working" {
          do { try await Task.sleep(for: .seconds(1)) } catch { return }
          await refresh()
        }
      }
      .task(id: active) {
        guard active else { return }
        while !Task.isCancelled && !closed {
          do { try await Task.sleep(for: .seconds(2)) } catch { return }
          await observeOperations()
        }
      }
      .onChange(of: selection) { _, _ in step = [:]; output = ""; progress = [:]; Task { await refresh() } }
      .onChange(of: active) { _, visible in
        if !visible {
          learnMore = false; advanced = false; operation = nil; showOperationLog = false
        }
      }
      .onAppear { closed = false }
      .onDisappear { closed = true }
  }

  private var setupGuide: some View {
    VStack(alignment: .leading, spacing: 16) {
      devicePanel
      presetPanel
      if !showInstalled { enginePanel }
      Text("Download a starter model only when it is not already installed. Review each install, download and load before it runs.").foregroundStyle(.secondary)
      CatalogPopup(label: "Model", options: setupChoices.map { row in
        CatalogPopupOption(id: string(row, "id"), title: string(row, "name") + " · " + string(row["fit"] as? [String: Any] ?? [:], "rating", "Unknown"))
      }, selection: $selection, placeholder: "Choose a model or preset")
        .disabled(busy || state == "working")
      if let row = choices.first(where: { string($0, "id") == selection }) {
        Text(string(row, "detail")).font(.callout).foregroundStyle(.secondary)
        if let context = row["suggested_context"] as? Int {
          Text("Requested context: \(context.formatted()) tokens · output up to \(row["max_tokens"] as? Int ?? 2048) · KV cache: " + string(row, "kv_cache", "auto"))
            .font(.caption).foregroundStyle(.secondary)
        }
      }
      if let row = choices.first(where: { string($0, "id") == selection }) {
        Text(string(row["fit"] as? [String: Any] ?? [:], "verdict")).font(.caption)
      }
      Text("Fit includes weights, context/KV cache, buffers and headroom. It is an estimate, not a guarantee.").font(.caption).foregroundStyle(.secondary)
      VStack(alignment: .leading, spacing: 12) {
        if state == "working" {
          ProgressView("Setting up your local model…")
          if !progress.isEmpty { LocalDownloadProgress(value: progress) }
          Text("You can close this guide and reopen it to check progress. Engine shutdown interrupts active work.").font(.caption).foregroundStyle(.secondary)
        } else if state == "ready" {
          Label("Ready to start coding", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
          Text("The model completed a read-tool check on generated data. Editing and full coding quality still depend on the model and task.")
          Text("The primary model uses this machine. Other tools or project configuration may use the network.").font(.caption).foregroundStyle(.secondary)
        } else if !plan.isEmpty {
          Text(stepTitle).font(.headline)
          if let requested = plan["context"] as? Int {
            Text("This reviewed step requests \(requested.formatted()) context tokens.").font(.caption)
          }
          Text(string(plan, "note", string(plan, "guidance"))).font(.callout)
          if state == "download" {
            Text("Download size is reported during transfer. Free disk: " + localBytes(plan["disk_free_bytes"]))
            Text("Existing cached weights are reused. No coding prompt is sent by downloading.").font(.caption)
          }
          if state == "verify" { Text("Checks loaded context, tool-call shapes and context recall, then runs a Core read-tool check on generated data. No project files are read.").font(.caption) }
          DisclosureGroup("Advanced operation details") {
            Text(string(plan, "command")).font(.caption.monospaced()).textSelection(.enabled)
          }
        } else if !string(step, "message").isEmpty {
          Text(string(step, "message"))
          if let url = URL(string: string(step, "url")), url.scheme == "https" { Link("Open official installation guide", destination: url) }
        }
        if let verification = step["verification"] as? [String: Any], !verification.isEmpty {
          LocalReadinessSummary(verification: verification)
        }
        if !output.isEmpty { DisclosureGroup("Setup output") { Text(output).font(.caption.monospaced()).textSelection(.enabled) } }
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
        if downloads.isEmpty && !busy {
          Text(showInstalled
            ? "No starter download is suggested for this Mac. Use an installed model above, or open Advanced setup."
            : "No starter download is suggested for this Mac.")
        }
      }.frame(maxWidth: .infinity, alignment: .leading)
      HStack {
        if !embedded { Button("Close") { closed = true; dismiss() } }
        if state == "working" { Button("Cancel setup") { app.perform { _ = try await app.engine.call("jobs.cancel", ["id": string(step, "job")]) } } }
        Spacer()
        Button("Re-detect engines") { Task { await load() } }.disabled(busy)
        Button("Check again") { Task { await refresh() } }.disabled(busy || selection.isEmpty || project.isEmpty || !validProject)
        if state == "ready" {
          Button("Start coding") { Task { await useModel() } }.buttonStyle(BrandButtonStyle()).disabled(busy || app.anyActive || !validProject)
        } else if !plan.isEmpty {
          Button(stepTitle) { Task { await runStep() } }.buttonStyle(BrandButtonStyle()).disabled(busy || app.anyActive || !validProject)
        } else if state == "retry" {
          Button("Retry remaining setup") { Task { await refresh(retry: true) } }.disabled(busy || !validProject)
        }
      }
    }
  }

  private var presetPanel: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text("Choose a starting point").font(.headline)
      HStack(alignment: .top, spacing: 10) {
        ForEach(presets, id: \.projectRowID) { preset in
          let choice = preset["choice"] as? [String: Any] ?? [:]
          Button {
            selection = string(choice, "id")
          } label: {
            VStack(alignment: .leading, spacing: 6) {
              Label(string(preset, "name"), systemImage: string(preset, "id") == "fast" ? "bolt.fill" : string(preset, "id") == "balanced" ? "scale.3d" : "cpu")
                .font(.headline).foregroundStyle(Color.qAccent)
              Text(string(choice, "model", "No fitting suggestion")).font(.caption).lineLimit(2)
              Text(string(preset, "detail")).font(.caption2).foregroundStyle(.secondary)
              if let context = choice["suggested_context"] as? Int {
                Text("\(context.formatted()) context · " + (choice["installed"] as? Bool == true ? "Reuse installed" : "Review download"))
                  .font(.caption2).foregroundStyle(.secondary)
              }
            }.frame(maxWidth: .infinity, minHeight: 118, alignment: .topLeading).padding(12)
              .background(selection == string(choice, "id") ? Color.qAccent.opacity(0.12) : Color.secondary.opacity(0.05), in: RoundedRectangle(cornerRadius: 10))
          }.buttonStyle(.plain).disabled(choice.isEmpty || busy || state == "working")
        }
      }
      Text("These are memory-based starting points. Speed and coding quality need measurement. Selecting a card prepares setup; each download, load and check is reviewed separately.")
        .font(.caption).foregroundStyle(.secondary)
    }
  }

  private var memoryLabel: String {
    if let memory = hardware["unified_memory_gb"] as? Int { return "\(memory) GB" }
    return "Memory not reported"
  }
  private var devicePanel: some View {
    VStack(alignment: .leading, spacing: 4) {
      Text("Your Mac").font(.headline)
      Text(string(hardware, "chip", "Chip not reported") + " · " + memoryLabel + " · macOS " + string(hardware, "macos_version", "Unknown")).font(.caption)
      Text("Model GPU budget is estimated at about 70% of unified memory, with extra headroom reserved.").font(.caption).foregroundStyle(.secondary)
      ForEach(warnings, id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
      if project.isEmpty { Text("Open a project to finish guided model setup and start coding. Engine controls remain available here.").font(.caption) }
    }
  }
  private var agentBusy: Bool {
    app.jobs.contains {
      string($0, "kind") != "local"
        && ["running", "needs_approval", "queued", "cancelling"].contains(string($0, "status"))
    }
  }
  private var enginePanel: some View {
    VStack(alignment: .leading, spacing: 8) {
      ForEach(engines, id: \.projectRowID) { row in
        let installed = row["installed"] as? Bool == true
        let running = row["running"] as? Bool == true
        let identifier = string(row, "id")
        HStack {
          VStack(alignment: .leading) {
            Text(string(row, "name")).font(.headline)
            Text(running ? "Server running" : installed ? "Installed · server stopped" : "Not installed").font(.caption).foregroundStyle(.secondary)
          }
          Spacer()
          if identifier == "lmstudio" && row["cli_available"] as? Bool != true && !running {
            Button("Install LM Studio (recommended)…") { operation = ["action": "install", "engine": "lmstudio"] }
          }
          if identifier == "ollama" {
            Link("Get Ollama", destination: URL(string: "https://ollama.com/download")!)
            if !installed && (row["install"] as? [String: Any])?["automatic"] as? Bool == true {
              Button("Install with Homebrew…") { operation = ["action": "install", "engine": "ollama"] }
            }
          }
          if installed && (identifier != "lmstudio" || row["cli_available"] as? Bool == true || running) {
            Button(running ? "Context and server…" : "Start server…") {
              operation = ["action": "serve", "engine": identifier]
            }.disabled(agentBusy || busy || state == "working")
          }
          if row["can_stop"] as? Bool == true {
            Button("Stop…") { operation = ["action": "stop", "engine": identifier] }
              .disabled(agentBusy || busy || state == "working")
          }
        }.font(.caption)
      }
      if let row = choices.first(where: { string($0, "id") == selection }), row["installed"] as? Bool == true {
        Button("Unload selected model…") { operation = ["action": "unload", "engine": string(row, "engine"), "model": string(row, "model")] }
          .disabled(app.anyActive || busy || state == "working")
      }
      if !operationJob.isEmpty {
        HStack {
          if ["queued", "running"].contains(operationStatus) { ProgressView().controlSize(.small) }
          Button("Operation output and progress…") { showOperationLog = true }
        }
        if !progress.isEmpty { LocalDownloadProgress(value: progress) }
        Text(output).font(.caption).lineLimit(2).foregroundStyle(.secondary)
      }
    }
  }
  private func observeOperations() async {
    guard !closed else { return }
    do {
      let rows = try await app.engine.call("local.models.jobs") as? [[String: Any]] ?? []
      guard !closed, state != "working" else { return }
      if let row = rows.first {
        let changed = operationJob != string(row, "id") || operationStatus != string(row, "status")
        operationJob = string(row, "id")
        operationStatus = string(row, "status")
        progress = row["progress"] as? [String: Any] ?? [:]
        output = string(row, "title") + " · " + string(row, "status")
        if changed && ["completed", "failed", "cancelled"].contains(string(row, "status")) { await load() }
      }
    } catch { failure = error.localizedDescription }
  }

  private var downloads: [[String: Any]] { choices.filter { $0["installed"] as? Bool != true && $0["setup_preset"] == nil } }
  private var setupChoices: [[String: Any]] {
    choices.filter { ($0["installed"] as? Bool != true && $0["setup_preset"] == nil) || string($0, "id") == selection }
  }
  private var stepTitle: String {
    switch state {
    case "install": return "Install runtime (consent)"
    case "serve": return "Start local server"
    case "download": return "Download model"
    case "load": return "Load model"
    case "verify": return "Run local tool check"
    default: return "Continue"
    }
  }
  private func load() async {
    busy = true
    defer { busy = false }
    do {
      let result = try await app.engine.call("local.models.quickstart.catalog", ["project": project]) as? [String: Any] ?? [:]
      guard validProject, !Task.isCancelled else { return }
      hardware = result["hardware"] as? [String: Any] ?? [:]
      engines = result["engines"] as? [[String: Any]] ?? []
      warnings = (result["guardrails"] as? [String: Any])?["warnings"] as? [String] ?? []
      choices = result["choices"] as? [[String: Any]] ?? []
      presets = result["setup_presets"] as? [[String: Any]] ?? []
      for preset in presets {
        if let choice = preset["choice"] as? [String: Any], !choices.contains(where: { string($0, "id") == string(choice, "id") }) {
          choices.append(choice)
        }
      }
      let saved = selection.isEmpty ? string(result, "selected") : selection
      let savedRow = choices.first { string($0, "id") == saved }
      // Installed models are chosen from the list above. Do not open them as a download.
      if (savedRow?["installed"] as? Bool == true && savedRow?["setup_preset"] == nil) || !choices.contains(where: { string($0, "id") == saved }) {
        selection = ""
      } else {
        selection = saved
      }
    } catch { failure = error.localizedDescription }
  }
  private func refresh(retry: Bool = false) async {
    let selected = selection
    guard validProject, !project.isEmpty, !selected.isEmpty else { return }
    busy = true
    defer { busy = false }
    do {
      let value = try await app.engine.call("local.models.quickstart.prepare", ["project": project, "choice": selected, "retry": retry]) as? [String: Any] ?? [:]
      guard validProject, selected == selection, !Task.isCancelled else { return }
      step = value; failure = ""; command = UUID().uuidString
      if !string(value, "job").isEmpty {
        let job = try await app.engine.call("jobs.get", ["id": string(value, "job")]) as? [String: Any] ?? [:]
        guard validProject, selected == selection else { return }
        let events = job["events"] as? [[String: Any]] ?? []
        progress = events.last(where: { string($0, "type") == "progress" })?["data"] as? [String: Any] ?? [:]
        output = String(events.map { string($0["data"] as? [String: Any] ?? [:], "text", string($0["data"] as? [String: Any] ?? [:], "message")) }.joined(separator: "\n").suffix(20000))
      }
    } catch { if validProject && selected == selection { failure = error.localizedDescription } }
  }
  private func runStep() async {
    guard validProject else { return }
    busy = true
    defer { busy = false }
    do {
      let job = try await app.engine.call("local.models.quickstart.start", ["project": project, "choice": selection, "plan": string(plan, "id"), "expected_digest": string(plan, "digest"), "command_id": command]) as? [String: Any] ?? [:]
      guard validProject else { return }
      step = ["step": "working", "job": string(job, "id")]; output = ""; failure = ""
    } catch { failure = error.localizedDescription }
  }
  private func useModel() async {
    guard validProject else { return }
    busy = true
    defer { busy = false }
    do {
      let requested = app.harness.isEmpty ? "core" : app.harness
      let result = try await connect(requested)
      guard validProject, !app.anyActive else { return }
      app.chooseHarness(string(result, "harness")); app.chooseModelRoute(string(result, "provider"), string(result, "model"))
      try await app.warmLocalModel(
        endpoint: string(result, "endpoint"), model: string(result, "model"), server: string(result, "provider"))
      app.section = "Workspace"; closed = true; dismiss()
    } catch { failure = error.localizedDescription }
  }
  private func connect(_ requested: String) async throws -> [String: Any] {
    do {
      return try await app.engine.call("local.models.use", [
        "project": project, "engine": string(step, "engine"), "model": string(step, "model"), "harness": requested,
      ]) as? [String: Any] ?? [:]
    } catch {
      if requested == "core" { throw error }
      return try await app.engine.call("local.models.use", [
        "project": project, "engine": string(step, "engine"), "model": string(step, "model"), "harness": "core",
      ]) as? [String: Any] ?? [:]
    }
  }
}


private struct LocalReadinessSummary: View {
  let verification: [String: Any]
  private var readiness: [String: Any] { verification["readiness"] as? [String: Any] ?? [:] }
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Local check results").font(.headline)
      if let requested = readiness["requested_context"] as? Int {
        Text("Requested context: \(requested.formatted()) tokens").font(.caption)
      }
      if let window = readiness["context_window"] as? Int {
        Text("Reported context: \(window.formatted()) tokens · " + string(readiness, "context_source")).font(.caption)
      } else {
        Text("Loaded context was not reported. Keep context conservative; no maximum context size was verified.").font(.caption).foregroundStyle(.orange)
      }
      ForEach(verification["checks"] as? [[String: Any]] ?? [], id: \.projectRowID) { check in
        Label(string(check, "name"), systemImage: check["ok"] as? Bool == true ? "checkmark.circle" : "exclamationmark.circle")
          .font(.caption).foregroundStyle(check["ok"] as? Bool == true ? Color.secondary : .orange)
      }
      ForEach(readiness["checks"] as? [[String: Any]] ?? [], id: \.projectRowID) { check in
        Label(string(check, "name") + ": " + string(check, "detail"), systemImage: check["ok"] as? Bool == true ? "checkmark.circle" : "exclamationmark.circle")
          .font(.caption).foregroundStyle(check["ok"] as? Bool == true ? Color.secondary : .orange)
      }
      ForEach(readiness["warnings"] as? [String] ?? [], id: \.self) { warning in
        Text(warning).font(.caption).foregroundStyle(.orange)
      }
    }
  }
}


struct LocalAINotice: View {
  @Binding var learnMore: Bool
  static let copy = "Local AI runs on your Mac. No subscription needed. Pick a model that fits your Mac and use it responsibly."
  var body: some View {
    HStack(alignment: .top, spacing: 8) {
      Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
      Text(Self.copy).font(.caption)
      Button("Learn more") { learnMore = true }.buttonStyle(.link).font(.caption)
    }.padding(10).background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
  }
}

struct LocalAILearnMoreView: View {
  @DialogDismiss private var dismiss
  static let points: [(String, String)] = [
    ("What runs where", "Models run entirely on your Mac, using its memory, processor and battery."),
    ("Pick a model that fits", "Choose one marked Fits for your Mac. A model that is too large can make your Mac slow, warm or noisy."),
    ("Keep context sensible", "The suggested context size is tuned for your Mac. Larger sizes use much more memory."),
    ("Long sessions", "Plug in, keep the Mac ventilated, and expect fans or slowdowns under heavy load. That is normal."),
    ("When you are done", "Use Stop or Unload to free memory. Downloads still use disk space."),
    ("Privacy", "Your model runs locally. Tools and other project configuration can still use the network."),
    ("Your responsibility", "You choose which models to run and how. SuperQode gives guidance but cannot guarantee how a model performs on your hardware.")
  ]
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Text("About Local AI").font(.title2)
      ForEach(Self.points.indices, id: \.self) { index in
        VStack(alignment: .leading, spacing: 4) {
          Text(Self.points[index].0).font(.headline)
          Text(Self.points[index].1).font(.callout).foregroundStyle(.secondary)
        }
      }
      HStack { Spacer(); Button("Done") { dismiss() } }
    }.padding(24).frame(width: 620)
  }
}
