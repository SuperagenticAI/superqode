import AppKit
import SwiftUI

@MainActor final class ExternalSessionLibrary: ObservableObject {
  @Published var sources: [[String: Any]] = []
  @Published var rows: [[String: Any]] = []
  @Published var count = 0
  @Published var cursor = ""
  @Published var loading = false
  @Published var failure = ""
  private var generation = 0
  private var scope = ""

  func load(engine: Engine, source: String, project: String, query: String, more: Bool = false) async {
    if more && (loading || cursor.isEmpty) { return }
    if !more {
      generation += 1
      let nextScope = source + "\n" + project + "\n" + query
      if nextScope != scope { rows = []; count = 0; cursor = ""; scope = nextScope }
    }
    let token = generation
    loading = true
    defer { if generation == token { loading = false } }
    do {
      let nextSources = try await engine.call("external.sources.list") as? [[String: Any]] ?? []
      guard generation == token, !Task.isCancelled else { return }
      sources = nextSources
      let result = try await engine.call("external.sessions.list", ["source": source, "project": project,
        "query": query, "cursor": more ? cursor : ""]) as? [String: Any] ?? [:]
      guard generation == token, !Task.isCancelled else { return }
      var seen = Set<String>()
      rows = (more ? rows + (result["items"] as? [[String: Any]] ?? []) : result["items"] as? [[String: Any]] ?? [])
        .filter { seen.insert(string($0, "id")).inserted }
      count = result["count"] as? Int ?? 0
      cursor = string(result, "next_cursor")
      failure = ""
    } catch is CancellationError {} catch {
      if generation == token { failure = error.localizedDescription }
    }
  }
}

