import SwiftUI

/// One reviewed handoff of a finished coding turn to a target from the Send to… menu.
struct HandoffRequest: Identifiable {
  let id = UUID()
  let project: String
  let job: String
  let target: String
  let title: String
}

/// Pure rules for the Send to… menu, kept separate so they can be tested.
enum HandoffMenuRules {
  static let finished: Set<String> = ["completed", "failed", "cancelled", "interrupted", "regressed"]

  /// A finished coding turn: the only kind of run the Send to… menu can hand off.
  static func isFinishedCodingTurn(_ detail: [String: Any]) -> Bool {
    let request = detail["request"] as? [String: Any] ?? [:]
    return string(detail, "kind") == "task" && finished.contains(string(detail, "status"))
      && string(request, "interaction_mode") != "chat"
  }

  /// Why nothing can be sent right now, or nil when a target may be chosen.
  static func blocker(connected: Bool, projectID: String, job: String, anyActive: Bool,
    detail: [String: Any], source: [String: Any]) -> String? {
    if !connected { return "The local engine is not running." }
    if projectID.isEmpty { return "Open a project first." }
    if job.isEmpty { return "Select a finished coding turn first." }
    let detailProject = string(detail, "project")
    if !detailProject.isEmpty && detailProject != projectID {
      return "This turn belongs to another project. Open that project."
    }
    if string(detail, "kind") == "task" && !finished.contains(string(detail, "status")) {
      return "Wait for this turn to finish, then send it."
    }
    let request = detail["request"] as? [String: Any] ?? [:]
    if string(request, "interaction_mode") == "chat" {
      return "This is a chat turn. Send a finished coding turn instead."
    }
    if anyActive { return "Finish the current run first." }
    if string(source, "job") != job { return "Checking this turn…" }
    if source["ready"] as? Bool != true {
      return string(source, "reason", "This turn cannot be sent.")
    }
    return nil
  }

  static func available(_ row: [String: Any]) -> Bool { row["available"] as? Bool == true }

  /// A menu item title. An unavailable target keeps its reason in the title.
  static func itemTitle(_ row: [String: Any]) -> String {
    let title = string(row, "title", string(row, "id"))
    if available(row) { return title + "…" }
    let reason = string(row, "reason")
    return reason.isEmpty ? title : title + " · " + reason
  }
}

/// Targets are shared by the composer and run header menus, so one check serves both.
@MainActor final class HandoffTargetStore: ObservableObject {
  @Published var targets: [[String: Any]] = []
  @Published var source: [String: Any] = [:]
  @Published var loading = false
  @Published var failure = ""
  private var loadedKey = ""
  private var loadedAt = Date.distantPast

  func load(engine: Engine, project: String, job: String, key: String, force: Bool = false) async {
    guard !project.isEmpty else {
      targets = []; source = [:]; loadedKey = key; return
    }
    if !force, key == loadedKey, loading || Date().timeIntervalSince(loadedAt) < 5 { return }
    loadedKey = key
    loading = true
    defer { if key == loadedKey { loading = false } }
    do {
      let result = try await engine.call("handoff.targets", ["project": project, "job": job]) as? [String: Any] ?? [:]
      guard key == loadedKey else { return }
      targets = result["targets"] as? [[String: Any]] ?? []
      source = result["source"] as? [String: Any] ?? [:]
      failure = ""
      loadedAt = Date()
    } catch {
      guard key == loadedKey else { return }
      targets = []; source = [:]
      failure = error.localizedDescription
    }
  }
}

@MainActor extension Workspace {
  func openHandoff(target row: [String: Any]) {
    guard connected, !projectID.isEmpty, !selectedJob.isEmpty, !busy, !openingProject,
      !anyActive, HandoffMenuRules.available(row) else { return }
    handoffRequest = HandoffRequest(project: projectID, job: selectedJob,
      target: string(row, "id"), title: string(row, "title", string(row, "id")))
  }
}

/// The Send to… menu. One item per handoff target; unavailable ones show why.
struct HandoffMenu: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var store: HandoffTargetStore
  var identifier = "composer.sendTo"

  private var refreshKey: String {
    [app.projectID, app.selectedJob, string(app.detail, "status"), String(app.anyActive), String(app.connected)]
      .joined(separator: "\n")
  }
  private var blocker: String? {
    HandoffMenuRules.blocker(connected: app.connected, projectID: app.projectID, job: app.selectedJob,
      anyActive: app.anyActive, detail: app.detail, source: store.source)
  }

  var body: some View {
    Menu {
      if let blocker { Text(blocker) }
      if store.loading && store.targets.isEmpty {
        Text("Checking targets…")
      } else if store.targets.isEmpty {
        Text(store.failure.isEmpty ? "No handoff targets yet" : store.failure)
        Button("Set up exo cluster…") { app.openLocalAIAdvanced("exo") }
      } else {
        ForEach(store.targets, id: \.projectRowID) { row in
          Button(HandoffMenuRules.itemTitle(row)) { app.openHandoff(target: row) }
            .disabled(blocker != nil || !HandoffMenuRules.available(row))
        }
      }
      Divider()
      Button("Refresh targets") { Task { await reload(force: true) } }
        .disabled(store.loading || !app.connected)
    } label: {
      Label("Send to…", systemImage: "paperplane")
    }
    .menuStyle(.borderlessButton).fixedSize()
    .help(blocker ?? "Send this finished coding turn to another model. You review it before anything is sent.")
    .accessibilityIdentifier(identifier)
    .task(id: refreshKey) { await reload(force: false) }
  }

  private func reload(force: Bool) async {
    guard app.connected else { return }
    await store.load(engine: app.engine, project: app.projectID, job: app.selectedJob, key: refreshKey, force: force)
  }
}

