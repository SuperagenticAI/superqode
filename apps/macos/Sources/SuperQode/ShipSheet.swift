import AppKit
import SwiftUI

/// Rules for the commit sheet, kept free of view state so they can be tested.
enum ShipRules {
  /// SuperQode project state (checkpoints, work orders, drafts) is never offered
  /// for commit, even if an older engine lists it.
  static func isPrivate(_ path: String) -> Bool {
    path.split(separator: "/").contains { $0 == ".superqode" || $0.hasPrefix(".superqode-") }
  }

  /// A drafted message may replace the text only when the box is empty or still
  /// holds the previous draft unchanged. Typed text is never overwritten.
  static func mayApplyDraft(current: String, lastDraft: String) -> Bool {
    current.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || (!lastDraft.isEmpty && current == lastDraft)
  }
}

/// Commit, push and open a pull request with the user's own Git setup.
struct ShipSheet: View {
  /// Files the turn changed; preselected when they still have changes.
  let turnFiles: [String]
  let prompt: String
  var close: () -> Void
  @EnvironmentObject var app: Workspace
  @State private var status: [String: Any] = [:]
  @State private var files: [[String: Any]] = []
  @State private var selected: Set<String> = []
  @State private var message = ""
  /// The last message drafted automatically, to tell it apart from typed text.
  @State private var lastDraft = ""
  /// The project when the sheet opened. Git actions never follow navigation.
  @State private var project = ""
  @State private var newBranch = ""
  @State private var working = false
  @State private var failure = ""
  @State private var notice = ""
  @State private var loaded = false
  @State private var committedSha = ""
  @State private var prTitle = ""
  @State private var prBody = ""
  @State private var prBase = ""
  @State private var prDraft = true
  @State private var prURL = ""

