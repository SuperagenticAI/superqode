import AppKit
import SwiftUI

@MainActor final class HarnessStudioLibrary: ObservableObject {
  @Published var text = "" { didSet { if text != oldValue { invalidate() } } }
  @Published var name = "my-harness" { didSet { if name != oldValue { expectedFileDigest = ""; invalidate() } } }
  @Published var source = "definition" { didSet { if source != oldValue { invalidate() } } }
  @Published var provider = "openai" { didSet { if provider != oldValue { invalidate() } } }
  @Published var model = "" { didSet { if model != oldValue { invalidate() } } }
  @Published var localEngine = "ollama" { didSet { if localEngine != oldValue { invalidate() } } }
  @Published var review: [String: Any] = [:]
  @Published var catalog: [[String: Any]] = []
  @Published var evidence: [[String: Any]] = []
  @Published var busy = false
  @Published var failure = ""
  @Published var message = ""
  @Published private(set) var project = ""
  @Published private(set) var expectedFileDigest = ""
  private var generation = 0
  private var drafts: [String: [String: String]] = [:]
  var editVersion: Int { generation }

  var route: [String: Any] {
    source == "local" ? ["source": source, "engine": localEngine, "model": model]
      : source == "provider" ? ["source": source, "provider": provider, "model": model] : ["source": source]
  }
  func invalidate() { generation += 1; review = [:]; message = ""; busy = false }
  func enter(_ identity: String) {
    guard identity != project else { return }
    if !project.isEmpty { drafts[project] = ["text": text, "name": name, "source": source, "provider": provider, "model": model, "engine": localEngine, "file": expectedFileDigest] }
    invalidate(); project = identity; busy = false; failure = ""; catalog = []; evidence = []
    let draft = drafts[identity] ?? [:]
    text = draft["text"] ?? ""; name = draft["name"] ?? "my-harness"
    source = draft["source"] ?? "definition"; provider = draft["provider"] ?? "openai"
    model = draft["model"] ?? ""; localEngine = draft["engine"] ?? "ollama"; expectedFileDigest = draft["file"] ?? ""
  }
  func load(engine: Engine, reference: String = "core", revision: String = "", savedName: String = "") async {
    invalidate(); let token = generation; let identity = project
    busy = true; failure = ""
    defer { if generation == token { busy = false } }
    do {
      var params: [String: Any] = ["project": identity, "reference": reference]
      if !revision.isEmpty { params["revision"] = revision; params["name"] = savedName }
      let result = try await engine.call("studio.open", params) as? [String: Any] ?? [:]
      guard generation == token, project == identity, !Task.isCancelled else { return }
      text = string(result, "yaml"); name = string(result, "name")
      expectedFileDigest = string(result, "expected_file_digest")
      let selected = result["route"] as? [String: Any] ?? [:]
      source = string(selected, "source", "definition"); provider = string(selected, "provider", "openai")
      model = string(selected, "model"); localEngine = string(selected, "engine", "ollama")
      busy = false; review = [:]; message = revision.isEmpty ? "Preset loaded into the draft." : "Revision loaded. Validate and save to update the project definition."
    } catch { if generation == token, !Task.isCancelled { failure = error.localizedDescription } }
  }
  func validate(engine: Engine) async {
    invalidate(); let token = generation; let identity = project
    busy = true; failure = ""
    defer { if generation == token { busy = false } }
    do {
      let result = try await engine.call("studio.inspect", ["project": identity, "name": name, "yaml": text, "route": route]) as? [String: Any] ?? [:]
      guard generation == token, project == identity, !Task.isCancelled else { return }
      text = string(result, "yaml"); review = result; busy = false
      message = "Definition validated without model calls. Review routes and capabilities before saving or checking."
    } catch { if generation == token, !Task.isCancelled { failure = error.localizedDescription } }
  }
  @discardableResult func save(engine: Engine, reason: String) async throws -> Bool {
    let identity = project; let token = generation
    let result = try await engine.call("studio.save", ["project": identity, "review": string(review, "review"), "digest": string(review, "digest"), "reason": reason, "expected_file_digest": expectedFileDigest]) as? [String: Any] ?? [:]
    guard project == identity, generation == token else { return false }
    expectedFileDigest = string(result, "digest"); review = [:]
    message = "Revision saved. Selecting or evaluating it is a separate action."
    await refresh(engine: engine)
    return project == identity && generation == token
  }
  func refresh(engine: Engine) async {
    let identity = project
    do {
      let rows = try await engine.call("studio.list", ["project": identity]) as? [[String: Any]] ?? []
      try Task.checkCancellation()
      let checks = try await engine.call("studio.evidence", ["project": identity]) as? [[String: Any]] ?? []
      guard project == identity, !Task.isCancelled else { return }
      if !NSArray(array: catalog).isEqual(to: rows) { catalog = rows }
      if !NSArray(array: evidence).isEqual(to: checks) { evidence = checks }
    } catch { if project == identity, !Task.isCancelled { failure = error.localizedDescription } }
  }
}

