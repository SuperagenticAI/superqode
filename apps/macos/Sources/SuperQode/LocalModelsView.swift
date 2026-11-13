import AppKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor final class LocalModelLibrary: ObservableObject {
  @Published var overview: [String: Any] = [:]
  @Published var hits: [[String: Any]] = []
  @Published var jobs: [[String: Any]] = []
  @Published var searching = false
  @Published var failure = ""
  private var generation = 0
  func search(engine: Engine, query: String, source: String, format: String) async {
    generation += 1
    let token = generation
    hits = []
    searching = true
    defer { if token == generation { searching = false } }
    do {
      let rows = try await engine.call("local.models.search", ["query": query, "source": source, "format": format]) as? [[String: Any]] ?? []
      guard token == generation, !Task.isCancelled else { return }
      hits = rows; failure = ""
    } catch { if token == generation { failure = error.localizedDescription } }
  }
  func refresh(engine: Engine) async {
    do {
      let value = try await engine.call("local.models.overview") as? [String: Any] ?? [:]
      guard !Task.isCancelled else { return }
      if !NSDictionary(dictionary: overview).isEqual(to: value) { overview = value }
      if !failure.isEmpty { failure = "" }
    } catch { failure = error.localizedDescription }
  }
  func refreshJobs(engine: Engine) async {
    do {
      let value = try await engine.call("local.models.jobs") as? [[String: Any]] ?? []
      let servers = try await engine.call("local.models.servers") as? [[String: Any]] ?? []
      guard !Task.isCancelled else { return }
      if !NSArray(array: jobs).isEqual(to: value) { jobs = value }
      if !NSArray(array: overview["engines"] as? [[String: Any]] ?? []).isEqual(to: servers) { overview["engines"] = servers }
    }
    catch { failure = error.localizedDescription }
  }
}

struct ModelsView: View {
  @EnvironmentObject var app: Workspace
  var active = true
  @State private var tab = "local"
  @State private var localDraft = LocalQuickStartDraft()
  var body: some View {
    VStack(spacing: 0) {
      Picker("Model workspace", selection: $tab) {
        Text("Quick Start").tag("local")
        Text("Advanced").tag("advanced")
      }.pickerStyle(.segmented).padding(.horizontal, 28).padding(.top, 20)
      if tab == "local" {
        if active { LocalQuickStartView(project: app.projectID, embedded: true, active: active, form: localDraft).id(app.projectID) }
      } else { AdvancedLocalAIView(active: active) }
    }
  }
}

struct AdvancedLocalAIView: View {
  var active = true
  @State private var tab = "comparisons"
  var body: some View {
    VStack(spacing: 0) {
      Picker("Advanced Local AI", selection: $tab) {
        Text("Compare").tag("comparisons")
        Text("Model routes").tag("routes")
        Text("Models & setup").tag("models")
      }.pickerStyle(.segmented).padding(.horizontal, 28).padding(.top, 20)
      if tab == "comparisons" { LocalComparisonWorkspace(active: active) }
      else if tab == "routes" { ModelRoutesView() }
      else { LocalModelWorkbenchView(active: active) }
    }
  }
}

