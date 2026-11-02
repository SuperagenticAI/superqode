import SwiftUI

struct ThreadForkView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  let source: String
  @State private var title = "Forked task"
  @State private var branch = "superqode/fork-" + String(UUID().uuidString.prefix(8)).lowercased()
  @State private var plan: [String: Any] = [:]
  @State private var failure = ""
  @State private var busy = false
  @State private var closed = false
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      PageTitle(eyebrow: "Explore independently", title: "Fork into a worktree",
        subtitle: "Start a separate working directory and Git branch with reviewed conversation context.")
      TextField("Task name", text: $title).textFieldStyle(.roundedBorder)
      TextField("New Git branch", text: $branch).textFieldStyle(.roundedBorder)
      Text("Files start at the source repository’s committed HEAD. Pending edits, ignored files, credentials and agent sessions are not copied.")
        .font(.callout).foregroundStyle(.secondary)
      Button("Review fork") {
        busy = true; failure = ""; plan = [:]
        Task {
          defer { busy = false }
          do {
            let result = try await app.engine.call("threads.fork.preview", ["project": project, "id": source, "title": title, "branch": branch]) as? [String: Any] ?? [:]
            guard !closed, app.projectID == project else { return }
            plan = result
          } catch { failure = error.localizedDescription }
        }
      }.disabled(busy || app.projectID != project)
      if busy { ProgressView(plan.isEmpty ? "Reading the repository and context…" : "Creating the fork workspace…") }
      if !plan.isEmpty {
        Label("Base commit · " + String(string(plan, "base_commit").prefix(12)), systemImage: "arrow.triangle.branch")
          .font(.caption.monospaced())
        if plan["source_dirty"] as? Bool == true {
          Text("The source has pending changes. This fork uses the committed files shown above.").font(.callout).foregroundStyle(.orange)
        }
        ScrollView {
          Text(string(plan, "context")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading).padding(12)
        }.brandSurface()
      } else { Spacer() }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      HStack {
        Button(busy && !plan.isEmpty ? "Close" : "Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
        Spacer()
        Button("Create fork workspace") {
          busy = true; failure = ""
          let reviewed = plan
          Task {
            defer { busy = false }
            do {
              let result = try await app.engine.call("threads.fork.create", ["project": project, "id": source,
                "title": string(reviewed, "title"), "branch": string(reviewed, "branch"),
                "fork_id": string(reviewed, "fork_id"), "expected_digest": string(reviewed, "digest")]) as? [String: Any] ?? [:]
              guard !closed, app.projectID == project else { return }
              dismiss()
              try await app.openForkWorkspace(result, includeContext: true)
            } catch { failure = error.localizedDescription }
          }
        }.buttonStyle(BrandButtonStyle()).disabled(busy || plan.isEmpty || app.projectID != project)
      }
      Text(busy && !plan.isEmpty ? "Creation continues if you close this window. The workspace will appear in the source thread library." : "Creating a fork does not send a prompt. Review and send its draft when ready.")
        .font(.caption).foregroundStyle(.secondary)
    }.padding(24).frame(width: 740, height: 620)
      .onChange(of: title) { _, _ in plan = [:] }
      .onChange(of: branch) { _, _ in plan = [:] }
      .onDisappear { closed = true }
  }
}

struct ForkWorkspaceBar: View {
  @EnvironmentObject var app: Workspace
  @State private var mergePlan: [String: Any]?
  var body: some View {
    if let fork = app.forkWorkspaces.first(where: { string($0, "project") == app.projectID }) {
      HStack(spacing: 12) {
        Label(string(fork, "branch"), systemImage: "arrow.triangle.branch").lineLimit(1)
        Text("Fork workspace").foregroundStyle(.secondary)
        Spacer()
        Button("Source thread") { app.perform { try await app.openForkSource(fork) } }
        Button("Review branch") {
          app.reviewSelection = ReviewSelection(scope: .branch, baseRef: string(fork, "base_commit"))
          app.section = "Review"
        }
        Button("Merge…") {
          app.perform { mergePlan = try await app.engine.call("threads.fork.merge.plan", ["id": string(fork, "id")]) as? [String: Any] }
        }.disabled(app.hasActiveWork(project: app.projectID) || app.hasActiveWork(project: string(fork, "source_project")) || app.busy)
      }.font(.caption).padding(.horizontal, 24).padding(.vertical, 10)
        .centeredDialog(isPresented: Binding(get: { mergePlan != nil }, set: { if !$0 { mergePlan = nil } }), title: "Review fork integration") {
          if let plan = mergePlan {
            VStack(alignment: .leading, spacing: 16) {
              Text("Merge into the source workspace").font(.title2)
              Text(string(plan, "message")).foregroundStyle(.secondary)
              Text("Source: " + String(string(plan, "source_head").prefix(12)) + "\nFork: " + String(string(plan, "fork_head").prefix(12)))
                .font(.callout.monospaced()).textSelection(.enabled)
              Text("Only a clean fast-forward is available here. Both workspaces and the fork branch remain after merging.")
                .font(.caption).foregroundStyle(.secondary)
              Button("Merge reviewed commits") {
                app.perform {
                  _ = try await app.engine.call("threads.fork.merge", ["id": string(plan, "id"), "expected_digest": string(plan, "digest")])
                  mergePlan = nil
                  await app.refreshGit()
                  app.notice = "Reviewed commits merged into the source. The fork workspace was retained."
                }
              }.buttonStyle(BrandButtonStyle()).disabled(plan["can_merge"] as? Bool != true || app.hasActiveWork(project: app.projectID) || app.hasActiveWork(project: string(fork, "source_project")) || app.busy)
            }.padding(24).frame(width: 620)
          }
        }
    }
  }
}

@MainActor extension Workspace {
  func openForkWorkspace(_ fork: [String: Any], includeContext: Bool = false) async throws {
    guard !openingProject, !restoringNavigation else { throw EngineError(message: "Wait for navigation to finish.") }
    try await open(string(fork, "path"), expectedProjectID: string(fork, "project"))
    let contextKey = "forkContextLoaded:" + string(fork, "id")
    var loadContext = includeContext
    if !loadContext && !preferences.bool(forKey: contextKey) && selectedJob.isEmpty && draft.isEmpty {
      let history = try await engine.call("threads.list", ["project": projectID, "view": "all", "limit": 1]) as? [String: Any] ?? [:]
      loadContext = (history["items"] as? [[String: Any]] ?? []).isEmpty
    }
    if loadContext {
      let result = try await engine.call("threads.fork.context", ["id": string(fork, "id")]) as? [String: Any] ?? [:]
      guard projectID == string(fork, "project") else { return }
      selectJob("", targetSection: "Workspace")
      draft += (draft.isEmpty ? "" : "\n\n") + string(result, "text")
      saveDraft(flush: false)
      if flushRecovery() { preferences.set(true, forKey: contextKey) }
    }
    notice = "Fork workspace opened. Review the draft and choose an agent before sending."
  }

  func openForkSource(_ fork: [String: Any]) async throws {
    let source = string(fork, "source_project")
    guard let project = projects.first(where: { string($0, "id") == source }) else { throw EngineError(message: "Open the source project manually to inspect its saved thread.") }
    try await open(string(project, "path"), expectedProjectID: source)
    selectJob(string(fork, "source_run"), conversationID: string(fork, "source_thread"), targetSection: "Workspace")
  }
}
