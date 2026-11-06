import SwiftUI

@MainActor final class ThreadLibrary: ObservableObject {
  @Published private(set) var items: [RemoteRecord] = []
  @Published private(set) var loading = false
  @Published private(set) var cursor = ""
  @Published var issue = ""
  private var generation = 0

  func load(_ api: any CompanionTransport, project: String, query: String, view: String, reset: Bool = true) async {
    if reset { generation += 1; cursor = ""; items = [] }
    else if loading || cursor.isEmpty { return }
    let request = generation
    loading = true
    defer { if request == generation { loading = false } }
    var params: [String: JSONValue] = ["project": .string(project), "query": .string(query), "view": .string(view), "limit": .number(50)]
    if !reset { params["cursor"] = .string(cursor) }
    do {
      let page = try await api.rpc("threads.list", params).object
      try Task.checkCancellation()
      guard request == generation else { return }
      var known = Set(items.map { $0.text("conversation_id", $0.id) })
      let next = page.records("items").filter { known.insert($0.text("conversation_id", $0.id)).inserted }
      items.append(contentsOf: next)
      cursor = page.text("next_cursor")
      issue = ""
    } catch is CancellationError { }
    catch { if request == generation { issue = error.localizedDescription } }
  }
}

struct ProjectScreen: View {
  let project: RemoteRecord
  @EnvironmentObject private var store: CompanionStore
  @StateObject private var library = ThreadLibrary()
  @State private var query = ""
  @State private var filter = "active"
  @State private var compose = false
  @State private var evaluate = false
  @State private var renaming: RemoteRecord?
  @State private var renameTitle = ""
  private var canOrganize: Bool {
    store.canMutate && store.permissions.contains("tasks")
      && (store.features["threads"]?.array.contains(.string("rename")) == true)
  }

  var body: some View {
    List {
      Section {
        HStack(spacing: 12) {
          NavigationLink { FilesScreen(project: project.id) } label: { Label("Files", systemImage: "doc.text") }
          NavigationLink { ChangesScreen(project: project.id) } label: { Label("Changes", systemImage: "arrow.triangle.branch") }
          Button { evaluate = true } label: { Label("Evaluate", systemImage: "chart.bar.xaxis") }
            .disabled(!store.permissions.contains("evaluate") && !store.permissions.contains("optimize"))
        }.font(.subheadline).buttonStyle(.borderless)
      }.listRowBackground(CompanionTheme.panel)
      Section {
        Picker("Conversations", selection: $filter) {
          Text("Recent").tag("active"); Text("Pinned").tag("pinned"); Text("Archived").tag("archived")
        }.pickerStyle(.segmented).listRowBackground(Color.clear)
        if !library.issue.isEmpty { Text(library.issue).foregroundStyle(CompanionTheme.warning) }
        if library.loading && library.items.isEmpty { ProgressView("Loading conversations…") }
        ForEach(library.items) { thread in
          NavigationLink { JobScreen(identity: thread.id) } label: { JobRow(job: thread) }
            .contextMenu {
              Button { renaming = thread; renameTitle = thread.text("conversation_title", thread.text("title")) } label: { Label("Rename", systemImage: "pencil") }.disabled(!canOrganize)
              Button { Task { await update(thread, ["pinned": .bool(!thread.flag("pinned"))]) } } label: { Label(thread.flag("pinned") ? "Unpin" : "Pin", systemImage: "pin") }.disabled(!canOrganize)
              Button { Task { await update(thread, ["archived": .bool(!thread.flag("archived"))]) } } label: { Label(thread.flag("archived") ? "Restore" : "Archive", systemImage: "archivebox") }.disabled(!canOrganize || thread.active)
            }
        }.listRowBackground(CompanionTheme.panel)
        if !library.loading && library.items.isEmpty && library.issue.isEmpty {
          ContentUnavailableView(query.isEmpty ? "A clean slate" : "No matching conversations",
            systemImage: query.isEmpty ? "bubble.left.and.bubble.right" : "magnifyingglass",
            description: Text(query.isEmpty ? "Start a conversation using a connection shared by your Mac." : "Try another title or switch the filter."))
        }
        if !library.cursor.isEmpty {
          Button { Task { await load(reset: false) } } label: { HStack { Text("Load more conversations"); if library.loading { ProgressView() } } }
            .disabled(library.loading)
        }
      } header: { Text("Conversations") }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background)
      .navigationTitle(project.text("name"))
      .searchable(text: $query, prompt: "Search every conversation")
      .toolbar { Button { compose = true } label: { Label("New conversation", systemImage: "square.and.pencil") }.disabled(!store.permissions.contains("tasks")) }
      .sheet(isPresented: $compose, onDismiss: { Task { await load() } }) { NavigationStack { ComposeTaskScreen(project: project.id) } }
      .sheet(isPresented: $evaluate) { NavigationStack { EvaluationScreen(project: project.id) } }
      .refreshable { await load() }
      .task(id: query + ":" + filter) {
        do { if !query.isEmpty { try await Task.sleep(for: .milliseconds(250)) }; try Task.checkCancellation(); await load() }
        catch { }
      }
      .alert("Rename conversation", isPresented: Binding(get: { renaming != nil }, set: { if !$0 { renaming = nil } })) {
        TextField("Conversation title", text: $renameTitle)
        Button("Save") { if let thread = renaming { let title = renameTitle; Task { await update(thread, ["title": .string(title)]) } }; renaming = nil }
        Button("Cancel", role: .cancel) { renaming = nil }
      }
  }

