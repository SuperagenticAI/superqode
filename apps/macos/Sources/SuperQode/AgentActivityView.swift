import SwiftUI

@MainActor final class AgentActivityLibrary: ObservableObject {
  @Published var rows: [[String: Any]] = []
  @Published var counts: [String: Any] = [:]
  @Published var cursor = ""
  @Published var loading = false
  @Published var failure = ""
  @Published var expanded = false
  private var generation = 0
  func load(engine: Engine, project: String, query: String, view: String, more: Bool = false) async {
    if more && (loading || cursor.isEmpty) { return }
    if !more { generation += 1; expanded = false } else { expanded = true }
    let token = generation
    loading = true
    defer { if generation == token { loading = false } }
    do {
      let result = try await engine.call("activity.list", ["project": project, "query": query, "view": view, "cursor": more ? cursor : ""]) as? [String: Any] ?? [:]
      guard generation == token, !Task.isCancelled else { return }
      let incoming = result["items"] as? [[String: Any]] ?? []
      var seen = Set<String>()
      rows = (more ? rows + incoming : incoming).filter { seen.insert(string($0, "id")).inserted }
      counts = result["counts"] as? [String: Any] ?? [:]
      cursor = string(result, "next_cursor")
      failure = ""
    } catch is CancellationError {} catch {
      if generation == token { failure = error.localizedDescription }
    }
  }
}

struct AgentFleetView: View {
  @EnvironmentObject var app: Workspace
  @StateObject private var library = AgentActivityLibrary()
  @State private var query = ""
  @State private var view = "all"
  @State private var scope = ""
  private var signature: String { scope + "\n" + query + "\n" + view }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      PageTitle(eyebrow: "Across your projects", title: "All work",
        subtitle: "Track your SuperQode threads and discover recorded sessions from outside the app.")
      Picker("Work source", selection: $app.workSource) {
        Text("SuperQode threads").tag("app")
        Text("External history").tag("external")
      }.pickerStyle(.segmented)
      if app.workSource == "external" { ExternalSessionsView() }
      else { appThreads }
    }.padding(28)
  }
  private var appThreads: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack(spacing: 12) {
        metric("Needs attention", key: "attention", color: .orange)
        metric("Working", key: "working", color: .blue)
        metric("Completed", key: "done", color: .green)
      }
      ThreadAlertControls(alerts: app.threadNotifications)
      HStack {
        TextField("Find a thread or project", text: $query).textFieldStyle(.roundedBorder)
          .onChange(of: query) { _, value in if value.count > 200 { query = String(value.prefix(200)) } }
        Picker("Project", selection: $scope) {
          Text("All projects").tag("")
          ForEach(app.projects, id: \.projectRowID) { row in
            Text(string(row, "name", URL(fileURLWithPath: string(row, "path")).lastPathComponent)).tag(string(row, "id"))
          }
        }.frame(width: 220)
        Button { Task { await reload() } } label: { Image(systemName: "arrow.clockwise") }
          .accessibilityLabel("Refresh agent activity").disabled(library.loading)
      }
      Picker("Show activity", selection: $view) {
        Text("All threads").tag("all")
        Text("Needs attention").tag("attention")
        Text("Working").tag("working")
        Text("Completed").tag("done")
      }.pickerStyle(.segmented)
      if !library.failure.isEmpty {
        HStack { Text(library.failure).foregroundStyle(.orange); Button("Retry") { Task { await reload() } } }
      }
      ScrollView {
        LazyVStack(spacing: 10) {
          ForEach(library.rows, id: \.projectRowID) { row in
            Button {
              app.perform { try await app.openActivityThread(row) }
            } label: {
              HStack(alignment: .top, spacing: 14) {
                HarnessIconStack(row: row, size: 32)
                VStack(alignment: .leading, spacing: 7) {
                  HStack {
                    Text(string(row, "conversation_title", string(row, "title"))).font(.headline).lineLimit(2)
                    Spacer()
                    Label(activityTitle(row), systemImage: activitySymbol(row))
                      .font(.caption).foregroundStyle(activityColor(row))
                  }
                  Text((row["fork_origin"] as? [String: Any]).map { string($0, "title") } ?? string(row, "project_name")).font(.caption).foregroundStyle(.secondary)
                  if let fork = row["fork_origin"] as? [String: Any] {
                    Label(string(fork, "branch"), systemImage: "arrow.triangle.branch").font(.caption).foregroundStyle(.secondary)
                  }
                  if let updated = row["updated"] as? Double { Text(Date(timeIntervalSince1970: updated), style: .relative).font(.caption).foregroundStyle(.secondary) }
                }
              }.padding(18).brandSurface().contentShape(Rectangle())
            }.buttonStyle(.plain).disabled(app.busy || app.openingProject || app.restoringNavigation)
          }
          if library.loading { ProgressView("Loading activity…").padding() }
          if library.rows.isEmpty && !library.loading && library.failure.isEmpty {
            ContentUnavailableView("No matching threads", systemImage: "square.stack.3d.up", description: Text("Start work in a project or choose another filter."))
          }
          if !library.cursor.isEmpty && !library.loading {
            Button("Load more threads") { Task { await reload(more: true) } }.padding()
          }
        }.padding(.bottom, 12)
      }
      Text("App-owned threads show recorded execution states. Choose External history to connect sessions started elsewhere.")
        .font(.caption).foregroundStyle(.secondary)
    }
      .task(id: signature) {
        do { try await Task.sleep(for: .milliseconds(180)) } catch { return }
        await reload()
      }
      .task {
        while !Task.isCancelled {
          do { try await Task.sleep(for: .seconds(3)) } catch { return }
          // Keep a paged list stable; users can refresh by changing a filter.
          if !library.expanded && !library.loading { await reload() }
        }
      }
  }
  private func metric(_ title: String, key: String, color: Color) -> some View {
    VStack(alignment: .leading, spacing: 6) {
      Text(String(library.counts[key] as? Int ?? 0)).font(.title2.monospacedDigit()).foregroundStyle(color)
      Text(title).font(.caption).foregroundStyle(.secondary)
    }.padding(16).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
  }
  private func reload(more: Bool = false) async {
    await library.load(engine: app.engine, project: scope, query: query, view: view, more: more)
  }
}

