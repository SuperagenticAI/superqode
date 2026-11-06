import SwiftUI

enum ProjectInspection: String, Identifiable, CaseIterable {
  case workorders = "WorkOrders", queue = "Task queue", checkpoints = "Checkpoints"
  var id: String { rawValue }
  var method: String { self == .workorders ? "workorders.snapshot" : self == .queue ? "queue.list" : "checkpoints.list" }
  var capability: String { self == .workorders ? "workorders" : self == .queue ? "queue" : "checkpoints" }
}

struct ProjectInspectionScreen: View {
  let project: String
  let kind: ProjectInspection
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.scenePhase) private var scenePhase
  @State private var snapshot: [String: JSONValue] = [:]
  @State private var issue = ""
  @State private var loading = false
  var body: some View {
    List {
      Section { ConnectionStatus(); Text(explanation).font(.footnote).foregroundStyle(.secondary) }.listRowBackground(Color.clear)
      if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      if loading && snapshot.isEmpty { ProgressView("Loading \(kind.rawValue.lowercased())…") }
      if kind == .queue {
        Label(snapshot.flag("running") ? "Queue running" : "Queue paused", systemImage: "list.number")
        ForEach(snapshot.records("items")) { item in queue(item) }
      } else if kind == .checkpoints {
        ForEach(snapshot.records("items")) { item in checkpoint(item) }
      } else {
        ForEach(Array(snapshot.records("items").enumerated()), id: \.offset) { _, item in
          NavigationLink { WorkOrderDetailScreen(project: project, order: item.raw) } label: {
            VStack(alignment: .leading, spacing: 8) {
              Text(item.text("goal", "WorkOrder")).font(.headline).lineLimit(3)
              Text(item.text("status").replacingOccurrences(of: "_", with: " ").capitalized).font(.caption).foregroundStyle(.secondary)
            }.padding(.vertical, 6)
          }
        }
      }
      if !loading && issue.isEmpty && snapshot.records("items").isEmpty {
        ContentUnavailableView("No \(kind.rawValue.lowercased()) yet", systemImage: "tray", description: Text("Recorded project work from your Mac appears here."))
      }
      if snapshot.flag("truncated") { Text("More records are available on the Mac.").font(.caption).foregroundStyle(.secondary) }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background).navigationTitle(kind.rawValue)
      .refreshable { await load() }
      .task(id: scenePhase) {
        guard scenePhase == .active else { return }
        await load()
        if kind == .workorders {
          while !Task.isCancelled {
            do { try await Task.sleep(for: .seconds(5)) } catch { break }
            await load()
          }
        }
      }
  }
  private var explanation: String {
    switch kind {
    case .workorders: return "Track agent tasks, worker responsiveness, budgets and acceptance checks. WorkOrders are created and managed on the Mac."
    case .queue: return "Inspect the queue and open its recorded runs. Starting, pausing, reordering and retrying queued tasks remain Mac actions."
    case .checkpoints: return "Inspect saved task changes. Restoring, undoing and redoing checkpoints remain Mac actions. Finish active project work before inspecting checkpoints."
    }
  }
  private func queue(_ item: RemoteRecord) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      Text(item.raw.object("request").text("prompt")).lineLimit(5).textSelection(.enabled)
      Text(item.text("state").capitalized).font(.caption.weight(.semibold)).foregroundStyle(CompanionTheme.accent)
      HarnessBadge(name: item.raw.object("request").text("harness"))
      if !item.text("error").isEmpty { Text(item.text("error")).font(.footnote).foregroundStyle(CompanionTheme.warning) }
      if item.flag("prompt_truncated") { Text("Prompt excerpt; inspect the complete queued request on the Mac.").font(.caption).foregroundStyle(.secondary) }
      if !item.text("job").isEmpty { NavigationLink("Open run") { JobScreen(identity: item.text("job")) } }
    }.padding(.vertical, 8).listRowBackground(CompanionTheme.panel)
  }
  private func checkpoint(_ item: RemoteRecord) -> some View {
    Section {
      Text(item.text("name", "Task checkpoint")).font(.headline)
      Text(item.text("timestamp")).font(.caption).foregroundStyle(.secondary)
      if !item.flag("sealed") { Text("Interrupted checkpoint: review manually on the Mac.").font(.footnote).foregroundStyle(CompanionTheme.warning) }
      ForEach(Array(item.raw.records("changes").enumerated()), id: \.offset) { _, change in
        NavigationLink {
          RecordedDiffScreen(title: change.text("path"), method: "checkpoints.diff", params: ["project": .string(project), "id": .string(item.id), "path": .string(change.text("path"))])
        } label: { Label(change.text("path") + " · " + change.text("change_type"), systemImage: "doc.text") }
      }
      if item.flag("changes_truncated") { Text("Additional changes are available on the Mac.").font(.caption) }
    }.listRowBackground(CompanionTheme.panel)
  }
  private func load() async {
    guard !loading, let api = store.api else { return }
    guard store.hasProjectInspection(kind.capability) else { issue = "Update the Mac build to enable this project view."; return }
    loading = true
    defer { loading = false }
    do {
      let next = try await api.rpc(kind.method, ["project": .string(project)]).object
      try Task.checkCancellation()
      snapshot = next; issue = ""
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
}

struct WorkOrderDetailScreen: View {
  let project: String
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.scenePhase) private var scenePhase
  @State private var order: [String: JSONValue]
  @State private var issue = ""
  init(project: String, order: [String: JSONValue]) { self.project = project; _order = State(initialValue: order) }
  var body: some View {
    List {
      Section {
        ConnectionStatus()
        if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
        Text(order.text("goal")).font(.headline)
        Text(order.text("status").replacingOccurrences(of: "_", with: " ").capitalized).foregroundStyle(CompanionTheme.accent)
        HarnessBadge(name: order.text("harness"))
        LabeledContent("Elapsed", value: evidenceMetric(order["elapsed_seconds"]))
        if !order.text("error").isEmpty { Text(order.text("error")).foregroundStyle(CompanionTheme.warning) }
      }.listRowBackground(CompanionTheme.panel)
      Section("Tasks") {
        ForEach(Array(order.records("tasks").enumerated()), id: \.offset) { _, task in
          VStack(alignment: .leading, spacing: 6) {
            Text(task.text("title")).font(.headline)
            Text(task.text("role") + " · " + task.text("status")).font(.caption).foregroundStyle(.secondary)
            if !task.text("worker_id").isEmpty { Text("Worker: " + task.text("worker_id")).font(.caption.monospaced()) }
            if task.raw["lease_remaining_seconds"]?.number != nil { LabeledContent("Lease remaining", value: evidenceMetric(task.raw["lease_remaining_seconds"])) }
            if !task.text("error").isEmpty { Text(task.text("error")).font(.footnote).foregroundStyle(CompanionTheme.warning) }
          }.padding(.vertical, 5)
        }
        if order.flag("tasks_truncated") { Text("More tasks are available on the Mac.").font(.caption) }
      }.listRowBackground(CompanionTheme.panel)
      Section("Workers") {
        ForEach(Array(order.records("workers").enumerated()), id: \.offset) { _, worker in
          LabeledContent(worker.text("worker_id"), value: worker.flag("responsive") ? "Responsive" : "Not responding")
        }
      }.listRowBackground(CompanionTheme.panel)
      Section("Checks and reviews") {
        let gates = order.object("gates")
        LabeledContent("Recorded checks", value: String(Int(gates.number("check_results"))))
        if gates.number("check_results") > 0 { LabeledContent("Latest check", value: gates.flag("last_check_passed") ? "Passed" : "Not passed") }
        LabeledContent("Approved reviews", value: String(Int(gates.number("approved_reviews"))))
        ForEach((gates["conflicts"]?.array ?? []).map(\.text), id: \.self) { Text("Conflict: " + $0).foregroundStyle(CompanionTheme.warning) }
        Text("These are recorded checks, not permission to merge or release.").font(.caption).foregroundStyle(.secondary)
      }.listRowBackground(CompanionTheme.panel)
      Section("Budget and usage") {
        JSONDetails(title: "Budget", value: order["budget"] ?? .null)
        JSONDetails(title: "Usage", value: order["usage"] ?? .null)
      }.listRowBackground(CompanionTheme.panel)
    }.scrollContentBackground(.hidden).background(CompanionTheme.background).navigationTitle("WorkOrder")
      .refreshable { await refresh() }
      .task(id: scenePhase) {
        guard scenePhase == .active else { return }
        while !Task.isCancelled {
          await refresh()
          do { try await Task.sleep(for: .seconds(5)) } catch { break }
        }
      }
  }
  private func refresh() async {
    guard let api = store.api else { return }
    do {
      let page = try await api.rpc("workorders.snapshot", ["project": .string(project)]).object
      try Task.checkCancellation()
      if let next = page.records("items").first(where: { $0.text("work_order_id") == order.text("work_order_id") }) {
        if next.raw != order { order = next.raw }; issue = ""
      } else { issue = "This WorkOrder is no longer in the recent project snapshot. Inspect its history on the Mac." }
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
}

struct RecordedDiffScreen: View {
  let title: String
  let method: String
  let params: [String: JSONValue]
  @EnvironmentObject private var store: CompanionStore
  @State private var diff = ""
  @State private var issue = ""
  @State private var loading = true
  var body: some View {
    Group {
      if loading { ProgressView("Reading saved changes…") }
      else if !issue.isEmpty { ContentUnavailableView("Changes unavailable", systemImage: "exclamationmark.triangle", description: Text(issue)) }
      else { MobileCodeBlock(code: diff.isEmpty ? "No text changes recorded." : diff, language: "diff", fullHeight: true).padding(12) }
    }.navigationTitle(title).navigationBarTitleDisplayMode(.inline).background(CompanionTheme.background)
      .task {
        defer { loading = false }
        guard let api = store.api else { return }
        do { diff = try await api.rpc(method, params).object.text("diff") }
        catch is CancellationError { }
        catch { issue = error.localizedDescription }
      }
  }
}

extension CompanionStore {
  func hasProjectInspection(_ kind: String) -> Bool { features["project_inspection"]?.array.contains(.string(kind)) == true }
}
