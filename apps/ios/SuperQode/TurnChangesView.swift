import SwiftUI

struct CompanionTurnChangeFile: Identifiable, Equatable {
  let path: String
  let change: String
  let added: Int?
  let removed: Int?
  let binary: Bool
  var id: String { path }
  var name: String { (path as NSString).lastPathComponent }
}

struct CompanionTurnChanges: Equatable {
  var available = false
  var reason = ""
  var checkpoint = ""
  var live = false
  var running = false
  var files: [CompanionTurnChangeFile] = []
  var fileCount = 0
  var added = 0
  var removed = 0
  var canRestore = false
  var restoreReason = ""
  var laterTurns = 0
  var conflicts: [String] = []

  init(_ raw: [String: JSONValue]) {
    available = raw.flag("available")
    reason = raw.text("reason")
    checkpoint = raw.text("checkpoint")
    live = raw.flag("live")
    running = raw.flag("running")
    files = raw.records("files").map { row in
      CompanionTurnChangeFile(
        path: row.text("path"),
        change: row.text("change", "modified"),
        added: row.raw["added"].flatMap { if case .number(let n) = $0 { return Int(n) }; return nil },
        removed: row.raw["removed"].flatMap { if case .number(let n) = $0 { return Int(n) }; return nil },
        binary: row.flag("binary"))
    }
    fileCount = raw["file_count"] != nil ? Int(raw.number("file_count")) : files.count
    added = Int(raw.number("added"))
    removed = Int(raw.number("removed"))
    canRestore = raw.flag("can_restore")
    restoreReason = raw.text("restore_reason")
    laterTurns = Int(raw.number("later_turns"))
    conflicts = (raw["conflicts"]?.array ?? []).map(\.text)
  }

  var headline: String {
    "\(fileCount) file\(fileCount == 1 ? "" : "s") changed"
  }
}

/// Inline per-turn changed files card with one-tap Review and guarded Undo this turn.
struct CompanionTurnChangesCard: View {
  let project: String
  let job: String
  var status: String = ""
  var active: Bool = false
  var onRestored: () -> Void = {}
  @EnvironmentObject private var store: CompanionStore
  @State private var summary: CompanionTurnChanges?
  @State private var expanded = false
  @State private var undoing = false
  @State private var confirmUndo = false
  @State private var checkpointRevision = ""
  @State private var issue = ""

  private var canUndo: Bool {
    guard let summary, summary.canRestore, !summary.live, !active, !undoing else { return false }
    return store.canMutate && store.permissions.contains("restore") && store.features.flag("checkpoint_restore")
  }

  var body: some View {
    Group {
      if let summary, summary.available, summary.fileCount > 0 {
        card(summary)
      }
    }
    .task(id: "\(project):\(job):\(status)") {
      await load()
    }
  }