struct ExternalSessionsView: View {
  @EnvironmentObject var app: Workspace
  @StateObject private var library = ExternalSessionLibrary()
  @State private var query = ""
  @State private var source = ""
  @State private var scope = ""
  @State private var operating = false
  @State private var operationError = ""
  @State private var handoff: [String: Any]?
  private var signature: String { source + "\n" + scope + "\n" + query }

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack(alignment: .top) {
        VStack(alignment: .leading, spacing: 5) {
          Text("Bring your existing work into view").font(.headline)
          Text("Connect a Codex sessions or archived_sessions folder. Only session metadata is indexed; message text is read when you review a handoff.")
            .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
        }
        Spacer(minLength: 16)
        Button("Add session folder…", systemImage: "folder.badge.plus", action: chooseFolder)
          .disabled(operating || !app.connected)
      }
      if !library.sources.isEmpty {
        ScrollView(.horizontal) {
          HStack(alignment: .top, spacing: 12) {
            ForEach(library.sources, id: \.projectRowID) { row in sourceCard(row) }
          }.padding(.bottom, 4)
        }.fixedSize(horizontal: false, vertical: true)
      }
      HStack {
        TextField("Find a project, branch or session ID", text: $query).textFieldStyle(.roundedBorder)
          .onChange(of: query) { _, value in if value.count > 200 { query = String(value.prefix(200)) } }
        Picker("Folder", selection: $source) {
          Text("All sources").tag("")
          ForEach(library.sources, id: \.projectRowID) { row in
            Text(URL(fileURLWithPath: string(row, "path")).lastPathComponent).tag(string(row, "id"))
          }
        }.frame(maxWidth: 170)
        Picker("Project", selection: $scope) {
          Text("All projects").tag("")
          ForEach(app.projects, id: \.projectRowID) { row in
            Text(string(row, "name", URL(fileURLWithPath: string(row, "path")).lastPathComponent)).tag(string(row, "id"))
          }
        }.frame(maxWidth: 190)
        Button { Task { await reload() } } label: { Image(systemName: "arrow.clockwise") }
          .accessibilityLabel("Reload indexed external history").help("Reload the saved index. Use Refresh source to read changes on disk.")
          .disabled(library.loading || operating)
      }
      if operating { ProgressView("Updating session sources…").controlSize(.small) }
      if !operationError.isEmpty { Text(operationError).foregroundStyle(.orange).textSelection(.enabled) }
      if !library.failure.isEmpty {
        HStack {
          Text(library.failure).foregroundStyle(.orange)
          Button("Retry") { Task { await reload() } }.disabled(operating)
        }
      }
      HStack {
        Text("\(library.count) recorded \(library.count == 1 ? "session" : "sessions")").font(.caption).foregroundStyle(.secondary)
        Spacer()
        Label("Live status unavailable", systemImage: "clock").font(.caption).foregroundStyle(.secondary)
      }
      ScrollView {
        LazyVStack(spacing: 10) {
          ForEach(library.rows, id: \.projectRowID) { row in sessionCard(row) }
          if library.loading { ProgressView("Loading external history…").padding() }
          if library.rows.isEmpty && !library.loading && library.failure.isEmpty {
            ContentUnavailableView(library.sources.isEmpty ? "Connect your existing sessions" : "No matching recorded sessions",
              systemImage: "tray.full", description: Text(library.sources.isEmpty
                ? "Choose a Codex session folder to get started. Nothing is scanned until you choose a folder."
                : "Try another filter or refresh a source. Only supported Codex JSONL sessions are indexed."))
          }
          if !library.cursor.isEmpty && !library.loading {
            Button("Load more sessions") { Task { await reload(more: true) } }.padding()
          }
        }.padding(.bottom, 12)
      }
      Text("External files stay unchanged. A handoff prepares text in a SuperQode draft; provider state, tools, permissions and attachments are not resumed.")
        .font(.caption).foregroundStyle(.secondary)
    }
    .task(id: signature) {
      do { try await Task.sleep(for: .milliseconds(180)) } catch { return }
      await reload()
    }
    .centeredDialog(isPresented: Binding(get: { handoff != nil }, set: { if !$0 { handoff = nil } }), title: "Review external session") {
      if let handoff { ExternalSessionHandoffView(row: handoff, project: app.projectID).environmentObject(app) }
    }
  }

  private func sourceCard(_ row: [String: Any]) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      Label("Codex session source", systemImage: "folder").font(.headline)
      Text(string(row, "path")).font(.caption).lineLimit(1).truncationMode(.middle).help(string(row, "path"))
      Text("\(row["count"] as? Int ?? 0) indexed \(row["count"] as? Int == 1 ? "session" : "sessions")").font(.caption).foregroundStyle(.secondary)
      if let scanned = row["scanned"] as? Double, scanned > 0 {
        Text("Indexed \(Date(timeIntervalSince1970: scanned).formatted(date: .abbreviated, time: .shortened))")
          .font(.caption2).foregroundStyle(.secondary)
      } else { Text("Not scanned yet").font(.caption2).foregroundStyle(.secondary) }
      if let report = row["report"] as? [String: Any] {
        if report["partial"] as? Bool == true {
          Text("Partial scan; choose a smaller folder for complete coverage.").font(.caption).foregroundStyle(.orange)
        }
        if let unavailable = report["unavailable"] as? Int, unavailable > 0 {
          Text("\(unavailable) files unavailable or changing.").font(.caption).foregroundStyle(.orange)
        }
        if let ignored = report["ignored"] as? Int, ignored > 0 {
          Text("\(ignored) files had no supported session metadata.").font(.caption).foregroundStyle(.secondary)
        }
      }
      HStack {
        Button("Refresh source") { updateSource("external.sources.scan", id: string(row, "id")) }
        Spacer()
        Button("Disconnect", role: .destructive) { updateSource("external.sources.remove", id: string(row, "id")) }
          .help("Remove this source and its index. Original session files are preserved.")
      }.controlSize(.small).disabled(operating || !app.connected)
    }.padding(16).frame(width: 340, alignment: .leading).brandSurface()
  }

  private func sessionCard(_ row: [String: Any]) -> some View {
    HStack(alignment: .top, spacing: 14) {
      HarnessIconStack(row: row, size: 34)
      VStack(alignment: .leading, spacing: 6) {
        Text(string(row, "title")).font(.headline).lineLimit(2)
        Text(string(row, "cwd")).font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
          .help(string(row, "cwd"))
        HStack {
          Label("Recorded · Codex", systemImage: "clock")
          if !string(row, "branch").isEmpty { Label(string(row, "branch"), systemImage: "arrow.triangle.branch").lineLimit(1) }
          if let updated = row["updated"] as? Double { Text(Date(timeIntervalSince1970: updated), style: .relative) }
        }.font(.caption).foregroundStyle(.secondary)
      }
      Spacer(minLength: 8)
      VStack(alignment: .trailing, spacing: 8) {
        Button("Review handoff…") { handoff = row }
          .disabled(app.projectID.isEmpty || app.busy || app.openingProject || app.restoringNavigation || operating)
          .help(app.projectID.isEmpty ? "Open a destination project first." : "Review recorded text before adding it to a draft in the current project.")
        Button("Show in Finder") {
          app.perform {
            let result = try await app.engine.call("external.sessions.reveal", ["id": string(row, "id"), "source": string(row, "source")]) as? [String: Any] ?? [:]
            let path = string(result, "path")
            guard !path.isEmpty else { return }
            NSWorkspace.shared.activateFileViewerSelecting([URL(fileURLWithPath: path)])
          }
        }.font(.caption)
      }
    }.padding(18).brandSurface()
  }

  private func reload(more: Bool = false) async {
    await library.load(engine: app.engine, source: source, project: scope, query: query, more: more)
  }

  private func chooseFolder() {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true
    panel.canChooseFiles = false
    panel.allowsMultipleSelection = false
    panel.showsHiddenFiles = true
    panel.prompt = "Connect session folder"
    panel.message = "Choose a Codex sessions or archived_sessions folder. SuperQode reads metadata here; full text is read only for a handoff you review."
    guard panel.runModal() == .OK, let url = panel.url else { return }
    operating = true
    operationError = ""
    Task {
      defer { operating = false }
      do {
        let added = try await app.engine.call("external.sources.add", ["provider": "codex", "path": url.path]) as? [String: Any] ?? [:]
        _ = try await app.engine.call("external.sources.scan", ["id": string(added, "id")])
      } catch { operationError = error.localizedDescription }
      await reload()
    }
  }

  private func updateSource(_ method: String, id: String) {
    operating = true
    operationError = ""
    Task {
      defer { operating = false }
      do {
        _ = try await app.engine.call(method, ["id": id])
        if method == "external.sources.remove", source == id { source = "" }
      } catch { operationError = error.localizedDescription }
      await reload()
    }
  }
}

