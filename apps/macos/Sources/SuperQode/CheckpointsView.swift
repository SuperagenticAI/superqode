import SwiftUI

struct CheckpointsView: View {
  @EnvironmentObject var app: Workspace
  @State private var items: [[String: Any]] = []
  @State private var diff = ""
  @State private var failure = ""
  @State private var canUndo = false
  @State private var canRedo = false
  @State private var loadGeneration = 0
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      PageTitle(
        eyebrow: "A way back", title: "Task checkpoints",
        subtitle:
          "Restore recorded task changes with revision checks. Your Git index stays unchanged.")
      HStack {
        Button("Refresh") { load() }
        Button("Undo last task") { restore("checkpoints.undo") }.disabled(!canUndo || app.anyActive)
        Button("Redo") { restore("checkpoints.redo") }.disabled(!canRedo || app.anyActive)
        Spacer()
      }
      if !failure.isEmpty {
        Text(failure).font(.callout).foregroundStyle(.orange).textSelection(.enabled)
      }
      HSplitView {
        ScrollView {
          LazyVStack(alignment: .leading, spacing: 12) {
            ForEach(items.reversed(), id: \.projectRowID) { item in
              VStack(alignment: .leading, spacing: 8) {
                Text(string(item, "name")).font(.headline)
                Text(string(item, "timestamp")).font(.caption.monospaced()).foregroundStyle(
                  .secondary)
                ForEach(item["changes"] as? [[String: Any]] ?? [], id: \.checkpointPath) { change in
                  Button(string(change, "change_type") + " · " + string(change, "path")) {
                    app.checkpointID = string(item, "id")
                    app.checkpointPath = string(change, "path")
                    loadSelectedDiff()
                  }.buttonStyle(.borderless).font(.caption.monospaced())
                }
                if (item["changes"] as? [Any] ?? []).isEmpty {
                  Text(
                    item["sealed"] as? Bool == true
                      ? "This task made no restorable file changes."
                      : "After-state unavailable; review interrupted work manually."
                  ).font(.caption).foregroundStyle(.secondary)
                }
                Button("Restore task baseline") {
                  restore("checkpoints.restore", id: string(item, "id"))
                }.disabled(
                  app.anyActive || item["sealed"] as? Bool != true
                    || (item["changes"] as? [Any] ?? []).isEmpty)
              }.padding(16).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
            }
            if items.isEmpty {
              Text(
                "Local coding runs create checkpoints automatically in a Git repository. Remote server tasks do not modify this Mac’s files."
              ).foregroundStyle(.secondary).padding()
            }
          }
        }.frame(minWidth: 250, idealWidth: 340, maxWidth: 440)
        CodeBlock(
          text: diff.isEmpty ? "Choose a changed file to inspect its checkpoint diff." : diff
        ).padding(.leading, 14)
      }
    }.padding(26).onAppear { load() }.onDisappear { loadGeneration += 1 }
      .onChange(of: app.checkpointPath) { _, _ in loadSelectedDiff() }
  }
  private func load() {
    loadGeneration += 1
    let generation = loadGeneration
    let project = app.projectID
    app.perform {
      do {
        let result =
          try await app.engine.call("checkpoints.list", ["project": project])
          as? [String: Any] ?? [:]
        guard project == app.projectID, generation == loadGeneration else { return }
        items = result["items"] as? [[String: Any]] ?? []
        canUndo = result["can_undo"] as? Bool ?? false
        canRedo = result["can_redo"] as? Bool ?? false
        failure = ""
        loadSelectedDiff()
      } catch {
        if project == app.projectID, generation == loadGeneration { failure = error.localizedDescription }
      }
    }
  }
  private func loadSelectedDiff() {
    let project = app.projectID
    let id = app.checkpointID
    let path = app.checkpointPath
    let generation = loadGeneration
    guard !id.isEmpty, !path.isEmpty else { diff = ""; return }
    diff = ""
    app.perform {
      do {
        let result = try await app.engine.call("checkpoints.diff", ["project": project, "id": id, "path": path])
          as? [String: Any] ?? [:]
        guard project == app.projectID, generation == loadGeneration,
          id == app.checkpointID, path == app.checkpointPath else { return }
        diff = string(result, "diff")
      } catch {
        if project == app.projectID, generation == loadGeneration,
          id == app.checkpointID, path == app.checkpointPath { failure = error.localizedDescription }
      }
    }
  }
  private func restore(_ method: String, id: String = "") {
    guard
      app.confirm(
        "Restore recorded project files?",
        "This changes files on disk. The engine refuses restoration if affected files changed after the task. Save any editor drafts before continuing. Git staging is preserved.",
        button: "Restore files")
    else { return }
    app.perform {
      _ = try await app.engine.call(method, ["project": app.projectID, "id": id])
      await app.refreshGit()
      load()
    }
  }
}
extension Dictionary where Key == String, Value == Any {
  var checkpointPath: String { string(self, "path") }
}