  private func card(_ summary: CompanionTurnChanges) -> some View {
    let shown = expanded ? summary.files : Array(summary.files.prefix(4))
    let hidden = max(0, summary.fileCount - shown.count)
    return CompanionCard {
      HStack(spacing: 8) {
        Image(systemName: "doc.on.doc").foregroundStyle(.secondary)
        Text(summary.headline).font(.subheadline.weight(.semibold))
        lineCounts(added: summary.added, removed: summary.removed)
        if summary.live {
          Text("updating").font(.caption2).foregroundStyle(.secondary)
        }
        Spacer(minLength: 0)
      }

      ScrollView(.horizontal, showsIndicators: false) {
        HStack(spacing: 8) {
          ForEach(shown) { file in
            NavigationLink {
              ProjectReviewScreen(project: project, job: job, preferredPath: file.path)
            } label: {
              HStack(spacing: 5) {
                Image(systemName: icon(file.change)).font(.caption2).foregroundStyle(.secondary)
                Text(file.name).lineLimit(1)
                lineCounts(added: file.added, removed: file.removed)
              }
              .font(.caption)
              .padding(.horizontal, 10)
              .padding(.vertical, 6)
              .background(CompanionTheme.background, in: Capsule())
              .overlay(Capsule().strokeBorder(Color.primary.opacity(0.12)))
            }
            .buttonStyle(.plain)
            .disabled(summary.live)
          }
          if hidden > 0 && !expanded {
            Button("+\(hidden) more") { expanded = true }
              .font(.caption.weight(.medium))
              .foregroundStyle(CompanionTheme.accent)
          } else if expanded && summary.files.count > 4 {
            Button("Show fewer") { expanded = false }
              .font(.caption.weight(.medium))
              .foregroundStyle(.secondary)
          }
        }
      }

      if !summary.live {
        HStack(spacing: 16) {
          NavigationLink {
            ProjectReviewScreen(project: project, job: job)
          } label: {
            Label("Review turn", systemImage: "text.magnifyingglass")
          }
          .font(.caption.weight(.semibold))

          Spacer(minLength: 8)

          if summary.canRestore || !summary.restoreReason.isEmpty {
            Button(role: .destructive) {
              Task { await prepareUndo() }
            } label: {
              Label(undoing ? "Undoing…" : "Undo turn", systemImage: "arrow.uturn.backward")
            }
            .font(.caption.weight(.semibold))
            .disabled(!canUndo)
          }
        }
      }

      if !summary.canRestore && !summary.live && !summary.restoreReason.isEmpty {
        Text(summary.restoreReason).font(.caption2).foregroundStyle(.secondary)
      } else if summary.canRestore && !summary.live && !store.isPreview && !store.permissions.contains("restore") {
        Text("Allow checkpoint restoration when pairing this \(CompanionDevice.name) on your Mac to undo turns.")
          .font(.caption2).foregroundStyle(.secondary)
      }
      if !issue.isEmpty {
        Text(issue).font(.caption).foregroundStyle(CompanionTheme.warning)
      }
    }
    .confirmationDialog("Undo this turn?", isPresented: $confirmUndo, titleVisibility: .visible) {
      Button("Undo turn", role: .destructive) {
        Task { await executeUndo(summary) }
      }
    } message: {
      Text(undoConfirmationMessage(summary))
    }
  }

  private func undoConfirmationMessage(_ summary: CompanionTurnChanges) -> String {
    let listed = summary.files.prefix(6).map { "• " + $0.path }.joined(separator: "\n")
    var message = "Restores the files changed by this turn:\n" + listed
    if summary.fileCount > 6 { message += "\n…and \(summary.fileCount - 6) more" }
    message += "\n\nIf any file changed after this turn, your Mac refuses the undo so newer edits are never overwritten."
    return message
  }

  @ViewBuilder
  private func lineCounts(added: Int?, removed: Int?) -> some View {
    HStack(spacing: 3) {
      if let added { Text("+\(added)").foregroundStyle(.green) }
      if let removed { Text("-\(removed)").foregroundStyle(.red) }
    }
    .font(.caption2.monospaced())
  }

  private func icon(_ change: String) -> String {
    switch change {
    case "added": return "plus"
    case "deleted": return "minus"
    default: return "pencil"
    }
  }

  private func load() async {
    guard !project.isEmpty, !job.isEmpty, store.features.flag("turn_changes"), let api = store.api else { return }
    do {
      let raw = try await api.rpc("turns.changes", ["project": .string(project), "job": .string(job)]).object
      try Task.checkCancellation()
      let next = CompanionTurnChanges(raw)
      if summary != next { summary = next }
    } catch { }
  }

  private func prepareUndo() async {
    guard let api = store.api, canUndo else { return }
    undoing = true; issue = ""
    defer { undoing = false }
    do {
      let snap = try await api.rpc("checkpoints.list", ["project": .string(project)]).object
      let rev = snap.text("revision")
      guard !rev.isEmpty else {
        issue = "Could not verify checkpoint state. Inspect checkpoints before undoing."
        return
      }
      checkpointRevision = rev
      confirmUndo = true
    } catch {
      issue = error.localizedDescription
    }
  }

  private func executeUndo(_ summary: CompanionTurnChanges) async {
    guard let api = store.api, !summary.checkpoint.isEmpty, !checkpointRevision.isEmpty else { return }
    undoing = true; issue = ""
    defer { undoing = false }
    do {
      _ = try await api.rpc(
        "checkpoints.restore",
        [
          "project": .string(project),
          "id": .string(summary.checkpoint),
          "revision": .string(checkpointRevision),
        ],
        key: "undo-turn:" + job + ":" + UUID().uuidString)
      CompanionHaptics.notify(.success)
      await load()
      onRestored()
    } catch {
      issue = error.localizedDescription
    }
  }
}