struct ExternalSessionHandoffView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let row: [String: Any]
  let project: String
  @State private var preview: [String: Any] = [:]
  @State private var failure = ""
  @State private var target = ""
  @State private var query = ""
  @State private var loading = false
  @State private var adding = false
  @State private var closed = false
  @StateObject private var targets = ThreadLibrary()

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Text("Continue from recorded Codex context").font(.title2)
      Text("Destination: \(string(app.project, "path"))").font(.caption).foregroundStyle(.secondary)
      Text("This is a text handoff. Review what will be included, then choose any supported harness in the destination before sending.")
        .foregroundStyle(.secondary)
      HStack {
        TextField("Find a destination thread", text: $query).textFieldStyle(.roundedBorder)
          .onChange(of: query) { _, value in
            target = ""
            if value.count > 200 { query = String(value.prefix(200)) }
          }
        Button("Reload preview") { Task { await loadPreview() } }.disabled(loading || adding)
      }
      Picker("Destination", selection: $target) {
        Text("New thread draft").tag("")
        ForEach(targets.rows.filter { string($0, "kind") == "task" && ["completed", "failed", "cancelled", "interrupted"].contains(string($0, "status")) }, id: \.projectRowID) { item in
          Text(string(item, "conversation_title", string(item, "title"))).tag(string(item, "id"))
        }
      }
      if !targets.cursor.isEmpty {
        Button("Load more destinations") { Task { await loadTargets(more: true) } }.disabled(targets.loading)
      }
      if !targets.failure.isEmpty { Text(targets.failure).font(.caption).foregroundStyle(.orange) }
      if loading { ProgressView("Reading recorded text…") }
      ScrollView {
        Text(string(preview, "text")).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
          .frame(maxWidth: .infinity, alignment: .leading).padding(12)
      }.brandSurface()
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      HStack {
        Text("Existing drafts are preserved. Nothing is sent automatically.").font(.caption).foregroundStyle(.secondary)
        Spacer()
        Button("Cancel") { closed = true; dismiss() }.keyboardShortcut(.cancelAction)
        Button("Add to draft", action: addToDraft).buttonStyle(BrandButtonStyle())
          .disabled(loading || adding || preview.isEmpty || app.projectID != project || app.busy || app.openingProject || app.restoringNavigation)
      }
    }.padding(24).frame(width: 760, height: 600)
      .task { await loadPreview() }
      .task(id: query) {
        do { try await Task.sleep(for: .milliseconds(180)) } catch { return }
        await loadTargets()
      }
      .onDisappear { closed = true }
  }

  private func loadTargets(more: Bool = false) async {
    await targets.load(engine: app.engine, project: project, query: query, view: "active", more: more)
  }
  private func loadPreview() async {
    loading = true
    preview = [:]
    failure = ""
    defer { loading = false }
    do {
      let result = try await app.engine.call("external.sessions.preview", ["id": string(row, "id"), "source": string(row, "source")]) as? [String: Any] ?? [:]
      guard !closed, !Task.isCancelled, app.projectID == project else { return }
      preview = result
    } catch { failure = error.localizedDescription }
  }
  private func addToDraft() {
    let destination = target
    let digest = string(preview, "digest")
    adding = true
    Task {
      defer { adding = false }
      do {
        let checked = try await app.engine.call("external.sessions.preview", ["id": string(row, "id"), "source": string(row, "source"), "expected_digest": digest]) as? [String: Any] ?? [:]
        let summary = destination.isEmpty ? nil : try await app.engine.call("threads.get", ["project": project, "id": destination]) as? [String: Any]
        guard !closed, !Task.isCancelled else { return }
        if app.addSharedThreadContext(string(checked, "text"), project: project,
          target: summary.map { string($0, "id") } ?? destination, targetSummary: summary) {
          app.notice = "External context added to the draft. Choose your harness and review before sending."
          dismiss()
        } else { failure = "The destination changed or is busy. Choose an idle thread in the current project." }
      } catch { failure = error.localizedDescription }
    }
  }
}