struct HarnessStudioView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var library: HarnessStudioLibrary
  var active = true
  @State private var tab = "Definition"
  @State private var preset = "core"
  @State private var reason = ""
  @State private var checkSheet = false
  @State private var output: String?
  @State private var availableModels: [String] = []
  @State private var serverFailure = ""
  @State private var serverGeneration = 0
  private var inspection: [String: Any] { library.review["inspection"] as? [String: Any] ?? [:] }
  private var idle: Bool { !app.anyActive && !app.busy && !library.busy }

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      PageTitle(eyebrow: "Create · validate · check · version", title: "Harness Studio",
        subtitle: "Build a project harness, inspect its routes and keep check evidence beside the exact definition you tested.")
      Picker("Studio workspace", selection: $tab) {
        Text("Definition").tag("Definition"); Text("Revision history").tag("Revisions"); Text("Check evidence").tag("Evidence")
      }.pickerStyle(.segmented)
      if !library.failure.isEmpty { Text(library.failure).foregroundStyle(.orange).textSelection(.enabled) }
      if !library.message.isEmpty { Text(library.message).font(.caption).foregroundStyle(.secondary) }
      if tab == "Definition" { definition }
      else if tab == "Revisions" { revisions }
      else { evidence }
    }.padding(28)
      .onChange(of: active) { _, visible in
        if !visible {
          if checkSheet { checkSheet = false }
          if output != nil { output = nil }
        }
      }
      .task(id: app.projectID + "\n" + String(active)) {
        guard active else { return }
        library.enter(app.projectID)
        guard !app.projectID.isEmpty else { return }
        if library.text.isEmpty { await library.load(engine: app.engine) }
        await library.refresh(engine: app.engine)
      }
      .centeredDialog(isPresented: $checkSheet, title: "Review harness check", onDismiss: { Task { await library.refresh(engine: app.engine) } }) {
        HarnessStudioCheckView(project: library.project, review: library.review).environmentObject(app)
      }
      .centeredDialog(isPresented: Binding(get: { output != nil }, set: { if !$0 { output = nil } }), title: "Harness check evidence", onDismiss: { Task { await library.refresh(engine: app.engine) } }) {
        if let output { HarnessStudioEvidenceView(job: output).environmentObject(app) }
      }
  }

  private var definition: some View {
    HSplitView {
      VStack(alignment: .leading, spacing: 12) {
        HStack {
          TextField("Harness name", text: $library.name).textFieldStyle(.roundedBorder)
          CatalogPopup(label: "Start from", options: app.harnesses.filter {
            string($0, "desktop_kind").isEmpty
          }.map { CatalogPopupOption(id: string($0, "id"), title: string($0, "name")) }, selection: $preset)
            .frame(width: 210)
          Button("Load") { Task { await library.load(engine: app.engine, reference: preset) } }.disabled(library.busy)
          Button("Import…", action: importYAML).disabled(library.busy)
        }
        SourceEditor(text: $library.text, path: library.name + ".yaml", editable: true,
          documentID: "harness-studio:" + app.projectID, active: active)
          .brandSurface()
        Text("Drafts stay in this app session. Save revision persists a snapshot and the project definition.").font(.caption2).foregroundStyle(.secondary)
        TextField("Reason for this revision", text: $reason).textFieldStyle(.roundedBorder)
        HStack {
          Button("Validate definition") { Task { await library.validate(engine: app.engine) } }.disabled(library.busy || library.text.isEmpty || library.source == "agent")
          Button("Save revision") { save() }.buttonStyle(BrandButtonStyle()).disabled(!idle || library.review.isEmpty || reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
          Button("Review check…") { checkSheet = true }.disabled(!idle || library.review.isEmpty || inspection["ok"] as? Bool != true)
          if library.busy { ProgressView().controlSize(.small) }
        }
      }.frame(minWidth: 430).padding(.trailing, 16)
      ScrollView {
        VStack(alignment: .leading, spacing: 16) {
          Text("Model source").font(.headline)
          Picker("Source", selection: $library.source) {
            Text("From definition").tag("definition"); Text("Local server").tag("local"); Text("Provider configuration").tag("provider"); Text("Agent-owned").tag("agent")
          }
          if library.source == "local" {
            Picker("Runtime", selection: $library.localEngine) {
              Text("Ollama").tag("ollama"); Text("LM Studio").tag("lmstudio"); Text("MLX").tag("mlx"); Text("llama.cpp").tag("llama.cpp")
            }.onChange(of: library.localEngine) { _, _ in availableModels = []; serverFailure = "" }
            HStack {
              TextField("Served model ID", text: $library.model).textFieldStyle(.roundedBorder)
              Button("Load models") { loadModels() }
            }
            if !availableModels.isEmpty {
              Picker("Available models", selection: $library.model) {
                Text("Choose a model").tag("")
                ForEach(availableModels, id: \.self) { Text($0).tag($0) }
              }
            }
            if !serverFailure.isEmpty { Text(serverFailure).font(.caption).foregroundStyle(.orange) }
            Button("Open Local AI") { app.section = "Models" }
          } else if library.source == "provider" {
            Picker("Provider", selection: $library.provider) {
              ForEach(app.providers, id: \.projectRowID) { row in Text(string(row, "name")).tag(string(row, "id")) }
            }
            TextField("Model ID", text: $library.model).textFieldStyle(.roundedBorder)
            Button("Provider credentials…") { app.openConnections("source:key") }
          } else if library.source == "agent" {
            Text("Configure the agent’s model through its connection and advertised controls.").font(.callout).foregroundStyle(.secondary)
            Button("Open agent connections") { app.openConnections() }
          }
          if !library.review.isEmpty {
            Divider(); Text("Validation & routes").font(.headline)
            let capabilities = inspection["capabilities"] as? [String: Any] ?? [:]
            HStack { Pill(title: string(library.review, "backend")); Pill(title: string(capabilities, "availability", "unknown")) }
            ForEach(Array((library.review["routes"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { _, row in
              VStack(alignment: .leading, spacing: 3) { Text(string(row, "role")).font(.caption.bold()); Text(string(row, "model")).font(.caption.monospaced()).textSelection(.enabled) }
            }
            let selected = library.review["route"] as? [String: Any] ?? [:]
            if !string(selected, "endpoint").isEmpty { Text(string(selected, "endpoint")).font(.caption.monospaced()).textSelection(.enabled) }
            Text("Tools: " + (library.review["tools"] as? [String] ?? []).joined(separator: ", ")).font(.caption)
            DisclosureGroup("Execution policy") { CodeBlock(text: pretty(library.review["policy"] ?? [:])) }
            ForEach(library.review["warnings"] as? [String] ?? [], id: \.self) { Text($0).font(.caption).foregroundStyle(.orange) }
            Text("Definition digest: " + String(string(library.review, "digest").prefix(12))).font(.caption2.monospaced())
          } else { Text("Validate to inspect the resolved model route, execution policy and backend capabilities. Validation sends no prompts.").font(.caption).foregroundStyle(.secondary) }
        }.padding(.leading, 16)
      }.frame(minWidth: 260, idealWidth: 320, maxWidth: 400)
    }
  }

  private var revisions: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack { Text("Immutable definition snapshots").font(.headline); Spacer(); Button("Refresh") { Task { await library.refresh(engine: app.engine) } } }
      ScrollView {
        VStack(alignment: .leading, spacing: 14) {
          if library.catalog.isEmpty { Text("Save a revision from the Definition tab to begin its history.").foregroundStyle(.secondary) }
          ForEach(library.catalog, id: \.projectRowID) { harness in
            Text(string(harness, "id")).font(.headline)
            ForEach(harness["revisions"] as? [[String: Any]] ?? [], id: \.projectRowID) { version in
              VStack(alignment: .leading, spacing: 10) {
                HStack {
                  Text(String(string(version, "id").prefix(12))).font(.caption.monospaced())
                  if version["current"] as? Bool == true { Pill(title: "Project definition") }
                  if version["intact"] as? Bool != true { Pill(title: "Changed / unavailable") }
                  Spacer()
                  if let time = version["created"] as? Double { Text(Date(timeIntervalSince1970: time), style: .date).font(.caption) }
                }
                Text(string(version, "reason")).font(.callout)
                HStack {
                  Button("Load into draft") { tab = "Definition"; Task { await library.load(engine: app.engine, revision: string(version, "id"), savedName: string(harness, "id")) } }
                  Button("Use this revision") { use(version, name: string(harness, "id"), evaluate: false) }
                  Button("Evaluate…") { use(version, name: string(harness, "id"), evaluate: true) }
                }.disabled(!idle || version["intact"] as? Bool != true)
              }.padding(14).brandSurface()
            }
          }
        }
      }
    }
  }
  private var evidence: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack { Text("Checks tied to a definition digest").font(.headline); Spacer(); Button("Refresh") { Task { await library.refresh(engine: app.engine) } } }
      Text("A reduced-profile check measures the selected backend/model’s read/edit path. Full harness evaluation and adoption use separate evidence.").font(.caption).foregroundStyle(.secondary)
      ScrollView {
        VStack(spacing: 12) {
          if library.evidence.isEmpty { Text("Validate a definition, then prepare a read or edit check.").foregroundStyle(.secondary) }
          ForEach(library.evidence, id: \.projectRowID) { row in
            let result = row["result"] as? [String: Any] ?? [:]
            let summary = result["summary"] as? [String: Any] ?? [:]
            HStack {
              VStack(alignment: .leading, spacing: 5) {
                Text(string(row, "title")).font(.headline)
                Text("Definition " + String(string(row, "source_digest").prefix(12))).font(.caption.monospaced())
                if let count = summary["attempts"] as? Int { Text("\(summary["passed"] as? Int ?? 0)/\(count) checks passed · includes failed attempts").font(.caption) }
              }
              Spacer(); Pill(title: string(row, "status")); Button("Inspect") { output = string(row, "id") }
            }.padding(16).brandSurface()
          }
        }
      }
    }
  }

  private func save() {
    library.busy = true
    let project = app.projectID; let version = library.editVersion
    Task {
      defer { if library.project == project, library.editVersion == version { library.busy = false } }
      do {
        guard try await library.save(engine: app.engine, reason: reason) else { return }
        guard app.projectID == project, library.editVersion == version else { return }
        let definitions = try await app.engine.call("harnesses.list", ["project": project]) as? [[String: Any]] ?? []
        guard app.projectID == project, library.editVersion == version else { return }
        app.harnesses = definitions + app.harnesses.filter { !string($0, "desktop_kind").isEmpty }
        tab = "Revisions"
      } catch { if library.project == project, library.editVersion == version { library.failure = error.localizedDescription } }
    }
  }
  private func use(_ version: [String: Any], name: String, evaluate: Bool) {
    library.busy = true
    let project = app.projectID; let editVersion = library.editVersion
    Task {
      defer { if library.project == project, library.editVersion == editVersion { library.busy = false } }
      do {
        let result = try await app.engine.call("studio.use", ["project": project, "name": name, "revision": string(version, "id")]) as? [String: Any] ?? [:]
        let definitions = try await app.engine.call("harnesses.list", ["project": project]) as? [[String: Any]] ?? []
        guard app.projectID == project, library.editVersion == editVersion, !app.anyActive else { return }
        app.harnesses = definitions + app.harnesses.filter { !string($0, "desktop_kind").isEmpty }
        app.chooseHarness(string(result, "reference"))
        let route = result["route"] as? [String: Any] ?? [:]
        if !string(route, "provider").isEmpty && !string(route, "model").isEmpty { app.chooseModelRoute(string(route, "provider"), string(route, "model")) }
        app.section = evaluate ? "Evaluations" : "Workspace"
        app.notice = "Saved revision selected. No prompt has been sent."
      } catch { if library.project == project, library.editVersion == editVersion { library.failure = error.localizedDescription } }
    }
  }
  private func loadModels() {
    serverGeneration += 1; let generation = serverGeneration
    let engine = library.localEngine; let project = library.project
    Task {
      do {
        let result = try await app.engine.call("local.models.available", ["engine": engine]) as? [String: Any] ?? [:]
        guard serverGeneration == generation, library.localEngine == engine, library.project == project else { return }
        availableModels = result["models"] as? [String] ?? []; serverFailure = ""
      } catch { if serverGeneration == generation, library.localEngine == engine, library.project == project { serverFailure = error.localizedDescription } }
    }
  }
  private func importYAML() {
    let panel = NSOpenPanel(); panel.canChooseDirectories = false; panel.allowsMultipleSelection = false
    if panel.runModal() == .OK, let url = panel.url {
      do {
        let size = try url.resourceValues(forKeys: [.fileSizeKey]).fileSize ?? Int.max
        guard size <= 250_000 else { throw EngineError(message: "Choose a UTF-8 definition smaller than 250 KB.") }
        let bytes = try Data(contentsOf: url)
        guard bytes.count <= 250_000, let text = String(data: bytes, encoding: .utf8) else { throw EngineError(message: "Choose a UTF-8 definition smaller than 250 KB.") }
        library.text = text; library.failure = ""
      } catch { library.failure = error.localizedDescription }
    }
  }
}

