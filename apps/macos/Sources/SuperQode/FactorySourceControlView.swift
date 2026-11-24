import SwiftUI

/// Explicit, saved-source-only Git review. Runtime state remains hidden by the engine.
struct FactorySourceControlView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var library: FactoryStudioLibrary
  var active = true
  @State private var selected: Set<String> = []
  @State private var focused = ""
  @State private var commitMessage = ""
  @State private var branchName = ""
  @State private var committing = false
  @State private var creatingBranch = false
  @State private var confirmCommit = false
  private var files: [[String: Any]] { library.sourceReview["files"] as? [[String: Any]] ?? [] }
  private var changed: [[String: Any]] { files.filter { $0["changed"] as? Bool == true } }
  private var branch: String { string(library.sourceReview, "branch") }
  private var idle: Bool { !library.busy && !app.anyActive && !app.busy && !creatingBranch && !committing }
  private var canCommit: Bool {
    idle && !selected.isEmpty && !branch.isEmpty && !string(library.sourceReview, "review").isEmpty
      && !commitMessage.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        VStack(alignment: .leading, spacing: 4) {
          Text("Version the saved Factory").font(.headline)
          Text("Review and commit the definition and its declared components. Unsaved draft edits are separate.")
            .font(.caption).foregroundStyle(.secondary)
        }
        Spacer()
        Button("Refresh source review") { Task { await library.refreshSources(engine: app.engine) } }.disabled(!idle)
      }
      if !library.sourceReview.isEmpty {
        HStack {
          Label(branch.isEmpty ? "Detached HEAD" : branch, systemImage: "arrow.triangle.branch").font(.caption.monospaced())
          Text("HEAD " + String(string(library.sourceReview, "head").prefix(12))).font(.caption.monospaced()).foregroundStyle(.secondary)
          Spacer(); Text("\(selected.count) of \(changed.count) changed files selected").font(.caption)
        }
        HStack {
          TextField("Optional new branch name", text: $branchName).textFieldStyle(.roundedBorder)
          Button("Create branch") { createBranch() }.disabled(!idle || branchName.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        }
        if branch == "main" || branch == "master" { Text("This is the default branch. Create a branch above to keep this work separate.").font(.caption).foregroundStyle(.orange) }
        HSplitView {
          ScrollView {
            VStack(alignment: .leading, spacing: 10) {
              HStack {
                Button("Select changed") { selectChanged() }.disabled(!idle)
                Button("None") { selected = [] }.disabled(!idle)
              }.font(.caption)
              if files.isEmpty { Text("No declared Factory source files.").foregroundStyle(.secondary) }
              ForEach(files.map { string($0, "path") }, id: \.self) { path in
                let row = files.first { string($0, "path") == path } ?? [:]
                HStack(alignment: .top, spacing: 8) {
                  Toggle("Include \(path)", isOn: Binding(get: { selected.contains(path) }, set: { on in
                    if on { selected.insert(path) } else { selected.remove(path) }
                  })).labelsHidden().toggleStyle(.checkbox)
                    .disabled(!idle || row["changed"] as? Bool != true || row["diff_truncated"] as? Bool == true)
                  Button { focused = path } label: {
                    VStack(alignment: .leading, spacing: 4) {
                      Text(path).font(.caption.monospaced()).multilineTextAlignment(.leading)
                      Pill(title: string(row, "status"), color: row["changed"] as? Bool == true ? .orange : .secondary)
                    }.frame(maxWidth: .infinity, alignment: .leading)
                  }.buttonStyle(.plain)
                }.padding(10).background(focused == path ? Color.qAccent.opacity(0.10) : Color.clear,
                  in: RoundedRectangle(cornerRadius: 8))
              }
            }.padding(.trailing, 12)
          }.frame(minWidth: 200, idealWidth: 260, maxWidth: 350)
          ScrollView {
            VStack(alignment: .leading, spacing: 10) {
              if let row = files.first(where: { string($0, "path") == focused }) {
                Text(focused).font(.caption.monospaced()).textSelection(.enabled)
                if row["diff_truncated"] as? Bool == true {
                  Text("This diff exceeds the review limit. It cannot be committed from this review.")
                    .font(.caption).foregroundStyle(.orange)
                }
                CodeBlock(text: string(row, "diff").isEmpty ? "No changes from HEAD." : string(row, "diff"))
              } else { Text("Choose a file to review its complete diff against HEAD.").foregroundStyle(.secondary) }
            }.frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 12)
          }.frame(minWidth: 270)
        }
        Text("Commit Factory sources before preparing a trial: committing advances HEAD, while existing trials keep their original baseline.")
          .font(.caption).foregroundStyle(.secondary)
        Text("Runtime databases, snapshots, sessions, credentials and signing keys remain excluded. New declared dependencies must be included with the definition.")
          .font(.caption).foregroundStyle(.secondary)
        TextField("Factory commit message", text: $commitMessage).textFieldStyle(.roundedBorder).disabled(!idle)
        HStack {
          Text("Creates a local Git commit. Hooks and commit signing follow your Git configuration.")
            .font(.caption).foregroundStyle(.secondary)
          Spacer()
          Button("Commit reviewed sources…") { confirmCommit = true }
            .buttonStyle(BrandButtonStyle()).disabled(!canCommit)
        }
      } else {
        Spacer()
        Text("Save a valid Factory definition, then refresh to review its sources. The application needs an initial Git commit.")
          .font(.callout).foregroundStyle(.secondary)
        Spacer()
      }
    }
    .task(id: library.project + "\n" + String(active)) {
      guard active else { return }; await library.refreshSources(engine: app.engine)
    }
    .onChange(of: string(library.sourceReview, "digest")) { _, _ in
      selectChanged(); focused = string(changed.first ?? files.first ?? [:], "path")
    }
    .onChange(of: active) { _, visible in if !visible { confirmCommit = false } }
    .onChange(of: library.project) { _, _ in selected = []; focused = ""; commitMessage = ""; confirmCommit = false }
    .factoryConfirmation(
      isPresented: $confirmCommit,
      title: "Commit reviewed Factory sources?",
      message: "Create a local commit on \(branch) containing the \(selected.count) selected Factory source files. The engine rechecks the saved files, dependencies, branch and HEAD. Unrelated staged work is kept separate. Nothing is pushed or deployed.",
      kind: .source,
      badges: [
        FactoryConfirmBadge(label: branch.isEmpty ? "Local Git" : branch, symbol: "arrow.triangle.branch", color: Color(red: 0.18, green: 0.48, blue: 0.84)),
        FactoryConfirmBadge(label: "\(selected.count) files", symbol: "doc.on.doc", color: Brand.purple)
      ],
      confirmTitle: "Commit sources",
      onConfirm: { commit() }
    )
  }
  private func selectChanged() {
    selected = Set(changed.filter { $0["diff_truncated"] as? Bool != true }.map { string($0, "path") })
  }
  private func commit() {
    guard canCommit else { return }
    let paths = selected.sorted(); let message = commitMessage; let identity = library.project
    committing = true
    Task {
      defer { committing = false }
      await library.commitSources(engine: app.engine, paths: paths, message: message)
      guard library.project == identity else { return }
      await app.refreshGit()
    }
  }
  private func createBranch() {
    let identity = library.project; let name = branchName
    creatingBranch = true
    Task {
      defer { creatingBranch = false }
      do {
        _ = try await app.engine.call("ship.create_branch", ["project": identity, "name": name])
        guard library.project == identity else { return }
        branchName = ""; await library.refreshSources(engine: app.engine); await app.refreshGit()
      } catch { if library.project == identity { library.failure = error.localizedDescription } }
    }
  }
}
