import AppKit
import SwiftUI

struct ReviewLine: Equatable, Identifiable {
  let id: Int
  let old: Int?
  let new: Int?
  let text: String
  let kind: String
}

func reviewLines(_ patch: String) -> [ReviewLine] {
  var old = 0, new = 0
  var inHunk = false
  return patch.components(separatedBy: "\n").enumerated().map { index, line in
    if line.hasPrefix("@@ ") {
      let parts = line.split(separator: " ")
      if parts.count >= 3 {
        old = Int(parts[1].dropFirst().split(separator: ",").first ?? "") ?? 0
        new = Int(parts[2].dropFirst().split(separator: ",").first ?? "") ?? 0
      }
      inHunk = true
      return ReviewLine(id: index, old: nil, new: nil, text: line, kind: "meta")
    }
    guard inHunk, !line.hasPrefix("\\"), !line.isEmpty else {
      return ReviewLine(id: index, old: nil, new: nil, text: line, kind: "meta")
    }
    if line.hasPrefix("+") {
      defer { new += 1 }
      return ReviewLine(id: index, old: nil, new: new, text: String(line.dropFirst()), kind: "added")
    }
    if line.hasPrefix("-") {
      defer { old += 1 }
      return ReviewLine(id: index, old: old, new: nil, text: String(line.dropFirst()), kind: "removed")
    }
    guard line.hasPrefix(" ") else {
      return ReviewLine(id: index, old: nil, new: nil, text: line, kind: "meta")
    }
    defer { old += 1; new += 1 }
    return ReviewLine(id: index, old: old, new: new, text: String(line.dropFirst()), kind: "context")
  }
}

struct ReviewPair: Identifiable {
  let id: Int
  let left: ReviewLine?
  let right: ReviewLine?
}

func pairedReviewLines(_ lines: [ReviewLine]) -> [ReviewPair] {
  var pairs: [ReviewPair] = []
  var index = 0
  while index < lines.count {
    let line = lines[index]
    if line.kind == "removed" || line.kind == "added" {
      var removed: [ReviewLine] = [], added: [ReviewLine] = []
      while index < lines.count && lines[index].kind == "removed" { removed.append(lines[index]); index += 1 }
      while index < lines.count && lines[index].kind == "added" { added.append(lines[index]); index += 1 }
      for n in 0..<max(removed.count, added.count) {
        pairs.append(ReviewPair(id: pairs.count, left: n < removed.count ? removed[n] : nil, right: n < added.count ? added[n] : nil))
      }
    } else {
      pairs.append(ReviewPair(id: pairs.count, left: line, right: line)); index += 1
    }
  }
  return pairs
}