struct LocalModelWorkbenchView: View {
  var active = true
  @EnvironmentObject var app: Workspace
  @StateObject private var library = LocalModelLibrary()
  @State private var query = ""
  @State private var source = "recommended"
  @State private var format = "gguf"
  @State private var fitsOnly = false
  @State private var action: [String: Any]?
  @State private var connecting: String?
  @State private var log: String?
  @State private var workflow = false
  @State private var setup = false
  @State private var compatibility = false
  @State private var quickStart = false
  private var rows: [[String: Any]] { library.hits.filter { !fitsOnly || ($0["fit"] as? [String: Any])?["likely_fits"] as? Bool == true } }
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      PageTitle(eyebrow: "Your models. Your machine.", title: "Local AI",
        subtitle: "Find weights, review their size, start a server and choose a harness to code with.")
      HStack {
        VStack(alignment: .leading, spacing: 4) {
          Text("Start coding with a local model").font(.headline)
          Text("Reuse a model or get guided through download, setup and a tool check.").font(.callout).foregroundStyle(.secondary)
        }
        Spacer()
        Button("Local Quick Start…") { quickStart = true }.buttonStyle(BrandButtonStyle()).disabled(app.projectID.isEmpty)
      }.padding(16).brandSurface()
      if app.projectID.isEmpty { Text("Open a project to use Local Quick Start.").font(.caption).foregroundStyle(.secondary) }
      HStack {
        let hardware = library.overview["hardware"] as? [String: Any] ?? [:]
        Label(string(hardware, "chip", "Detecting device…"), systemImage: "desktopcomputer")
        Text("\(hardware["unified_memory_gb"] ?? "Unknown") GB memory").foregroundStyle(.secondary)
        Spacer()
        Button("Storage & Hub access…") { setup = true }
        Button("Harness compatibility…") { compatibility = true }
        Button("Refresh device") { Task { await library.refresh(engine: app.engine) } }
        Button("Local benchmarks…") { workflow = true }.disabled(app.projectID.isEmpty)
      }.font(.caption)
      if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.orange).textSelection(.enabled) }
      ScrollView {
        VStack(alignment: .leading, spacing: 20) {
          LazyVGrid(columns: [GridItem(.adaptive(minimum: 240), spacing: 12)], spacing: 12) {
            ForEach(library.overview["engines"] as? [[String: Any]] ?? [], id: \.projectRowID) { row in
              LocalServerCard(row: row, onOperation: { action = $0 }, onConnect: { connecting = $0 })
            }
          }
          HStack {
            TextField("Search families or enter an Ollama tag", text: $query).textFieldStyle(.roundedBorder).onSubmit { search() }
              .onChange(of: query) { _, value in if value.count > 160 { query = String(value.prefix(160)) } }
            Picker("Source", selection: $source) {
              Text("Recommended · TUI catalog").tag("recommended")
              Text("Hugging Face").tag("hf")
              Text("LM Studio compatible · HF").tag("lmstudio")
            }.frame(maxWidth: 260)
            if source == "hf" {
              Picker("Format", selection: $format) { Text("GGUF").tag("gguf"); Text("MLX").tag("mlx") }.frame(width: 110)
            }
            Button("Search", action: search).disabled(library.searching || !app.connected)
          }
          HStack {
            Toggle("Likely to fit this device", isOn: $fitsOnly).toggleStyle(.checkbox)
            Spacer()
            Link("Ollama library", destination: URL(string: "https://ollama.com/search")!)
            Button("Review exact Ollama tag…") { action = ["action": "download", "source": "ollama", "model": query, "engine": "ollama"] }
              .disabled(query.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
          }.font(.caption)
          if library.searching { ProgressView("Searching models…") }
          LazyVGrid(columns: [GridItem(.adaptive(minimum: 290), spacing: 12)], spacing: 12) {
            ForEach(rows, id: \.projectRowID) { row in
              VStack(alignment: .leading, spacing: 10) {
                Label(string(row, "name"), systemImage: "cube.transparent").font(.headline).lineLimit(2)
                Text(string(row, "origin")).font(.caption).foregroundStyle(.secondary)
                Text(string(row["fit"] as? [String: Any] ?? [:], "verdict", "Size unknown")).font(.caption)
                HStack {
                  Pill(title: string(row, "format").uppercased())
                  if row["gated"] as? Bool == true { Label("Access required", systemImage: "lock").font(.caption) }
                  Spacer()
                  if row["manual_setup"] as? Bool == true {
                    Button("Configure DS4…") { action = ["action": "serve", "engine": "ds4"] }
                      .disabled(app.anyActive)
                  } else if string(row, "format") == "weights" {
                    Button("Find GGUF / MLX builds") {
                      query = string(row, "id").components(separatedBy: "/").last ?? ""
                      source = "hf"; search()
                    }
                  } else {
                    Button("Review download…") {
                      action = ["action": "download", "model": string(row, "id"), "source": string(row, "source"),
                        "format": string(row, "format"), "engine": string(row, "format") == "mlx" ? "mlx" : source == "lmstudio" ? "lmstudio" : string(row, "source") == "ollama" ? "ollama" : "llama.cpp"]
                    }
                  }
                }
                if let url = URL(string: string(row, "docs_url")), url.scheme == "https" {
                  Link("Model documentation", destination: url).font(.caption)
                }
              }.padding(16).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
            }
          }
          if rows.isEmpty && !library.searching { Text("No matches. Search Hugging Face or review an exact local Ollama tag.").foregroundStyle(.secondary) }
          Text("Fit estimates include context/KV cache, buffers and headroom. Runtime support and coding/tool quality still need verification. LM Studio-compatible search uses Hugging Face artifacts.")
            .font(.caption).foregroundStyle(.secondary)
          if !library.jobs.isEmpty { operations }
        }.padding(.bottom, 16)
      }
    }.padding(28)
      .onChange(of: active) { _, visible in
        if !visible {
          action = nil; connecting = nil; log = nil
          workflow = false; setup = false; compatibility = false; quickStart = false
        }
      }
      .task(id: active) {
        guard active else { return }
        if library.hits.isEmpty { await library.search(engine: app.engine, query: query, source: source, format: format) }
        await library.refresh(engine: app.engine)
        await library.refreshJobs(engine: app.engine)
      }
      .task(id: active) {
        guard active else { return }
        while !Task.isCancelled {
          do { try await Task.sleep(for: .seconds(3)) } catch { return }
          await library.refreshJobs(engine: app.engine)
        }
      }
      .centeredDialog(isPresented: Binding(get: { action != nil }, set: { if !$0 { action = nil } }), title: "Local model operation", onDismiss: {
        guard active else { return }
        Task { await library.refreshJobs(engine: app.engine); await library.refresh(engine: app.engine) }
      }) { if let action { LocalModelActionView(request: action).environmentObject(app) } }
      .centeredDialog(isPresented: Binding(get: { connecting != nil }, set: { if !$0 { connecting = nil } }), title: "Use a local model") {
        if let connecting { LocalModelConnectionView(engine: connecting, project: app.projectID).environmentObject(app) }
      }
      .centeredDialog(isPresented: Binding(get: { log != nil }, set: { if !$0 { log = nil } }), title: "Local operation output") {
        if let log { LocalModelOperationView(job: log).environmentObject(app) }
      }
      .centeredDialog(isPresented: $workflow, title: "Local model benchmarks") {
        ToolsView(workflow: "local bench").environmentObject(app).frame(width: 920, height: 680)
      }
      .centeredDialog(isPresented: $setup, title: "Local AI setup", onDismiss: {
        guard active else { return }
        Task { await library.refresh(engine: app.engine) }
      }) { LocalModelSetupView().environmentObject(app) }
      .centeredDialog(isPresented: $compatibility, title: "Local harness compatibility") {
        LocalModelCompatibilityView(project: app.projectID).environmentObject(app)
      }
      .centeredDialog(isPresented: $quickStart, title: "Local Quick Start") {
        LocalQuickStartView(project: app.projectID).environmentObject(app)
      }
  }
  private func search() { Task { await library.search(engine: app.engine, query: query, source: source, format: format) } }
  private var operations: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text("Downloads and setup history").font(.headline)
      ForEach(library.jobs, id: \.projectRowID) { row in
        HStack {
          Text(string(row, "title")).lineLimit(1); Spacer()
          Text(string(row, "status")).font(.caption).foregroundStyle(.secondary)
          if string(row, "status") == "running" { LocalDownloadProgress(value: row["progress"] as? [String: Any] ?? [:]).frame(width: 150) }
          Button("Output") { log = string(row, "id") }
          if let result = row["result"] as? [String: Any], !string(result, "serve_model").isEmpty {
            Button("Configure server…") {
              let provider = string(result, "provider")
              action = ["action": "serve", "engine": provider == "llamacpp" ? "llama.cpp" : provider, "model": string(result, "serve_model")]
            }.disabled(app.anyActive)
          }
        }.padding(12).brandSurface()
      }
    }
  }
}

