import SwiftUI

func visibleContextPath(_ path: String) -> Bool {
  let parts = path.split(separator: "/").map(String.init)
  let binary = ["png", "jpg", "jpeg", "gif", "webp", "pdf", "zip", "gz", "gguf", "bin", "sqlite3", "db", "pyc", "dylib", "so", "ttf", "woff2"]
  return !path.hasPrefix("/") && !path.contains("\\") && !path.hasPrefix(".superqode/checkpoints/")
    && !parts.contains { ["..", ".git", ".ssh", ".aws"].contains($0) || $0.hasPrefix(".env") }
    && !binary.contains(URL(fileURLWithPath: path).pathExtension.lowercased())
}

struct ContextFilesScreen: View {
  let profile: String
  let initial: [String]
  let apply: ([String]) -> Void
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @State private var files: [String] = []
  @State private var selected: Set<String> = []
  @State private var query = ""
  @State private var issue = ""
  @State private var loading = true
  @State private var checking = false
  var body: some View {
    List {
      Section {
        Text("Attach up to ten non-sensitive UTF-8 project files, 64 KB in total. Files are validated now and snapshotted again when the task starts.").font(.footnote).foregroundStyle(.secondary)
        ConnectionStatus()
      }.listRowBackground(Color.clear)
      if loading { ProgressView("Loading project files…") }
      if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      ForEach(files.filter { query.isEmpty || $0.localizedCaseInsensitiveContains(query) }, id: \.self) { path in
        Button {
          if selected.contains(path) { selected.remove(path) }
          else if selected.count < 10 { selected.insert(path) }
        } label: {
          HStack { Text(path).font(.subheadline.monospaced()).foregroundStyle(.primary); Spacer(); Image(systemName: selected.contains(path) ? "checkmark.circle.fill" : "circle").foregroundStyle(CompanionTheme.accent) }
        }.disabled(checking || (selected.count >= 10 && !selected.contains(path))).listRowBackground(CompanionTheme.panel)
      }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background).navigationTitle("Reference files")
      .searchable(text: $query, prompt: "Find a project file")
      .toolbar {
        ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() }.disabled(checking) }
        ToolbarItem(placement: .confirmationAction) { Button(checking ? "Checking…" : "Attach \(selected.count)") { Task { await confirm() } }.disabled(checking || loading) }
      }.interactiveDismissDisabled(checking)
      .task {
        selected = Set(initial)
        defer { loading = false }
        guard let api = store.api, let connection = store.profiles.first(where: { $0.id == profile }) else { return }
        do { files = try await api.rpc("files.list", ["project": .string(connection.text("project"))]).array.map(\.text).filter(visibleContextPath) }
        catch is CancellationError { }
        catch { issue = error.localizedDescription }
      }
  }
  private func confirm() async {
    guard let api = store.api, !checking else { return }
    checking = true; issue = ""
    defer { checking = false }
    do {
      let paths = selected.sorted()
      _ = try await api.rpc("context.preview", ["profile": .string(profile), "prompt": .string("Validate the selected reference files."), "interaction_mode": .string("code"), "context_files": .array(paths.map(JSONValue.string))])
      apply(paths); dismiss()
    } catch { issue = error.localizedDescription }
  }
}

struct ContextPreviewScreen: View {
  let params: [String: JSONValue]
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @State private var result: [String: JSONValue] = [:]
  @State private var issue = ""
  @State private var loading = true
  @State private var expanded = false
  var body: some View {
    List {
      Section { ConnectionStatus(); Text("Reference material is untrusted input. The task reads current file contents again when it starts.").font(.footnote).foregroundStyle(.secondary) }
      if loading { ProgressView("Preparing context…") }
      if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      ForEach(Array(result.records("files").enumerated()), id: \.offset) { _, file in
        VStack(alignment: .leading, spacing: 6) {
          Text(file.text("path")).font(.subheadline.monospaced())
          Text("\(Int(file.raw.number("bytes"))) bytes · " + String(file.text("sha256").prefix(12))).font(.caption.monospaced()).foregroundStyle(.secondary)
        }
      }
      DisclosureGroup("Show prepared model input", isExpanded: $expanded) {
        if expanded { Text(result.text("prompt")).font(.system(.caption, design: .monospaced)).textSelection(.enabled) }
      }
    }.navigationTitle("Check context").scrollContentBackground(.hidden).background(CompanionTheme.background)
      .toolbar { Button("Done") { dismiss() } }
      .task {
        defer { loading = false }
        guard let api = store.api else { return }
        do { result = try await api.rpc("context.preview", params).object }
        catch is CancellationError { }
        catch { issue = error.localizedDescription }
      }
  }
}
