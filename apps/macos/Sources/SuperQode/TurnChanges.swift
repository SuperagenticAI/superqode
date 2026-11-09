import SwiftUI

/// Files changed by one coding turn, read from the turn's local checkpoint.
struct TurnChangeFile: Identifiable, Equatable {
  let path: String
  let change: String
  let added: Int?
  let removed: Int?
  var id: String { path }
  var name: String { (path as NSString).lastPathComponent }
}

struct TurnChangeSummary: Equatable {
  var available = false
  var reason = ""
  var checkpoint = ""
  var live = false
  var running = false
  var files: [TurnChangeFile] = []
  var fileCount = 0
  var added = 0
  var removed = 0
  var canRestore = false
  var restoreReason = ""
  var laterTurns = 0
  var conflicts: [String] = []

  init() {}
  init(_ raw: [String: Any]) {
    available = raw["available"] as? Bool ?? false
    reason = string(raw, "reason")
    checkpoint = string(raw, "checkpoint")
    live = raw["live"] as? Bool ?? false
    running = raw["running"] as? Bool ?? false
    files = (raw["files"] as? [[String: Any]] ?? []).map {
      TurnChangeFile(path: string($0, "path"), change: string($0, "change"),
        added: $0["added"] as? Int, removed: $0["removed"] as? Int)
    }
    fileCount = raw["file_count"] as? Int ?? files.count
    added = raw["added"] as? Int ?? 0
    removed = raw["removed"] as? Int ?? 0
    canRestore = raw["can_restore"] as? Bool ?? false
    restoreReason = string(raw, "restore_reason")
    laterTurns = raw["later_turns"] as? Int ?? 0
    conflicts = raw["conflicts"] as? [String] ?? []
  }

  var headline: String {
    "\(fileCount) file\(fileCount == 1 ? "" : "s") changed"
  }
}

/// Caches summaries so scrolling a long transcript does not refetch every turn.
/// The transcript holds this without observing it, so a summary arriving only
/// re-renders its own chips, not the whole conversation.
@MainActor final class TurnChangesStore: ObservableObject {
  @Published private(set) var summaries: [String: TurnChangeSummary] = [:]
  /// One sheet host for every turn in the transcript.
  @Published var shipRequest: TurnShipRequest?
  @Published var diffRequest: TurnDiffRequest?
  private var inFlight: Set<String> = []
  /// What each summary was loaded for (the run status for the live turn).
  private var stamps: [String: String] = [:]

  func summary(_ job: String) -> TurnChangeSummary? { summaries[job] }

  /// Loads once per job and stamp. `force` refetches regardless, for live turns.
  func load(engine: Engine, project: String, job: String, stamp: String = "", force: Bool = false) async {
    guard !project.isEmpty, !job.isEmpty, !inFlight.contains(job) else { return }
    if !force, summaries[job] != nil, stamps[job] == stamp { return }
    inFlight.insert(job)
    defer { inFlight.remove(job) }
    do {
      let raw = try await engine.call("turns.changes", ["project": project, "job": job]) as? [String: Any] ?? [:]
      let next = TurnChangeSummary(raw)
      stamps[job] = stamp
      if summaries[job] != next { summaries[job] = next }
    } catch {
      // Older engines do not know this method. Hide the summary quietly.
      stamps[job] = stamp
      if summaries[job] == nil { summaries[job] = TurnChangeSummary() }
    }
  }

  func invalidate() {
    summaries.removeAll()
    stamps.removeAll()
  }
}

struct TurnShipRequest: Identifiable {
  let id = UUID()
  let files: [String]
  let prompt: String
}

struct TurnDiffRequest: Identifiable {
  let job: String
  let path: String
  var id: String { job + "\n" + path }
}

/// Presents the commit and diff sheets for any turn. Attached once to the
/// transcript instead of two sheet modifiers on every turn.
struct TurnChangesSheets: View {
  @ObservedObject var store: TurnChangesStore
  @EnvironmentObject var app: Workspace
  var body: some View {
    Color.clear.frame(width: 0, height: 0)
      .sheet(item: $store.shipRequest) { request in
        ShipSheet(turnFiles: request.files, prompt: request.prompt) { store.shipRequest = nil }
          .environmentObject(app)
      }
      .sheet(item: $store.diffRequest) { request in
        TurnDiffSheet(job: request.job, path: request.path) { store.diffRequest = nil }
          .environmentObject(app)
      }
  }
}

/// Inline "files changed" chips under a turn, with undo for sealed turns.
struct TurnChangesView: View {
  let job: String
  /// The visible, currently selected turn. Live turns refresh while running.
  var current = false
  /// The turn's prompt, used to draft a commit message.
  var prompt = ""
  @EnvironmentObject var app: Workspace
  @EnvironmentObject var store: TurnChangesStore
  @State private var expanded = false
  @State private var undoing = false
  private let collapsedCount = 4

