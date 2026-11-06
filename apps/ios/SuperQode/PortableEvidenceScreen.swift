import SwiftUI
import UniformTypeIdentifiers

struct PortableEvidenceDocument: FileDocument {
  static let readableContentTypes: [UTType] = [.plainText, .json, .html]
  var text: String
  init(text: String) { self.text = text }
  init(configuration: ReadConfiguration) throws { text = String(decoding: configuration.file.regularFileContents ?? Data(), as: UTF8.self) }
  func fileWrapper(configuration: WriteConfiguration) throws -> FileWrapper { FileWrapper(regularFileWithContents: Data(text.utf8)) }
}

struct RecordedEvidenceExportScreen: View {
  let project: String
  let job: String
  @EnvironmentObject private var store: CompanionStore
  @State private var format = "markdown"
  @State private var result: [String: JSONValue] = [:]
  @State private var loading = false
  @State private var issue = ""
  @State private var exporting = false
  @State private var expanded = false
  private var type: UTType { format == "json" ? .json : format == "html" ? .html : .plainText }
  var body: some View {
    List {
      Section {
        ConnectionStatus()
        Text("Export recorded evidence from your Mac. Task exports contain visible prompts and answers; agent permissions and private reasoning are not transferred.").font(.footnote).foregroundStyle(.secondary)
        Picker("Format", selection: $format) { Text("Markdown").tag("markdown"); Text("JSON").tag("json"); Text("HTML").tag("html") }
        Button("Prepare export") { Task { await prepare() } }.disabled(loading || !store.reachable)
        if loading { ProgressView("Preparing recorded evidence…") }
        if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      }
      if !result.isEmpty {
        Section {
          if result.flag("truncated") { Text("This run exceeds the mobile export limit. Export the complete evidence from your Mac.").foregroundStyle(CompanionTheme.warning) }
          Button("Save to Files…") { exporting = true }.disabled(result.text("content").isEmpty)
          ShareLink(item: result.text("content")) { Label("Share export", systemImage: "square.and.arrow.up") }
          DisclosureGroup("Preview export", isExpanded: $expanded) {
            if expanded { Text(result.text("content")).font(.caption.monospaced()).textSelection(.enabled) }
          }
        }
      }
    }.navigationTitle("Export evidence").scrollContentBackground(.hidden).background(CompanionTheme.background)
      .onChange(of: format) { _, _ in result = [:]; expanded = false }
      .fileExporter(isPresented: $exporting, document: PortableEvidenceDocument(text: result.text("content")), contentType: type, defaultFilename: result.text("name", "superqode-evidence")) { outcome in
        if case .failure(let error) = outcome { issue = error.localizedDescription }
      }
  }
  private func prepare() async {
    guard let api = store.api, !loading else { return }
    let selected = format
    loading = true; issue = ""; defer { loading = false }
    do {
      let next = try await api.rpc("jobs.export", ["project": .string(project), "id": .string(job), "format": .string(selected)]).object
      try Task.checkCancellation()
      if format == selected { result = next }
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
}

struct ThreadHandoffScreen: View {
  let project: String
  let job: String
  @EnvironmentObject private var store: CompanionStore
  @State private var context: [String: JSONValue] = [:]
  @State private var issue = ""
  @State private var expanded = false
  @State private var draft: LocalDraft?
  var body: some View {
    List {
      Section {
        ConnectionStatus()
        Text("Bring this conversation's visible context into a fresh thread. Review the quote, choose a connection and send explicitly. Permissions, images and private reasoning are not inherited.").font(.footnote).foregroundStyle(.secondary)
        if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
        if context.isEmpty && issue.isEmpty { ProgressView("Preparing quoted context…") }
        if context.number("omitted_messages") > 0 { Text("Earlier messages were omitted to keep the handoff bounded. Export the full conversation on your Mac if needed.").foregroundStyle(CompanionTheme.warning) }
      }
      if !context.text("text").isEmpty {
        Section {
          Button("Use in a new conversation") {
            var next = LocalDraft(project: project)
            next.origin = store.address; next.prompt = context.text("text")
            draft = next
          }.disabled(!store.permissions.contains("tasks"))
          ShareLink(item: context.text("text")) { Label("Share context", systemImage: "square.and.arrow.up") }
          DisclosureGroup("Review quoted context", isExpanded: $expanded) {
            if expanded { Text(context.text("text")).font(.caption.monospaced()).textSelection(.enabled) }
          }
        }
      }
    }.navigationTitle("Thread handoff").scrollContentBackground(.hidden).background(CompanionTheme.background)
      .sheet(item: $draft) { item in NavigationStack { ComposeTaskScreen(project: project, restored: item) } }
      .task {
        guard let api = store.api else { return }
        do { context = try await api.rpc("conversations.share", ["project": .string(project), "id": .string(job)]).object }
        catch is CancellationError { }
        catch { issue = error.localizedDescription }
      }
  }
}
