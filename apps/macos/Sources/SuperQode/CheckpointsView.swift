import SwiftUI

struct CheckpointsView: View {
  @EnvironmentObject var app: Workspace
  @State private var items: [[String: Any]] = []
  @State private var diff = ""
  @State private var failure = ""
  @State private var canUndo = false
  @State private var canRedo = false
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
                    app.perform {
                      let result =
                        try await app.engine.call(
                          "checkpoints.diff",
                          [
                            "project": app.projectID, "id": string(item, "id"),
                            "path": string(change, "path"),
                          ]) as? [String: Any] ?? [:]
                      diff = string(result, "diff")
                    }
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
    }.padding(26).onAppear { load() }
  }
  private func load() {
    app.perform {
      do {
        let result =
          try await app.engine.call("checkpoints.list", ["project": app.projectID])
          as? [String: Any] ?? [:]
        items = result["items"] as? [[String: Any]] ?? []
        canUndo = result["can_undo"] as? Bool ?? false
        canRedo = result["can_redo"] as? Bool ?? false
        failure = ""
      } catch { failure = error.localizedDescription }
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