struct LocalServerCard: View {
  @EnvironmentObject var app: Workspace
  let row: [String: Any]
  let onOperation: ([String: Any]) -> Void
  let onConnect: (String) -> Void

  private var id: String { string(row, "id") }
  private var isDS4: Bool { id == "ds4" }
  private var running: Bool { row["running"] as? Bool == true }

  var body: some View {
    VStack(alignment: .leading, spacing: 9) {
      HStack {
        Label(string(row, "name", id), systemImage: "server.rack").font(.headline)
        Spacer()
        Pill(title: string(row, "state"))
      }
      Text(string(row, "base_url")).font(.caption.monospaced()).foregroundStyle(.secondary)
      HStack {
        if isDS4 || row["installed"] as? Bool == true {
          Button("Configure & start…") { operation("serve") }
            .disabled(app.anyActive || string(row, "state") == "starting")
          if running {
            Button("Use model…") { onConnect(id) }.disabled(app.projectID.isEmpty || app.anyActive)
            Button("Check…") { operation("verify") }.disabled(app.anyActive)
          }
        } else {
          let install = row["install"] as? [String: Any] ?? [:]
          if install["automatic"] as? Bool == true {
            Button("Review installation…") { operation("install") }
          }
          if let url = URL(string: string(install, "docs_url")) { Link("Setup guide", destination: url) }
        }
      }.controlSize(.small)
      if isDS4 {
        Link("DS4 setup guide", destination: URL(string: "https://github.com/antirez/ds4")!).font(.caption)
      }
      if row["can_stop"] as? Bool == true {
        Button("Review stop…") { operation("stop") }.font(.caption).disabled(app.anyActive)
      }
    }.padding(16).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
  }

