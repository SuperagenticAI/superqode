import SwiftUI

struct ProjectReviewScreen: View {
  let project: String
  var job: String? = nil
  @EnvironmentObject private var store: CompanionStore
  @State private var scope = "uncommitted"
  @State private var base = "main"
  @State private var listing: [String: JSONValue] = [:]
  @State private var loading = false
  @State private var issue = ""
  init(project: String, job: String? = nil) {
    self.project = project; self.job = job
    _scope = State(initialValue: job == nil ? "uncommitted" : "turn")
  }
  private var params: [String: JSONValue] {
    var value: [String: JSONValue] = ["project": .string(project), "scope": .string(scope)]
    if scope == "branch" { value["base_ref"] = .string(base) }
    if scope == "turn", let job { value["job"] = .string(job) }
    return value
  }
  var body: some View {
    List {
      Section {
        ConnectionStatus()
        Picker("Review scope", selection: $scope) {
          Text("Uncommitted").tag("uncommitted")
          Text("Branch").tag("branch")
          if job != nil { Text("This turn").tag("turn") }
        }
        if scope == "branch" { TextField("Base branch or commit", text: $base).textInputAutocapitalization(.never).autocorrectionDisabled() }
        Text(listing.text("label", "Review exact file revisions before requesting changes or staging.")).font(.footnote).foregroundStyle(.secondary)
      }.listRowBackground(CompanionTheme.panel)
      if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      if loading { ProgressView("Loading changes…") }
      ForEach(listing.records("files")) { file in
        NavigationLink { ReviewedFileScreen(file: file, params: params, parent: scope == "turn" ? job : nil) } label: {
          VStack(alignment: .leading, spacing: 5) {
            Text(file.text("path")).font(.subheadline.monospaced())
            Text(file.text("layer").capitalized + " · " + file.text("change")).font(.caption).foregroundStyle(.secondary)
          }
        }.listRowBackground(CompanionTheme.panel)
      }
      if !loading && issue.isEmpty && listing.records("files").isEmpty { ContentUnavailableView("No matching changes", systemImage: "checkmark.circle") }
      if listing.number("excluded_count") > 0 { Text("Sensitive paths are excluded from review.").font(.caption).foregroundStyle(.secondary) }
      if listing.flag("truncated") { Text("This view is limited to 500 files. Narrow the review on your Mac.").font(.caption).foregroundStyle(.secondary) }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background).navigationTitle("Review changes")
      .task(id: scope + ":" + base) {
        do { try await Task.sleep(for: .milliseconds(250)); try Task.checkCancellation(); await load() } catch { }
      }.refreshable { await load() }
  }
  private func load() async {
    guard let api = store.api else { return }
    guard store.hasProjectInspection("review") else { issue = "Update the Mac build to enable contextual review."; return }
    let request = params
    loading = true; listing = [:]
    defer { if request == params { loading = false } }
    do {
      let next = try await api.rpc("review.list", request).object
      try Task.checkCancellation()
      guard request == params else { return }
      listing = next; issue = ""
    } catch is CancellationError { }
    catch { if request == params { issue = error.localizedDescription } }
  }
}