struct ChangeReviewView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  @State private var scope = "working"
  @State private var base = "main"
  @State private var appliedBase = "main"
  @State private var files: [[String: Any]] = []
  @State private var selected = ""
  @State private var patch = ""
  @State private var binary = false
  @State private var hidden = 0
  @State private var failure = ""
  @State private var loading = false
  @State private var changing = false
  @State private var revision = 0
  @State private var layout = "Unified"
  @State private var search = ""
  @State private var match = 0
  @State private var commit = ""
  @State private var command = ""
  @State private var actions: [[String: Any]] = []
  private var rows: [ReviewLine] { reviewLines(patch) }
  private var row: [String: Any] { files.first { string($0, "path") == selected } ?? [:] }
  private var matches: [Int] { search.isEmpty ? [] : rows.filter { $0.text.localizedCaseInsensitiveContains(search) }.map(\.id) }
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Label("Review changes", systemImage: "doc.text.magnifyingglass").font(.title2.weight(.semibold))
        Spacer()
        Text(string(app.project, "name")).foregroundStyle(.secondary)
        nativeButton("review.done", action: { dismiss() }, title: "Close change review") { Text("Done") }
      }
      HStack {
        Picker("Compare", selection: $scope) {
          Text("All working changes").tag("working")
          Text("Staged").tag("staged")
          Text("Unstaged tracked files").tag("unstaged")
          Text("Branch commits").tag("branch")
        }.frame(width: 300)
        if scope == "branch" {
          TextField("Base branch or commit", text: $base).textFieldStyle(.roundedBorder).frame(width: 180)
          Button("Compare") { appliedBase = base; revision += 1 }
        }
        Spacer()
        Picker("Diff layout", selection: $layout) {
          Text("Unified").tag("Unified"); Text("Side by side").tag("Split")
        }.pickerStyle(.segmented).labelsHidden().frame(width: 210)
        Button("Refresh") { revision += 1 }.disabled(loading)
      }
      if scope == "branch" {
        Text("Committed changes from the merge base to HEAD. Working edits are excluded.").font(.caption).foregroundStyle(.secondary)
      } else {
        Text("Project changes can include your edits and earlier work. They are not automatically attributed to this agent.").font(.caption).foregroundStyle(.secondary)
      }
      if !failure.isEmpty { Label(failure, systemImage: "exclamationmark.triangle").foregroundStyle(.orange).textSelection(.enabled) }
      HSplitView {
        VStack(alignment: .leading, spacing: 8) {
          Text("\(files.count) changed files").font(.caption.weight(.medium))
          List(selection: $selected) {
            ForEach(files, id: \.reviewPath) { file in
              VStack(alignment: .leading, spacing: 3) {
                Text(string(file, "path")).font(.system(size: 12, design: .monospaced))
                Text(file["exists"] as? Bool == false ? "Deleted" : file["staged"] as? Bool == true ? "Has staged changes" : "Working changes")
                  .font(.caption2).foregroundStyle(.secondary)
              }.tag(string(file, "path"))
            }
          }.scrollContentBackground(.hidden)
          if hidden > 0 { Text("\(hidden) private or external paths hidden").font(.caption).foregroundStyle(.secondary) }
        }.frame(minWidth: 180, idealWidth: 230, maxWidth: 300)
        VStack(alignment: .leading, spacing: 8) {
          HStack {
            Text(selected.isEmpty ? "Choose a changed file" : selected).font(.caption.monospaced()).textSelection(.enabled)
            Spacer()
            Button("Open file") {
              app.requestedFile = selected; app.section = "Files"; dismiss()
            }.disabled(selected.isEmpty || row["exists"] as? Bool != true)
            Button("Ask agent") { ask(nil) }.disabled(selected.isEmpty)
            Button("Copy diff") { NSPasteboard.general.clearContents(); NSPasteboard.general.setString(patch, forType: .string) }.disabled(patch.isEmpty)
          }
          HStack {
            TextField("Find in this diff", text: $search).textFieldStyle(.roundedBorder)
            if !search.isEmpty {
              Text("\(matches.isEmpty ? 0 : match % matches.count + 1)/\(matches.count)").font(.caption.monospacedDigit())
              Button { match = max(0, match - 1) } label: { Image(systemName: "chevron.up") }.accessibilityLabel("Previous match")
              Button { match += 1 } label: { Image(systemName: "chevron.down") }.accessibilityLabel("Next match")
            }
          }
          if loading { ProgressView().controlSize(.small) }
          if binary {
            EmptyState(icon: "doc", title: "Binary file", detail: "Text comparison is unavailable. Review it in the appropriate application.")
          } else {
            diffBody.frame(maxWidth: .infinity, maxHeight: .infinity)
          }
          HStack {
            Button("Stage file") { mutate("git.stage_file") }
              .disabled(selected.isEmpty || app.projectActive || changing || scope == "branch")
            Button("Unstage file") { mutate("git.unstage_file") }
              .disabled(selected.isEmpty || row["staged"] as? Bool != true || app.projectActive || changing || scope == "branch")
            Spacer()
            TextField("Commit message · all staged changes", text: $commit).textFieldStyle(.roundedBorder)
            Button("Commit staged…") { commitStaged() }.disabled(commit.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || app.projectActive || changing)
          }
        }.padding(.leading, 12).frame(minWidth: 580)
      }
      Divider()
      HStack {
        if !actions.isEmpty {
          Menu("Project actions") {
            ForEach(actions, id: \.reviewAction) { action in
              Button(string(action, "name") + " · " + string(action, "command")) { command = string(action, "command") }
            }
          }
        }
        TextField("Check command, e.g. npm test or uv run pytest", text: $command).textFieldStyle(.roundedBorder)
        Button("Run check…") {
          guard app.confirm("Run this project check?", command, button: "Run check") else { return }
          app.start("checks.start", extra: ["command": command, "source_job": string(app.detail, "kind") == "task" ? app.selectedJob : ""]); dismiss()
        }.disabled(command.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || app.projectActive || app.busy)
        Text("Runs on your Mac").font(.caption).foregroundStyle(.secondary)
      }
    }.padding(20).frame(width: 1020, height: 650).background(Color.qPanel)
      .task(id: app.projectID) {
        do { actions = try await app.engine.call("project.actions", ["project": app.projectID]) as? [[String: Any]] ?? [] }
        catch { actions = [] }
      }
      .task(id: "\(app.projectID):\(scope):\(appliedBase):\(revision)") { await loadFiles() }
      .task(id: "\(app.projectID):\(scope):\(appliedBase):\(selected):\(revision)") { await loadDiff() }
  }
  private var diffBody: some View {
    ScrollViewReader { proxy in
      ScrollView {
        LazyVStack(alignment: .leading, spacing: 0) {
          if patch.isEmpty && !loading { Text("No text changes in this scope.").foregroundStyle(.secondary).padding() }
          if layout == "Split" {
            ForEach(pairedReviewLines(rows)) { pair in
              HStack(alignment: .top, spacing: 0) {
                lineView(pair.left, old: true).frame(maxWidth: .infinity, alignment: .leading)
                Divider()
                lineView(pair.right, old: false).frame(maxWidth: .infinity, alignment: .leading)
              }.fixedSize(horizontal: false, vertical: true).id(pair.right?.id ?? pair.left?.id ?? -1)
            }
          } else {
            ForEach(rows) { row in lineView(row, old: false).id(row.id) }
          }
        }
      }.outlinedSurface(radius: 8)
        .onChange(of: search) { _, _ in match = 0; revealMatch(proxy) }
        .onChange(of: match) { _, _ in revealMatch(proxy) }
    }
  }
  @ViewBuilder private func lineView(_ row: ReviewLine?, old: Bool) -> some View {
    if let row {
      HStack(alignment: .top, spacing: 8) {
        Text(layout == "Split" ? (old ? row.old : row.new).map(String.init) ?? "" : "\(row.old.map(String.init) ?? "") \(row.new.map(String.init) ?? "")")
          .foregroundStyle(.secondary).frame(width: layout == "Split" ? 38 : 65, alignment: .trailing)
        Text(row.text.isEmpty ? " " : row.text).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
      }.font(.system(size: 12, design: .monospaced)).padding(.vertical, 3).padding(.horizontal, 6)
        .background(!search.isEmpty && row.text.localizedCaseInsensitiveContains(search) ? Color.yellow.opacity(0.20)
          : row.kind == "added" ? Color.green.opacity(0.12) : row.kind == "removed" ? Color.red.opacity(0.12) : .clear)
        .contextMenu { Button("Ask agent about this line") { ask(row) } }
    } else { Text(" ").font(.system(size: 12, design: .monospaced)).frame(maxWidth: .infinity) }
  }
  private func revealMatch(_ proxy: ScrollViewProxy) {
    guard !matches.isEmpty else { return }
    let target = matches[match % matches.count]
    if layout == "Split", let pair = pairedReviewLines(rows).first(where: { $0.left?.id == target || $0.right?.id == target }) {
      proxy.scrollTo(pair.right?.id ?? pair.left?.id ?? -1, anchor: .center)
    } else { proxy.scrollTo(target, anchor: .center) }
  }
  private func loadFiles() async {
    failure = ""
    do {
      let data = try await app.engine.call("git.review", ["project": app.projectID, "scope": scope, "base": appliedBase]) as? [String: Any] ?? [:]
      guard !Task.isCancelled else { return }
      files = data["files"] as? [[String: Any]] ?? []; hidden = data["hidden"] as? Int ?? 0
      if !files.contains(where: { string($0, "path") == selected }) { selected = files.first.map { string($0, "path") } ?? "" }
    } catch { if !Task.isCancelled { failure = error.localizedDescription; files = []; selected = "" } }
  }
  private func loadDiff() async {
    patch = ""; binary = false; search = ""; loading = false
    guard !selected.isEmpty else { return }
    failure = ""; loading = true
    defer { if !Task.isCancelled { loading = false } }
    do {
      let data = try await app.engine.call("git.review", ["project": app.projectID, "scope": scope, "base": appliedBase, "path": selected]) as? [String: Any] ?? [:]
      guard !Task.isCancelled else { return }
      patch = string(data, "diff"); binary = data["binary"] as? Bool == true
    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
  }
  private func ask(_ row: ReviewLine?) {
    let excerpt = row.map { "Line \($0.new ?? $0.old ?? 0): " + $0.text } ?? String(patch.prefix(12000))
    let context = "Please review this \(scope) change in \(selected):\n\n```diff\n\(excerpt)\n```"
    app.draft = app.draft.isEmpty ? context : app.draft + "\n\n" + context
    app.section = "Workspace"; dismiss()
  }
  private func mutate(_ method: String) {
    guard app.confirm(method == "git.stage_file" ? "Stage this file?" : "Unstage this file?", selected, button: "Continue") else { return }
    changing = true
    app.perform {
      defer { changing = false }
      do {
        _ = try await app.engine.call(method, ["project": app.projectID, "path": selected])
        await app.refreshGit(); revision += 1
      } catch { failure = error.localizedDescription }
    }
  }
  private func commitStaged() {
    guard app.confirm("Commit all staged changes?", "This creates a local commit from the entire Git index.\n\n" + commit, button: "Create commit") else { return }
    changing = true
    app.perform {
      defer { changing = false }
      do {
        _ = try await app.engine.call("git.commit", ["project": app.projectID, "message": commit])
        commit = ""; await app.refreshGit(); revision += 1
      } catch { failure = error.localizedDescription }
    }
  }
}

extension Dictionary where Key == String, Value == Any {
  var reviewPath: String { string(self, "path") }
  var reviewAction: String { string(self, "command") }
}
