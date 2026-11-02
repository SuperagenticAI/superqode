import AppKit
import SwiftUI

@MainActor final class ThreadLibrary: ObservableObject {
  @Published var query = ""
  @Published var filter = "active"
  @Published var rows: [[String: Any]] = []
  @Published var loading = false
  @Published var failure = ""
  @Published var cursor = ""
  private var generation = 0

  func load(engine: Engine, project: String, query: String, view: String, more: Bool = false) async {
    if more && (loading || cursor.isEmpty) { return }
    if !more { generation += 1; cursor = "" }
    let token = generation
    let position = more ? cursor : ""
    loading = true
    failure = ""
    defer { if generation == token { loading = false } }
    do {
      let result = try await engine.call("threads.list", [
        "project": project, "query": query, "view": view, "cursor": position,
      ]) as? [String: Any] ?? [:]
      guard generation == token, !Task.isCancelled else { return }
      let incoming = result["items"] as? [[String: Any]] ?? []
      rows = more ? merge(rows, incoming) : incoming
      cursor = string(result, "next_cursor")
    } catch is CancellationError {} catch {
      if generation == token { failure = error.localizedDescription }
    }
  }

  private func merge(_ existing: [[String: Any]], _ incoming: [[String: Any]]) -> [[String: Any]] {
    var seen = Set<String>()
    return (existing + incoming).filter { seen.insert(string($0, "conversation_id")).inserted }
  }
}