  private func operation(_ action: String) { onOperation(["action": action, "engine": id]) }
}

struct LocalModelActionView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let request: [String: Any]
  @State private var engine = ""
  @State private var model = ""
  @State private var filename = ""
  @State private var files: [[String: Any]] = []
  @State private var servedModels: [String] = []
  @State private var context = 16384
  @State private var cache = "auto"
  @State private var check = "readiness"
  @State private var ds4Binary = ""
  @State private var ds4KVDirectory = ""
  @State private var ds4DiskMB = 8192
  @State private var hubSetup = false
  @State private var reviewGeneration = 0
  @State private var fileGeneration = 0
  @State private var plan: [String: Any] = [:]
  @State private var busy = false
  @State private var failure = ""
  @State private var closed = false
  @State private var commandID = UUID().uuidString
  private var signature: String { [engine, model, filename, String(context), cache, check, ds4Binary, ds4KVDirectory, String(ds4DiskMB)].joined(separator: "\n") }
  private var parameters: [String: Any] {
    var values: [String: Any] = ["engine": engine, "model": model, "filename": filename, "context": context, "kv_cache": cache, "check": check]
    if engine == "ds4" { values.merge(["binary": ds4Binary, "kv_disk_dir": ds4KVDirectory, "kv_disk_space_mb": ds4DiskMB]) { _, new in new } }
    return request.merging(values) { _, value in value }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      Text(string(request, "action") == "download" ? "Choose weights to download" : string(request, "action") == "verify" ? "Check model readiness" : "Configure your local runtime").font(.title2)
      if engine == "ds4" && string(request, "action") == "serve" {
        Text("DS4 · DeepSeek V4").font(.headline)
        HStack {
          TextField("ds4-server executable", text: $ds4Binary).textFieldStyle(.roundedBorder)
          Button("Choose executable…") { chooseDS4Location(.executable) }
        }
        Text("Select an existing build. SuperQode does not install DS4 or download weights when you open this screen.").font(.caption).foregroundStyle(.secondary)
      }
      if string(request, "action") == "verify" {
        Picker("Served model", selection: $model) { ForEach(servedModels, id: \.self) { Text($0).tag($0) } }
        Picker("Check", selection: $check) { Text("Model readiness probes").tag("readiness"); Text("Core read-tool roundtrip").tag("core-read") }.pickerStyle(.segmented)
        Text(check == "core-read" ? "Executes the read tool on generated data with a bounded, read-only Core profile. Writes, shell and delegation are excluded. Other harnesses and full coding quality remain unverified." : "Runs several short prompts through this server. It inspects tool-call shapes without executing tools or reading project files.").font(.caption).foregroundStyle(.secondary)
      }
      if string(request, "source") == "hf" && string(request, "format") != "mlx" {
        Picker("Runtime", selection: $engine) { Text("llama.cpp").tag("llama.cpp"); Text("Ollama").tag("ollama"); Text("LM Studio").tag("lmstudio") }
        Picker("GGUF file / quantization", selection: $filename) {
          Text("Choose a file").tag("")
          ForEach(files.filter { string($0, "name").lowercased().hasSuffix(".gguf") }, id: \.localModelFileID) { row in Text(string(row, "name")).tag(string(row, "name")) }
        }
        Button("Refresh model files") { Task { await loadFiles() } }.disabled(busy)
        Text("All split-GGUF shards are included. LM Studio imports a link to cached weights.").font(.caption).foregroundStyle(.secondary)
      }
      TextField(engine == "ds4" ? "Downloaded GGUF file" : "Model ID or downloaded path", text: $model).textFieldStyle(.roundedBorder).disabled(string(request, "action") != "serve")
      if string(request, "source") == "hf" {
        HStack {
          if let url = URL(string: "https://huggingface.co/" + model) { Link("Model card & access conditions", destination: url) }
          Spacer(); Button("Hub access…") { hubSetup = true }
        }.font(.caption)
      }
      if string(request, "action") == "serve" {
        HStack {
          Stepper("Context: \(context.formatted()) tokens", value: $context, in: 512...262144, step: 512)
          if ["mlx", "llama.cpp", "ds4"].contains(engine) { Button("Choose weights…", action: chooseWeights) }
        }
        if engine == "ds4" {
          HStack {
            TextField("Disk-KV cache directory", text: $ds4KVDirectory).textFieldStyle(.roundedBorder)
            Button("Choose cache…") { chooseDS4Location(.cache) }
          }
          Stepper("Disk-KV limit: \(ds4DiskMB.formatted()) MB", value: $ds4DiskMB, in: 512...1048576, step: 512)
          Text("Local endpoint: http://127.0.0.1:8000/v1. Context and disk-KV settings apply when starting a new server. A running server keeps its current settings.").font(.caption).foregroundStyle(.secondary)
        } else {
        Picker("KV cache", selection: $cache) {
          Text("Automatic").tag("auto"); Text("f16").tag("f16"); Text("q8_0").tag("q8_0"); Text("q4_0").tag("q4_0")
        }.disabled(!["ollama", "llama.cpp"].contains(engine))
        Text("Larger context needs more memory. Quantized KV enables Flash Attention where supported. Existing servers keep their settings; MLX controls context in its model and LM Studio at load.").font(.caption).foregroundStyle(.secondary)
        }
      }
      Button("Review operation") { Task { await prepare() } }.disabled(busy || engine.isEmpty)
      if busy { ProgressView("Preparing local operation…") }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      if !plan.isEmpty {
        ScrollView {
          VStack(alignment: .leading, spacing: 10) {
            Text(string(plan, "title")).font(.headline)
            Text(string(plan["fit"] as? [String: Any] ?? [:], "verdict")).font(.callout)
            if string(request, "action") == "download" {
              Text("Transfer: \(localBytes(plan["download_bytes"])) · Free disk: \(localBytes(plan["disk_free_bytes"]))")
              Text("Cached files may be reused. Transfer size is an upper bound when cache status is unknown.").font(.caption).foregroundStyle(.secondary)
              if !string(plan, "cache_dir").isEmpty { Text("Download location: " + string(plan, "cache_dir")).font(.caption.monospaced()).textSelection(.enabled) }
            }
            if !string(plan, "revision").isEmpty { Text("Pinned revision: \(string(plan, "revision").prefix(12))").font(.caption.monospaced()) }
            ForEach(plan["files"] as? [[String: Any]] ?? [], id: \.localModelFileID) { file in Text(string(file, "name") + " · " + localBytes(file["bytes"])).font(.caption.monospaced()) }
            Text(string(plan, "note", string(plan, "guidance"))).font(.caption).foregroundStyle(.secondary)
            DisclosureGroup("Operation details") { Text(string(plan, "command")).font(.caption.monospaced()).textSelection(.enabled) }
          }.frame(maxWidth: .infinity, alignment: .leading).padding(16)
        }.brandSurface()
      } else { Spacer(minLength: 0) }
      HStack {
        Text(string(request, "action") == "verify" ? "Running this check sends readiness prompts to the selected server." : "This does not send a coding prompt.").font(.caption).foregroundStyle(.secondary); Spacer()
        Button("Cancel") { closed = true; dismiss() }.keyboardShortcut(.cancelAction)
        Button("Run reviewed operation", action: start).buttonStyle(BrandButtonStyle()).disabled(plan.isEmpty || busy)
      }
    }.padding(24).frame(width: 760, height: engine == "ds4" && string(request, "action") == "serve" ? 740 : 620)
      .task {
        engine = string(request, "engine", "ollama"); model = string(request, "model")
        if engine == "ds4" && string(request, "action") == "serve" {
          busy = true
          do {
            let config = try await app.engine.call("local.models.ds4") as? [String: Any] ?? [:]
            guard !closed, !Task.isCancelled else { return }
            ds4Binary = string(config, "binary"); ds4KVDirectory = string(config, "kv_disk_dir")
            ds4DiskMB = config["kv_disk_space_mb"] as? Int ?? 8192
            context = config["context"] as? Int ?? 32768
            if model.isEmpty { model = string(config, "model") }
          } catch { failure = error.localizedDescription }
          busy = false
        }
        if string(request, "action") == "verify" {
          busy = true
          defer { busy = false }
          do {
            let data = try await app.engine.call("local.models.available", ["engine": engine]) as? [String: Any] ?? [:]
            guard !closed, !Task.isCancelled else { return }
            servedModels = data["models"] as? [String] ?? []
            if !servedModels.contains(model) { model = servedModels.first ?? "" }
          } catch { failure = error.localizedDescription }
        }
        if string(request, "source") == "hf" && string(request, "format") != "mlx" {
          await loadFiles()
        }
      }
      .onChange(of: signature) { _, _ in plan = [:]; commandID = UUID().uuidString }
      .onChange(of: hubSetup) { _, _ in reviewGeneration += 1; plan = [:] }
      .onDisappear { closed = true }
      .centeredDialog(isPresented: $hubSetup, title: "Hugging Face access", onDismiss: {
        plan = [:]
        if string(request, "format") != "mlx" { Task { await loadFiles() } }
      }) {
        LocalModelSetupView().environmentObject(app)
      }
  }
  private func loadFiles() async {
    let selected = model
    fileGeneration += 1
    let generation = fileGeneration
    busy = true; plan = [:]; failure = ""
    defer { if generation == fileGeneration { busy = false } }
    do {
      let data = try await app.engine.call("local.models.files", ["model": selected]) as? [String: Any] ?? [:]
      guard !closed, !Task.isCancelled, model == selected, generation == fileGeneration else { return }
      files = data["files"] as? [[String: Any]] ?? []
      if !files.contains(where: { string($0, "name") == filename }) { filename = "" }
    } catch { if generation == fileGeneration { failure = error.localizedDescription } }
  }
  private func prepare() async {
    let reviewed = signature
    reviewGeneration += 1
    let generation = reviewGeneration
    busy = true; plan = [:]; failure = ""
    defer { busy = false }
    do {
      let result = try await app.engine.call("local.models.prepare", parameters) as? [String: Any] ?? [:]
      guard !closed, !Task.isCancelled, signature == reviewed, generation == reviewGeneration else { return }
      plan = result
    } catch { failure = error.localizedDescription }
  }
  private func start() {
    busy = true
    Task {
      defer { busy = false }
      do {
        _ = try await app.engine.call("local.models.start", ["plan": string(plan, "id"), "expected_digest": string(plan, "digest"), "command_id": commandID])
        guard !closed else { return }; dismiss()
      } catch { failure = error.localizedDescription }
    }
  }
  private func chooseWeights() {
    let panel = NSOpenPanel()
    panel.canChooseFiles = ["llama.cpp", "ds4"].contains(engine); panel.canChooseDirectories = engine == "mlx"; panel.allowsMultipleSelection = false
    if engine == "ds4" { panel.allowedContentTypes = [.init(filenameExtension: "gguf") ?? .data] }
    if panel.runModal() == .OK, let url = panel.url { model = url.path }
  }
  private enum DS4Location { case executable, cache }
  private func chooseDS4Location(_ location: DS4Location) {
    let panel = NSOpenPanel()
    panel.canChooseFiles = location == .executable; panel.canChooseDirectories = location == .cache
    panel.canCreateDirectories = location == .cache; panel.allowsMultipleSelection = false
    panel.prompt = location == .executable ? "Choose executable" : "Choose cache"
    if panel.runModal() == .OK, let url = panel.url {
      if location == .executable { ds4Binary = url.path } else { ds4KVDirectory = url.path }
    }
  }
}

