import SwiftUI
import UIKit

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
  @State private var showingAttachments = false
  @State private var connections: [RemoteRecord] = []
  @State private var harnessChoice = ""
  @State private var choosingHarness = false
  @State private var showHarnesses = false
  @FocusState private var editing: Bool
  init(project: String, parent: String? = nil, restored: LocalDraft? = nil, enqueue: Bool = false) {
    self.project = project
    self.parent = parent
    var initial = restored ?? LocalDraft(project: project, parent: parent)
    if restored == nil { initial.enqueue = enqueue }
    _draft = State(initialValue: initial)
  }
  private var profiles: [RemoteRecord] { store.profiles.filter { $0.text("project") == project } }
  private var profile: RemoteRecord? { profiles.first { $0.id == draft.profile } }
  private var frozen: Bool { draft.attempt != nil || submitted }
  private var wrongMac: Bool { !draft.origin.isEmpty && draft.origin != store.address }
  private var supportedMode: Bool {
    draft.mode == "code" || (draft.mode == "plan" && profile?.flag("enforces_controls") == true)
      || (draft.mode == "chat" && profile?.flag("chat") == true)
  }
  private var canSend: Bool {
    !submitting && store.canMutate && store.permissions.contains("tasks")
      && (draft.enqueue != true || store.permissions.contains("queue")) && !wrongMac && supportedMode
      && !(draft.mode == "chat" && !(draft.contextFiles ?? []).isEmpty) && !draft.profile.isEmpty
      && !draft.prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty && draft.prompt.count <= 32000
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
          HStack {
            Button("Close") { dismiss() }.disabled(submitting).accessibilityIdentifier("composer.close")
            Spacer()
            if saved { Label("Saved on iPhone", systemImage: "checkmark.circle").font(.caption).foregroundStyle(.secondary) }
          }
          ConnectionStatus()
          if !store.reachable { Button("Try again") { Task { await store.refresh() } } }
          if wrongMac { Text("This draft belongs to another Mac. Pair that Mac to submit it.").foregroundStyle(CompanionTheme.warning) }
          connectionCard
          DisclosureGroup("Reference files and images · \((draft.contextFiles ?? []).count + (draft.images ?? []).count)", isExpanded: $showingAttachments) {
            contextCard
            MobileImageAttachments(draft: $draft, frozen: frozen || submitting)
          }.font(.subheadline)
          if submitted {
            Label("Your task was accepted by the Mac", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
          } else if frozen {
            if !issue.isEmpty { Label(issue, systemImage: "exclamationmark.triangle").font(.subheadline).foregroundStyle(CompanionTheme.warning).textSelection(.enabled) }
            pendingRequestCard
          } else {
            if !store.permissions.contains("tasks") { Text("Allow coding tasks when pairing this phone on the Mac to send feedback or start work.").font(.caption).foregroundStyle(CompanionTheme.warning) }
            Text(store.isPreview ? "Pair your own Mac to send a task. Explore mode does not execute requests or save drafts." : "Your Mac runs the task. Queued tasks run when their queue is started. You can return to the same recorded work later.")
              .font(.caption).foregroundStyle(.secondary)
            promptDock
          }
        }.padding(20).frame(maxWidth: 760).frame(maxWidth: .infinity)
    }
    .scrollDismissesKeyboard(.interactively)
    .background(CompanionTheme.background).navigationTitle(draft.enqueue == true ? "Queue a task" : parent == nil ? "New thread" : "Continue conversation")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItemGroup(placement: .keyboard) { Spacer(); Button("Done") { editing = false } }
      }
      .interactiveDismissDisabled(submitting)
      .sheet(isPresented: $showHarnesses) { harnessSheet }
      .sheet(isPresented: $showFiles) { NavigationStack { ContextFilesScreen(profile: draft.profile, initial: draft.contextFiles ?? []) { draft.contextFiles = $0 } } }
      .sheet(isPresented: $showContext) { NavigationStack { ContextPreviewScreen(params: ["profile": .string(draft.profile), "prompt": .string(draft.prompt), "interaction_mode": .string(draft.mode), "context_files": .array((draft.contextFiles ?? []).map(JSONValue.string))]) } }
      .task {
        // A new thread stays on "Choose a connection" until the harness is picked.
        if draft.profile.isEmpty, parent != nil {
          draft.profile = profiles.first?.id ?? ""
        }
        await loadConnections()
      }
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

  private var promptDock: some View {
    VStack(alignment: .leading, spacing: 6) {
      HStack {
        Text(draft.enqueue == true ? "Task" : "Message").font(.caption.weight(.semibold)).foregroundStyle(.secondary)
        Spacer()
        Text("\(draft.prompt.count.formatted()) / 32,000").font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
        if !draft.prompt.isEmpty { Button("Copy") { PrivateClipboard.copy(draft.prompt) }.font(.caption2) }
      }
      if !issue.isEmpty {
        Label(issue, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(CompanionTheme.warning).textSelection(.enabled)
      }
      HStack(alignment: .bottom, spacing: 8) {
        TextEditor(text: $draft.prompt)
          .frame(minHeight: 88)
          .scrollContentBackground(.hidden)
          .focused($editing)
          .disabled(frozen || submitting)
          .accessibilityLabel("Task prompt")
          .accessibilityIdentifier("composer.prompt")
          .padding(.horizontal, 10)
          .padding(.vertical, 6)
          .background(CompanionTheme.background, in: RoundedRectangle(cornerRadius: 14))
        Button {
          editing = false
          UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
          Task { await submit() }
        } label: {
          Image(systemName: draft.enqueue == true ? "plus.circle.fill" : "arrow.up.circle.fill")
            .font(.system(size: 32))
            .frame(width: 36, height: 36)
            .foregroundStyle(canSend ? CompanionTheme.accent : Color.secondary)
        }
        .buttonStyle(.plain)
        .accessibilityIdentifier("composer.send")
        .accessibilityLabel(draft.enqueue == true ? "Add to queue" : "Send")
        .disabled(!canSend)
      }
    }
    .padding(.horizontal, 12)
    .padding(.top, 8)
    .padding(.bottom, 6)
    .background(.bar)
  }

  private var connectionCard: some View {
    CompanionCard {
      HStack {
        SuperQodeMark(size: 26)
        Text("Harness").font(.headline)
      }
      if parent == nil {
        Text("This starts a separate thread. Pick the harness first.").font(.caption).foregroundStyle(.secondary)
      }
      Picker("Harness connection", selection: $draft.profile) {
        Text("Choose a connection").tag("")
        ForEach(profiles) { Text($0.text("name")).tag($0.id) }
      }
      .disabled(frozen || submitting)
      .accessibilityIdentifier("composer.connection")
      .accessibilityLabel(draft.profile.isEmpty ? "Choose a connection" : "Harness connection")
      if !connections.isEmpty {
        Button { showHarnesses = true } label: {
          HStack(spacing: 10) {
            if let selected = selectedHarness {
              HarnessMark(name: selected.text("name"), iconKey: selected.text("icon_key"), size: 22)
              Text(selected.text("name")).lineLimit(1)
            } else {
              Text("Choose a harness")
            }
            Spacer()
            Image(systemName: "chevron.up.chevron.down").foregroundStyle(.secondary)
          }
        }
        .buttonStyle(.plain)
        .disabled(frozen || submitting || choosingHarness)
        .accessibilityIdentifier("composer.harness")
        .accessibilityLabel("Harness")
        Text("Only harnesses your Mac allows for this project are listed. Subscriptions, connect a model, SuperQode harnesses, then ACP agents and protocols.")
          .font(.caption).foregroundStyle(.secondary)
      }
      if let profile {
        HarnessBadge(name: profile.text("harness"), iconKey: selectedHarness?.text("icon_key") ?? "")
        Text(profile.text("permission_note")).font(.caption).foregroundStyle(.secondary)
        if !profile.flag("local_only") { Label("This connection may use cloud models", systemImage: "cloud").font(.caption).foregroundStyle(.secondary) }
        if !profile.flag("chat") { Text("Use Code for conversations with this agent. Direct Chat requires a local or API model connection.").font(.caption).foregroundStyle(.secondary) }
      } else {
        Text("Choose a harness for this conversation. You can switch it later from the thread.").font(.caption).foregroundStyle(.secondary)
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

  private var selectedHarness: RemoteRecord? {
    let current = harnessChoice.isEmpty ? profile?.text("harness") ?? "" : harnessChoice
    return connections.first { $0.id == current }
  }

  private var harnessSheet: some View {
    NavigationStack {
      List {
        ForEach(HarnessChoiceGroup.sections(connections)) { section in
          Section {
            ForEach(section.rows) { choice in
              Button {
                let picked = choice.id
                showHarnesses = false
                guard picked != profile?.text("harness") else { return }
                harnessChoice = picked
                Task { await selectHarness(picked) }
              } label: {
                HarnessChoiceLabel(choice: choice, selected: choice.id == (selectedHarness?.id ?? ""))
                  .frame(maxWidth: .infinity, alignment: .leading)
                  .contentShape(Rectangle())
              }
              .buttonStyle(.plain)
              .disabled(choosingHarness)
            }
          } header: {
            Text(section.title)
          } footer: {
            Text(section.subtitle)
          }
        }
      }
      .navigationTitle("Harness")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) {
          Button("Close") { showHarnesses = false }
        }
      }
    }
  }

  private func loadConnections() async {
    guard let api = store.api, !store.isPreview else { return }
    do {
      connections = try await api.rpc("project.connections", ["project": .string(project)]).array.map { RemoteRecord(raw: $0.object) }
      if harnessChoice.isEmpty { harnessChoice = profile?.text("harness") ?? "" }
    } catch { }
  }

  private func selectHarness(_ choice: String) async {
    guard let api = store.api, let selected = connections.first(where: { $0.id == choice }), !choosingHarness else { return }
    choosingHarness = true
    defer { choosingHarness = false }
    do {
      _ = try await api.rpc("project.connection", [
        "project": .string(project), "harness": .string(selected.id),
        "provider": .string(selected.text("provider", "agent")), "model": .string(selected.text("model")),
      ], key: "connection-" + UUID().uuidString)
      await store.refresh()
      draft.profile = profiles.first?.id ?? draft.profile
    } catch { issue = error.localizedDescription }
  }

  private func saveOnExit() {
    guard !submitted, !submitting, !store.isPreview else { return }
    let snapshot = draft
    Task { try? await store.drafts.save(snapshot) }
  }
  private func open(_ identity: String) async {
    submitted = true
    try? await store.drafts.remove(draft.id)
    if draft.attempt?.method == "queue.add" { dismiss(); return }
    startedRun = OpenedRun(id: identity)
    await store.refreshActivity()
  }
  private func submit() async {
    guard let api = store.api, store.canMutate, store.permissions.contains("tasks"), !wrongMac, !submitting, !draft.isExperiment, draft.fileEdit == nil else { return }
    guard draft.enqueue != true || store.permissions.contains("queue") else { return }
    guard draft.attempt != nil || supportedMode else { return }
    submitting = true; issue = ""
    defer { submitting = false }
    if draft.attempt == nil {
      var params: [String: JSONValue] = ["profile": .string(draft.profile), "prompt": .string(draft.prompt), "interaction_mode": .string(draft.mode)]
      if let parent = draft.parent { params["parent_id"] = .string(parent) }
      if let paths = draft.contextFiles, !paths.isEmpty { params["context_files"] = .array(paths.map(JSONValue.string)) }
      do {
        for index in (draft.images ?? []).indices {
          guard let image = draft.images?[index], image.macID == nil else { continue }
          let bytes = try await store.drafts.imageData(draft: draft.id, image: image)
          let result = try await api.rpc("images.upload", ["project": .string(project), "name": .string(image.name), "data": .string(bytes.base64EncodedString())], key: image.id).object
          guard !result.text("id").isEmpty else { throw CompanionError("The Mac did not confirm the image upload.") }
          draft.images?[index].macID = result.text("id")
          try await store.drafts.save(draft)
        }
      } catch { issue = error.localizedDescription; return }
      let images = (draft.images ?? []).compactMap(\.macID)
      if !images.isEmpty { params["image_ids"] = .array(images.map(JSONValue.string)) }
      draft.attempt = SubmissionAttempt(key: UUID().uuidString, params: params, method: draft.enqueue == true ? "queue.add" : "tasks.start")
    }
    guard let attempt = draft.attempt else { return }
    do {
      try await store.drafts.save(draft)
      let result = try await api.rpc(attempt.method ?? "tasks.start", attempt.params, key: attempt.key).object
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