struct ThreadsView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var library: ThreadLibrary
  @State private var renaming: [String: Any]?
  @State private var newTitle = ""
  @State private var mutation = false
  @State private var forkSource: [String: Any]?
  private var searchIdentity: String {
    let activity = app.projectJobs.filter { string($0, "kind") == "task" }.map {
      string($0, "id") + ":" + string($0, "status") + ":" + String(describing: $0["updated"] ?? 0)
        + ":" + string($0, "conversation_title") + ":" + String(describing: $0["pinned"] ?? false)
        + ":" + String(describing: $0["archived"] ?? false)
    }.joined(separator: "\n")
    return app.projectID + "\n" + library.filter + "\n" + library.query + "\n" + activity
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack(alignment: .top) {
        PageTitle(eyebrow: "Your project history", title: "Threads",
          subtitle: "Return to an idea, keep important work close, and continue with the agent you choose.")
        Spacer()
        Button("New thread", systemImage: "square.and.pencil") { app.runWorkspaceCommand(.newTask) }
          .buttonStyle(BrandButtonStyle()).disabled(app.busy)
      }
      HStack {
        TextField("Search titles, agents, models or thread IDs", text: $library.query)
          .textFieldStyle(.roundedBorder).onChange(of: library.query) { _, value in
            if value.count > 200 { library.query = String(value.prefix(200)) }
          }
        Picker("Show", selection: $library.filter) {
          Text("Current").tag("active")
          Text("Pinned").tag("pinned")
          Text("Working").tag("working")
          Text("Needs attention").tag("attention")
          Text("Archived").tag("archived")
          Text("All").tag("all")
        }.frame(width: 190)
        Button { Task { await reload() } } label: { Image(systemName: "arrow.clockwise") }
          .help("Refresh threads").accessibilityLabel("Refresh threads").disabled(library.loading)
      }
      if !app.forkWorkspaces.isEmpty {
        DisclosureGroup("Fork workspaces · \(app.forkWorkspaces.count)") {
          ForEach(app.forkWorkspaces, id: \.projectRowID) { fork in
            HStack {
              Label(string(fork, "title"), systemImage: "arrow.triangle.branch")
              Text(string(fork, "branch")).font(.caption.monospaced()).foregroundStyle(.secondary)
              Spacer()
              if string(fork, "state") == "ready" {
                Button(string(fork, "project") == app.projectID ? "Source thread" : "Open workspace") {
                  app.perform {
                    if string(fork, "project") == app.projectID { try await app.openForkSource(fork) }
                    else { try await app.openForkWorkspace(fork) }
                  }
                }
              } else { Text("Needs inspection · " + string(fork, "issue")).font(.caption).foregroundStyle(.orange) }
            }.padding(10)
          }
        }
      }
      if !library.failure.isEmpty {
        HStack {
          Text(library.failure).foregroundStyle(.orange).textSelection(.enabled)
          Button("Retry") { Task { await reload() } }
        }
      }
      ScrollView {
        LazyVStack(spacing: 10) {
          if library.rows.isEmpty && !library.loading && library.failure.isEmpty {
            ContentUnavailableView(library.query.isEmpty ? "No threads here yet" : "No matching threads",
              systemImage: "bubble.left.and.bubble.right", description: Text("Try another filter or start a new thread."))
          }
          ForEach(library.rows, id: \.threadIdentity) { row in threadRow(row) }
          if library.loading { ProgressView("Loading threads…").padding() }
          if !library.cursor.isEmpty && !library.loading {
            Button("Load more threads") { Task { await reload(more: true) } }.padding()
          }
        }.padding(.bottom, 16)
      }
      Text("Archiving keeps the transcript and drafts on your Mac. It does not delete agent sessions or project files.")
        .font(.caption).foregroundStyle(.secondary)
    }.padding(28)
      .task(id: searchIdentity) {
        do { try await Task.sleep(for: .milliseconds(200)) } catch { return }
        await reload()
      }
      .centeredDialog(isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } }), title: "Rename thread") {
        VStack(alignment: .leading, spacing: 16) {
          Text("Rename thread").font(.title2)
          TextField("Thread title", text: $newTitle).textFieldStyle(.roundedBorder)
          Text("Only the local thread title changes. Recorded messages stay intact.").font(.caption).foregroundStyle(.secondary)
          HStack {
            Button("Cancel") { renaming = nil }.keyboardShortcut(.cancelAction)
            Spacer()
            Button("Save title") {
              if let row = renaming { update(row, changes: ["title": newTitle]) }
              renaming = nil
            }.keyboardShortcut(.defaultAction)
              .disabled(newTitle.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || newTitle.count > 200 || mutation)
          }
        }.padding(24).frame(width: 480)
      }
      .centeredDialog(isPresented: Binding(get: { forkSource != nil }, set: { if !$0 { forkSource = nil } }), title: "Fork thread") {
        if let source = forkSource {
          ThreadForkView(project: string(source, "project"), source: string(source, "id"))
        }
      }
  }

  private func threadRow(_ row: [String: Any]) -> some View {
    HStack(alignment: .top, spacing: 14) {
      HarnessIconStack(row: row, size: 32).padding(.top, 2)
      Button { app.openSavedThread(row) } label: {
        VStack(alignment: .leading, spacing: 8) {
          HStack {
            if row["pinned"] as? Bool == true { Image(systemName: "pin.fill").foregroundStyle(Color.qAccent).accessibilityLabel("Pinned") }
            Text(string(row, "conversation_title", "Untitled thread")).font(.headline).lineLimit(2)
          }
          HStack {
            Text(string(row, "status").replacingOccurrences(of: "_", with: " "))
            Text("· \((row["turn_count"] as? Int) ?? 1) turns")
            if let date = row["updated"] as? Double { Text(Date(timeIntervalSince1970: date), style: .relative) }
          }.font(.caption).foregroundStyle(.secondary)
          let route = [string(row, "harness"), string(row, "model")].filter { !$0.isEmpty }.joined(separator: " · ")
          if !route.isEmpty { Text(route).font(.caption.monospaced()).foregroundStyle(.secondary).lineLimit(1) }
          if HarnessIdentity.used(in: row).count > 1 {
            Text("Used " + HarnessIdentity.used(in: row).map(\.name).joined(separator: " · "))
              .font(.caption).foregroundStyle(.secondary).lineLimit(2)
          }
        }.frame(maxWidth: .infinity, alignment: .leading).contentShape(Rectangle())
      }.buttonStyle(.plain).disabled(app.busy || app.openingProject)
      Menu {
        Button(row["pinned"] as? Bool == true ? "Unpin" : "Pin") { update(row, changes: ["pinned": row["pinned"] as? Bool != true]) }
        Button("Rename…") { newTitle = string(row, "conversation_title"); renaming = row }
        Button("Fork into worktree…") { forkSource = row }
          .disabled(!["completed", "failed", "cancelled", "interrupted"].contains(string(row, "status")))
        Button(row["archived"] as? Bool == true ? "Restore thread" : "Archive thread") {
          update(row, changes: ["archived": row["archived"] as? Bool != true])
        }.disabled(row["working"] as? Bool == true && row["archived"] as? Bool != true)
        Button("Copy thread ID") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(string(row, "conversation_id"), forType: .string) }
      } label: { Image(systemName: "ellipsis") }
        .menuStyle(.borderlessButton).frame(width: 28).disabled(mutation)
        .accessibilityLabel("Actions for " + string(row, "conversation_title"))
    }.padding(18).brandSurface()
  }

  private func reload(more: Bool = false) async {
    await library.load(engine: app.engine, project: app.projectID, query: library.query, view: library.filter, more: more)
  }

  private func update(_ row: [String: Any], changes: [String: Any]) {
    let project = app.projectID
    mutation = true
    Task {
      defer { mutation = false }
      do {
        _ = try await app.engine.call("threads.update", ["project": project, "id": string(row, "id")].merging(changes) { _, new in new })
        guard app.projectID == project else { return }
        await app.refreshJobs()
        await reload()
      } catch { library.failure = error.localizedDescription }
    }
  }
}

extension Dictionary where Key == String, Value == Any {
  var threadIdentity: String { string(self, "conversation_id", string(self, "id")) }
}

@MainActor extension Workspace {
  func restoreSelectedThread() {
    let project = projectID
    let job = selectedJob
    perform {
      _ = try await self.engine.call("threads.update", ["project": project, "id": job, "archived": false])
      guard self.projectID == project, self.selectedJob == job else { return }
      await self.refreshDetail()
      await self.refreshJobs()
    }
  }

  func openSavedThread(_ row: [String: Any]) {
    guard string(row, "project") == projectID, !busy, !openingProject, !restoringNavigation else { return }
    selectJob(string(row, "id"), conversationID: string(row, "conversation_id"), targetSection: "Workspace")
    showWelcome = false
  }
}
