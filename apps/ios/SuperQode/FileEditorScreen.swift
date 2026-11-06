import SwiftUI

struct FileEditorScreen: View {
  let project: String
  let path: String
  let creating: Bool
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @Environment(\.scenePhase) private var phase
  @State private var draft: LocalDraft
  @State private var loaded = false
  @State private var saving = false
  @State private var saved = false
  @State private var issue = ""
  @State private var confirming = false
  @State private var proposed: SubmissionAttempt?
  @State private var resolving = false
  @FocusState private var editing: Bool
  init(project: String, path: String, creating: Bool = false, restored: LocalDraft? = nil) {
    self.project = project; self.path = path; self.creating = creating
    var initial = LocalDraft(project: project)
    initial.fileEdit = SavedFileEdit(path: path, digest: "", text: "", create: creating)
    _draft = State(initialValue: restored ?? initial)
    _loaded = State(initialValue: restored != nil || creating)
  }
  private var file: SavedFileEdit { draft.fileEdit ?? SavedFileEdit(path: path, digest: "", text: "", create: creating) }
  private var writable: Bool { store.canMutate && store.permissions.contains("edit") && (draft.origin.isEmpty || draft.origin == store.address) }
  private var frozen: Bool { saving || draft.attempt != nil }
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      ConnectionStatus()
      if !draft.origin.isEmpty && draft.origin != store.address { Text("This draft belongs to another Mac. Pair that Mac before saving.").font(.footnote).foregroundStyle(CompanionTheme.warning) }
      if !loaded { ProgressView("Reading file revision…") }
      if file.create {
        TextField("Relative file path", text: Binding(get: { file.path }, set: { draft.fileEdit?.path = $0 })).textInputAutocapitalization(.never).autocorrectionDisabled().textFieldStyle(.roundedBorder).disabled(frozen)
      } else { Text(file.path).font(.caption.monospaced()).foregroundStyle(.secondary) }
      TextEditor(text: Binding(get: { file.text }, set: { draft.fileEdit?.text = $0 })).font(.system(.body, design: .monospaced)).focused($editing).disabled(!loaded || frozen).accessibilityIdentifier("file.editor")
      Text("\(file.text.utf8.count.formatted()) / 1,000,000 bytes · Unsent edits are protected on this iPhone.").font(.caption).foregroundStyle(.secondary)
      if !issue.isEmpty { Text(issue).font(.footnote).foregroundStyle(CompanionTheme.warning).textSelection(.enabled) }
      if draft.attempt != nil {
        Text("The previous save may have completed. Check its status before making another change.").font(.footnote)
        Button("Check save status") { Task { await reconcile() } }.disabled(!writable || saving)
        Button("Retry original save") { Task { await save() } }.disabled(!writable || saving)
        Button("Review current file to resolve") { resolving = true }.disabled(!writable || saving)
      } else {
        Button(file.create ? "Review new file" : "Review save") {
          editing = false
          let params: [String: JSONValue] = ["project": .string(project), "path": .string(file.path), "text": .string(file.text), "digest": .string(file.digest)]
          proposed = SubmissionAttempt(key: UUID().uuidString, params: file.create ? params.filter { $0.key != "digest" } : params, method: file.create ? "files.create" : "files.write")
          confirming = true
        }
          .buttonStyle(CompanionPrimaryButton()).disabled(!writable || !loaded || file.path.isEmpty || file.text.utf8.count > 1_000_000)
      }
      if saving { ProgressView("Saving the reviewed revision…") }
      if !store.permissions.contains("edit") { Text("Allow file editing when approving this phone on your Mac.").font(.caption).foregroundStyle(.secondary) }
      if store.isPreview { Text("Explore mode cannot save files.").font(.caption).foregroundStyle(.secondary) }
    }.padding(18).background(CompanionTheme.background).navigationTitle(file.create ? "New file" : "Edit file").navigationBarTitleDisplayMode(.inline)
      .toolbar {
        ToolbarItem(placement: .cancellationAction) { Button("Close") { dismiss() }.disabled(saving) }
        ToolbarItemGroup(placement: .keyboard) { Spacer(); Button("Done") { editing = false } }
      }.interactiveDismissDisabled(saving)
      .confirmationDialog("Save \(file.path) on your Mac?", isPresented: $confirming, titleVisibility: .visible) {
        if let request = proposed { Button("Save reviewed content") { Task { draft.attempt = request; await save() } } }
      } message: { Text(file.create ? "Creates this file only if it does not already exist. No code is executed." : "Replaces the loaded file revision. If the file changed on the Mac, saving is refused. No code is executed.") }
      .sheet(isPresented: $resolving) {
        NavigationStack { FileEditConflictScreen(project: project, path: file.path, proposed: file.text) { digest in
          draft.fileEdit?.digest = digest; draft.fileEdit?.create = false; draft.attempt = nil; issue = "Current revision selected. Review your edits and save explicitly."
        } }
      }
      .task { await load() }
      .task(id: draft) {
        guard loaded, !saved, !saving, !store.isPreview else { return }
        do { try await Task.sleep(for: .milliseconds(400)); try Task.checkCancellation(); try await store.drafts.save(draft) }
        catch is CancellationError { }
        catch { issue = "Local draft could not be saved: " + error.localizedDescription }
      }
      .onDisappear { protect() }.onChange(of: phase) { _, next in if next != .active { protect() } }
  }
  private func load() async {
    if draft.origin.isEmpty { draft.origin = store.address }
    guard !loaded, let api = store.api else { return }
    do {
      let result = try await api.rpc("files.read", ["project": .string(project), "path": .string(path)]).object
      try Task.checkCancellation()
      draft.fileEdit = SavedFileEdit(path: path, digest: result.text("digest"), text: result.text("text"), create: false)
      loaded = true
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
  private func protect() {
    guard loaded, !saved, !saving, !store.isPreview else { return }
    let snapshot = draft
    Task { try? await store.drafts.save(snapshot) }
  }
  private func save() async {
    guard writable, !saving, let api = store.api else { return }
    saving = true; issue = ""
    defer { saving = false }
    if draft.attempt == nil {
      let params: [String: JSONValue] = ["project": .string(project), "path": .string(file.path), "text": .string(file.text), "digest": .string(file.digest)]
      draft.attempt = SubmissionAttempt(key: UUID().uuidString, params: file.create ? params.filter { $0.key != "digest" } : params, method: file.create ? "files.create" : "files.write")
    }
    guard let attempt = draft.attempt else { return }
    do {
      try await store.drafts.save(draft)
      _ = try await api.rpc(attempt.method ?? "files.write", attempt.params, key: attempt.key)
      try await finish()
    } catch { issue = error.localizedDescription }
  }
  private func finish() async throws { try await store.drafts.remove(draft.id); saved = true; dismiss() }
  private func reconcile() async {
    guard let attempt = draft.attempt, let api = store.api, writable, !saving else { return }
    saving = true; defer { saving = false }
    do {
      let result = try await api.rpc("companion.request_status", ["key": .string(attempt.key)]).object
      if result.text("state") == "completed" { try await finish() }
      else { issue = result.text("state") == "not_recorded" ? "This save was not recorded. Retry the original save to keep its revision check." : "The outcome is uncertain. Inspect the file on your Mac before another save." }
    } catch { issue = error.localizedDescription }
  }
}

struct FileEditConflictScreen: View {
  let project: String
  let path: String
  let proposed: String
  let useRevision: (String) -> Void
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @State private var current: [String: JSONValue] = [:]
  @State private var issue = ""
  @State private var confirming = false
  var body: some View {
    ScrollView {
      LazyVStack(alignment: .leading, spacing: 18) {
        ConnectionStatus()
        Text("Compare both versions. Using the current revision keeps your draft text and requires another explicit save; it does not merge the files for you.").font(.footnote).foregroundStyle(.secondary)
        if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
        Text("Current Mac file").font(.headline)
        MobileCodeBlock(code: current.text("text"), language: URL(fileURLWithPath: path).pathExtension)
        Text("Your unsent edits").font(.headline)
        MobileCodeBlock(code: proposed, language: URL(fileURLWithPath: path).pathExtension)
        Button("Use current revision as base") { confirming = true }.buttonStyle(CompanionPrimaryButton()).disabled(current.text("digest").isEmpty || !store.canMutate)
      }.padding(20)
    }.navigationTitle("Resolve file edit").background(CompanionTheme.background)
      .toolbar { Button("Close") { dismiss() } }
      .confirmationDialog("Keep your draft over this reviewed revision?", isPresented: $confirming, titleVisibility: .visible) {
        let digest = current.text("digest")
        Button("Use reviewed revision") { useRevision(digest); dismiss() }
      } message: { Text("Your next save replaces the current file with your draft if this revision still matches. Review and incorporate any Mac changes before saving.") }
      .task {
        guard let api = store.api else { return }
        do { current = try await api.rpc("files.read", ["project": .string(project), "path": .string(path)]).object }
        catch { issue = error.localizedDescription }
      }
  }
}