  private var summary: TurnChangeSummary? { store.summary(job) }
  private var stamp: String { current ? string(app.detail, "status") : "" }
  private var refreshKey: String { job + "\n" + stamp + "\n" + String(app.connected) }

  var body: some View {
    Group {
      if let summary, summary.available, summary.fileCount > 0 { chips(summary) }
    }
    .task(id: refreshKey) {
      guard app.connected, !app.projectID.isEmpty else { return }
      let live = current && app.active
      if store.summary(job) == nil {
        // Let the transcript draw first; navigating away cancels the fetch.
        try? await Task.sleep(for: .milliseconds(120))
        guard !Task.isCancelled else { return }
      }
      await store.load(engine: app.engine, project: app.projectID, job: job, stamp: stamp, force: live)
      // Live turns: refresh at a calm pace while the agent edits files.
      while current, app.active, !Task.isCancelled {
        try? await Task.sleep(for: .seconds(6))
        guard !Task.isCancelled, app.active else { break }
        await store.load(engine: app.engine, project: app.projectID, job: job, stamp: stamp, force: true)
      }
    }
  }

  private func chips(_ summary: TurnChangeSummary) -> some View {
    let shown = expanded ? summary.files : Array(summary.files.prefix(collapsedCount))
    let hidden = summary.fileCount - shown.count
    return VStack(alignment: .leading, spacing: 8) {
      HStack(spacing: 8) {
        Image(systemName: "doc.on.doc").foregroundStyle(.secondary)
        Text(summary.headline).font(.caption.weight(.semibold))
        LineCounts(added: summary.added, removed: summary.removed)
        if summary.live { Text("updating").font(.caption2).foregroundStyle(.secondary) }
        Spacer(minLength: 0)
        if !summary.live {
          Button { store.shipRequest = TurnShipRequest(files: summary.files.map(\.path), prompt: prompt) } label: { Label("Commit…", systemImage: "arrow.up.circle") }
            .buttonStyle(.plain).font(.caption)
            .disabled(!app.connected || app.hasActiveWork(project: app.projectID))
            .help("Commit these changes, push, and open a pull request with your Git setup")
          undoButton(summary)
        }
      }
      FlowChips(spacing: 6) {
        ForEach(shown) { file in
          Button { store.diffRequest = TurnDiffRequest(job: job, path: file.path) } label: {
            HStack(spacing: 5) {
              Image(systemName: icon(file.change)).font(.system(size: 9)).foregroundStyle(.secondary)
              Text(file.name).lineLimit(1)
              LineCounts(added: file.added, removed: file.removed)
            }
            .font(.system(size: 11)).padding(.horizontal, 8).padding(.vertical, 4)
            .background(Color.primary.opacity(0.06), in: Capsule())
            .contentShape(Capsule())
          }
          .buttonStyle(.plain)
          .disabled(summary.live)
          .help(summary.live ? file.path + "\nThe diff opens when the turn finishes." : file.path + "\nOpen this file's diff for the turn")
        }
        if hidden > 0 && !expanded {
          Button("+\(hidden) more") { expanded = true }.buttonStyle(.plain)
            .font(.system(size: 11)).foregroundStyle(.secondary)
            .padding(.horizontal, 8).padding(.vertical, 4)
        } else if expanded && summary.files.count > collapsedCount {
          Button("Show fewer") { expanded = false }.buttonStyle(.plain)
            .font(.system(size: 11)).foregroundStyle(.secondary)
            .padding(.horizontal, 8).padding(.vertical, 4)
        }
      }
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(Color.qPanel.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.primary.opacity(0.08), lineWidth: 1))
  }

  @ViewBuilder private func undoButton(_ summary: TurnChangeSummary) -> some View {
    let blockedByRun = app.hasActiveWork(project: app.projectID)
    let enabled = summary.canRestore && !blockedByRun && !undoing && app.connected
    Button {
      undo(summary)
    } label: {
      Label(undoing ? "Undoing…" : "Undo this turn", systemImage: "arrow.uturn.backward")
    }
    .buttonStyle(.plain).font(.caption)
    .foregroundStyle(enabled ? Color.primary : Color.secondary)
    .disabled(!enabled)
    .help(enabled ? "Restore the files this turn changed to their state before it ran"
      : blockedByRun ? "Finish or stop project work before undoing a turn"
      : summary.restoreReason.isEmpty ? "Undo is not available for this turn" : summary.restoreReason)
  }

