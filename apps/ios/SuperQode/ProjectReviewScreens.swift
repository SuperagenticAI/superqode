import SwiftUI

struct FilesScreen: View {
  let project: String
  @EnvironmentObject private var store: CompanionStore
  @State private var files: [String] = []
  @State private var query = ""
  @State private var issue = ""
  var body: some View {
    List {
      if !issue.isEmpty { Text(issue).foregroundStyle(.orange) }
      ForEach(files.filter { query.isEmpty || $0.localizedCaseInsensitiveContains(query) }, id: \.self) { path in
        NavigationLink { FilePreviewScreen(project: project, path: path) } label: {
          Label(path, systemImage: "doc.text").font(.subheadline)
        }
      }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background)
      .navigationTitle("Project files").searchable(text: $query)
      .task { await load() }.refreshable { await load() }
  }
  private func load() async {
    guard let api = store.api else { return }
    do { files = try await api.rpc("files.list", ["project": .string(project)]).array.map(\.text); issue = "" }
    catch { issue = error.localizedDescription }
  }
}

struct FilePreviewScreen: View {
  let project: String
  let path: String
  @EnvironmentObject private var store: CompanionStore
  @State private var content = ""
  @State private var issue = ""
  var body: some View {
    ScrollView([.horizontal, .vertical]) {
      Text(issue.isEmpty ? content : issue).font(.system(.caption, design: .monospaced))
        .foregroundStyle(issue.isEmpty ? Color.primary : Color.orange)
        .textSelection(.enabled).padding(20).frame(maxWidth: .infinity, alignment: .leading)
    }.background(CompanionTheme.background).navigationTitle(path).navigationBarTitleDisplayMode(.inline)
      .task {
        guard let api = store.api else { return }
        do { content = try await api.rpc("files.read", ["project": .string(project), "path": .string(path)]).object.text("text") }
        catch { issue = error.localizedDescription }
      }
  }
}

struct ChangesScreen: View {
  let project: String
  @EnvironmentObject private var store: CompanionStore
  @State private var changes: [String: JSONValue] = [:]
  @State private var issue = ""
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        if !issue.isEmpty { Text(issue).foregroundStyle(.orange) }
        CompanionCard {
          Label(changes.text("branch", "Working tree"), systemImage: "arrow.triangle.branch").font(.headline)
          Text(changes.text("status", "No working-tree changes.")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
          if !changes.text("stat").isEmpty { Text(changes.text("stat")).font(.system(.caption, design: .monospaced)) }
        }
        if !changes.text("diff").isEmpty {
          Text(changes.text("diff")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
        }
        Text("Read-only review. Commits, merges and restores stay on your Mac.").font(.caption).foregroundStyle(.secondary)
      }.padding(20)
    }.background(CompanionTheme.background).navigationTitle("Changes")
      .task { await load() }.refreshable { await load() }
  }
  private func load() async {
    guard let api = store.api else { return }
    do { changes = try await api.rpc("git.status", ["project": .string(project)]).object; issue = "" }
    catch { issue = error.localizedDescription }
  }
}