  private func load(reset: Bool = true) async {
    guard let api = store.api else { return }
    await library.load(api, project: project.id, query: query, view: filter, reset: reset)
  }
  private func update(_ thread: RemoteRecord, _ changes: [String: JSONValue]) async {
    guard let api = store.api, canOrganize else { return }
    do {
      var params = changes
      params["project"] = .string(project.id)
      params["id"] = .string(thread.id)
      _ = try await api.rpc("threads.update", params, key: UUID().uuidString)
      await load()
    } catch { library.issue = error.localizedDescription }
  }
}

struct DraftsScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @State private var drafts: [LocalDraft] = []
  @State private var deleting: LocalDraft?
  @State private var issue = ""
  var body: some View {
    List {
      Section {
        Text("Unsent text is saved only on this iPhone, with device protection and backup exclusion. Drafts never start work automatically.")
          .font(.footnote).foregroundStyle(.secondary)
      }.listRowBackground(Color.clear)
      if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      ForEach(drafts) { draft in
        NavigationLink {
          if draft.isExperiment { EvaluationScreen(project: draft.project, restored: draft) }
          else { ComposeTaskScreen(project: draft.project, parent: draft.parent, restored: draft) }
        } label: {
          VStack(alignment: .leading, spacing: 8) {
            Label(draft.attempt == nil ? "Unsent draft" : "Saved request", systemImage: draft.attempt == nil ? "square.and.pencil" : "arrow.triangle.2.circlepath")
              .font(.caption).foregroundStyle(draft.attempt == nil ? CompanionTheme.accent : .orange)
            Text(draft.prompt).lineLimit(3)
            Text(draft.updated, style: .relative).font(.caption).foregroundStyle(.secondary)
          }.padding(.vertical, 6)
        }.swipeActions { Button("Delete", role: .destructive) { deleting = draft } }
      }.listRowBackground(CompanionTheme.panel)
      if drafts.isEmpty && issue.isEmpty { ContentUnavailableView("No saved drafts", systemImage: "square.and.pencil", description: Text("Your unsent conversations will appear here.")) }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background).navigationTitle("Saved drafts")
      .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Done") { dismiss() } } }
      .task { await load() }
      .confirmationDialog("Delete this draft?", isPresented: Binding(get: { deleting != nil }, set: { if !$0 { deleting = nil } }), titleVisibility: .visible) {
        Button("Delete draft", role: .destructive) { if let draft = deleting { Task { do { try await store.drafts.remove(draft.id); await load() } catch { issue = error.localizedDescription } } }; deleting = nil }
      } message: { Text("Deleting a draft does not cancel a job already accepted by the Mac.") }
  }
  private func load() async {
    guard !store.isPreview else { drafts = []; issue = ""; return }
    do { drafts = try await store.drafts.list().filter { $0.origin == store.address }; issue = "" }
    catch { issue = error.localizedDescription }
  }
}