struct LocalModelConnectionView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let engine: String
  let project: String
  @State private var models: [String] = []
  @State private var harnesses: [[String: Any]] = []
  @State private var model = ""
  @State private var harness = ""
  @State private var failure = ""
  @State private var busy = false
  @State private var closed = false
  @State private var checking = false
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      if busy {
        ModelWarmupCard(
          message: "Warming the model so your first question is ready…",
          subject: model)
      } else {
      Text("Code with a local model").font(.title2)
      Text("Choose a model advertised by this loopback server. Selecting a route does not start inference.").foregroundStyle(.secondary)
      Picker("Served model", selection: $model) { ForEach(models, id: \.self) { Text($0).tag($0) } }
      Picker("Harness", selection: $harness) {
        ForEach(harnesses.filter { $0["selectable"] as? Bool == true }, id: \.projectRowID) { row in Text(string(row, "name")).tag(string(row, "id")) }
      }
      Text("The primary model is bound to this Mac’s endpoint. Delegation and fallback models keep their own configuration; inspect them before claiming fully offline execution.").font(.caption).foregroundStyle(.secondary)
      DisclosureGroup("Other harness adapters") {
        ForEach(harnesses.filter { $0["selectable"] as? Bool != true }, id: \.projectRowID) { row in Text(string(row, "name") + ": " + string(row, "note")).font(.caption).foregroundStyle(.secondary) }
      }
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
      if !busy {
      HStack {
        Button("Build a harness…") { dismiss(); app.openConnections("builder") }; Spacer()
        Button("Review readiness check…") { checking = true }.disabled(busy || model.isEmpty || app.anyActive)
        Button("Use model") {
          busy = true
          Task {
            defer { busy = false }
            do {
              let result = try await app.engine.call("local.models.use", ["engine": engine, "project": project, "model": model, "harness": harness]) as? [String: Any] ?? [:]
              guard !closed, app.projectID == project, !app.busy, !app.anyActive else { return }
              app.chooseHarness(string(result, "harness")); app.chooseModelRoute(string(result, "provider"), string(result, "model"))
              try await app.warmLocalModel(
                endpoint: string(result, "endpoint"), model: string(result, "model"), server: string(result, "provider"))
              app.section = "Workspace"; app.notice = "The model is ready. Describe a change to start coding."; dismiss()
            } catch { failure = error.localizedDescription }
          }
        }.buttonStyle(BrandButtonStyle()).disabled(busy || model.isEmpty || harness.isEmpty || app.projectID != project || app.anyActive)
      }
      }
    }.padding(24).frame(width: 780, height: 540)
      .centeredDialog(isPresented: $checking, title: "Check local model readiness") {
        LocalModelActionView(request: ["action": "verify", "engine": engine, "model": model]).environmentObject(app)
      }
      .task {
        do {
          let result = try await app.engine.call("local.models.available", ["engine": engine]) as? [String: Any] ?? [:]
          let choices = try await app.engine.call("local.models.harnesses", ["project": project]) as? [[String: Any]] ?? []
          guard !closed, !Task.isCancelled else { return }
          models = result["models"] as? [String] ?? []; harnesses = choices; model = models.first ?? ""
          harness = choices.first(where: { string($0, "id") == "core" && $0["selectable"] as? Bool == true }).map { string($0, "id") }
            ?? choices.first(where: { $0["selectable"] as? Bool == true }).map { string($0, "id") } ?? ""
        } catch { failure = error.localizedDescription }
      }.onDisappear { closed = true }
  }
}

