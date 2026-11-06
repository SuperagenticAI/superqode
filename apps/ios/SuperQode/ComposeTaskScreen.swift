import SwiftUI

struct ComposeTaskScreen: View {
  let project: String
  var parent: String? = nil
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @Environment(\.scenePhase) private var scenePhase
  @State private var draft: LocalDraft
  @State private var submitting = false
  @State private var issue = ""
  @State private var saved = false
  @State private var submitted = false
  @State private var startedRun: OpenedRun?
  @State private var discard = false
  @State private var showFiles = false
  @State private var showContext = false
  @FocusState private var editing: Bool
  init(project: String, parent: String? = nil, restored: LocalDraft? = nil) {
    self.project = project
    self.parent = parent
    _draft = State(initialValue: restored ?? LocalDraft(project: project, parent: parent))
  }
  private var profiles: [RemoteRecord] { store.profiles.filter { $0.text("project") == project } }
  private var profile: RemoteRecord? { profiles.first { $0.id == draft.profile } }
  private var frozen: Bool { draft.attempt != nil || submitted }
  private var wrongMac: Bool { !draft.origin.isEmpty && draft.origin != store.address }
  private var supportedMode: Bool {
    draft.mode == "code" || (draft.mode == "plan" && profile?.flag("enforces_controls") == true)
      || (draft.mode == "chat" && profile?.flag("chat") == true)
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        ConnectionStatus()
        if !store.reachable { Button("Reconnect to Mac") { Task { await store.refresh() } } }
        if wrongMac { Text("This draft belongs to another Mac. Pair that Mac to submit it.").foregroundStyle(CompanionTheme.warning) }
        connectionCard
        contextCard
        CompanionCard {
          HStack {
            Text("What are we building?").font(.headline)
            Spacer()
            if saved { Label("Saved on iPhone", systemImage: "checkmark.circle").font(.caption).foregroundStyle(.secondary) }
          }
          TextEditor(text: $draft.prompt).frame(minHeight: 200).scrollContentBackground(.hidden)
            .focused($editing).disabled(frozen || submitting)
            .accessibilityLabel("Task prompt").accessibilityIdentifier("composer.prompt")
          HStack {
            Text("\(draft.prompt.count.formatted()) / 32,000").font(.caption.monospacedDigit()).foregroundStyle(.secondary)
            Spacer()
            if !draft.prompt.isEmpty { Button("Copy") { PrivateClipboard.copy(draft.prompt) }.font(.caption) }
          }
        }
        if !issue.isEmpty { Label(issue, systemImage: "exclamationmark.triangle").font(.subheadline).foregroundStyle(CompanionTheme.warning).textSelection(.enabled) }
        if submitted {
          Label("Your task was accepted by the Mac", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
        } else if frozen {
          pendingRequestCard
        } else {
          Button { editing = false; Task { await submit() } } label: {
            HStack { if submitting { ProgressView().tint(.white) }; Label("Send to \(store.macName)", systemImage: "arrow.up") }
          }.buttonStyle(CompanionPrimaryButton()).accessibilityIdentifier("composer.send")
            .disabled(submitting || !store.canMutate || !store.permissions.contains("tasks") || wrongMac || !supportedMode || (draft.mode == "chat" && !(draft.contextFiles ?? []).isEmpty) || draft.profile.isEmpty || draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || draft.prompt.count > 32000)
          if !store.permissions.contains("tasks") { Text("Allow coding tasks when pairing this phone on the Mac to send feedback or start work.").font(.caption).foregroundStyle(CompanionTheme.warning) }
          Text(store.isPreview ? "Pair your own Mac to send a task. Explore mode does not execute requests or save drafts." : "Your Mac runs the task. You can close the phone app and return to the same job later.")
            .font(.caption).foregroundStyle(.secondary)
        }
      }.padding(20).frame(maxWidth: 760).frame(maxWidth: .infinity)
    }.background(CompanionTheme.background).navigationTitle(parent == nil ? "New conversation" : "Continue conversation")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() }.disabled(submitting).accessibilityIdentifier("composer.close") }
        ToolbarItemGroup(placement: .keyboard) { Spacer(); Button("Done") { editing = false } }
      }
      .interactiveDismissDisabled(submitting)
      .sheet(isPresented: $showFiles) { NavigationStack { ContextFilesScreen(profile: draft.profile, initial: draft.contextFiles ?? []) { draft.contextFiles = $0 } } }
      .sheet(isPresented: $showContext) { NavigationStack { ContextPreviewScreen(params: ["profile": .string(draft.profile), "prompt": .string(draft.prompt), "interaction_mode": .string(draft.mode), "context_files": .array((draft.contextFiles ?? []).map(JSONValue.string))]) } }
      .navigationDestination(item: $startedRun) { JobScreen(identity: $0.id).toolbar { ToolbarItem(placement: .confirmationAction) { Button("Done") { dismiss() } } } }
      .task {
        if draft.origin.isEmpty { draft.origin = store.address }
      }
      .task(id: draft) {
        guard !submitted, !submitting, !store.isPreview else { return }
        saved = false
        do {
          try await Task.sleep(for: .milliseconds(350))
          try Task.checkCancellation()
          guard !submitted, !submitting else { return }
          try await store.drafts.save(draft)
          saved = !draft.prompt.isEmpty
        } catch is CancellationError { }
        catch { issue = "Draft could not be saved: " + error.localizedDescription }
      }
      .onDisappear { saveOnExit() }
      .onChange(of: scenePhase) { _, phase in if phase != .active { saveOnExit() } }
      .onChange(of: profile) { _, _ in if !frozen && !supportedMode { draft.mode = "code" } }
      .confirmationDialog("Discard this saved request?", isPresented: $discard, titleVisibility: .visible) {
        Button("Discard draft", role: .destructive) { Task {
          do { try await store.drafts.remove(draft.id); submitted = true; dismiss() }
          catch { issue = error.localizedDescription }
        } }
      } message: { Text("This removes the iPhone draft. It does not cancel a task the Mac may already have accepted. Check Activity before starting another.") }
  }

  private var connectionCard: some View {
    CompanionCard {
      HStack {
        SuperQodeMark(size: 26)
        Text(parent == nil ? "Start with a clean slate" : "Pick up where you left off").font(.headline)
      }
      Picker("Harness connection", selection: $draft.profile) {
        Text("Choose a connection").tag("")
        ForEach(profiles) { Text($0.text("name")).tag($0.id) }
      }.disabled(frozen || submitting).accessibilityIdentifier("composer.connection")
      if let profile {
        HarnessBadge(name: profile.text("harness"))
        Text(profile.text("permission_note")).font(.caption).foregroundStyle(.secondary)
        if !profile.flag("local_only") { Label("This connection may use cloud models", systemImage: "cloud").font(.caption).foregroundStyle(.secondary) }
        if !profile.flag("chat") { Text("Use Code for conversations with this agent. Direct Chat requires a local or API model connection.").font(.caption).foregroundStyle(.secondary) }
      } else {
        Text("Every new conversation starts without a connection. Choose one explicitly.").font(.caption).foregroundStyle(.secondary)
      }
      Picker("Mode", selection: $draft.mode) {
        Text("Code").tag("code")
        Text("Plan").tag("plan").disabled(profile?.flag("enforces_controls") != true)
        Text("Chat").tag("chat").disabled(profile?.flag("chat") != true)
      }.pickerStyle(.segmented).disabled(frozen || submitting)
    }
  }

  private var contextCard: some View {
    CompanionCard {
      Label("Reference files", systemImage: "paperclip").font(.headline)
      ForEach(draft.contextFiles ?? [], id: \.self) { path in Text(path).font(.caption.monospaced()).lineLimit(2) }
      Button((draft.contextFiles ?? []).isEmpty ? "Attach project files" : "Change attachments") { showFiles = true }
        .disabled(frozen || submitting || draft.profile.isEmpty || draft.mode == "chat" || !store.reachable || !store.features.flag("context_files"))
      if !(draft.contextFiles ?? []).isEmpty {
        Button("Review prepared context") { showContext = true }.disabled(submitting || draft.profile.isEmpty || draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || draft.mode == "chat" || !store.reachable)
        Button("Remove attachments", role: .destructive) { draft.contextFiles = [] }.disabled(frozen || submitting)
      }
      Text(draft.mode == "chat" ? "Project reference files require Code or Plan. Remove attachments or change mode before sending." : "Choose a connection, then attach up to ten project text files. Credentials and sensitive paths are excluded.").font(.caption).foregroundStyle(.secondary)
    }
  }

  private var pendingRequestCard: some View {
    CompanionCard {
      Label("Your request is saved", systemImage: "arrow.triangle.2.circlepath").font(.headline)
      Text("The connection may have dropped after the Mac accepted it. Check its status first. A retry uses the same request ID.")
        .font(.subheadline).foregroundStyle(.secondary)
      Button("Check request status") { Task { await reconcile() } }
        .buttonStyle(CompanionPrimaryButton())
        .disabled(submitting || !store.canMutate || !store.features.flag("request_reconciliation") || wrongMac)
      Button("Retry the same request") { Task { await submit() } }.disabled(submitting || !store.canMutate || wrongMac)
      Button("Discard saved draft", role: .destructive) { discard = true }.disabled(submitting)
      if submitting { ProgressView() }
    }
  }

  private func saveOnExit() {
    guard !submitted, !submitting, !store.isPreview else { return }
    let snapshot = draft
    Task { try? await store.drafts.save(snapshot) }
  }
  private func open(_ identity: String) async {
    submitted = true
    try? await store.drafts.remove(draft.id)
    startedRun = OpenedRun(id: identity)
    await store.refreshActivity()
  }
  private func submit() async {
    guard let api = store.api, store.canMutate, store.permissions.contains("tasks"), !wrongMac, !submitting, !draft.isExperiment else { return }
    guard draft.attempt != nil || supportedMode else { return }
    submitting = true; issue = ""
    defer { submitting = false }
    if draft.attempt == nil {
      var params: [String: JSONValue] = ["profile": .string(draft.profile), "prompt": .string(draft.prompt), "interaction_mode": .string(draft.mode)]
      if let parent = draft.parent { params["parent_id"] = .string(parent) }
      if let paths = draft.contextFiles, !paths.isEmpty { params["context_files"] = .array(paths.map(JSONValue.string)) }
      draft.attempt = SubmissionAttempt(key: UUID().uuidString, params: params)
    }
    guard let attempt = draft.attempt else { return }
    do {
      try await store.drafts.save(draft)
      let result = try await api.rpc("tasks.start", attempt.params, key: attempt.key).object
      guard !result.text("id").isEmpty else { throw CompanionError("The Mac returned no run ID. Check the saved request status before retrying.") }
      await open(result.text("id"))
    } catch { issue = error.localizedDescription }
  }
  private func reconcile() async {
    guard let api = store.api, let attempt = draft.attempt, !submitting else { return }
    submitting = true; issue = ""
    defer { submitting = false }
    do {
      let status = try await api.rpc("companion.request_status", ["key": .string(attempt.key)]).object
      let identity = status.object("result").text("id")
      if !identity.isEmpty { await open(identity) }
      else { issue = status.text("state") == "not_recorded"
        ? "The Mac has not recorded this request. Retrying with its original ID is safe."
        : "The outcome is still uncertain. Check Activity or inspect the Mac before starting another task." }
    } catch { issue = error.localizedDescription }
  }
}