func activityTitle(_ row: [String: Any]) -> String {
  switch string(row, "status") {
  case "needs_approval": return "Needs you"
  case "failed": return "Failed"
  case "interrupted": return "Interrupted"
  case "running", "queued": return "Working"
  case "cancelling": return "Stopping"
  case "completed": return "Completed"
  case "cancelled": return "Stopped"
  default: return string(row, "status", "Unknown")
  }
}
private func activitySymbol(_ row: [String: Any]) -> String {
  switch string(row, "status") {
  case "needs_approval": return "hand.raised"
  case "failed", "interrupted": return "exclamationmark.circle"
  case "running", "queued", "cancelling": return "circle.dotted"
  case "completed": return "checkmark.circle"
  default: return "circle"
  }
}
private func activityColor(_ row: [String: Any]) -> Color {
  switch string(row, "status") {
  case "needs_approval", "failed", "interrupted": return .orange
  case "running", "queued", "cancelling": return .blue
  case "completed": return .green
  default: return .secondary
  }
}

@MainActor extension Workspace {
  func openActivityThread(_ row: [String: Any]) async throws {
    let target = string(row, "project")
    guard !openingProject, !restoringNavigation else { throw EngineError(message: "Wait for navigation to finish.") }
    if target != projectID { try await open(string(row, "project_path"), expectedProjectID: target) }
    guard projectID == target else { return }
    selectJob(string(row, "id"), conversationID: string(row, "conversation_id"), targetSection: "Workspace")
  }
}