struct LocalModelOperationView: View {
  @EnvironmentObject var app: Workspace
  let job: String
  @State private var detail: [String: Any] = [:]
  @State private var lines = ""
  @State private var after = 0
  @State private var failure = ""
  @State private var progress: [String: Any] = [:]
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      Text(string(detail, "title", "Local model operation")).font(.title2)
      Text(string(detail, "status")).foregroundStyle(.secondary)
      if string(detail, "status") == "running" { LocalDownloadProgress(value: progress) }
      ScrollView { Text(lines).font(.caption.monospaced()).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
      HStack {
        Text("Cache entries are reused on retry. Cancellation is not a pause/resume guarantee.").font(.caption).foregroundStyle(.secondary); Spacer()
        Button("Cancel operation") { app.perform { _ = try await app.engine.call("jobs.cancel", ["id": job]) } }
          .disabled(!["running", "queued", "needs_approval"].contains(string(detail, "status")))
      }
    }.padding(24).frame(width: 760, height: 550)
      .task {
        while !Task.isCancelled {
          do {
            let value = try await app.engine.call("jobs.get", ["id": job, "after": after]) as? [String: Any] ?? [:]
            guard !Task.isCancelled else { return }; detail = value
            for event in value["events"] as? [[String: Any]] ?? [] {
              let data = event["data"] as? [String: Any] ?? [:]
              if string(event, "type") == "progress" { progress = data; continue }
              lines += string(data, "text", string(data, "message", string(event, "type") == "result" ? pretty(data) : "")) + "\n"
            }
            lines = String(lines.suffix(150000)); after = value["next_sequence"] as? Int ?? after
            if !["running", "queued", "needs_approval", "cancelling"].contains(string(value, "status")) && value["has_more_events"] as? Bool != true { return }
            try await Task.sleep(for: .seconds(1))
          } catch is CancellationError { return } catch { failure = error.localizedDescription; return }
        }
      }
  }
}

private extension Dictionary where Key == String, Value == Any {
  var localModelFileID: String { string(self, "name") }
}
func localBytes(_ value: Any?) -> String {
  guard let bytes = value as? NSNumber else { return "Unknown" }
  return ByteCountFormatter.string(fromByteCount: bytes.int64Value, countStyle: .file)
}

struct LocalDownloadProgress: View {
  let value: [String: Any]
  var body: some View {
    VStack(alignment: .leading, spacing: 4) {
      if let done = value["completed"] as? NSNumber, let total = value["total"] as? NSNumber,
        total.doubleValue > 0, done.doubleValue >= 0 {
        ProgressView(value: min(done.doubleValue, total.doubleValue), total: total.doubleValue)
        Text(string(value, "unit") == "B" ? localBytes(done) + " / " + localBytes(total)
          : "\(done.intValue) / \(total.intValue) \(string(value, "unit", "items"))").font(.caption2).foregroundStyle(.secondary)
      } else { ProgressView().controlSize(.small) }
    }.help(string(value, "label", "Waiting for runtime progress"))
  }
}
