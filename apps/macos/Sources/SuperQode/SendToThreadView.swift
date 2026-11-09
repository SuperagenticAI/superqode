import SwiftUI

struct SendToThreadRequest: Identifiable {
  let id = UUID()
  let project: String
  let source: String
  var fromTurn = ""
}

/// One shared host at the window root. Rows only set the request on click.
struct SendToThreadSheetHost: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    Color.clear.frame(width: 0, height: 0)
      .sheet(item: $app.sendToThreadRequest) { request in
        SendToThreadView(request: request) { app.sendToThreadRequest = nil }
          .environmentObject(app)
      }
  }
}

enum ThreadDraftText {
  static func appending(_ context: String, to draft: String) -> String {
    guard !context.isEmpty else { return draft }
    return draft + (draft.isEmpty ? "" : "\n\n") + context
  }
}

@MainActor extension Workspace {
  func openSendToThread(source: String, fromTurn: String = "") {
    guard connected, !projectID.isEmpty, !source.isEmpty, !busy, !openingProject,
      !restoringNavigation, !loadingConversationDraft else { return }
    sendToThreadRequest = SendToThreadRequest(project: projectID, source: source, fromTurn: fromTurn)
  }
}

struct SendToThreadView: View {
  @EnvironmentObject var app: Workspace
  let request: SendToThreadRequest
  let close: () -> Void
  @StateObject private var targets = ThreadLibrary()
  @State private var search = ""
  @State private var target = ""
  @State private var preview = ""
  @State private var sourceThread = ""
  @State private var sourceTitle = ""
  @State private var sourceHarness = ""
  @State private var turns = 0
  @State private var omitted = 0
  @State private var availableTurns: [[String: Any]] = []
  @State private var partial = false
  @State private var fromTurn = ""
  @State private var includeChanges = true
  @State private var loading = true
  @State private var adding = false
  @State private var failure = ""
  @State private var destinationFailure = ""
  @State private var closed = false

  init(request: SendToThreadRequest, close: @escaping () -> Void) {
    self.request = request
    self.close = close
    _partial = State(initialValue: !request.fromTurn.isEmpty)
    _fromTurn = State(initialValue: request.fromTurn)
  }

