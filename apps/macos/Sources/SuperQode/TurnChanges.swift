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
@MainActor final class TurnChangesStore: ObservableObject {
  @Published private(set) var summaries: [String: TurnChangeSummary] = [:]
  private var inFlight: Set<String> = []

  func summary(_ job: String) -> TurnChangeSummary? { summaries[job] }

  func load(engine: Engine, project: String, job: String, force: Bool = false) async {
    guard !project.isEmpty, !job.isEmpty, !inFlight.contains(job) else { return }
    if !force, summaries[job] != nil { return }
    inFlight.insert(job)
    defer { inFlight.remove(job) }
    do {
      let raw = try await engine.call("turns.changes", ["project": project, "job": job]) as? [String: Any] ?? [:]
      let next = TurnChangeSummary(raw)
      if summaries[job] != next { summaries[job] = next }
    } catch {
      // Older engines do not know this method. Hide the summary quietly.
      if summaries[job] == nil { summaries[job] = TurnChangeSummary() }
    }
  }

  func invalidate() { summaries.removeAll() }
}

/// Inline "files changed" chips under a turn.
struct TurnChangesView: View {
  let job: String
  /// The visible, currently selected turn. Live turns refresh while running.
  var current = false
  @EnvironmentObject var app: Workspace
  @EnvironmentObject var store: TurnChangesStore
  @State private var expanded = false
  @State private var diffPath: String?
  private let collapsedCount = 4

  private var summary: TurnChangeSummary? { store.summary(job) }
  private var refreshKey: String { job + "\n" + (current ? string(app.detail, "status") : "") + "\n" + String(app.connected) }

  var body: some View {
    Group {
      if let summary, summary.available, summary.fileCount > 0 { chips(summary) }
    }
    .task(id: refreshKey) {
      guard app.connected, !app.projectID.isEmpty else { return }
      await store.load(engine: app.engine, project: app.projectID, job: job, force: current)
      // Live turns: refresh at a calm pace while the agent edits files.
      while current, app.active, !Task.isCancelled {
        try? await Task.sleep(for: .seconds(6))
        guard !Task.isCancelled, app.active else { break }
        await store.load(engine: app.engine, project: app.projectID, job: job, force: true)
      }
    }
    .sheet(item: Binding(get: { diffPath.map(TurnDiffTarget.init) }, set: { diffPath = $0?.path })) { target in
      TurnDiffSheet(job: job, path: target.path) { diffPath = nil }.environmentObject(app)
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
      }
      FlowChips(spacing: 6) {
        ForEach(shown) { file in
          Button { diffPath = file.path } label: {
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

  private func icon(_ change: String) -> String {
    switch change {
    case "added": return "plus"
    case "deleted": return "minus"
    default: return "pencil"
    }
  }
}

private struct TurnDiffTarget: Identifiable {
  let path: String
  var id: String { path }
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
        DiffView(text: diff).frame(maxWidth: .infinity, maxHeight: .infinity)
      }
      Spacer(minLength: 0)
    }
    .padding(16).frame(width: 860, height: 560)
    .task {
      await review.load(engine: app.engine, project: app.projectID, job: job, scope: .turn, preferredPath: path)
    }
  }
}
