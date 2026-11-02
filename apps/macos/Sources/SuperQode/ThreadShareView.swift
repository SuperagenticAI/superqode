import SwiftUI

struct ThreadShareView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  let source: String
  @State private var target = ""
  @State private var preview = ""
  @State private var sourceThread = ""
  @State private var omitted = 0
  @State private var failure = ""
  @State private var targetSearch = ""
  @State private var adding = false
  @State private var closed = false
  @StateObject private var targets = ThreadLibrary()

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Text("Share context to a thread").font(.title2)
        Spacer()
        Button("Cancel") { closed = true; dismiss() }.keyboardShortcut(.cancelAction)
      }
      Text("Preview the visible conversation, then add it to another thread’s draft. Review and send it there when ready.")
        .foregroundStyle(.secondary)
      TextField("Find a destination thread", text: $targetSearch).textFieldStyle(.roundedBorder)
        .onChange(of: targetSearch) { _, _ in target = "" }
      Picker("Destination", selection: $target) {
        Text("New thread").tag("")
        ForEach(targets.rows.filter {
          string($0, "kind") == "task" && string($0, "conversation_id", string($0, "id")) != sourceThread
            && ["completed", "failed", "cancelled", "interrupted"].contains(string($0, "status"))
        }, id: \.projectRowID) { row in
          Text(string(row, "conversation_title", string(row, "title"))).tag(string(row, "id"))
        }
      }
      if !targets.cursor.isEmpty {
        Button("Load more destinations") {
          Task { await targets.load(engine: app.engine, project: project, query: targetSearch, view: "active", more: true) }
        }.disabled(targets.loading)
      }
      if !targets.failure.isEmpty { Text(targets.failure).font(.caption).foregroundStyle(.orange) }
      if preview.isEmpty && failure.isEmpty { ProgressView("Loading recorded conversation…") }
      if omitted > 0 {
        Text("\(omitted) messages omitted to fit the transfer limit. Complete history remains in the source thread.")
          .foregroundStyle(.orange)
      }
      ScrollView {
        Text(preview).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
          .frame(maxWidth: .infinity, alignment: .leading).padding(12)
      }.brandSurface()
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      HStack {
        Text("Existing draft text is preserved. No message is sent automatically.")
          .font(.caption).foregroundStyle(.secondary)
        Spacer()
        Button("Add to draft") {
          let destination = target
          adding = true
          Task {
            defer { adding = false }
            do {
              let summary = destination.isEmpty ? nil : try await app.engine.call("threads.get", ["project": project, "id": destination]) as? [String: Any]
              guard !closed, !Task.isCancelled else { return }
              let latest = summary.map { string($0, "id") } ?? destination
              if app.addSharedThreadContext(preview, project: project, target: latest, targetSummary: summary) { dismiss() }
              else { failure = "The destination changed or is busy. Choose an idle thread in this project." }
            } catch { failure = error.localizedDescription }
          }
        }.buttonStyle(BrandButtonStyle())
          .disabled(adding || preview.isEmpty || app.projectID != project || app.busy || app.openingProject)
      }
    }.padding(24).frame(width: 740, height: 580)
      .task {
        do {
          let result = try await app.engine.call("conversations.share", ["project": project, "id": source]) as? [String: Any] ?? [:]
          guard !Task.isCancelled, app.projectID == project else { return }
          preview = string(result, "text")
          sourceThread = string(result, "source_thread")
          omitted = result["omitted_messages"] as? Int ?? 0
        } catch { failure = error.localizedDescription }
      }
      .task(id: targetSearch) {
        do { try await Task.sleep(for: .milliseconds(200)) } catch { return }
        await targets.load(engine: app.engine, project: project, query: targetSearch, view: "active")
      }
      .onDisappear { closed = true }
  }
}