struct ReviewedFileScreen: View {
  let file: RemoteRecord
  let params: [String: JSONValue]
  let parent: String?
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @State private var document: [String: JSONValue] = [:]
  @State private var issue = ""
  @State private var loading = true
  @State private var working = false
  @State private var comment = ""
  @State private var selectedHunk = 0
  @State private var firstRow = 1
  @State private var lastRow = 1
  @State private var feedbackDraft: LocalDraft?
  @State private var stageRequest: [String: JSONValue]?
  @State private var stageKey = UUID().uuidString
  private var request: [String: JSONValue] { params.merging(["file_id": .string(file.id)]) { _, new in new } }
  private var hunks: [RemoteRecord] { document.records("hunks") }
  private var hunk: [String: JSONValue] { hunks.indices.contains(selectedHunk) ? hunks[selectedHunk].raw : [:] }
  private var lines: [RemoteRecord] { hunk.records("lines") }
  private var complete: Bool { !loading && !document.text("snapshot_id").isEmpty && document.text("issue").isEmpty && !document.flag("truncated") }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        ConnectionStatus()
        if loading { ProgressView("Reading reviewed revisions…") }
        if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
        if !document.text("issue").isEmpty { Text(document.text("issue")).foregroundStyle(CompanionTheme.warning) }
        ForEach(Array(hunks.enumerated()), id: \.offset) { _, item in
          MobileCodeBlock(code: render(item.raw), language: "diff")
        }
        if document.flag("truncated") { Text("The diff is incomplete. Review the complete file on the Mac before staging.").foregroundStyle(CompanionTheme.warning) }
        if complete && !hunks.isEmpty { feedback }
        if complete && document.flag("can_stage") {
          CompanionCard {
            Button("Stage reviewed file") { stageRequest = request.merging(["snapshot_id": .string(document.text("snapshot_id"))]) { _, new in new } }
              .buttonStyle(CompanionPrimaryButton()).disabled(working || !store.canMutate || !store.permissions.contains("review"))
            Text(store.permissions.contains("review") ? "Stages every reviewed hunk in this file. Current file text is preserved; no commit is created." : "To stage from the phone, enable Allow staging reviewed files when approving the device on your Mac.").font(.caption).foregroundStyle(.secondary)
          }
        }
        if working { ProgressView("Waiting for your Mac…") }
      }.padding(20).frame(maxWidth: 950).frame(maxWidth: .infinity)
    }.background(CompanionTheme.background).navigationTitle(file.text("path")).navigationBarTitleDisplayMode(.inline)
      .toolbar { Button("Refresh") { Task { await load() } }.disabled(working) }
      .task { await load() }.interactiveDismissDisabled(working)
      .sheet(item: $feedbackDraft) { draft in NavigationStack { ComposeTaskScreen(project: params.text("project"), parent: parent, restored: draft) } }
      .confirmationDialog("Stage \(file.text("path"))?", isPresented: Binding(get: { stageRequest != nil }, set: { if !$0 { stageRequest = nil } }), titleVisibility: .visible) {
        if let snapshot = stageRequest {
          Button("Stage reviewed file") { Task { await stage(snapshot) } }
        }
      } message: { Text("This updates the Git index with the reviewed file. If its revision changed, the Mac refuses the request. It does not commit or merge changes.") }
  }
  private var feedback: some View {
    CompanionCard {
      Label("Request a change", systemImage: "text.bubble").font(.headline)
      Picker("Hunk", selection: $selectedHunk) { ForEach(Array(hunks.enumerated()), id: \.offset) { index, item in Text(item.text("header")).tag(index) } }
      Stepper("First displayed row: \(firstRow)", value: $firstRow, in: 1...max(1, lines.count))
      Stepper("Last displayed row: \(lastRow)", value: $lastRow, in: firstRow...max(firstRow, lines.count))
      Text("Row numbers include context lines in this hunk. Check the numbered excerpt below before preparing feedback. Select up to 80 rows.").font(.caption).foregroundStyle(.secondary)
      if !lines.isEmpty {
        MobileCodeBlock(code: lines.enumerated().filter { $0.offset >= firstRow - 1 && $0.offset <= lastRow - 1 }.prefix(80).map { index, line in
          "\(index + 1) | " + (line.text("kind") == "add" ? "+" : line.text("kind") == "delete" ? "-" : " ") + line.text("text")
        }.joined(separator: "\n"), language: "Selected rows")
      }
      TextField("What should change?", text: $comment, axis: .vertical).lineLimit(3...7)
      Button("Prepare feedback draft") { Task { await prepare() } }
        .disabled(working || !store.reachable || comment.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || comment.count > 4000 || lastRow - firstRow >= 80 || lines.isEmpty)
      Text("Creates a draft with exact file revisions and quoted lines. Choose a connection and send explicitly; nothing runs automatically.").font(.caption).foregroundStyle(.secondary)
    }.disabled(working)
      .onChange(of: selectedHunk) { _, _ in firstRow = 1; lastRow = 1 }
      .onChange(of: firstRow) { _, start in lastRow = max(start, lastRow) }
  }
  private func render(_ value: [String: JSONValue]) -> String {
    value.text("header") + "\n" + value.records("lines").map { row in
      (row.text("kind") == "add" ? "+" : row.text("kind") == "delete" ? "-" : " ") + row.text("text")
    }.joined(separator: "\n")
  }
  private func load() async {
    guard let api = store.api else { loading = false; return }
    loading = true
    do {
      let next = try await api.rpc("review.diff", request).object
      try Task.checkCancellation()
      if next.text("snapshot_id") != document.text("snapshot_id") { stageKey = UUID().uuidString; firstRow = 1; lastRow = 1; selectedHunk = 0 }
      document = next; issue = ""
    }
    catch is CancellationError { }
    catch { issue = error.localizedDescription }
    loading = false
  }
  private func prepare() async {
    guard let api = store.api, complete, !working else { return }
    working = true; issue = ""
    defer { working = false }
    do {
      let values = request.merging(["snapshot_id": .string(document.text("snapshot_id")), "hunk_id": .number(hunk.number("id")), "start": .number(Double(firstRow - 1)), "end": .number(Double(lastRow - 1)), "comment": .string(comment)]) { _, new in new }
      let result = try await api.rpc("review.feedback", values).object
      guard !result.text("text").isEmpty else { throw CompanionError("The Mac returned no feedback text. Refresh the reviewed file.") }
      var draft = LocalDraft(project: params.text("project"), parent: parent)
      draft.prompt = result.text("text"); draft.origin = store.address
      feedbackDraft = draft
    } catch { issue = error.localizedDescription }
  }
  private func stage(_ snapshot: [String: JSONValue]) async {
    guard let api = store.api, store.canMutate, store.permissions.contains("review"), !working else { return }
    working = true; issue = ""
    defer { working = false }
    do { _ = try await api.rpc("review.stage", snapshot, key: stageKey); dismiss() }
    catch { issue = error.localizedDescription }
  }
}