  private var branch: String { string(status, "branch") }
  private var upstream: String { string(status, "upstream") }
  private var ahead: Int { status["ahead"] as? Int ?? 0 }
  private var behind: Int { status["behind"] as? Int ?? 0 }
  private var remotes: [String] { status["remotes"] as? [String] ?? [] }
  private var onDefault: Bool { status["on_default_branch"] as? Bool ?? false }
  private var ghInstalled: Bool { status["gh_installed"] as? Bool ?? false }
  private var ghReady: Bool { status["gh_ready"] as? Bool ?? false }
  private var projectID: String { project.isEmpty ? app.projectID : project }
  private var busy: Bool { working || app.hasActiveWork(project: projectID) }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Text("Commit changes").font(.headline)
        Spacer()
        Button("Close", action: close).keyboardShortcut(.cancelAction)
      }
      if !loaded {
        ProgressView("Reading Git status…").font(.caption)
      } else {
        branchLine
        if branch.isEmpty || onDefault { createBranchRow }
        fileList
        Text("Message").font(.caption.weight(.semibold))
        TextEditor(text: $message).font(.system(size: 13)).frame(minHeight: 80, maxHeight: 140)
          .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.primary.opacity(0.12)))
        HStack {
          Button("Draft message") { draft() }.disabled(selected.isEmpty || working)
            .help("Writes a summary from this turn's prompt and the selected files. Text you typed is kept.")
          Spacer()
          if ahead > 0 || (upstream.isEmpty && !committedSha.isEmpty && !remotes.isEmpty) {
            Button("Push") { push() }.disabled(busy || branch.isEmpty)
          }
          Button("Commit") { commit(andPush: false) }.disabled(!canCommit)
          Button("Commit and Push") { commit(andPush: true) }.disabled(!canCommit || remotes.isEmpty)
            .keyboardShortcut(.defaultAction)
        }
        if app.hasActiveWork(project: projectID) {
          Text("Finish or stop the active run before committing.").font(.caption).foregroundStyle(.orange)
        }
        if !committedSha.isEmpty || ahead > 0 { prSection }
      }
      if !notice.isEmpty { Text(notice).font(.caption).foregroundStyle(.secondary).textSelection(.enabled) }
      if !failure.isEmpty {
        ScrollView { Text(failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading) }
          .frame(maxHeight: 120)
      }
      if working { ProgressView().controlSize(.small) }
    }
    .padding(18).frame(width: 640).frame(minHeight: 420)
    .task {
      if project.isEmpty { project = app.projectID }
      await load(draftMessage: true)
    }
  }

  private var canCommit: Bool {
    !busy && !selected.isEmpty && !message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && !branch.isEmpty
  }

  private var branchLine: some View {
    VStack(alignment: .leading, spacing: 4) {
      HStack(spacing: 8) {
        Image(systemName: "arrow.triangle.branch").foregroundStyle(.secondary)
        Text(branch.isEmpty ? "Detached HEAD" : branch).font(.callout.monospaced())
        if !upstream.isEmpty {
          Text("→ " + upstream).font(.caption.monospaced()).foregroundStyle(.secondary)
          if ahead > 0 { Text("↑\(ahead)").font(.caption.monospaced()) }
          if behind > 0 { Text("↓\(behind)").font(.caption.monospaced()).foregroundStyle(.orange) }
        } else if !branch.isEmpty {
          Text(remotes.isEmpty ? "no remote" : "no upstream yet").font(.caption).foregroundStyle(.secondary)
        }
      }
      if onDefault {
        Label("You are on the default branch. Pushing here updates it directly.", systemImage: "exclamationmark.triangle")
          .font(.caption).foregroundStyle(.orange)
      }
      if behind > 0 {
        Text("The remote has \(behind) commit\(behind == 1 ? "" : "s") you do not have. Pull in Terminal before pushing.")
          .font(.caption).foregroundStyle(.orange)
      }
    }
  }

  private var createBranchRow: some View {
    HStack {
      TextField(branch.isEmpty ? "New branch name" : "Optional: new branch for this work", text: $newBranch).textFieldStyle(.roundedBorder)
      Button("Create branch") { createBranch() }.disabled(newBranch.isEmpty || busy)
    }
  }

  private var fileList: some View {
    VStack(alignment: .leading, spacing: 4) {
      HStack {
        Text("\(selected.count) of \(files.count) changed file\(files.count == 1 ? "" : "s") selected").font(.caption.weight(.semibold))
        Spacer()
        Button("All") { selected = Set(files.map { string($0, "path") }) }.buttonStyle(.plain).font(.caption)
        Button("This turn") { selectTurn() }.buttonStyle(.plain).font(.caption)
        Button("None") { selected = [] }.buttonStyle(.plain).font(.caption)
      }
      ScrollView {
        LazyVStack(alignment: .leading, spacing: 2) {
          ForEach(files.map { string($0, "path") }, id: \.self) { path in
            Toggle(isOn: Binding(get: { selected.contains(path) }, set: { on in
              if on { selected.insert(path) } else { selected.remove(path) }
            })) {
              HStack(spacing: 6) {
                Text(code(path)).font(.caption.monospaced()).foregroundStyle(.secondary).frame(width: 22, alignment: .leading)
                Text(path).font(.system(size: 12)).lineLimit(1).truncationMode(.middle)
              }
            }.toggleStyle(.checkbox)
          }
        }
      }.frame(height: min(180, CGFloat(max(files.count, 1)) * 22))
      if files.isEmpty { Text("No uncommitted changes.").font(.caption).foregroundStyle(.secondary) }
    }
  }

  @ViewBuilder private var prSection: some View {
    Divider()
    if !ghInstalled {
      Text("To open pull requests from here, install the GitHub CLI and run gh auth login in Terminal.")
        .font(.caption).foregroundStyle(.secondary)
    } else if !ghReady {
      Text("The GitHub CLI is installed but not signed in. Run gh auth login in Terminal to create pull requests here.")
        .font(.caption).foregroundStyle(.secondary)
    } else if upstream.isEmpty {
      Text("Push this branch to create a pull request.").font(.caption).foregroundStyle(.secondary)
    } else if !prURL.isEmpty {
      HStack {
        Label("Pull request ready", systemImage: "checkmark.circle").font(.callout)
        Button("Open") { if let url = URL(string: prURL) { NSWorkspace.shared.open(url) } }
        Text(prURL).font(.caption.monospaced()).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle).textSelection(.enabled)
      }
    } else {
      Text("Pull request").font(.caption.weight(.semibold))
      TextField("Title", text: $prTitle).textFieldStyle(.roundedBorder)
      TextEditor(text: $prBody).font(.system(size: 12)).frame(height: 70)
        .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.primary.opacity(0.12)))
      HStack {
        TextField("Base branch", text: $prBase).textFieldStyle(.roundedBorder).frame(width: 180)
        Toggle("Draft", isOn: $prDraft).toggleStyle(.checkbox)
        Spacer()
        Button("Create PR") { createPR() }.disabled(busy || prTitle.isEmpty || onDefault)
          .help(onDefault ? "Create a branch for this work before opening a pull request" : "Runs gh pr create with your GitHub CLI sign-in")
      }
    }
  }

  private func code(_ path: String) -> String {
    string(files.first { string($0, "path") == path } ?? [:], "code")
  }

  private func selectTurn() {
    let changed = Set(files.map { string($0, "path") })
    selected = Set(turnFiles).intersection(changed)
  }

  private func load(draftMessage: Bool) async {
    do {
      let result = try await app.engine.call("ship.status", ["project": projectID]) as? [String: Any] ?? [:]
      status = result
      files = (result["files"] as? [[String: Any]] ?? []).filter { !ShipRules.isPrivate(string($0, "path")) }
      if !loaded {
        selectTurn()
        if selected.isEmpty && turnFiles.isEmpty { selected = Set(files.map { string($0, "path") }) }
        prBase = string(result, "default_branch")
      }
      loaded = true
      if draftMessage && message.isEmpty && !selected.isEmpty { draft() }
    } catch {
      loaded = true
      failure = error.localizedDescription
    }
  }

  private func draft() {
    let paths = Array(selected).sorted()
    let project = projectID
    Task {
      do {
        let result = try await app.engine.call("ship.draft_message", ["project": project, "paths": paths, "prompt": prompt]) as? [String: Any] ?? [:]
        let drafted = string(result, "message")
        // Checked when the draft arrives, so typing while it loads wins.
        if ShipRules.mayApplyDraft(current: message, lastDraft: lastDraft) {
          message = drafted
          lastDraft = drafted
        } else {
          notice = "Your message was kept. Clear it to use a drafted one."
        }
      } catch { failure = error.localizedDescription }
    }
  }

  private func run(_ body: @escaping () async throws -> Void) {
    working = true; failure = ""; notice = ""
    Task {
      defer { working = false }
      do { try await body() } catch { failure = error.localizedDescription }
      await load(draftMessage: false)
      await app.refreshGit()
    }
  }

  private func confirmPushIfNeeded() -> Bool {
    guard onDefault else { return true }
    return app.confirm("Push to \(branch)?",
      "This is the repository's default branch. The push updates it directly for everyone. SuperQode never force pushes.",
      button: "Push to \(branch)")
  }

  private func commit(andPush: Bool) {
    if andPush && !confirmPushIfNeeded() { return }
    let paths = Array(selected).sorted()
    let text = message
    let project = projectID
    run {
      let result = try await app.engine.call("ship.commit", ["project": project, "paths": paths, "message": text]) as? [String: Any] ?? [:]
      committedSha = string(result, "sha")
      notice = "Committed " + committedSha + "."
      let subject = text.split(separator: "\n", maxSplits: 1).first.map(String.init) ?? text
      if prTitle.isEmpty { prTitle = subject }
      if prBody.isEmpty { prBody = text.split(separator: "\n", maxSplits: 1).dropFirst().joined().trimmingCharacters(in: .whitespacesAndNewlines) }
      if message == text { message = ""; lastDraft = "" }
      if andPush { try await pushNow() }
    }
  }

  private func push() {
    guard confirmPushIfNeeded() else { return }
    run { try await pushNow() }
  }

  private func pushNow() async throws {
    _ = try await app.engine.call("ship.push", ["project": projectID, "set_upstream": upstream.isEmpty])
    notice += (notice.isEmpty ? "" : " ") + (upstream.isEmpty ? "Pushed and set upstream." : "Pushed.")
  }

  private func createBranch() {
    let name = newBranch
    run {
      _ = try await app.engine.call("ship.create_branch", ["project": projectID, "name": name])
      notice = "Switched to new branch " + name + "."
      newBranch = ""
    }
  }

  private func createPR() {
    let params: [String: Any] = ["project": projectID, "title": prTitle, "body": prBody, "base": prBase, "draft": prDraft]
    run {
      let result = try await app.engine.call("ship.create_pr", params) as? [String: Any] ?? [:]
      prURL = string(result, "url")
      if let url = URL(string: prURL), !prURL.isEmpty { NSWorkspace.shared.open(url) }
    }
  }
}