struct HarnessStudioCheckView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  let review: [String: Any]
  @State private var check = "read"
  @State private var repeats = 1
  @State private var plan: [String: Any] = [:]
  @State private var busy = false
  @State private var failure = ""
  @State private var closed = false
  @State private var command = UUID().uuidString
  @State private var generation = 0
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Text("Review a bounded harness check").font(.title2)
      Text("Uses disposable generated files with this backend and model. Source hooks, MCP, delegation, fallbacks and shell are excluded.").foregroundStyle(.secondary)
      Picker("Check", selection: $check) { Text("Read tool roundtrip").tag("read"); Text("Read, edit & syntax check").tag("edit") }.pickerStyle(.segmented).disabled(busy)
      Stepper("Attempts: \(repeats)", value: $repeats, in: 1...5).disabled(busy)
      Button("Prepare check") {
        generation += 1; let token = generation; let selectedCheck = check; let count = repeats
        busy = true; plan = [:]; failure = ""
        Task {
          defer { busy = false }
          do {
            let value = try await app.engine.call("studio.check.prepare", ["project": project, "review": string(review, "review"), "digest": string(review, "digest"), "check": selectedCheck, "repeats": count]) as? [String: Any] ?? [:]
            guard !closed, token == generation, selectedCheck == check, count == repeats else { return }; plan = value
          } catch { failure = error.localizedDescription }
        }
      }.disabled(busy)
      if !plan.isEmpty {
        Text(string(plan, "title")).font(.headline)
        Text(string(plan, "scope")).font(.callout).foregroundStyle(.secondary)
        Text("Definition: " + String(string(plan, "source_digest").prefix(12))).font(.caption.monospaced())
        CodeBlock(text: pretty(plan["route"] ?? [:])).frame(height: 110)
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
      Spacer()
      HStack {
        Button("Cancel") { closed = true; dismiss() }.keyboardShortcut(.cancelAction); Spacer()
        Button("Run reviewed check") {
          busy = true
          Task {
            defer { busy = false }
            do {
              let result = try await app.engine.call("studio.check.start", ["project": project, "plan": string(plan, "plan"), "digest": string(plan, "digest"), "command_id": command]) as? [String: Any] ?? [:]
              guard !closed else { return }; app.notice = "Harness check started. Inspect it in Harness Studio → Check evidence. Run " + String(string(result, "id").prefix(8)); dismiss()
            } catch { failure = error.localizedDescription }
          }
        }.buttonStyle(BrandButtonStyle()).disabled(plan.isEmpty || busy || app.projectID != project || app.anyActive)
      }
    }.padding(24).frame(width: 760, height: 560)
      .onChange(of: check) { _, _ in generation += 1; plan = [:]; command = UUID().uuidString }
      .onChange(of: repeats) { _, _ in generation += 1; plan = [:]; command = UUID().uuidString }
      .onDisappear { closed = true }
  }
}