/// One shared host at the window root. Menus only set the request.
struct HandoffSheetHost: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    Color.clear.frame(width: 0, height: 0)
      .sheet(item: $app.handoffRequest) { request in
        HandoffPreviewView(request: request) { app.handoffRequest = nil }
          .environmentObject(app)
      }
  }
}

/// The editable preview: objective and patch, target model, and the harness the run will use.
struct HandoffPreviewView: View {
  @EnvironmentObject var app: Workspace
  let request: HandoffRequest
  let close: () -> Void
  @State private var preview: [String: Any] = [:]
  @State private var prompt = ""
  @State private var model = ""
  @State private var loading = true
  @State private var sending = false
  @State private var failure = ""
  @State private var closed = false

  private var models: [[String: Any]] { preview["models"] as? [[String: Any]] ?? [] }
  private var tooLong: Bool { prompt.utf8.count > 16000 }
  private var harnessLine: String {
    let name = string(preview, "harness_name", string(preview, "harness"))
    if name.isEmpty { return "" }
    return preview["kept_harness"] as? Bool == true
      ? "Harness: \(name), the same as this turn"
      : "Harness: \(name). This turn's harness cannot run on this model."
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Text("Send to " + request.title).font(.title2).lineLimit(1)
        Spacer()
        Button("Cancel") { closed = true; close() }.keyboardShortcut(.cancelAction)
      }
      if !string(preview, "detail").isEmpty {
        Text(string(preview, "destination", "On your network") + " · " + string(preview, "detail"))
          .font(.callout).foregroundStyle(.secondary)
      }
      HStack(spacing: 12) {
        Picker("Model", selection: $model) {
          ForEach(models, id: \.projectRowID) { row in
            Text(string(row, "title", string(row, "id"))).tag(string(row, "id"))
          }
        }.pickerStyle(.menu).frame(maxWidth: 420).disabled(loading || sending || models.isEmpty)
          .accessibilityIdentifier("handoff.model")
        if loading { ProgressView().controlSize(.small) }
      }
      if !harnessLine.isEmpty { Text(harnessLine).font(.callout).accessibilityIdentifier("handoff.harness") }
      if !string(preview, "endpoint").isEmpty {
        Text(string(preview, "endpoint")).font(.caption.monospaced()).foregroundStyle(.secondary)
      }
      Text("Review the objective and patch below. You can edit them. Later tool results can also go to the target while the run uses them.")
        .font(.caption).foregroundStyle(.secondary)
      TextEditor(text: $prompt).font(.system(.body, design: .monospaced))
        .frame(minHeight: 300).padding(6).brandSurface().disabled(loading || sending)
        .accessibilityIdentifier("handoff.preview")
      if tooLong { Text("Shorten the preview to 16 KB or less.").font(.caption).foregroundStyle(.orange) }
      if !failure.isEmpty {
        HStack {
          Text(failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled)
          Button("Retry preview") { Task { await load() } }.disabled(loading)
        }
      }
      HStack {
        Text("Starts a new run with permission prompts on. Files change only on this Mac.")
          .font(.caption).foregroundStyle(.secondary)
        Spacer()
        Button("Send", action: send).buttonStyle(BrandButtonStyle())
          .accessibilityIdentifier("handoff.send")
          .disabled(loading || sending || !failure.isEmpty || model.isEmpty || tooLong
            || prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || app.anyActive || app.busy || app.projectID != request.project)
      }
    }.padding(24).frame(width: 760, height: 680)
      .task(id: request.id) { await load() }
      .onChange(of: app.projectID) { _, project in if project != request.project { closed = true; close() } }
      .onDisappear { closed = true }
  }

  private func load() async {
    loading = true
    failure = ""
    defer { loading = false }
    do {
      let result = try await app.engine.call("handoff.preview", [
        "project": request.project, "job": request.job, "target": request.target,
      ]) as? [String: Any] ?? [:]
      guard !closed, !Task.isCancelled, app.projectID == request.project else { return }
      preview = result
      prompt = string(result, "prompt")
      model = string(result, "model")
    } catch { if !closed && !Task.isCancelled { failure = error.localizedDescription } }
  }

  private func send() {
    let text = prompt
    let chosen = model
    sending = true
    Task {
      defer { sending = false }
      do {
        guard app.projectID == request.project, !app.anyActive else { return }
        let result = try await app.engine.call("handoff.start", [
          "project": request.project, "job": request.job, "target": request.target,
          "model": chosen, "digest": string(preview, "digest"), "prompt": text,
          "command_id": UUID().uuidString,
        ]) as? [String: Any] ?? [:]
        guard !string(result, "id").isEmpty else { throw EngineError(message: "The run did not start.") }
        closed = true
        close()
        await app.refreshJobs()
        guard app.projectID == request.project else { return }
        app.selectJob(string(result, "id"))
        app.section = "Workspace"
        app.notice = "Sent to " + request.title + ". The new run uses " + chosen + "."
      } catch { failure = error.localizedDescription }
    }
  }
}