  private func undo(_ summary: TurnChangeSummary) {
    let project = app.projectID
    let checkpoint = summary.checkpoint
    guard !checkpoint.isEmpty else { return }
    let listed = summary.files.prefix(12).map { file -> String in
      switch file.change {
      case "added": return "• " + file.path + " (will be removed)"
      case "deleted": return "• " + file.path + " (will be restored)"
      default: return "• " + file.path
      }
    }
    var message = "These files return to how they were before this turn:\n" + listed.joined(separator: "\n")
    if summary.fileCount > listed.count { message += "\n…and \(summary.fileCount - listed.count) more" }
    message += "\n\nOther files are not touched. Git staging is preserved."
    if summary.laterTurns > 0 {
      message += "\n\n\(summary.laterTurns) later turn\(summary.laterTurns == 1 ? " was" : "s were") recorded after this one. Their files stay as they are, but their undo checkpoints are replaced when the next run starts."
    }
    message += "\n\nIf any of these files changed after the turn (later turns or your own unsaved or uncommitted edits), undo is refused so nothing newer is overwritten. Save editor drafts first."
    guard app.confirm("Undo this turn?", message, button: "Undo turn") else { return }
    undoing = true
    app.perform {
      defer { undoing = false }
      _ = try await app.engine.call("checkpoints.restore", ["project": project, "id": checkpoint])
      store.invalidate()
      await app.refreshGit()
      await store.load(engine: app.engine, project: project, job: job, stamp: stamp, force: true)
    }
  }

  private func icon(_ change: String) -> String {
    switch change {
    case "added": return "plus"
    case "deleted": return "minus"
    default: return "pencil"
    }
  }
}

private struct LineCounts: View {
  let added: Int?
  let removed: Int?
  var body: some View {
    HStack(spacing: 3) {
      if let added { Text("+\(added)").foregroundStyle(.green) }
      if let removed { Text("-\(removed)").foregroundStyle(.red) }
    }.font(.system(size: 10, design: .monospaced))
  }
}

/// Wraps chips onto new lines when the transcript is narrow.
private struct FlowChips: Layout {
  var spacing: CGFloat = 6
  func sizeThatFits(proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) -> CGSize {
    let width = proposal.width ?? .infinity
    var x: CGFloat = 0, y: CGFloat = 0, row: CGFloat = 0, widest: CGFloat = 0
    for view in subviews {
      let size = view.sizeThatFits(.unspecified)
      if x > 0 && x + size.width > width { y += row + spacing; x = 0; row = 0 }
      x += size.width + spacing
      row = max(row, size.height)
      widest = max(widest, x - spacing)
    }
    return CGSize(width: min(widest, width), height: y + row)
  }
  func placeSubviews(in bounds: CGRect, proposal: ProposedViewSize, subviews: Subviews, cache: inout ()) {
    var x = bounds.minX, y = bounds.minY, row: CGFloat = 0
    for view in subviews {
      let size = view.sizeThatFits(.unspecified)
      if x > bounds.minX && x + size.width > bounds.maxX { y += row + spacing; x = bounds.minX; row = 0 }
      view.place(at: CGPoint(x: x, y: y), proposal: ProposedViewSize(size))
      x += size.width + spacing
      row = max(row, size.height)
    }
  }
}

/// One file's diff for one turn, using the review "This turn" scope.
struct TurnDiffSheet: View {
  let job: String
  let path: String
  var close: () -> Void
  @EnvironmentObject var app: Workspace
  @StateObject private var review = WorkbenchReview()
  private var diff: String {
    guard let document = review.document else { return "" }
    return document.hunks.map { hunk in
      hunk.header + "\n" + hunk.lines.map { $0.marker + $0.text }.joined(separator: "\n")
    }.joined(separator: "\n")
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Text(path).font(.headline.monospaced()).lineLimit(1).truncationMode(.middle).textSelection(.enabled)
        Spacer()
        Button("Done", action: close).keyboardShortcut(.cancelAction)
      }
      if let listing = review.listing, listing.files.count > 1 {
        Picker("File", selection: Binding(get: { review.document?.id ?? "" }, set: { id in
          Task { await review.select(id, engine: app.engine) }
        })) {
          ForEach(listing.files) { file in Text(file.path).tag(file.id) }
        }.labelsHidden().frame(maxWidth: 420)
      }
      if !review.failure.isEmpty {
        Text(review.failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled)
      }
      if review.loading || review.loadingFile {
        ProgressView("Loading diff…").font(.caption)
      } else if let document = review.document {
        if !document.issue.isEmpty { Text(document.issue).font(.caption).foregroundStyle(.orange) }
        if document.truncated { Text("Incomplete diff preview.").font(.caption).foregroundStyle(.orange) }
        CommentableDiff(document: document).frame(maxWidth: .infinity, maxHeight: .infinity)
        PendingCommentsTray(store: app.pendingComments)
      }
      Spacer(minLength: 0)
    }
    .padding(16).frame(width: 860, height: 560)
    .task {
      await review.load(engine: app.engine, project: app.projectID, job: job, scope: .turn, preferredPath: path)
    }
  }
}
