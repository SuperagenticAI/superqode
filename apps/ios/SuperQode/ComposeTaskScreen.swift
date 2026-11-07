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
  @State private var macRefused = false
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
  @State private var showModels = false
  @State private var modelChoices: [RemoteRecord] = []
  @State private var pendingHarness: RemoteRecord?
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
    VStack(alignment: .leading, spacing: 12) {
      HStack {
        Button("Close") { dismiss() }.disabled(submitting).accessibilityIdentifier("composer.close")
        Spacer()
      }
      ConnectionStatus()
      if !store.reachable { Button("Try again") { Task { await store.refresh() } } }
      if wrongMac { Text("This draft belongs to another Mac. Pair that Mac to submit it.").foregroundStyle(CompanionTheme.warning) }
      if submitted {
        Label("Your task was accepted by the Mac", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
      } else if frozen {
        if !issue.isEmpty { Label(issue, systemImage: "exclamationmark.triangle").font(.subheadline).foregroundStyle(CompanionTheme.warning).textSelection(.enabled) }
        pendingRequestCard
      } else {
        connectionCard
        DisclosureGroup("Reference files and images · \((draft.contextFiles ?? []).count + (draft.images ?? []).count)", isExpanded: $showingAttachments) {
          contextCard
          MobileImageAttachments(draft: $draft, frozen: frozen || submitting)
        }.font(.subheadline)
        promptField
          .frame(maxWidth: .infinity, maxHeight: .infinity)
          .layoutPriority(1)
        if !store.permissions.contains("tasks") {
          Text("Allow coding tasks when pairing this phone on the Mac to send work.")
            .font(.caption).foregroundStyle(CompanionTheme.warning)
        }
        if !issue.isEmpty {
          Label(issue, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(CompanionTheme.warning).textSelection(.enabled)
        }
      }
    }
    .padding(.horizontal, 16)
    .padding(.top, 4)
    .frame(maxWidth: 760)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
    .background(CompanionTheme.background)
    .safeAreaInset(edge: .bottom, spacing: 0) {
      if !frozen && !submitted { sendBar }
    }
    .navigationTitle(workspaceName.isEmpty ? (draft.enqueue == true ? "Queue a task" : parent == nil ? "New thread" : "Continue conversation") : workspaceName)
      .navigationBarTitleDisplayMode(.inline)
      .interactiveDismissDisabled(submitting)
      .sheet(isPresented: $showHarnesses) { harnessSheet }
      .sheet(isPresented: $showModels) {
        MacModelChoiceSheet(choices: modelChoices) { model in
          let harness = pendingHarness
          showModels = false
          guard let harness else { return }
          Task { await commitHarness(harness, model: model) }
        }
      }
      .sheet(isPresented: $showFiles) { NavigationStack { ContextFilesScreen(profile: draft.profile, initial: draft.contextFiles ?? []) { draft.contextFiles = $0 } } }
      .sheet(isPresented: $showContext) { NavigationStack { ContextPreviewScreen(params: ["profile": .string(draft.profile), "prompt": .string(draft.prompt), "interaction_mode": .string(draft.mode), "context_files": .array((draft.contextFiles ?? []).map(JSONValue.string))]) } }
      .task {
        // A follow-up keeps the conversation's connection. A new thread uses the
        // one connection already chosen with the workspace. Preview stays blank.
        if draft.profile.isEmpty, parent != nil || (!store.isPreview && profiles.count == 1) {
          draft.profile = profiles.first?.id ?? ""
        }
        await loadConnections()
      }
      .onChange(of: profiles.map(\.id)) { _, _ in
        guard draft.profile.isEmpty, !store.isPreview, profiles.count == 1 else { return }
        draft.profile = profiles[0].id
      }
      .navigationDestination(item: $startedRun) { JobScreen(identity: $0.id) }
      .task {
        if draft.origin.isEmpty { draft.origin = store.address }
      }
      .task(id: draft) {
        guard !submitted, !submitting, !store.isPreview else { return }
        do {
          try await Task.sleep(for: .milliseconds(350))
          try Task.checkCancellation()
          guard !submitted, !submitting else { return }
          try await store.drafts.save(draft)
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

  private var promptField: some View {
    ZStack(alignment: .topLeading) {
      if draft.prompt.isEmpty {
        Text("Describe the change")
          .foregroundStyle(.secondary)
          .padding(.horizontal, 6)
          .padding(.vertical, 8)
          .allowsHitTesting(false)
      }
      TextEditor(text: $draft.prompt)
        .font(.body)
        .scrollContentBackground(.hidden)
        .focused($editing)
        .disabled(frozen || submitting)
        .accessibilityLabel("Task prompt")
        .accessibilityIdentifier("composer.prompt")
    }
    .padding(12)
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .background(CompanionTheme.panel, in: RoundedRectangle(cornerRadius: 16))
    .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(Color.primary.opacity(0.12)))
  }

  private var sendBar: some View {
    VStack(spacing: 6) {
      if draft.prompt.count > 28_000 {
        Text("\(draft.prompt.count.formatted()) / 32,000")
          .font(.caption2.monospacedDigit())
          .foregroundStyle(.secondary)
          .frame(maxWidth: .infinity, alignment: .trailing)
      }
      Button {
        editing = false
        UIApplication.shared.sendAction(#selector(UIResponder.resignFirstResponder), to: nil, from: nil, for: nil)
        Task { await submit() }
      } label: {
        Label(draft.enqueue == true ? "Add to queue" : "Send", systemImage: "arrow.up")
      }
      .buttonStyle(CompanionPrimaryButton())
      .accessibilityIdentifier("composer.send")
      .accessibilityLabel(draft.enqueue == true ? "Add to queue" : "Send")
      .disabled(!canSend || submitting)
    }
    .padding(.horizontal, 16)
    .padding(.top, 8)
    .padding(.bottom, 8)
    .background(CompanionTheme.background)
  }

  private var workspaceName: String {
    store.projects.first { $0.id == project }?.text("name") ?? ""
  }
  /// The workspace was already chosen. Show its folder name, not the short share name.
  private var connectionCard: some View {
    VStack(alignment: .leading, spacing: 10) {
      if !store.isPreview, profiles.count == 1, let only = profiles.first, draft.profile == only.id {
        VStack(alignment: .leading, spacing: 2) {
          Text(workspaceName.isEmpty ? only.text("name") : workspaceName)
            .font(.headline)
            .lineLimit(1)
          Text(companionConnectionTitle(only))
            .font(.subheadline)
            .foregroundStyle(.secondary)
            .lineLimit(1)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .accessibilityElement(children: .combine)
        .accessibilityIdentifier("composer.connection")
        .accessibilityLabel(workspaceName.isEmpty ? only.text("name") : workspaceName)
      } else {
        Picker("Harness connection", selection: $draft.profile) {
          Text("Choose a connection").tag("")
          ForEach(profiles) { Text($0.text("name")).tag($0.id) }
        }
        .disabled(frozen || submitting)
        .accessibilityIdentifier("composer.connection")
        .accessibilityLabel(draft.profile.isEmpty ? "Choose a connection" : "Harness connection")
      }
      if !connections.isEmpty {
        Button { showHarnesses = true } label: {
          HStack(spacing: 10) {
            if let selected = selectedHarness {
              HarnessMark(name: selected.text("name"), iconKey: selected.text("icon_key"), size: 22)
              Text(harnessButtonTitle(selected)).lineLimit(1)
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
        .accessibilityValue(selectedHarness.map { harnessButtonTitle($0) } ?? "None chosen")
        .accessibilityHint("Choose the harness and model for this conversation")
      }
      Picker("Mode", selection: $draft.mode) {
        Text("Code").tag("code")
        Text("Plan").tag("plan").disabled(profile?.flag("enforces_controls") != true)
        Text("Chat").tag("chat").disabled(profile?.flag("chat") != true)
      }.pickerStyle(.segmented).disabled(frozen || submitting)
        .accessibilityIdentifier("composer.mode")
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
      Text(macRefused
        ? "The Mac answered with an error, so this was not a dropped connection. Check its status, then retry with the same request ID."
        : "The connection may have dropped after the Mac accepted it. Check its status first. A retry uses the same request ID.")
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
              .accessibilityIdentifier("harness.choice." + choice.id)
              .disabled(choosingHarness || !HarnessChoiceGroup.readyOnMac(choice))
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

  private func harnessButtonTitle(_ selected: RemoteRecord) -> String {
    let model = profile?.text("model") ?? ""
    if HarnessChoiceGroup.groupID(selected) == "harness", !model.isEmpty, profile?.text("provider") != "agent" {
      return selected.text("name") + " · " + model
    }
    return selected.text("name")
  }

  private func selectHarness(_ choice: String) async {
    guard let selected = connections.first(where: { $0.id == choice }), !choosingHarness else { return }
    guard HarnessChoiceGroup.readyOnMac(selected) else {
      issue = "Set up this harness or connection on the Mac first"
      return
    }
    if HarnessChoiceGroup.needsConnectedModel(selected, profile: profile) {
      await presentModels(for: selected)
      return
    }
    await commitHarness(selected, model: nil)
  }

  private func presentModels(for choice: RemoteRecord) async {
    guard let api = store.api, !choosingHarness else { return }
    choosingHarness = true
    defer { choosingHarness = false }
    do {
      let models = try await api.rpc("project.models", ["project": .string(project)]).array.map { RemoteRecord(raw: $0.object) }
      if models.isEmpty {
        issue = "Connect a model on the Mac first. SuperQode harnesses use a model already set up there."
        return
      }
      if models.count == 1 {
        choosingHarness = false
        await commitHarness(choice, model: models[0])
        return
      }
      pendingHarness = choice
      modelChoices = models
      showModels = true
    } catch { issue = error.localizedDescription }
  }

  private func commitHarness(_ choice: RemoteRecord, model: RemoteRecord?) async {
    guard let api = store.api, !choosingHarness else { return }
    choosingHarness = true
    defer { choosingHarness = false }
    do {
      let provider = model?.text("provider") ?? choice.text("provider", "agent")
      let modelID = model?.text("model") ?? choice.text("model")
      _ = try await api.rpc("project.connection", [
        "project": .string(project), "harness": .string(choice.id),
        "provider": .string(provider), "model": .string(modelID),
      ], key: "connection-" + UUID().uuidString)
      await store.refresh()
      draft.profile = profiles.first?.id ?? draft.profile
      harnessChoice = choice.id
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
    submitting = true; issue = ""; macRefused = false
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
    } catch let error as CompanionError {
      issue = error.localizedDescription
      macRefused = !error.transport && error.status != 0
    } catch { issue = error.localizedDescription }
  }
  private func reconcile() async {
    guard let api = store.api, let attempt = draft.attempt, !submitting else { return }
    submitting = true; issue = ""; macRefused = false
    defer { submitting = false }
    do {
      let status = try await api.rpc("companion.request_status", ["key": .string(attempt.key)]).object
      let identity = status.object("result").text("id")
      if !identity.isEmpty { await open(identity) }
      else { issue = status.text("state") == "not_recorded"
        ? "The Mac has not recorded this request. Retrying with its original ID is safe."
        : "The outcome is still uncertain. Check Activity or inspect the Mac before starting another task." }
    } catch let error as CompanionError {
      issue = error.localizedDescription
      macRefused = !error.transport && error.status != 0
    } catch { issue = error.localizedDescription }
  }
}
