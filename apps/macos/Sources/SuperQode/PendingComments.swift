import SwiftUI

/// A review comment waiting to be sent to the agent as one follow-up.
struct PendingComment: Codable, Identifiable, Equatable {
  var id = UUID().uuidString
  var path: String
  /// For example "L12-18" in the new file, or "hunk @@ -10,4 +10,6 @@".
  var lines: String
  var excerpt: String
  var text: String
  /// Engine-formatted feedback, when the comment came from the review workspace.
  var formatted = ""

  var promptBlock: String {
    if !formatted.isEmpty { return formatted }
    var block = "\(path) \(lines)"
    if !excerpt.isEmpty { block += "\n```diff\n\(excerpt)\n```" }
    return block + "\n" + text
  }
}

/// Pending comments per thread, kept across launches until sent or cleared.
@MainActor final class PendingCommentStore: ObservableObject {
  private static let key = "nativePendingReviewComments"
  @Published private(set) var byThread: [String: [PendingComment]] = [:]
  private let defaults: UserDefaults

  init(defaults: UserDefaults = .standard) {
    self.defaults = defaults
    if let data = defaults.data(forKey: Self.key),
      let saved = try? JSONDecoder().decode([String: [PendingComment]].self, from: data) {
      byThread = saved
    }
  }

  func comments(_ thread: String) -> [PendingComment] { byThread[thread] ?? [] }

  func add(_ comment: PendingComment, thread: String) {
    guard !thread.isEmpty else { return }
    byThread[thread, default: []].append(comment)
    save()
  }

  func remove(_ id: String, thread: String) {
    byThread[thread]?.removeAll { $0.id == id }
    if byThread[thread]?.isEmpty == true { byThread.removeValue(forKey: thread) }
    save()
  }

  /// Removes the sent comments only, keeping any added while sending.
  func remove(ids: Set<String>, thread: String) {
    byThread[thread]?.removeAll { ids.contains($0.id) }
    if byThread[thread]?.isEmpty == true { byThread.removeValue(forKey: thread) }
    save()
  }

  func clear(_ thread: String) {
    byThread.removeValue(forKey: thread)
    save()
  }

  static func prompt(_ comments: [PendingComment]) -> String {
    let blocks = comments.enumerated().map { index, comment in "\(index + 1). " + comment.promptBlock }
    return "Please address these review comments:\n\n" + blocks.joined(separator: "\n\n")
  }

  private func save() {
    if let data = try? JSONEncoder().encode(byThread) { defaults.set(data, forKey: Self.key) }
  }
}

extension Workspace {
  /// Moves a thread's pending comments into a follow-up. Sends right away when
  /// the agent is idle and the message box is empty; otherwise adds them to the
  /// message box so they go with the next message once the current run finishes.
  /// `thread` is the thread the comments were written for, captured when the
  /// diff or tray opened; nothing is sent if another thread is now in view.
  func sendPendingComments(thread requested: String? = nil) {
    let thread = requested ?? composerKey
    let comments = pendingComments.comments(thread)
    guard !comments.isEmpty else { return }
    guard thread == composerKey else {
      notice = "These comments belong to another thread. Open that thread to send them."
      return
    }
    let text = PendingCommentStore.prompt(comments)
    if !active && !busy && connected && draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty {
      draft = text
      // Clear only once the engine accepted the follow-up. On failure the
      // comments stay pending and the message box is emptied again.
      send(continueSession: !selectedJob.isEmpty) { [weak self] accepted in
        guard let self else { return }
        if accepted {
          self.pendingComments.remove(ids: Set(comments.map(\.id)), thread: thread)
        } else if self.draft == text {
          self.draft = ""
          self.saveDraft(flush: false)
        }
      }
      if !busy {
        // send() declined before starting (for example no connected agent).
        if draft == text { draft = "" }
        notice = "Review comments were not sent. They are still pending."
      }
    } else {
      draft += (draft.isEmpty ? "" : "\n\n") + text
      saveDraft(flush: false)
      pendingComments.clear(thread)
      notice = active
        ? "Review comments are in your message box. Send them when the agent finishes."
        : "Review comments added to your message box."
    }
  }
}