struct HarnessStudioEvidenceView: View {
  @EnvironmentObject var app: Workspace
  let job: String
  @State private var detail: [String: Any] = [:]
  @State private var failure = ""
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      Text(string(detail, "title", "Harness check")).font(.title2)
      Pill(title: string(detail, "status", "Loading"))
      let result = detail["result"] as? [String: Any] ?? [:]
      let summary = result["summary"] as? [String: Any] ?? [:]
      if let count = summary["attempts"] as? Int {
        Text("\(summary["passed"] as? Int ?? 0)/\(count) attempts passed").font(.headline)
        if let interval = summary["wilson_95"] as? [Double], interval.count == 2 { Text(String(format: "95%% Wilson interval: %.0f–%.0f%% · limited to this check", interval[0]*100, interval[1]*100)).font(.caption).foregroundStyle(.secondary) }
        Text("Input tokens: \((summary["tokens_in"] as? Int).map(String.init) ?? "Unknown") · Output tokens: \((summary["tokens_out"] as? Int).map(String.init) ?? "Unknown")")
          .font(.caption)
      }
      Text(string(result, "note", "Preparing recorded evidence…")).font(.caption).foregroundStyle(.secondary)
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          ForEach(Array((result["attempts"] as? [[String: Any]] ?? []).enumerated()), id: \.offset) { index, attempt in
            DisclosureGroup("Attempt \(index+1) · \(string(attempt, "status"))") { CodeBlock(text: pretty(attempt)) }
          }
          if result.isEmpty { Text(pretty(detail["events"] ?? [])).font(.caption.monospaced()).textSelection(.enabled) }
        }
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
      HStack { Text("Execution completion and check quality are separate.").font(.caption).foregroundStyle(.secondary); Spacer()
        Button("Cancel check") { app.perform { _ = try await app.engine.call("jobs.cancel", ["id": job]) } }
          .disabled(!["running", "queued", "needs_approval"].contains(string(detail, "status")))
      }
    }.padding(24).frame(width: 840, height: 620)
      .task {
        while !Task.isCancelled {
          do {
            let result = try await app.engine.call("jobs.get", ["id": job]) as? [String: Any] ?? [:]
            guard !Task.isCancelled else { return }; detail = result
            if !["running", "queued", "cancelling", "needs_approval"].contains(string(result, "status")) { return }
            try await Task.sleep(for: .seconds(1))
          } catch is CancellationError { return } catch { failure = error.localizedDescription; return }
        }
      }
  }
}
