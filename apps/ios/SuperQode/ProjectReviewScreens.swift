import SwiftUI

struct FilesScreen: View {
  let project: String
  @EnvironmentObject private var store: CompanionStore
  @State private var files: [String] = []
  @State private var query = ""
  @State private var issue = ""
  @State private var loading = true
  @State private var creating = false
  var body: some View {
    List {
      if loading { ProgressView("Loading project files…") }
      if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      ForEach(files.filter { query.isEmpty || $0.localizedCaseInsensitiveContains(query) }, id: \.self) { path in
        NavigationLink { FilePreviewScreen(project: project, path: path) } label: {
          Label(path, systemImage: "doc.text").font(.subheadline)
            .accessibilityIdentifier("project.file." + path)
        }.listRowBackground(CompanionTheme.panel)
      }
      if !loading && files.isEmpty && issue.isEmpty { ContentUnavailableView("No files to display", systemImage: "doc.text.magnifyingglass") }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background)
      .navigationTitle("Project files").searchable(text: $query)
      .toolbar { Button("New file", systemImage: "doc.badge.plus") { creating = true }.disabled(!store.canMutate || !store.permissions.contains("edit")) }
      .sheet(isPresented: $creating, onDismiss: { Task { await load() } }) { NavigationStack { FileEditorScreen(project: project, path: "", creating: true) } }
      .task { await load() }.refreshable { await load() }
  }
  private func load() async {
    guard let api = store.api else { loading = false; return }
    loading = true
    defer { loading = false }
    do { files = try await api.rpc("files.list", ["project": .string(project)]).array.map(\.text); issue = "" }
    catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
}

struct FilePreviewScreen: View {
  let project: String
  let path: String
  @EnvironmentObject private var store: CompanionStore
  @State private var content = ""
  @State private var issue = ""
  @State private var loading = true
  var body: some View {
    Group {
      if loading { ProgressView("Opening file…").frame(maxWidth: .infinity, maxHeight: .infinity) }
      else if !issue.isEmpty { ContentUnavailableView("File unavailable", systemImage: "doc.badge.ellipsis", description: Text(issue)) }
      else { MobileCodeBlock(code: content, language: URL(fileURLWithPath: path).pathExtension, fullHeight: true).padding(12) }
    }.background(CompanionTheme.background).navigationTitle(URL(fileURLWithPath: path).lastPathComponent).navigationBarTitleDisplayMode(.inline)
      .toolbar { NavigationLink("Edit") { FileEditorScreen(project: project, path: path) }.disabled(!store.permissions.contains("edit")) }
      .task {
        guard let api = store.api else { loading = false; return }
        defer { loading = false }
        do { content = try await api.rpc("files.read", ["project": .string(project), "path": .string(path)]).object.text("text") }
        catch is CancellationError { }
        catch { issue = error.localizedDescription }
      }
  }
}

struct ChangesScreen: View {
  let project: String
  @EnvironmentObject private var store: CompanionStore
  @State private var changes: [String: JSONValue] = [:]
  @State private var issue = ""
  @State private var loading = true
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      if loading { ProgressView("Reading working tree…") }
      if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      CompanionCard {
        Label(changes.text("branch", "Working tree"), systemImage: "arrow.triangle.branch").font(.headline)
        Text(changes.text("status", loading ? "Checking changes…" : "Working tree is clean.")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
        if !changes.text("stat").isEmpty { Text(changes.text("stat")).font(.system(.caption, design: .monospaced)) }
      }.fixedSize(horizontal: false, vertical: true)
      if !changes.text("diff").isEmpty {
        MobileCodeBlock(code: changes.text("diff"), language: "diff", fullHeight: true)
      } else { Spacer(minLength: 0) }
      Text("Read-only working-tree review. Agent tasks still follow their configured tool permissions.")
        .font(.caption).foregroundStyle(.secondary)
    }.padding(16).background(CompanionTheme.background).navigationTitle("Changes")
      .task { await load() }.refreshable { await load() }
  }
  private func load() async {
    guard let api = store.api else { loading = false; return }
    loading = true
    defer { loading = false }
    do { changes = try await api.rpc("git.status", ["project": .string(project)]).object; issue = "" }
    catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
}