/// Tray above the composer listing pending comments for this thread.
struct PendingCommentsTray: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var store: PendingCommentStore
  /// The thread captured when a diff sheet opened. Nil follows the composer.
  var thread: String? = nil
  @State private var expanded = false
  var body: some View {
    let thread = self.thread ?? app.composerKey
    let comments = store.comments(thread)
    if !comments.isEmpty {
      VStack(alignment: .leading, spacing: 6) {
        HStack(spacing: 8) {
          Image(systemName: "text.bubble").foregroundStyle(Color.qAccent)
          Button {
            expanded.toggle()
          } label: {
            Text("\(comments.count) review comment\(comments.count == 1 ? "" : "s") pending")
              .font(.caption.weight(.semibold))
          }.buttonStyle(.plain)
          Spacer(minLength: 0)
          Button("Clear") {
            if app.confirm("Clear pending review comments?", "Remove \(comments.count) unsent comment\(comments.count == 1 ? "" : "s") for this thread.", button: "Clear") {
              store.clear(thread)
            }
          }.font(.caption)
          Button(app.active ? "Add to message" : "Send comments to agent") { app.sendPendingComments(thread: thread) }
            .font(.caption).disabled(!app.connected || thread != app.composerKey)
            .help(app.active ? "The agent is working. Comments go into your message box to send next." : "Send all pending comments as one follow-up")
        }
        if expanded {
          ForEach(comments) { comment in
            HStack(alignment: .top, spacing: 6) {
              VStack(alignment: .leading, spacing: 2) {
                Text(comment.path + " " + comment.lines).font(.caption.monospaced()).foregroundStyle(.secondary).lineLimit(1)
                Text(comment.text.isEmpty ? comment.formatted : comment.text).font(.caption).lineLimit(3)
              }
              Spacer(minLength: 0)
              Button { store.remove(comment.id, thread: thread) } label: { Image(systemName: "xmark") }
                .buttonStyle(.plain).font(.caption2).help("Remove comment")
            }
          }
        }
      }
      .padding(8)
      .background(Color.qAccent.opacity(0.06), in: RoundedRectangle(cornerRadius: 6))
    }
  }
}

/// Hunk-by-hunk diff with a comment affordance on each hunk.
struct CommentableDiff: View {
  let document: ReviewDocument
  /// The thread the diff was opened for. Comments always attach to it, even if
  /// background updates change the visible thread while the sheet is open.
  let thread: String
  @EnvironmentObject var app: Workspace
  @State private var commenting: Int?
  @State private var text = ""
  var body: some View {
    ScrollView([.vertical]) {
      LazyVStack(alignment: .leading, spacing: 10) {
        ForEach(document.hunks) { hunk in
          VStack(alignment: .leading, spacing: 0) {
            HStack {
              Text(hunk.header).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
              Spacer()
              Button { commenting = commenting == hunk.id ? nil : hunk.id; text = "" } label: {
                Label("Comment", systemImage: "text.bubble")
              }.buttonStyle(.plain).font(.caption)
            }.padding(.horizontal, 8).padding(.vertical, 4).background(Color.primary.opacity(0.05))
            ScrollView(.horizontal) {
              VStack(alignment: .leading, spacing: 0) {
                ForEach(hunk.lines) { line in
                  Text(line.marker + line.text)
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(line.kind == "add" ? Color.green : line.kind == "delete" ? Color.red : Color.primary)
                    .fixedSize(horizontal: true, vertical: false)
                    .textSelection(.enabled)
                }
              }.padding(8)
            }
            if commenting == hunk.id {
              VStack(alignment: .leading, spacing: 6) {
                TextEditor(text: $text).font(.system(size: 12)).frame(height: 60)
                  .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.primary.opacity(0.12)))
                HStack {
                  Text("Lines " + lineRange(hunk)).font(.caption).foregroundStyle(.secondary)
                  Spacer()
                  Button("Cancel") { commenting = nil; text = "" }
                  Button("Add comment") { add(hunk) }
                    .disabled(text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || text.count > 4000)
                }.font(.caption)
              }.padding(8)
            }
          }
          .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.primary.opacity(0.08)))
        }
      }.padding(2)
    }
  }

  private func lineRange(_ hunk: ReviewHunk) -> String {
    let lines = hunk.lines.compactMap { $0.newLine ?? $0.oldLine }
    guard let first = lines.first, let last = lines.last else { return hunk.header }
    return first == last ? "L\(first)" : "L\(first)-\(last)"
  }

  private func add(_ hunk: ReviewHunk) {
    let changed = hunk.lines.filter { $0.kind == "add" || $0.kind == "delete" }.prefix(12)
    let excerpt = changed.map { ($0.kind == "add" ? "+" : "-") + $0.text }.joined(separator: "\n")
    app.pendingComments.add(
      PendingComment(path: document.path, lines: lineRange(hunk), excerpt: excerpt,
        text: text.trimmingCharacters(in: .whitespacesAndNewlines)),
      thread: thread)
    commenting = nil
    text = ""
  }
}