  private var previewKey: String {
    request.id.uuidString + "\n" + (partial ? fromTurn : "") + "\n" + String(includeChanges)
  }
  private var destinations: [[String: Any]] {
    targets.rows.filter {
      string($0, "kind") == "task" && string($0, "conversation_id", string($0, "id")) != sourceThread
        && ["completed", "failed", "cancelled", "interrupted"].contains(string($0, "status"))
    }
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Text("Send to thread").font(.title2)
        Spacer()
        Button("Cancel") { closed = true; close() }.keyboardShortcut(.cancelAction)
      }
      Text("From: \(sourceTitle) · \(sourceHarness) · \(turns) turns")
        .font(.callout).lineLimit(2)
      TextField("Search destination threads…", text: $search).textFieldStyle(.roundedBorder)
        .onChange(of: search) { _, value in
          target = ""
          if value.count > 200 { search = String(value.prefix(200)) }
        }
      ScrollView {
        LazyVStack(alignment: .leading, spacing: 6) {
          destinationButton(id: "", title: "New thread…", detail: "Choose any connection after reviewing the draft")
          ForEach(destinations, id: \.projectRowID) { row in
            let names = HarnessIdentity.used(in: row).map(\.name).joined(separator: " · ")
            HStack {
              destinationButton(id: string(row, "id"), title: string(row, "conversation_title", string(row, "title")), detail: names)
              if let date = row["updated"] as? Double {
                Text(Date(timeIntervalSince1970: date), style: .relative).font(.caption).foregroundStyle(.secondary)
              }
            }
          }
          if targets.loading { ProgressView().controlSize(.small) }
          if !targets.cursor.isEmpty {
            Button("Load more threads") {
              Task { await targets.load(engine: app.engine, project: request.project, query: search, view: "active", more: true) }
            }.disabled(targets.loading)
          }
        }
      }.frame(height: 125)
      if !targets.failure.isEmpty { Text(targets.failure).font(.caption).foregroundStyle(.orange) }
      HStack {
        Picker("Include", selection: $partial) {
          Text("Whole conversation").tag(false)
          Text("From this turn on").tag(true)
        }.pickerStyle(.radioGroup).horizontalRadioGroupLayout()
        Toggle("Changed files list", isOn: $includeChanges)
      }.disabled(loading || adding)
      if partial {
        Picker("Starting turn", selection: $fromTurn) {
          ForEach(availableTurns, id: \.projectRowID) { row in
            Text(string(row, "title")).lineLimit(1).tag(string(row, "id"))
          }
        }.disabled(loading || adding)
      }
      HStack {
        Text("Preview (editable)").font(.headline)
        if loading { ProgressView().controlSize(.small) }
        Spacer()
        Text("Changing scope refreshes the preview.").font(.caption).foregroundStyle(.secondary)
      }
      TextEditor(text: $preview).font(.system(.callout, design: .monospaced))
        .padding(6).brandSurface().disabled(loading || adding)
        .accessibilityIdentifier("sendToThread.preview")
      if omitted > 0 {
        Text("\(omitted) messages left out to fit. Full history remains in the source thread.")
          .font(.caption).foregroundStyle(.orange)
      }
      if !failure.isEmpty {
        HStack {
          Text(failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled)
          Button("Retry preview") { Task { await loadPreview() } }.disabled(loading)
        }
      }
      if !destinationFailure.isEmpty { Text(destinationFailure).font(.caption).foregroundStyle(.orange) }
      HStack {
        Text("Appends to the destination draft. No message is sent. Its agent session stays unchanged.")
          .font(.caption).foregroundStyle(.secondary)
        Spacer()
        Button("Send as draft", action: addDraft).buttonStyle(BrandButtonStyle())
          .accessibilityIdentifier("sendToThread.addDraft")
          .disabled(loading || adding || !failure.isEmpty || preview.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || app.projectID != request.project || app.busy || app.openingProject)
      }
    }.padding(24).frame(width: 780, height: 710)
      .task(id: previewKey) { await loadPreview() }
      .task(id: search) {
        do { try await Task.sleep(for: .milliseconds(200)) } catch { return }
        await targets.load(engine: app.engine, project: request.project, query: search, view: "active")
      }
      .onChange(of: app.projectID) { _, project in if project != request.project { closed = true; close() } }
      .onDisappear { closed = true }
  }

  private func destinationButton(id: String, title: String, detail: String) -> some View {
    Button { target = id; destinationFailure = "" } label: {
      HStack(alignment: .top) {
        Image(systemName: target == id ? "largecircle.fill.circle" : "circle")
          .foregroundStyle(target == id ? Color.qAccent : Color.secondary)
        VStack(alignment: .leading, spacing: 2) {
          Text(title).lineLimit(1)
          Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
        }
        Spacer(minLength: 0)
      }.padding(5).contentShape(Rectangle())
    }.buttonStyle(.plain).disabled(adding)
  }

  private func loadPreview() async {
    let key = previewKey
    loading = true
    failure = ""
    defer { if key == previewKey { loading = false } }
    do {
      var params: [String: Any] = ["project": request.project, "id": request.source, "include_changes": includeChanges]
      if partial && !fromTurn.isEmpty { params["from_turn"] = fromTurn }
      let result = try await app.engine.call("threads.send.preview", params) as? [String: Any] ?? [:]
      guard !Task.isCancelled, !closed, key == previewKey, app.projectID == request.project else { return }
      preview = string(result, "text")
      sourceThread = string(result, "source_thread")
      sourceTitle = string(result, "source_title")
      sourceHarness = string(result, "source_harness")
      turns = result["turns"] as? Int ?? 0
      omitted = result["omitted_messages"] as? Int ?? 0
      availableTurns = result["available_turns"] as? [[String: Any]] ?? []
      if fromTurn.isEmpty { fromTurn = availableTurns.first.map { string($0, "id") } ?? "" }
    } catch { if !Task.isCancelled, key == previewKey { failure = error.localizedDescription } }
  }

  private func addDraft() {
    let destination = target
    let text = preview
    adding = true
    Task {
      defer { adding = false }
      do {
        let summary = destination.isEmpty ? nil : try await app.engine.call("threads.get", ["project": request.project, "id": destination]) as? [String: Any]
        guard !closed, !Task.isCancelled, app.projectID == request.project else { return }
        let latest = summary.map { string($0, "id") } ?? destination
        guard summary.map({ string($0, "conversation_id", latest) != sourceThread }) ?? true else {
          destinationFailure = "Choose another destination thread."
          return
        }
        if app.addSharedThreadContext(text, project: request.project, target: latest, targetSummary: summary) {
          app.notice = "Context from \"\(sourceTitle)\" added as a draft. Review and send."
          closed = true
          close()
        } else { destinationFailure = "The destination changed or is busy. Choose an idle thread in this project." }
      } catch { destinationFailure = error.localizedDescription }
    }
  }
}

/// A lightweight action for a recorded turn, using the action-only workspace
/// environment so the historical Markdown does not observe global changes.
struct SendTurnMenu: View {
  let turn: String
  let context: TurnChangesContext
  @Environment(\.turnChangesWorkspace) private var workspace
  var body: some View {
    Menu {
      Button("Send to thread from this turn…") {
        guard let app = workspace else { return }
        app.openSendToThread(source: app.selectedJob, fromTurn: turn)
      }.disabled(turn.isEmpty || !context.connected || context.projectBusy)
    } label: { Image(systemName: "ellipsis") }
      .menuStyle(.borderlessButton).fixedSize()
      .accessibilityLabel("Turn actions")
  }
}
