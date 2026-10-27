import AppKit
import SwiftUI

struct ReviewWorkspaceView: View {
  @EnvironmentObject var app: Workspace
  @Environment(\.colorScheme) private var colorScheme
  @Environment(\.colorSchemeContrast) private var contrast
  @ObservedObject var commentStore: ReviewCommentStore
  @State private var listing: ReviewListing?
  @State private var document: ReviewDocument?
  @State private var selection = ReviewLineSelection()
  @State private var baseInput = "main"
  @State private var failure = ""
  @State private var listingGeneration = 0
  @State private var fileGeneration = 0
  @State private var loadingList = false
  @State private var loadingFile = false
  @State private var applying = false
  private var unavailable: Bool { loadingList || loadingFile || applying }
  private var projectBusy: Bool {
    app.busy
      || app.projectJobs.contains {
        ["running", "needs_approval", "queued", "cancelling"].contains(string($0, "status"))
      }
  }
  private var selectedHunk: ReviewHunk? {
    document?.hunks.first { $0.id == selection.hunkID }
  }
  private var selectedRange: ClosedRange<Int>? {
    selectedHunk.flatMap { selection.range(in: $0) }
  }
  private var comment: Binding<String> {
    Binding(
      get: {
        document?.snapshotID.flatMap { commentStore.drafts[$0]?.text } ?? ""
      },
      set: { text in
        guard let document, let snapshot = document.snapshotID else { return }
        if text.isEmpty {
          commentStore.drafts.removeValue(forKey: snapshot)
        } else {
          commentStore.drafts[snapshot] = ReviewCommentDraft(
            path: document.path,
            snapshotID: snapshot, text: text, selection: selection)
        }
      })
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      PageTitle(
        eyebrow: "Review before the next step", title: "Changes",
        subtitle: "Inspect a specific source of changes, select lines and prepare feedback.")
      controls
      if let listing {
        Text(listing.label).font(.caption).foregroundStyle(.secondary).textSelection(.enabled)
        if listing.excludedCount > 0 || listing.truncated {
          Text(
            listing.truncated
              ? "Showing the first 500 change entries. Narrow larger reviews using your Git tools."
              : "\(listing.excludedCount) sensitive or unsupported paths are excluded."
          )
          .font(.caption).foregroundStyle(.orange)
        }
      }
      if !failure.isEmpty {
        HStack {
          Label(failure, systemImage: "exclamationmark.triangle").textSelection(.enabled)
          Button("Retry", action: loadListing).disabled(applying)
        }.font(.callout).foregroundStyle(.orange)
      }
      HSplitView {
        fileList.frame(minWidth: 190, idealWidth: 240, maxWidth: 320)
        VStack(alignment: .leading, spacing: 10) {
          if loadingFile {
            ProgressView("Loading revision…")
          } else if let document {
            documentHeader(document)
            if !document.issue.isEmpty {
              Text(document.issue).font(.callout).foregroundStyle(.orange).textSelection(.enabled)
            }
            if document.truncated {
              Text(
                "This preview is incomplete. Review the full file externally before staging or commenting."
              )
              .font(.callout).foregroundStyle(.orange)
            }
            diff(document)
            feedbackEditor(document)
          } else {
            ContentUnavailableView(
              "Choose a change", systemImage: "text.magnifyingglass",
              description: Text("Select a changed file to inspect its revision and hunks."))
          }
        }.padding(.leading, 14).frame(minWidth: 420, maxWidth: .infinity, maxHeight: .infinity)
      }
    }.padding(24)
      .onAppear {
        baseInput = app.reviewSelection.baseRef
        loadListing()
      }
      .onChange(of: app.reviewSelection.scope) { _, _ in loadListing() }
      .onChange(of: app.reviewSelection.baseRef) { _, value in
        baseInput = value
        loadListing()
      }
      .onChange(of: app.reviewSelection.fileID) { _, _ in loadDocument() }
      .onChange(of: commentStore.drafts) { _, _ in app.scheduleDraftSave() }
      .onDisappear {
        listingGeneration += 1
        fileGeneration += 1
        app.saveDraft()
      }
  }

  private var controls: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(spacing: 12) {
        Picker("Review scope", selection: $app.reviewSelection.scope) {
          ForEach(ReviewScope.allCases) { scope in Text(scope.title).tag(scope) }
        }.pickerStyle(.segmented).frame(maxWidth: 360).disabled(applying)
        Button("Refresh", action: loadListing).disabled(unavailable)
        if loadingList { ProgressView().controlSize(.small) }
        Spacer()
        savedNotes
      }
      if app.reviewSelection.scope == .branch {
        HStack {
          Text("Compare with").font(.caption)
          TextField("Base branch or commit", text: $baseInput).textFieldStyle(.roundedBorder)
            .frame(maxWidth: 360).onSubmit(compareBranch).disabled(applying)
          Button("Compare", action: compareBranch).disabled(applying)
          Spacer()
        }
      }
    }
  }

  private var savedNotes: some View {
    Menu("Feedback drafts (\(commentStore.drafts.count))") {
      ForEach(commentStore.drafts.keys.sorted(), id: \.self) { key in
        if let note = commentStore.drafts[key] {
          Menu(note.path + " · " + String(key.prefix(8))) {
            Button("Copy saved note") {
              NSPasteboard.general.clearContents()
              NSPasteboard.general.setString(
                note.path + "\nSnapshot: " + note.snapshotID + "\n" + note.text, forType: .string)
            }
            Button("Discard saved note", role: .destructive) {
              commentStore.drafts.removeValue(forKey: key)
            }
          }
        }
      }
    }.disabled(commentStore.drafts.isEmpty || applying)
  }

  private var fileList: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("CHANGED FILES").font(.caption.monospaced()).foregroundStyle(.secondary)
      List(selection: $app.reviewSelection.fileID) {
        ForEach(listing?.files ?? []) { file in
          VStack(alignment: .leading, spacing: 4) {
            Text(file.path).font(.system(size: 12, design: .monospaced)).lineLimit(2)
            Text(file.layerTitle + " · " + file.change).font(.caption).foregroundStyle(.secondary)
          }.tag(file.id).padding(.vertical, 3)
        }
      }.scrollContentBackground(.hidden).disabled(loadingList || applying)
      if listing?.files.isEmpty == true && !loadingList {
        Text("No visible changes in this scope.").font(.caption).foregroundStyle(.secondary)
      }
    }
  }

  private func documentHeader(_ document: ReviewDocument) -> some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack {
        Text(document.path).font(.headline.monospaced()).lineLimit(2).textSelection(.enabled)
        Spacer()
        Button("Stage reviewed file") { stage(document) }
          .disabled(!document.complete || !document.canStage || projectBusy || applying)
          .help("Stage a complete Unstaged or Untracked text entry when project work is idle.")
      }
      Text("Snapshot " + String((document.snapshotID ?? "Unavailable").prefix(12)))
        .font(.caption.monospaced()).foregroundStyle(.secondary)
        .help(
          "Base file fingerprint: \(document.baseRevision ?? "Unavailable")\nTarget file fingerprint: \(document.targetRevision ?? "Unavailable")"
        )
      if let base = document.revisions?["base"], let head = document.revisions?["head"] {
        Text("Commits \(base.prefix(12)) → \(head.prefix(12))").font(.caption.monospaced())
      }
      if let before = document.baseMode, let after = document.targetMode, before != after {
        Text("File mode \(before) → \(after)").font(.caption.monospaced())
      }
    }
  }

  private func diff(_ document: ReviewDocument) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Button("Previous hunk") { moveHunk(-1, document: document) }
          .disabled(app.reviewSelection.hunkID <= 0 || document.hunks.isEmpty)
        Button("Next hunk") { moveHunk(1, document: document) }
          .disabled(app.reviewSelection.hunkID >= document.hunks.count - 1)
        Text("\(document.hunks.count) hunks").font(.caption).foregroundStyle(.secondary)
        Spacer()
      }
      ScrollViewReader { proxy in
        ScrollView([.horizontal, .vertical]) {
          LazyVStack(alignment: .leading, spacing: 2) {
            ForEach(document.hunks) { hunk in
              Text(hunk.header).font(.caption.monospaced()).foregroundStyle(Color.qAccent)
                .padding(.vertical, 8).id("review-hunk-\(hunk.id)")
              ForEach(hunk.lines) { line in
                reviewLine(line, hunk: hunk)
              }
            }
            if document.hunks.isEmpty && document.issue.isEmpty {
              Text(
                "No text hunks. This change may affect only file mode, an empty file or file metadata."
              )
              .font(.callout).foregroundStyle(.secondary).padding()
            }
          }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
        }.onAppear { proxy.scrollTo("review-hunk-\(app.reviewSelection.hunkID)", anchor: .top) }
          .onChange(of: app.reviewSelection.hunkID) { _, value in
            proxy.scrollTo("review-hunk-\(value)", anchor: .top)
          }
      }.outlinedSurface(radius: 8).frame(minHeight: 150, maxHeight: .infinity)
    }
  }

  private func reviewLine(_ line: ReviewLine, hunk: ReviewHunk) -> some View {
    let selected = selection.range(in: hunk)?.contains(line.id) ?? false
    return Button {
      selection.select(line.id, in: hunk.id, extending: NSEvent.modifierFlags.contains(.shift))
      app.reviewSelection.hunkID = hunk.id
      rememberSelection()
    } label: {
      HStack(alignment: .top, spacing: 8) {
        Text(line.oldLine.map(String.init) ?? "–").frame(width: 42, alignment: .trailing)
        Text(line.newLine.map(String.init) ?? "–").frame(width: 42, alignment: .trailing)
        Text(line.marker).frame(width: 12)
        Text(line.text + (line.noNewline ? "  ⟨no final newline⟩" : "")).fixedSize(
          horizontal: true, vertical: false)
      }.font(.system(size: 12, design: .monospaced))
        .foregroundStyle(lineInk(line.kind))
        .padding(.vertical, 3).padding(.horizontal, 5).frame(
          maxWidth: .infinity, alignment: .leading
        )
        .background(selected ? Color.qAccent.opacity(0.2) : Color.clear)
    }.buttonStyle(.plain).disabled(!documentComplete || applying)
      .accessibilityLabel("\(line.kind), \(line.numberLabel): \(line.text)")
      .accessibilityHint("Select this line; use the From and Through controls to extend the range.")
      .accessibilityAddTraits(selected ? .isSelected : [])
  }

  private var documentComplete: Bool { document?.complete ?? false }

  private func lineInk(_ kind: String) -> Color {
    guard contrast != .increased else { return .primary }
    if kind == "add" {
      return colorScheme == .dark
        ? Color(red: 0.52, green: 0.90, blue: 0.63) : Color(red: 0.08, green: 0.35, blue: 0.16)
    }
    if kind == "delete" {
      return colorScheme == .dark
        ? Color(red: 1, green: 0.69, blue: 0.72) : Color(red: 0.62, green: 0.15, blue: 0.15)
    }
    return .primary
  }

  private func feedbackEditor(_ document: ReviewDocument) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Feedback for selected lines").font(.caption.bold())
      if let hunk = selectedHunk {
        HStack {
          rangePicker("From", hunk: hunk, start: true)
          rangePicker("Through", hunk: hunk, start: false)
        }.disabled(applying)
      } else {
        Text("Select a line; Shift-click another line to select a range.")
          .font(.caption).foregroundStyle(.secondary)
      }
      TextEditor(text: comment).font(.system(size: 12)).frame(height: 64)
        .accessibilityLabel("Review feedback").disabled(!document.complete || applying)
        .outlinedSurface(radius: 6)
      HStack {
        Text("Feedback is added to your draft for review before sending.")
          .font(.caption).foregroundStyle(.secondary)
        Spacer()
        Button(app.selectedJob.isEmpty ? "Add to draft" : "Add to follow-up") {
          addFeedback(document)
        }
        .disabled(
          !document.complete || (selectedRange.map { $0.count > 80 } ?? true)
            || comment.wrappedValue.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || comment.wrappedValue.count > 4000 || applying)
      }
    }
  }

  private func rangePicker(_ title: String, hunk: ReviewHunk, start: Bool) -> some View {
    Picker(
      title,
      selection: Binding(
        get: { (start ? selection.start : selection.end) ?? -1 },
        set: { value in
          if start { selection.start = value } else { selection.end = value }
          rememberSelection()
        })
    ) {
      Text("Choose a line").tag(-1)
      ForEach(hunk.lines) { line in Text(line.numberLabel).tag(line.id) }
    }.frame(maxWidth: 300)
  }

  private func rememberSelection() {
    guard let snapshot = document?.snapshotID, var saved = commentStore.drafts[snapshot] else {
      return
    }
    saved.selection = selection
    commentStore.drafts[snapshot] = saved
  }

  private func moveHunk(_ offset: Int, document: ReviewDocument) {
    app.reviewSelection.hunkID = min(
      max(0, app.reviewSelection.hunkID + offset), max(0, document.hunks.count - 1))
  }

  private func compareBranch() {
    let value = baseInput.trimmingCharacters(in: .whitespacesAndNewlines)
    if app.reviewSelection.baseRef == value {
      loadListing()
    } else {
      app.reviewSelection.baseRef = value
    }
  }

  private func loadListing() {
    guard !applying else { return }
    listingGeneration += 1
    fileGeneration += 1
    let generation = listingGeneration
    let project = app.projectID
    let job = app.selectedJob
    let params = app.reviewSelection.parameters(project: project, job: job)
    loadingList = true
    loadingFile = false
    listing = nil
    document = nil
    failure = ""
    app.perform {
      defer { if generation == listingGeneration { loadingList = false } }
      do {
        let response = try await app.engine.call("review.list", params)
        guard generation == listingGeneration, project == app.projectID, job == app.selectedJob
        else { return }
        let next: ReviewListing = try decodeReview(response)
        listing = next
        loadingList = false
        if next.files.contains(where: { $0.id == app.reviewSelection.fileID }) {
          loadDocument()
        } else {
          app.reviewSelection.fileID = next.files.first?.id ?? ""
        }
      } catch {
        if generation == listingGeneration, project == app.projectID {
          failure = error.localizedDescription
        }
      }
    }
  }

  private func loadDocument() {
    fileGeneration += 1
    document = nil
    selection = ReviewLineSelection()
    loadingFile = false
    guard !loadingList, !applying,
      let item = listing?.files.first(where: { $0.id == app.reviewSelection.fileID })
    else { return }
    let generation = fileGeneration
    let project = app.projectID
    let job = app.selectedJob
    let params = app.reviewSelection.parameters(project: project, job: job)
    loadingFile = true
    failure = ""
    app.perform {
      defer { if generation == fileGeneration { loadingFile = false } }
      do {
        let response = try await app.engine.call("review.diff", params)
        guard generation == fileGeneration, project == app.projectID, job == app.selectedJob,
          item.id == app.reviewSelection.fileID
        else { return }
        let next = try ReviewDocument.decode(response)
        guard next.id == item.id, next.path == item.path else {
          throw EngineError(message: "The review file changed. Refresh to continue.")
        }
        document = next
        if let snapshot = next.snapshotID, let saved = commentStore.drafts[snapshot] {
          selection = saved.selection
        }
        if !next.hunks.contains(where: { $0.id == app.reviewSelection.hunkID }) {
          app.reviewSelection.hunkID = 0
        }
      } catch {
        if generation == fileGeneration, project == app.projectID {
          failure = error.localizedDescription
        }
      }
    }
  }

  private func addFeedback(_ document: ReviewDocument) {
    guard !applying, document.complete, app.section == "Review",
      let hunk = selectedHunk, let range = selection.range(in: hunk),
      let snapshot = document.snapshotID
    else { return }
    let project = app.projectID
    let conversation = app.composerKey
    let generation = fileGeneration
    var params = app.reviewSelection.parameters(project: project, job: app.selectedJob)
    params.merge([
      "snapshot_id": snapshot, "hunk_id": hunk.id, "start": range.lowerBound,
      "end": range.upperBound, "comment": comment.wrappedValue,
    ]) { _, new in new }
    applying = true
    app.perform {
      defer { applying = false }
      do {
        let result = try await app.engine.call("review.feedback", params) as? [String: Any] ?? [:]
        guard generation == fileGeneration, app.section == "Review" else { return }
        let text = string(result, "text")
        guard !text.isEmpty else {
          throw EngineError(message: "The engine returned no review feedback.")
        }
        if app.appendReviewFeedback(text, project: project, conversation: conversation) {
          commentStore.drafts.removeValue(forKey: snapshot)
          app.saveDraft()
        }
      } catch { if generation == fileGeneration { failure = error.localizedDescription } }
    }
  }

  private func stage(_ document: ReviewDocument) {
    guard !applying, document.complete, document.canStage, !projectBusy,
      let snapshot = document.snapshotID,
      app.confirm(
        "Stage the reviewed file?",
        "Stage all reviewed unstaged changes to \(document.path), including every hunk shown. A reviewed deletion removes this path from the index. Local file text is preserved.",
        button: "Stage file")
    else { return }
    let project = app.projectID
    var params = app.reviewSelection.parameters(project: project, job: app.selectedJob)
    params["snapshot_id"] = snapshot
    applying = true
    app.perform {
      do {
        _ = try await app.engine.call("review.stage", params)
        guard project == app.projectID else {
          applying = false
          return
        }
        app.notice = "Staged reviewed changes to " + document.path
        await app.refreshGit()
        applying = false
        if app.section == "Review" { loadListing() }
      } catch {
        applying = false
        failure = error.localizedDescription
      }
    }
  }
}
