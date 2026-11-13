import AppKit
import SwiftUI

struct ProviderConnectionView: View {
  @EnvironmentObject private var app: Workspace
  @DialogDismiss private var dismiss

  @State private var choice: Choice?
  @State private var route = ""
  @State private var providerQuery = ""
  @State private var showAllProviders = false
  @State private var modelQuery = ""
  @State private var selectedModel = ""
  @State private var models: [ModelRow] = []
  @State private var catalogLoading = false
  @State private var catalogError = ""
  @State private var key = ""
  @State private var remember = true
  @State private var saving = false
  @State private var restoringKey = false
  @State private var message = ""
  @State private var workspaceModels: [ModelRow] = []
  @State private var workspaceMessage = ""
  @State private var workspaceLookup: UUID?
  @State private var workspaceEndpoint = ""

  private struct Choice: Identifiable {
    let id: String
    let name: String
    let routes: [String]
    let searchText: String
  }

  private struct ModelRow: Identifiable {
    let id: String
    let name: String
    var releaseDate: String? = nil
  }

  private static let alibabaRoutes = ["qwen-intl", "qwen-cn", "alibaba"]
  private static let groupedRoutes = ["alibaba": alibabaRoutes, "zai": ["zai", "zhipu"]]
  private static let groupedNames = ["alibaba": "Alibaba Model Studio", "zai": "Z.AI"]
  private static let hiddenGroupMembers: Set<String> = ["qwen-intl", "qwen-cn", "zhipu"]
  private static let chinaOrder = [
    "deepseek", "moonshot", "zai", "minimax", "doubao", "baidu", "siliconflow",
  ]
  private static let usOrder = ["google", "anthropic", "openai", "xai", "meta", "nvidia", "poolside"]
  private static let hostOrder = ["baseten", "fireworks", "together", "modal", "openrouter"]
  private static let shortNames = [
    "xai": "xAI (Grok)", "meta": "Meta", "google": "Google", "siliconflow": "SiliconFlow",
  ]
  private static let apiKeyNotes = [
    "qwen-intl": "Use a Model Studio API key issued for the international region.",
    "qwen-cn": "Use a Model Studio API key issued for the China region.",
    "alibaba": "Use a DashScope API key.",
    "xai": "Use an API key from the xAI Console.",
  ]

  private var harness: [String: Any] {
    app.harnesses.first { string($0, "id") == app.harness } ?? [:]
  }
  private var providerRows: [[String: Any]] {
    let allowed = harness["byok_providers"] as? [String]
    return app.providers.filter { row in
      let id = string(row, "id")
      // The catalog also lists subscription plans that authenticate with keys.
      return row["local"] as? Bool != true && row["key_supported"] as? Bool == true
        && id != "alibaba-cn" && !id.split(separator: "-").contains("plan")
        && (allowed?.contains(id) ?? true)
    }
  }
  private var provider: [String: Any] {
    app.providers.first { string($0, "id") == route } ?? [:]
  }
  private var modelStudio: Bool { route == "qwen-intl" || route == "qwen-cn" }
  private var configured: Bool { provider["credential_configured"] as? Bool == true }
  private var saved: Bool { app.savedCredentialProviders.contains(route) }
  private var working: Bool { saving || restoringKey }
  private var modelID: String { selectedModel.trimmingCharacters(in: .whitespacesAndNewlines) }
  private var suppliedKey: String { key.trimmingCharacters(in: .whitespacesAndNewlines) }
  private func requiresPlan(_ id: String, for route: String) -> Bool {
    Self.alibabaRoutes.contains(route) && id.lowercased() == "qwen4-max-preview"
  }
  private var canConnect: Bool {
    !working && !modelID.isEmpty && !requiresPlan(modelID, for: route)
      && (configured || !suppliedKey.isEmpty)
  }

  var body: some View {
    Group {
      if let choice {
        detail(choice)
      } else {
        chooser
      }
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .task { app.prepareModelCatalog() }
  }

  private func choices(in rows: [[String: Any]], orderedBy order: [String] = []) -> [Choice] {
    let indexed = Dictionary(rows.map { (string($0, "id"), $0) }, uniquingKeysWith: { first, _ in first })
    let ordered = order + indexed.keys.filter { !order.contains($0) }.sorted {
      string(indexed[$0] ?? [:], "name").localizedStandardCompare(string(indexed[$1] ?? [:], "name")) == .orderedAscending
    }
    return ordered.compactMap { id in
      if Self.hiddenGroupMembers.contains(id) { return nil }
      let routes = (Self.groupedRoutes[id] ?? [id]).filter { indexed[$0] != nil }
      guard let first = routes.first, let row = indexed[first] else { return nil }
      let name = Self.groupedNames[id] ?? Self.shortNames[id] ?? string(row, "name", id)
      let search = routes.map { $0 + " " + string(indexed[$0] ?? [:], "name") }
      return Choice(id: id, name: name, routes: routes, searchText: ([name] + search).joined(separator: " "))
    }
  }

  private var chooser: some View {
    let rows = providerRows
    let curated = rows.filter { $0["curated"] as? Bool == true }
    let featured = choices(in: rows.filter { Self.alibabaRoutes.contains(string($0, "id")) },
      orderedBy: ["alibaba"]).first
    let query = providerQuery.trimmingCharacters(in: .whitespacesAndNewlines)
    let browsingCatalog = showAllProviders || !query.isEmpty
    let results = browsingCatalog ? choices(in: rows, orderedBy: ["alibaba"] + Self.chinaOrder + Self.usOrder)
      .filter { query.isEmpty || $0.searchText.localizedCaseInsensitiveContains(query) } : []
    return VStack(alignment: .leading, spacing: 0) {
      VStack(alignment: .leading, spacing: 12) {
        Text("Choose a provider").font(.title2.weight(.semibold)).accessibilityAddTraits(.isHeader)
        if let name = harness["name"] as? String, !app.connectionDisconnected {
          Text("Model provider for \(name)").font(.callout).foregroundStyle(.secondary)
        }
        if !rows.isEmpty {
          Picker("Provider catalog", selection: $showAllProviders) {
            Text("Featured providers").tag(false)
            Text("All providers").tag(true)
          }
          .pickerStyle(.segmented).labelsHidden()
          .accessibilityIdentifier("provider.catalogScope")
          .onChange(of: showAllProviders) { _, _ in providerQuery = "" }
        }
        ConnectionSearchField(title: "Search all providers", text: $providerQuery)
      }
      .padding(.horizontal, 24).padding(.vertical, 16)
      Divider()
      ScrollView {
        LazyVStack(alignment: .leading, spacing: 18) {
          if rows.isEmpty {
            if app.providers.isEmpty {
              ProgressView("Loading providers…")
            } else {
              EmptyState(icon: "key", title: "No API providers for this harness",
                detail: "Go back to choose a different connection or harness.")
            }
          } else if browsingCatalog {
            if results.isEmpty {
              Text("No providers match your search.").foregroundStyle(.secondary)
            } else {
              providerGrid(results)
            }
          } else {
            if let featured {
              providerButton(featured, subtitle: "Connect Qwen and other models with a Model Studio API key.")
            }
            providerSection("China Labs", rows: curated, category: "China Labs", order: Self.chinaOrder)
            providerSection("US Labs", rows: curated, category: "US Labs", order: Self.usOrder)
            providerSection("Other labs", rows: curated, category: "Other Labs")
            providerSection("Model hosts", rows: curated, category: "Model Hosts", order: Self.hostOrder)
            providerSection("Other providers", rows: curated, category: "Local / Self-Hosted")
          }
        }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
      }.id(showAllProviders)
      if app.modelCatalogStatus == "offline" || app.modelCatalogStatus == "empty" {
        Divider()
        Text(app.modelCatalogStatus == "offline" ? "Showing the saved catalog." : "Showing built-in model examples.")
          .font(.caption).foregroundStyle(.secondary).padding(.horizontal, 24).padding(.vertical, 8)
      }
    }
  }

  @ViewBuilder private func providerSection(
    _ title: String, rows: [[String: Any]], category: String, order: [String] = []
  ) -> some View {
    let entries = choices(in: rows.filter {
      string($0, "category") == category && string($0, "id") != "alibaba"
    }, orderedBy: order)
    if !entries.isEmpty {
      VStack(alignment: .leading, spacing: 8) {
        Text(title).font(.headline).accessibilityAddTraits(.isHeader)
        providerGrid(entries)
      }
    }
  }

  private func providerGrid(_ entries: [Choice]) -> some View {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 166), spacing: 8)], spacing: 8) {
      ForEach(entries) { entry in providerButton(entry) }
    }
  }

  private func providerButton(_ entry: Choice, subtitle: String? = nil) -> some View {
    let featured = subtitle != nil
    let keyAvailable = entry.routes.contains { id in
      app.savedCredentialProviders.contains(id) || app.providers.contains {
        string($0, "id") == id && $0["credential_configured"] as? Bool == true
      }
    }
    return Button {
      let entry = entry
      DispatchQueue.main.async {
        chooseRoute(entry.routes[0])
        choice = entry
      }
    } label: {
      ConnectionCardLabel(title: entry.name, subtitle: subtitle ?? "",
        status: keyAvailable ? "Key available" : "", featured: featured) {
        ProviderMark(providerID: entry.id)
          .frame(width: featured ? 36 : 24, height: featured ? 36 : 24)
      }
    }
    .buttonStyle(ConnectionChoiceStyle())
    .accessibilityIdentifier("provider." + entry.id)
  }

  private func detail(_ choice: Choice) -> some View {
    VStack(spacing: 0) {
      HStack(spacing: 10) {
        Button {
          DispatchQueue.main.async {
            self.choice = nil
            chooseRoute("")
          }
        } label: {
          Label("Providers", systemImage: "chevron.left")
        }.disabled(working)
        ProviderMark(providerID: choice.id).frame(width: 22, height: 22).accessibilityHidden(true)
        Text(choice.name).font(.title2.weight(.semibold)).accessibilityAddTraits(.isHeader)
        Spacer()
        if let url = URL(string: string(provider, "docs_url")), url.scheme == "https" {
          Link(destination: url) { Label("Provider docs", systemImage: "arrow.up.right.square") }
        }
      }.padding(.horizontal, 24).padding(.vertical, 14)
      if choice.routes.count > 1 {
        Picker("API route", selection: Binding(get: { route }, set: { chooseRoute($0) })) {
          ForEach(choice.routes, id: \.self) { id in Text(routeTitle(id)).tag(id) }
        }
        .pickerStyle(.segmented)
        .disabled(working)
        .padding(.horizontal, 24).padding(.bottom, 14)
      }
      Divider()
      HStack(spacing: 0) {
        modelPicker.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
        Divider()
        ScrollView {
          credentials.padding(18).frame(maxWidth: .infinity, alignment: .leading)
        }.frame(width: 284)
      }
      Divider()
      HStack {
        if !message.isEmpty {
          Text(message).font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
        }
        Spacer()
        if saving { ProgressView().controlSize(.small) }
        Button("Use provider", action: connect).buttonStyle(.borderedProminent).disabled(!canConnect)
      }.padding(.horizontal, 24).padding(.vertical, 12)
    }
    .task(id: "\(route):\(app.modelCatalogRevision)") { await loadCatalog(for: route) }
  }

  private var modelPicker: some View {
    let query = modelQuery.trimmingCharacters(in: .whitespacesAndNewlines)
    let workspaceIDs = Set(workspaceModels.map(\.id))
    let available = workspaceModels + models.filter { !workspaceIDs.contains($0.id) }
    let visible = query.isEmpty ? available : available.filter {
      $0.id.localizedCaseInsensitiveContains(query) || $0.name.localizedCaseInsensitiveContains(query)
    }
    return VStack(alignment: .leading, spacing: 0) {
      VStack(alignment: .leading, spacing: 8) {
        Text("Model").font(.headline).accessibilityAddTraits(.isHeader)
        ConnectionSearchField(title: "Search models", text: $modelQuery)
      }.padding(.horizontal, 18).padding(.top, 16).padding(.bottom, 8)
      ScrollView {
        LazyVStack(spacing: 5) {
          if visible.isEmpty {
            if catalogLoading && available.isEmpty {
              ProgressView("Loading models…").controlSize(.small)
            } else {
              Text(available.isEmpty ? "Enter a model ID below." : "No models match your search.")
                .font(.callout).foregroundStyle(.secondary)
            }
          }
          ForEach(visible) { row in
            let selected = modelID == row.id
            Button { selectedModel = row.id } label: {
              HStack(spacing: 10) {
                Image(systemName: selected ? "checkmark.circle.fill" : "circle")
                  .foregroundStyle(selected ? Color.qAccent : .secondary).accessibilityHidden(true)
                VStack(alignment: .leading, spacing: 2) {
                  Text(row.name).lineLimit(2)
                  if let detail = row.releaseDate ?? (row.name == row.id ? nil : row.id) {
                    Text(detail).font(.caption).foregroundStyle(.secondary).lineLimit(1)
                  }
                }
                Spacer(minLength: 0)
              }
              .padding(.horizontal, 10).padding(.vertical, 7).frame(minHeight: 36)
              .contentShape(Rectangle())
            }
            .buttonStyle(ConnectionChoiceStyle(selected: selected))
            .disabled(working)
            .accessibilityAddTraits(selected ? .isSelected : [])
          }
        }.padding(.horizontal, 18).padding(.vertical, 6).frame(maxWidth: .infinity, alignment: .leading)
      }.id(route)
      VStack(alignment: .leading, spacing: 4) {
        TextField("Model ID", text: $selectedModel).textFieldStyle(.roundedBorder).disabled(working)
          .accessibilityLabel("Model ID")
        if requiresPlan(modelID, for: route) {
          Text("Choose a model available through the Model Studio API.")
            .font(.caption).foregroundStyle(.secondary)
        }
        if !catalogError.isEmpty { Text(catalogError).font(.caption).foregroundStyle(.secondary) }
      }.padding(.horizontal, 18).padding(.vertical, 12)
    }
  }

  private var credentials: some View {
    VStack(alignment: .leading, spacing: 10) {
      Text("API key").font(.headline).accessibilityAddTraits(.isHeader)
      if configured {
        Label("Credential configured", systemImage: "checkmark.circle")
          .font(.callout).foregroundStyle(.secondary)
      }
      SecureField(configured ? "Replace API key (optional)" : "Enter API key", text: $key)
        .textFieldStyle(.roundedBorder).accessibilityLabel("API key")
      Toggle("Remember in Keychain", isOn: $remember).disabled(suppliedKey.isEmpty)
      if saved && !configured {
        Button(restoringKey ? "Opening Keychain…" : "Use saved key", action: useSavedKey)
      }
      if saved {
        Button("Forget saved key", role: .destructive, action: forgetKey)
      }
      let variables = (provider["credential_variables"] as? [String] ?? [])
        + (provider["optional_credential_variables"] as? [String] ?? [])
      if !variables.isEmpty {
        Text(variables.joined(separator: "\n")).font(.caption.monospaced()).foregroundStyle(.secondary)
          .textSelection(.enabled)
      }
      if let notes = Self.apiKeyNotes[route] ?? provider["notes"] as? String, !notes.isEmpty {
        Text(notes).font(.caption).foregroundStyle(.secondary)
      }
      if modelStudio {
        Divider().padding(.vertical, 3)
        TextField("Workspace endpoint (optional)", text: $workspaceEndpoint).textFieldStyle(.roundedBorder)
        HStack {
          Button("Load workspace models", action: loadWorkspaceModels)
            .disabled(workspaceLookup != nil || (suppliedKey.isEmpty && !configured))
          if workspaceLookup != nil { ProgressView().controlSize(.small) }
        }
        if !workspaceMessage.isEmpty {
          Text(workspaceMessage).font(.caption).foregroundStyle(.secondary)
        }
      }
      let endpoint = string(provider, modelStudio ? "workspace_base_url" : "default_base_url")
      if !endpoint.isEmpty {
        Text(endpoint).font(.caption.monospaced()).foregroundStyle(.secondary).textSelection(.enabled)
      }
    }
    .disabled(working)
    .onChange(of: key) { _, _ in resetWorkspaceModels() }
    .onChange(of: workspaceEndpoint) { _, _ in resetWorkspaceModels() }
  }

  private func routeTitle(_ id: String) -> String {
    switch id {
    case "qwen-intl": "International"
    case "qwen-cn": "China"
    case "alibaba": "DashScope"
    case "zai": "Z.AI"
    case "zhipu": "Zhipu"
    default: id
    }
  }

  private func chooseRoute(_ id: String) {
    guard route != id else { return }
    route = id
    let row = app.providers.first { string($0, "id") == id } ?? [:]
    selectedModel = id == app.provider ? app.model : ""
    key = ""
    message = ""
    models = []
    modelQuery = ""
    catalogError = ""
    catalogLoading = !id.isEmpty
    workspaceEndpoint = string(row, "workspace_endpoint_override")
    resetWorkspaceModels()
  }

  private func loadCatalog(for id: String) async {
    guard !id.isEmpty else { return }
    do {
      let payload = try await app.engine.call("providers.catalog.models", ["provider": id]) as? [String: Any] ?? [:]
      guard !Task.isCancelled, route == id else { return }
      let ids = payload["example_models"] as? [String] ?? []
      let names = payload["example_model_labels"] as? [String] ?? []
      models = ids.enumerated().compactMap { index, model in
        guard !requiresPlan(model, for: id) else { return nil }
        let label = index < names.count ? names[index] : model
        let modelSuffix = " · " + model
        if label.hasSuffix(modelSuffix) {
          return ModelRow(id: model, name: model, releaseDate: String(label.dropLast(modelSuffix.count)))
        }
        return ModelRow(id: model, name: label)
      }
      catalogError = ""
    } catch {
      guard !Task.isCancelled, route == id else { return }
      catalogError = "Model catalog unavailable. You can enter a model ID."
    }
    catalogLoading = false
  }

  private func useSavedKey() {
    let provider = route
    restoringKey = true
    message = ""
    Task {
      let restored = await app.restoreSavedProviderKey(provider)
      restoringKey = false
      if !restored { message = "The saved key could not be read." }
    }
  }

  private func forgetKey() {
    guard app.confirm("Forget this provider key?",
      "Remove the key saved by SuperQode from macOS Keychain.", button: "Forget key") else { return }
    let provider = route
    saving = true
    Task {
      defer { saving = false }
      do {
        try await app.forgetCredential(provider)
        resetWorkspaceModels()
        message = "Saved key removed."
      } catch { message = error.localizedDescription }
    }
  }

  private func resetWorkspaceModels() {
    workspaceLookup = nil
    workspaceModels = []
    workspaceMessage = ""
  }

  private func loadWorkspaceModels() {
    let lookup = UUID()
    workspaceLookup = lookup
    workspaceMessage = ""
    var params = ["provider": route, "endpoint": workspaceEndpoint]
    if !suppliedKey.isEmpty { params["key"] = suppliedKey }
    Task {
      defer { if workspaceLookup == lookup { workspaceLookup = nil } }
      do {
        let result = try await app.engine.call("providers.models", params) as? [String: Any] ?? [:]
        guard workspaceLookup == lookup else { return }
        let details = result["model_details"] as? [[String: Any]] ?? []
        let names = Dictionary(details.map { (string($0, "id"), string($0, "name")) },
          uniquingKeysWith: { first, _ in first })
        let ids = string(result, "source") == "live" ? result["models"] as? [String] ?? [] : []
        var seen = Set<String>()
        workspaceModels = ids.filter { !requiresPlan($0, for: route) && seen.insert($0).inserted }.map { ModelRow(id: $0, name: names[$0] ?? $0) }
        workspaceMessage = ids.isEmpty
          ? string(result, "error", "No workspace models returned.")
          : "Loaded \(workspaceModels.count) workspace models."
      } catch {
        guard workspaceLookup == lookup else { return }
        workspaceModels = []
        workspaceMessage = error.localizedDescription
      }
    }
  }

  private func connect() {
    guard canConnect else { return }
    saving = true
    message = ""
    let provider = route
    let model = modelID
    let key = suppliedKey
    let remember = remember
    let endpoint = workspaceEndpoint.trimmingCharacters(in: .whitespacesAndNewlines)
    let editedEndpoint = modelStudio && endpoint != string(self.provider, "workspace_endpoint_override")
      ? endpoint : nil
    Task {
      defer { saving = false }
      do {
        try await app.configureConnection(provider: provider, model: model, key: key,
          remember: remember, workspaceEndpoint: editedEndpoint)
        self.key = ""
        app.section = "Workspace"
        if !app.projectID.isEmpty { app.showWelcome = false }
        app.notice = app.projectID.isEmpty
          ? "Provider selected. Open a project to use it."
          : "Provider selected. Use Test model to verify the connection."
        dismiss()
      } catch { message = error.localizedDescription }
    }
  }
}

func codingModel(_ identifier: String) -> Bool {
  !identifier.localizedCaseInsensitiveContains("embed")
    && !identifier.localizedCaseInsensitiveContains("rerank")
}
func modelName(_ identifier: String) -> String {
  if let range = identifier.range(of: #"^(ollama|lmstudio):"#, options: .regularExpression) {
    return String(identifier[range.upperBound...])
  }
  return identifier
}

enum LocalPickerLayout { case classic, start }

/// Pick one installed local model and one harness, then start coding.
/// The `.start` layout is the shared Local AI Start view (see LocalAIStartView.swift).
struct InstalledLocalModelPicker: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  var dismissOnUse = false
  var active = true
  var preferredHarness = ""
  /// Local AI may embed a prompt after a model and harness are selected.
  var showsPrompt = false
  var openProject: (() -> Void)?
  var browseModels: (() -> Void)?
  var modelFit: [[String: Any]] = []
  var layout: LocalPickerLayout = .classic
  /// The Connect sheet uses a shorter header.
  var compact = false
  var openAdvanced: (() -> Void)?
  @State private var form: InstalledLocalDraft
  @State private var learnMore = false
  @State private var confirmLarge = false
  @State private var hideContinue = false
  @State private var downloadDraft = LocalQuickStartDraft()
  init(project: String, dismissOnUse: Bool = false, active: Bool = true, preferredHarness: String = "",
    showsPrompt: Bool = false, form: InstalledLocalDraft? = nil,
    openProject: (() -> Void)? = nil, browseModels: (() -> Void)? = nil,
    modelFit: [[String: Any]] = [], layout: LocalPickerLayout = .classic, compact: Bool = false,
    openAdvanced: (() -> Void)? = nil) {
    self.project = project; self.dismissOnUse = dismissOnUse; self.active = active
    self.preferredHarness = preferredHarness; self.showsPrompt = showsPrompt
    self.openProject = openProject; self.browseModels = browseModels; self.modelFit = modelFit
    self.layout = layout; self.compact = compact; self.openAdvanced = openAdvanced
    _form = State(initialValue: form ?? InstalledLocalDraft())
  }
  private var models: [[String: Any]] {
    get { form.models }
    nonmutating set { form.models = newValue }
  }
  private var engines: [[String: Any]] {
    get { form.engines }
    nonmutating set { form.engines = newValue }
  }
  private var harnesses: [[String: Any]] {
    get { form.harnesses }
    nonmutating set { form.harnesses = newValue }
  }
  private var harness: String {
    get { form.harness }
    nonmutating set { form.harness = newValue }
  }
  private var selected: String {
    get { form.selected }
    nonmutating set { form.selected = newValue }
  }
  private var inferenceEngine: String {
    get { form.inferenceEngine }
    nonmutating set { form.inferenceEngine = newValue }
  }
  private var failure: String {
    get { form.failure }
    nonmutating set { form.failure = newValue }
  }
  @State private var busy = false
  @State private var modelSearch = ""
  @State private var progress = ""
  @State private var showDownload = false
  private var step: String {
    get { form.step }
    nonmutating set { form.step = newValue }
  }
  private var prompt: String {
    get { form.prompt }
    nonmutating set { form.prompt = newValue }
  }
  @State private var serverRequest: [String: Any]?

  private var selectable: [[String: Any]] {
    harnesses.filter { $0["selectable"] as? Bool == true }
  }
  private var harnessRow: [String: Any]? {
    harnesses.first { string($0, "id") == harness }
  }
  private var needsInstall: Bool {
    guard let row = harnessRow else { return false }
    return row["selectable"] as? Bool != true && !string(row, "install_extra").isEmpty
  }
  private var visibleModels: [[String: Any]] {
    models.filter { row in
      let name = string(row, "model") + " " + string(row, "name")
      return !name.localizedCaseInsensitiveContains("mmproj")
        && (layout == .start || inferenceEngine.isEmpty || string(row, "engine") == inferenceEngine)
    }
  }
  private var filteredModels: [[String: Any]] {
    let query = modelSearch.trimmingCharacters(in: .whitespacesAndNewlines)
    return visibleModels.filter {
      query.isEmpty || (string($0, "name") + " " + string($0, "model")).localizedCaseInsensitiveContains(query)
    }
  }
  private var selectedRow: [String: Any]? {
    visibleModels.first { string($0, "id") == selected }
  }
  /// A local server job must not block coding. Agent runs still do.
  private var agentBusy: Bool {
    app.jobs.contains {
      string($0, "kind") != "local"
        && ["running", "needs_approval", "queued", "cancelling"].contains(string($0, "status"))
    }
  }
  private var canStart: Bool {
    guard !busy, !project.isEmpty, !harness.isEmpty, !needsInstall, let row = selectedRow, !agentBusy else { return false }
    return row["advertised"] as? Bool == true || engineReady(string(row, "engine"))
  }
  private var outgoingPrompt: String {
    showsPrompt ? prompt.trimmingCharacters(in: .whitespacesAndNewlines) : ""
  }
  private var actionTitle: String {
    if !outgoingPrompt.isEmpty { return "Send" }
    guard let row = selectedRow else { return "Start coding" }
    if row["advertised"] as? Bool == true { return "Start coding" }
    return "Start and code"
  }

  private var preparing: Bool { busy && !progress.isEmpty }
  private var warmupSubject: String {
    if progress.localizedCaseInsensitiveContains("install") {
      return string(harnessRow ?? [:], "name")
    }
    return string(selectedRow ?? [:], "name", string(selectedRow ?? [:], "model"))
  }

  var body: some View {
    Group {
      if layout == .start { startLayout } else { classicLayout }
    }
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .task(id: project + "\n" + String(active) + "\n" + String(form.refreshToken)) {
      guard active else { return }
      await load()
      if layout == .start { await loadStart() }
    }
    .onChange(of: inferenceEngine) { _, _ in
      if selectedRow == nil { selected = "" }
      failure = ""
    }
    .centeredDialog(isPresented: $showDownload, title: "Download a local model", onDismiss: {
      Task { await load(); if layout == .start { await loadStart() } }
    }) {
      LocalQuickStartView(project: project, showInstalled: false, form: downloadDraft).environmentObject(app)
    }
    .centeredDialog(
      isPresented: Binding(get: { serverRequest != nil }, set: { if !$0 { serverRequest = nil } }),
      title: "Review local operation", onDismiss: {
        Task { await load(); if layout == .start { await loadStart() } }
      }
    ) {
      if let serverRequest { LocalModelActionView(request: serverRequest).environmentObject(app) }
    }
    .centeredDialog(isPresented: $learnMore, title: "About Local AI") {
      LocalAILearnMoreView()
    }
  }

  private var classicLayout: some View {
    VStack(alignment: .leading, spacing: 14) {
      if preparing {
        ModelWarmupCard(message: progress, subject: warmupSubject)
      } else if step == "model" {
        Text("Installed models").font(.title2.weight(.semibold)).accessibilityAddTraits(.isHeader)
        modelStep
      } else if let row = selectedRow {
        Text("Choose a harness").font(.title2.weight(.semibold)).accessibilityAddTraits(.isHeader)
        Label(string(row, "name", string(row, "model")) + " · " + modelCaption(row), systemImage: "cpu")
          .font(.callout).foregroundStyle(.secondary)
        harnessStep
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      if showsPrompt && step == "harness" && !needsInstall && !preparing {
        TextField("Describe a change", text: $form.prompt, axis: .vertical)
          .lineLimit(2...5).textFieldStyle(.roundedBorder).disabled(busy)
          .accessibilityIdentifier("local.prompt")
      }
      if !preparing { actions }
    }
  }

  private var actions: some View {
    HStack {
      if step == "harness" {
        Button("Back to models") { step = "model"; failure = "" }.disabled(busy)
          .accessibilityIdentifier("local.back")
      }
      Button("Refresh") { Task { await load() } }.disabled(busy)
      Spacer()
      if step == "model" {
        Button("Download a model…") {
          if let browseModels { browseModels() } else { showDownload = true }
        }.disabled(busy)
        if !serverEngine.isEmpty {
          Button("Context and server…") { serverRequest = ["action": "serve", "engine": serverEngine] }
            .disabled(busy || agentBusy)
        }
        if project.isEmpty {
          Button("Open project…", action: openProject ?? app.chooseProject)
            .disabled(app.openingProject || !app.connected)
        } else {
          Button("Choose harness", action: chooseHarnessStep).buttonStyle(.borderedProminent)
            .disabled(busy || selectedRow == nil)
            .accessibilityIdentifier("local.chooseHarness")
        }
      } else if step == "harness" {
        if needsInstall {
          Button("Install harness…") { Task { await installSelected() } }
            .buttonStyle(.borderedProminent).disabled(busy || project.isEmpty)
            .accessibilityIdentifier("local.install")
        } else {
          Button(actionTitle) { Task { await startCoding() } }
            .buttonStyle(.borderedProminent).disabled(!canStart)
            .accessibilityIdentifier("local.startCoding")
        }
      }
    }
  }

  /// The selected model's server, or the first installed runtime.
  private var serverEngine: String {
    if let row = selectedRow, !string(row, "engine").isEmpty { return string(row, "engine") }
    if !inferenceEngine.isEmpty { return inferenceEngine }
    if let row = engines.first(where: { $0["installed"] as? Bool == true || $0["running"] as? Bool == true }) {
      return string(row, "id")
    }
    return ""
  }

  private var harnessStep: some View {
    Group {
      if !preferredHarness.isEmpty && !busy && !harnesses.contains(where: { string($0, "id") == preferredHarness }) {
        Text("The selected harness can’t use this local model setup. Choose a compatible harness below.")
          .font(.callout).foregroundStyle(.secondary)
      }
      if harnesses.isEmpty && busy {
        ProgressView("Loading harnesses…").controlSize(.small)
      } else if harnesses.isEmpty && !busy {
        Text("No harness here can run an Ollama or LM Studio model yet.")
          .foregroundStyle(.secondary)
      } else {
        harnessGrid(harnesses)
        if needsInstall {
          Text("Install this harness before connecting the model.").foregroundStyle(.secondary)
        }
      }
    }
  }

  private var modelStep: some View {
    VStack(alignment: .leading, spacing: 10) {
      if busy && models.isEmpty {
        ProgressView("Finding local models…").controlSize(.small)
      } else if models.isEmpty {
        Text("No Ollama or LM Studio models found. Download a model or connect a local server.")
          .foregroundStyle(.secondary)
      } else {
        Picker("Runtime", selection: $form.inferenceEngine) {
          Text("All runtimes").tag("")
          Text("Ollama").tag("ollama")
          Text("LM Studio").tag("lmstudio")
        }.pickerStyle(.segmented).disabled(busy)
        ConnectionSearchField(title: "Search models", text: $modelSearch)
        if filteredModels.isEmpty && !busy {
          Text("No models match your search.").foregroundStyle(.secondary)
        }
        ScrollView {
          LazyVStack(spacing: 5) {
            ForEach(filteredModels, id: \.projectRowID) { row in
              let active = selected == string(row, "id")
              Button {
                selected = string(row, "id")
                failure = ""
              } label: {
                HStack(spacing: 12) {
                  Image(systemName: active ? "checkmark.circle.fill" : "circle")
                    .foregroundStyle(active ? Color.qAccent : .secondary).accessibilityHidden(true)
                  VStack(alignment: .leading, spacing: 2) {
                    Text(string(row, "name", string(row, "model"))).font(.headline).lineLimit(2)
                    Text(modelCaption(row)).font(.caption).foregroundStyle(.secondary)
                  }
                  Spacer(minLength: 0)
                }
                .padding(.horizontal, 10).padding(.vertical, 7).frame(minHeight: 36)
                .contentShape(Rectangle())
              }
              .buttonStyle(ConnectionChoiceStyle(selected: active))
              .disabled(busy)
              .accessibilityAddTraits(active ? .isSelected : [])
            }
          }
        }.frame(maxHeight: 360)
        if let row = selectedRow { Text(readiness(row)).font(.callout).foregroundStyle(.secondary) }
      }
    }
  }

  private func harnessGrid(_ rows: [[String: Any]]) -> some View {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 205), spacing: 8)], spacing: 8) {
      ForEach(rows, id: \.projectRowID) { row in
        let id = string(row, "id")
        let active = harness == id
        Button {
          choose(id)
        } label: {
          let note = string(row, "note")
          ConnectionCardLabel(title: string(row, "name"),
            subtitle: string(row, "description"),
            status: row["selectable"] as? Bool == true ? "Ready to connect" : note) {
            Image(systemName: active ? "checkmark.circle.fill" : "cpu")
              .font(.title3).foregroundStyle(Color.qAccent)
          }
        }
        .buttonStyle(ConnectionChoiceStyle(selected: active))
        .disabled(busy)
        .accessibilityIdentifier("local.harness." + id)
        .accessibilityAddTraits(active ? .isSelected : [])
      }
    }
  }

  private func chooseHarnessStep() {
    if harness.isEmpty && harnesses.contains(where: { string($0, "id") == preferredHarness }) {
      harness = preferredHarness
    }
    step = "harness"
  }

  private func choose(_ id: String) {
    harness = id
    failure = ""
  }

  private func modelCaption(_ row: [String: Any]) -> String {
    let engine = string(row, "engine") == "lmstudio" ? "LM Studio" : "Ollama"
    var summary = [engine]
    if let size = row["size_gb"] as? Double, size > 0 {
      summary.append(String(format: "%.1f GB", size))
    }
    if let entry = fitRows.first(where: { $0.projectRowID == row.projectRowID }),
      let fit = entry["fit"] as? [String: Any], let rating = fit["rating"] as? String {
      summary.append(rating)
    }
    return summary.joined(separator: " · ")
  }

  private func readiness(_ row: [String: Any]) -> String {
    let engine = string(row, "engine") == "lmstudio" ? "LM Studio" : "Ollama"
    if row["advertised"] as? Bool == true { return "\(engine) is ready. Start coding connects this model." }
    if engineReady(string(row, "engine")) {
      if row["server_running"] as? Bool == true && string(row, "engine") == "lmstudio" {
        return "LM Studio is open. Start and code will load this model, then connect it."
      }
      return "\(engine) is installed and stopped. Start and code will launch it, then connect this model."
    }
    return "Install \(engine) to use this model."
  }

  private func engineReady(_ id: String) -> Bool {
    guard let row = engines.first(where: { string($0, "id") == id }) else { return false }
    return row["installed"] as? Bool == true || row["running"] as? Bool == true
  }

  private func load() async {
    busy = true
    defer { busy = false }
    do {
      try await reloadModels()
      guard !Task.isCancelled else { return }
      if !project.isEmpty {
        let options = try await app.engine.call("local.models.harnesses", ["project": project]) as? [[String: Any]] ?? []
        harnesses = options.filter { string($0, "id") != "apple-local" }
      }
      if !harness.isEmpty && !harnesses.contains(where: { string($0, "id") == harness }) {
        harness = ""
      }
      if let prepared = form.preparedModel {
        form.preparedModel = nil
        inferenceEngine = prepared.engine
        if let row = visibleModels.first(where: { string($0, "model") == prepared.model }) {
          selected = row.projectRowID
          chooseHarnessStep()
        } else {
          step = "model"
          failure = "Refresh to find the model you just set up."
          return
        }
      }
      if selectedRow == nil {
        selected = ""
        step = "model"
      }
      failure = ""
    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
  }

  private func installSelected() async {
    guard !project.isEmpty, needsInstall else { return }
    let name = string(harnessRow ?? [:], "name", "this harness")
    busy = true
    progress = "Installing \(name)…"
    defer { busy = false; progress = "" }
    do {
      let started = try await app.engine.call("local.models.install", [
        "project": project, "harness": harness,
      ]) as? [String: Any] ?? [:]
      if string(started, "status") == "completed" {
        await load()
        return
      }
      let id = string(started, "id")
      guard !id.isEmpty else { throw EngineError(message: "Could not start the install.") }
      for _ in 0..<600 {
        try await Task.sleep(for: .seconds(1))
        guard !Task.isCancelled else { throw CancellationError() }
        let status = try await app.engine.call(
          "local.models.install.status", ["id": id]
        ) as? [String: Any] ?? [:]
        if !string(status, "progress").isEmpty { progress = string(status, "progress") }
        let state = string(status, "status")
        if state == "completed" {
          await load()
          return
        }
        if state == "failed" {
          failure = string(status, "error", "The install did not finish.")
          return
        }
      }
      failure = "The install is still running. Press Install and continue again in a moment."
    } catch is CancellationError {
      return
    } catch {
      failure = error.localizedDescription
    }
  }

  private func reloadModels() async throws {
    let result = try await app.engine.call("local.models.installed") as? [String: Any] ?? [:]
    guard !Task.isCancelled else { return }
    models = result["models"] as? [[String: Any]] ?? []
    engines = result["engines"] as? [[String: Any]] ?? []
  }

  private func startCoding() async {
    guard canStart, let row = selectedRow else { return }
    let outgoing = outgoingPrompt
    busy = true
    progress = "Connecting…"
    var deliver = false
    defer {
      busy = false
      progress = ""
      if deliver { app.send(continueSession: false) }
    }
    do {
      let ready = try await bringOnline(row)
      await app.refreshJobs()
      guard app.projectID == project, !Task.isCancelled else { return }
      let otherWork = app.jobs.contains {
        string($0, "kind") != "local"
          && ["running", "needs_approval", "queued", "cancelling"].contains(string($0, "status"))
      }
      guard !otherWork else {
        failure = "Finish the current run, then connect this model."
        return
      }
      let result = try await app.engine.call("local.models.use", [
        "project": project,
        "engine": string(ready, "engine"),
        "model": string(ready, "model"),
        "harness": harness,
      ]) as? [String: Any] ?? [:]
      guard app.projectID == project else { return }
      let harnessID = string(result, "harness", harness)
      let providerID = string(result, "provider")
      let modelID = string(result, "model")
      guard !harnessID.isEmpty, !modelID.isEmpty else {
        failure = "The model connected, but Agent Space did not receive it. Choose the harness and model again."
        return
      }
      progress = "Warming the model so your first question is ready…"
      try await app.warmLocalModel(
        endpoint: string(result, "endpoint"),
        model: modelID,
        server: string(ready, "engine")
      )
      guard app.projectID == project, !Task.isCancelled else { return }
      // Leave the old thread first. Opening it restores that thread's route and
      // leaves Send disabled when this Mac has no connection yet.
      app.selectJob("", restoreConnection: false)
      app.checkingConnection = false
      if let route = result["route"] as? [String: Any] {
        app.chooseConnection(route)
        guard app.harness == string(route, "id") else { return }
        app.provider = providerID
        app.model = modelID
        app.savePreferences()
      } else {
        app.chooseHarness(harnessID)
        app.chooseModelRoute(providerID, modelID)
      }
      guard !app.connectionDisconnected, !app.model.isEmpty else {
        failure = "The model connected, but Agent Space did not keep it. Choose the harness and model again."
        return
      }
      app.section = "Workspace"
      app.showWelcome = false
      let model = modelID
      let harnessName = selectable.first { string($0, "id") == harnessID }
        .map { string($0, "name") } ?? harnessID
      if outgoing.isEmpty {
        app.notice = "Connected \(model) with \(harnessName). Type your request, then press Send."
      } else {
        prompt = ""
        app.draft = outgoing
        deliver = true
      }
      if dismissOnUse { dismiss() }
    } catch is CancellationError {
      return
    } catch {
      failure = error.localizedDescription
    }
  }

  /// Start a stopped server, or load an LM Studio weight, then return the advertised model.
  private func bringOnline(_ row: [String: Any]) async throws -> [String: Any] {
    if row["advertised"] as? Bool == true { return row }
    let engine = string(row, "engine")
    let name = engine == "lmstudio" ? "LM Studio" : "Ollama"
    guard engineReady(engine) else {
      throw EngineError(message: "Install \(name) to use this model.")
    }
    if row["server_running"] as? Bool != true {
      progress = "Starting \(name)…"
      try await startServer(engine, model: string(row, "model"))
    }
    if let match = try await waitForAdvertised(row) { return match }
    if engine == "lmstudio" {
      progress = "Loading the model in LM Studio…"
      try await runLocal([
        "action": "load", "engine": "lmstudio", "model": string(row, "model"), "context": 8192,
      ])
      if let match = try await waitForAdvertised(row) { return match }
    }
    throw EngineError(message: "\(name) started, but this model is not available yet. Refresh and try again.")
  }

  private func startServer(_ engine: String, model: String) async throws {
    if engine == "lmstudio" || model.isEmpty {
      try await runLocal(["action": "serve", "engine": engine, "kv_cache": "auto", "context": 8192, "model": ""])
      return
    }
    do {
      _ = try await app.engine.call("local.models.prepare", [
        "action": "serve", "engine": engine, "kv_cache": "auto", "context": 8192, "model": model,
      ])
    } catch {
      try await runLocal(["action": "serve", "engine": engine, "kv_cache": "auto", "context": 8192, "model": ""])
      return
    }
    try await runLocal(["action": "serve", "engine": engine, "kv_cache": "auto", "context": 8192, "model": model])
  }

  private func runLocal(_ request: [String: Any]) async throws {
    let plan = try await app.engine.call("local.models.prepare", request) as? [String: Any] ?? [:]
    guard !string(plan, "id").isEmpty else { throw EngineError(message: "Could not prepare the local server.") }
    let job = try await app.engine.call("local.models.start", [
      "plan": string(plan, "id"),
      "expected_digest": string(plan, "digest"),
      "command_id": UUID().uuidString,
    ]) as? [String: Any] ?? [:]
    let id = string(job, "id")
    guard !id.isEmpty else { throw EngineError(message: "Could not start the local server.") }
    for _ in 0..<180 {
      try await Task.sleep(for: .seconds(1))
      guard !Task.isCancelled else { throw CancellationError() }
      let row = try await app.engine.call("jobs.get", ["id": id]) as? [String: Any] ?? [:]
      let state = string(row, "status")
      if state == "completed" { return }
      if ["failed", "cancelled", "needs_approval"].contains(state) {
        let result = row["result"] as? [String: Any] ?? [:]
        throw EngineError(message: string(result, "error", "Could not finish starting the local server."))
      }
    }
    throw EngineError(message: "The local server is still starting. Wait a moment, then press Start coding again.")
  }

  private func waitForAdvertised(_ row: [String: Any]) async throws -> [String: Any]? {
    let engine = string(row, "engine")
    let model = string(row, "model")
    let needle = model.split(separator: "/").last.map(String.init)?.lowercased() ?? model.lowercased()
    for _ in 0..<20 {
      try await reloadModels()
      guard !Task.isCancelled else { throw CancellationError() }
      let advertised = models.filter { string($0, "engine") == engine && $0["advertised"] as? Bool == true }
      if let exact = advertised.first(where: { string($0, "model") == model }) { return exact }
      let matches = advertised.filter { string($0, "model").lowercased().contains(needle) && !needle.isEmpty }
      if matches.count == 1 { return matches[0] }
      try await Task.sleep(for: .seconds(1))
    }
    return nil
  }
}

// MARK: - Local AI Start layout
// Apple first, then Ollama and LM Studio, this Mac, models and a compact harness menu.
// Connecting reuses startCoding, installSelected and startServer above unchanged.

extension InstalledLocalModelPicker {
  private var fitRows: [[String: Any]] {
    modelFit.isEmpty ? (form.catalog["choices"] as? [[String: Any]] ?? []) : modelFit
  }
  private var startHardware: [String: Any] { form.catalog["hardware"] as? [String: Any] ?? [:] }
  private var startCapacity: [String: Any] { form.catalog["capacity"] as? [String: Any] ?? [:] }
  private var startStarter: [String: Any] { form.catalog["starter"] as? [String: Any] ?? [:] }
  private var otherEngines: [[String: Any]] {
    let rows = form.catalog["other_engines"] as? [[String: Any]] ?? []
    return rows.filter { $0["installed"] as? Bool == true || $0["running"] as? Bool == true }
  }
  /// Ollama and LM Studio, using the latest installed-model status first.
  private var mainEngines: [[String: Any]] {
    let catalogRows = form.catalog["engines"] as? [[String: Any]] ?? []
    var rows: [[String: Any]] = []
    for id in ["ollama", "lmstudio"] {
      if let row = engines.first(where: { string($0, "id") == id }) ?? catalogRows.first(where: { string($0, "id") == id }) {
        rows.append(row)
      }
    }
    return rows
  }
  private var anyEngineInstalled: Bool {
    mainEngines.contains { $0["installed"] as? Bool == true || $0["running"] as? Bool == true }
  }
  private var appleState: String { string(form.apple, "state") }
  private var appleReady: Bool {
    if let value = form.apple["available"] as? Bool { return value }
    return (form.apple["available"] as? NSNumber)?.boolValue ?? false
  }
  private var sortedModels: [[String: Any]] {
    filteredModels.enumerated().sorted { left, right in
      let a = fitOrder(fitRating(left.element))
      let b = fitOrder(fitRating(right.element))
      return a == b ? left.offset < right.offset : a < b
    }.map { $0.element }
  }
  private var continueSetup: [String: String]? {
    let saved = LocalAISetupMemory.load()
    guard !hideContinue, !saved.isEmpty, !project.isEmpty else { return nil }
    if saved["engine"] == "apple" { return appleReady ? saved : nil }
    let engine = saved["engine"] ?? ""
    let model = saved["model"] ?? ""
    let harnessID = saved["harness"] ?? ""
    guard models.contains(where: { string($0, "engine") == engine && string($0, "model") == model }),
      selectable.contains(where: { string($0, "id") == harnessID }) else { return nil }
    return saved
  }
  private var startBlocker: String? {
    if project.isEmpty { return "Open a project to start coding." }
    if agentBusy { return "Finish the current run, then start coding." }
    if form.appleSelected {
      return appleReady ? nil : "Apple's on-device model is not available right now."
    }
    guard let row = selectedRow else {
      return models.isEmpty ? "Add a model above to start coding." : "Choose a model above."
    }
    if harness.isEmpty { return "Choose a harness." }
    if needsInstall { return nil }
    if row["advertised"] as? Bool != true && !engineReady(string(row, "engine")) {
      return "Install " + engineName(string(row, "engine")) + " to use this model."
    }
    return nil
  }

  private func engineName(_ id: String) -> String {
    switch id {
    case "lmstudio": return "LM Studio"
    case "ollama": return "Ollama"
    case "apple": return "Apple on-device"
    default: return id
    }
  }
  private func harnessName(_ id: String) -> String {
    if id == "apple-local" { return "Apple on-device" }
    return harnesses.first { string($0, "id") == id }.map { string($0, "name", id) } ?? id
  }
  private func harnessTitle(_ row: [String: Any]) -> String {
    var title = string(row, "name", string(row, "id"))
    if row["recommended"] as? Bool == true { title += " (Recommended)" }
    if row["selectable"] as? Bool != true { title += " · needs install" }
    return title
  }
  private func fitRating(_ row: [String: Any]) -> String {
    guard let entry = fitRows.first(where: { $0.projectRowID == row.projectRowID }),
      let fit = entry["fit"] as? [String: Any] else { return "Unknown" }
    return string(fit, "rating", "Unknown")
  }
  private func fitOrder(_ rating: String) -> Int {
    switch rating {
    case "Fits": return 0
    case "Tight": return 1
    case "Too large": return 3
    default: return 2
    }
  }

  // MARK: Layout

  @ViewBuilder var startLayout: some View {
    if preparing {
      ModelWarmupCard(message: progress, subject: warmupSubject).padding(24)
    } else {
      VStack(spacing: 0) {
        ScrollView {
          VStack(alignment: .leading, spacing: 22) {
            startHeader
            if let saved = continueSetup { continueCard(saved) }
            appleCard
            enginesSection
            macSection
            modelsSection
          }.padding(24).frame(maxWidth: .infinity, alignment: .leading)
        }
        Divider()
        startFooter.padding(.horizontal, 24).padding(.vertical, 12).background(Color.qPanel)
      }
      .alert("This model may be too large for your Mac", isPresented: $confirmLarge) {
        Button("Start anyway") { beginCoding() }
        Button("Cancel", role: .cancel) {}
      } message: {
        Text("It can run slowly or make your Mac unresponsive. A model marked Fits is a better choice.")
      }
    }
  }

  private var startHeader: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(alignment: .center, spacing: 10) {
        VStack(alignment: .leading, spacing: 4) {
          if !compact {
            Text("Local AI").font(.largeTitle.weight(.semibold)).accessibilityAddTraits(.isHeader)
          }
          Text("Pick a model on this Mac, then start coding.")
            .font(compact ? .callout : .body).foregroundStyle(.secondary)
        }
        Spacer()
        Button("Refresh") { Task { await load(); await loadStart() } }.disabled(busy)
        nativeButton("local.runtimes.show", action: { openAdvanced?() }, title: "Advanced Local AI") {
          Label("Advanced Local AI…", systemImage: "slider.horizontal.3")
        }.disabled(openAdvanced == nil)
      }
      LocalAINotice(learnMore: $learnMore)
      if !preferredHarness.isEmpty && !harnesses.isEmpty
        && !harnesses.contains(where: { string($0, "id") == preferredHarness }) {
        Text("The harness you chose can't use a local model here, so a compatible one is selected below.")
          .font(.callout).foregroundStyle(.secondary)
      }
    }
  }

  private func continueCard(_ saved: [String: String]) -> some View {
    let apple = saved["engine"] == "apple"
    let model = saved["name"].flatMap { $0.isEmpty ? nil : $0 } ?? saved["model"] ?? ""
    let parts = apple
      ? ["Apple on-device model", "Built into your Mac"]
      : [model, engineName(saved["engine"] ?? ""), harnessName(saved["harness"] ?? "")]
    return HStack(spacing: 12) {
      Image(systemName: "arrow.uturn.forward.circle.fill").font(.title2).foregroundStyle(Color.qAccent)
        .accessibilityHidden(true)
      VStack(alignment: .leading, spacing: 2) {
        Text("Continue with " + parts.joined(separator: " · ")).font(.headline).lineLimit(2)
        Text("Your last local setup is still available.").font(.caption).foregroundStyle(.secondary)
      }
      Spacer()
      Button("Change") { hideContinue = true }.disabled(busy)
      Button("Continue") { continueWith(saved) }.buttonStyle(BrandButtonStyle())
        .disabled(busy || agentBusy)
        .accessibilityIdentifier("local.continue")
    }.padding(14).brandSurface()
  }

  // MARK: Built into your Mac

  private var appleStatusLine: String {
    switch appleState {
    case "": return "Checking availability…"
    case "ready": return "Ready on this Mac"
    case "intelligence-disabled": return "Turn on Apple Intelligence in System Settings to use it."
    case "model-not-ready": return "Apple Intelligence is still preparing the model. Keep your Mac on power and check again soon."
    case "device-ineligible", "unsupported-system": return "Not available on this Mac. Ollama or LM Studio below can run models locally instead."
    default: return string(form.apple, "guidance", "Not available right now.")
    }
  }

  private var appleCard: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Built into your Mac").font(.headline).accessibilityAddTraits(.isHeader)
      HStack(alignment: .center, spacing: 14) {
        Image(systemName: "apple.logo").font(.system(size: 26)).frame(width: 34).accessibilityHidden(true)
        VStack(alignment: .leading, spacing: 3) {
          Text("Apple on-device model").font(.headline)
          Text("Built into every Mac with Apple Intelligence, no download needed")
            .font(.callout).foregroundStyle(.secondary)
          Text(appleStatusLine).font(.caption).foregroundStyle(appleReady ? Color.green : Color.secondary)
            .accessibilityIdentifier("local.start.appleStatus")
        }
        Spacer(minLength: 8)
        appleAction
      }.padding(14).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
    }.accessibilityElement(children: .contain).accessibilityIdentifier("local.start.apple")
  }

  @ViewBuilder private var appleAction: some View {
    switch appleState {
    case "ready":
      Button("Use Apple model") {
        form.appleSelected = true
        startSelected()
      }.buttonStyle(BrandButtonStyle()).disabled(busy || agentBusy || project.isEmpty)
        .accessibilityIdentifier("local.useApple")
    case "intelligence-disabled":
      Button("Open System Settings") { openAppleIntelligenceSettings() }
    case "device-ineligible", "unsupported-system":
      EmptyView()
    default:
      Button("Check again") { Task { await loadApple() } }.disabled(busy)
    }
  }

  private func openAppleIntelligenceSettings() {
    for value in ["x-apple.systempreferences:com.apple.Siri-Settings.extension", "x-apple.systempreferences:"] {
      if let url = URL(string: value), NSWorkspace.shared.open(url) { return }
    }
  }

  // MARK: Inference engines

  private var enginesSection: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Inference engines on this Mac").font(.headline).accessibilityAddTraits(.isHeader)
      VStack(spacing: 0) {
        if mainEngines.isEmpty {
          HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            Text("Looking for Ollama and LM Studio…").foregroundStyle(.secondary)
            Spacer()
          }.padding(14)
        }
        ForEach(Array(mainEngines.enumerated()), id: \.offset) { index, row in
          if index > 0 { Divider() }
          engineRow(row)
        }
      }.brandSurface()
      if !mainEngines.isEmpty && !anyEngineInstalled {
        Text("Install LM Studio to get started. It can run quietly in the background.")
          .font(.callout).foregroundStyle(.secondary)
      }
      if !otherEngines.isEmpty {
        HStack(spacing: 6) {
          Text("Also found: " + otherEngines.map { string($0, "name", string($0, "id")) }.joined(separator: ", "))
            .font(.caption).foregroundStyle(.secondary)
          if openAdvanced != nil {
            Button("Open in Advanced") { openAdvanced?() }.buttonStyle(.link).font(.caption)
          }
        }
      }
    }
  }

  private func engineStatus(_ row: [String: Any]) -> String {
    let id = string(row, "id")
    if row["running"] as? Bool == true {
      let count = models.filter { string($0, "engine") == id }.count
      return "Running · \(count) " + (count == 1 ? "model" : "models")
    }
    return row["installed"] as? Bool == true ? "Installed · not running" : "Not installed"
  }

  private func engineRow(_ row: [String: Any]) -> some View {
    let id = string(row, "id")
    let installed = row["installed"] as? Bool == true
    let running = row["running"] as? Bool == true
    let cli = row["cli_available"] as? Bool == true
    let canServe = installed && (id != "lmstudio" || cli || running)
    let dot: Color = running ? .green : installed ? .orange : Color.secondary.opacity(0.4)
    return HStack(spacing: 10) {
      Circle().fill(dot).frame(width: 8, height: 8).accessibilityHidden(true)
      VStack(alignment: .leading, spacing: 2) {
        HStack(spacing: 6) {
          Text(string(row, "name", engineName(id))).font(.headline)
          if id == "lmstudio" && !installed && !running {
            Text("Recommended").font(.caption2).padding(.horizontal, 6).padding(.vertical, 2)
              .background(Color.qAccent.opacity(0.15), in: Capsule())
          }
        }
        Text(engineStatus(row)).font(.caption).foregroundStyle(.secondary)
      }
      Spacer()
      if id == "lmstudio" && !cli && !running {
        Button(installed ? "Set up LM Studio" : "Install LM Studio") {
          serverRequest = ["action": "install", "engine": "lmstudio"]
        }.disabled(busy)
      } else if id == "ollama" && !installed && !running {
        Link("Get Ollama", destination: URL(string: "https://ollama.com/download")!)
      } else if canServe && !running {
        Button("Start") { Task { await startEngine(id) } }.disabled(busy || agentBusy)
          .accessibilityIdentifier("local.engine.start." + id)
      }
      if canServe || running {
        engineMenu(id: id, canStop: row["can_stop"] as? Bool == true)
      }
    }.padding(.horizontal, 14).padding(.vertical, 10)
      .accessibilityElement(children: .contain).accessibilityIdentifier("local.engine." + id)
  }

  private func engineMenu(id: String, canStop: Bool) -> some View {
    Menu {
      Button("Context and server…") { serverRequest = ["action": "serve", "engine": id] }
      if let row = selectedRow, !form.appleSelected, string(row, "engine") == id, row["advertised"] as? Bool == true {
        Button("Unload " + string(row, "name", string(row, "model")) + "…") {
          serverRequest = ["action": "unload", "engine": id, "model": string(row, "model")]
        }
      }
      if canStop {
        Button("Stop server…") { serverRequest = ["action": "stop", "engine": id] }
      }
    } label: {
      Image(systemName: "ellipsis.circle")
    }
    .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize()
    .disabled(busy || agentBusy)
    .help("More actions for " + engineName(id))
    .accessibilityLabel("More actions for " + engineName(id))
  }

  // MARK: Your Mac

  private var macLine: String {
    var line = string(startHardware, "chip", "This Mac")
    if let memory = startHardware["unified_memory_gb"] as? Int { line += " · \(memory) GB memory" }
    return line
  }
  private var starterLine: String {
    let model = string(startStarter, "model")
    guard !model.isEmpty else { return "" }
    return startStarter["installed"] as? Bool == true
      ? "A good starter is already installed: " + model
      : "Suggested starter: " + model
  }

  private var macSection: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Your Mac").font(.headline).accessibilityAddTraits(.isHeader)
      VStack(alignment: .leading, spacing: 4) {
        if startHardware.isEmpty {
          Text("Checking chip and memory…").font(.callout).foregroundStyle(.secondary)
        } else {
          Label(macLine, systemImage: "laptopcomputer").font(.callout)
          if !string(startCapacity, "summary").isEmpty {
            Text(string(startCapacity, "summary")).font(.callout).foregroundStyle(.secondary)
          }
          if !starterLine.isEmpty {
            Text(starterLine).font(.callout).foregroundStyle(.secondary)
          }
        }
        if let warning = ((form.catalog["guardrails"] as? [String: Any])?["warnings"] as? [String])?.first {
          Text(warning).font(.caption).foregroundStyle(.orange)
        }
      }
      .padding(14).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
      .help("Estimates assume about 70% of memory is available to models, with headroom. They are guidance, not a guarantee.")
    }
  }

  // MARK: Models

  private var modelsSection: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Text("Models").font(.title3.weight(.semibold)).accessibilityAddTraits(.isHeader)
        Spacer()
        Button("Download a model…") { openDownload(choice: "") }.disabled(busy)
      }
      if visibleModels.count > 8 {
        ConnectionSearchField(title: "Search models", text: $modelSearch)
      }
      VStack(spacing: 5) {
        appleModelRow
        if busy && models.isEmpty {
          HStack(spacing: 8) {
            ProgressView().controlSize(.small)
            Text("Finding local models…").foregroundStyle(.secondary)
            Spacer()
          }.padding(10)
        } else if models.isEmpty {
          emptyModels
        } else {
          ForEach(sortedModels, id: \.projectRowID) { row in modelRow(row) }
          if filteredModels.isEmpty {
            Text("No models match your search.").foregroundStyle(.secondary).padding(10)
          }
        }
      }
      if !form.appleSelected, let row = selectedRow {
        Text(readiness(row)).font(.callout).foregroundStyle(.secondary)
      }
    }
  }

  @ViewBuilder private var emptyModels: some View {
    if !anyEngineInstalled {
      Text("Install an engine above to see your models.").foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading).padding(10)
    } else if !startStarter.isEmpty && startStarter["installed"] as? Bool != true {
      starterCard
    } else {
      Text("No Ollama or LM Studio models yet. Download a model to get started.").foregroundStyle(.secondary)
        .frame(maxWidth: .infinity, alignment: .leading).padding(10)
    }
  }

  private var starterCard: some View {
    let fit = startStarter["fit"] as? [String: Any] ?? [:]
    return HStack(spacing: 12) {
      Image(systemName: "arrow.down.circle.fill").font(.title2).foregroundStyle(Color.qAccent)
        .accessibilityHidden(true)
      VStack(alignment: .leading, spacing: 3) {
        Text("Get a starter model").font(.headline)
        Text(string(startStarter, "model") + " · " + engineName(string(startStarter, "engine"))).font(.callout)
        Text(string(fit, "verdict", "Size estimate unavailable")).font(.caption).foregroundStyle(.secondary)
      }
      Spacer()
      Button("Download") { openDownload(choice: string(startStarter, "id")) }
        .buttonStyle(BrandButtonStyle()).disabled(busy)
        .accessibilityIdentifier("local.starter.download")
    }.padding(14).brandSurface()
  }

  private var appleModelRow: some View {
    let chosen = form.appleSelected
    return Button {
      form.appleSelected = true
      failure = ""
    } label: {
      HStack(spacing: 12) {
        Image(systemName: chosen ? "checkmark.circle.fill" : "circle")
          .foregroundStyle(chosen ? Color.qAccent : Color.secondary).accessibilityHidden(true)
        Image(systemName: "apple.logo").frame(width: 16).accessibilityHidden(true)
        VStack(alignment: .leading, spacing: 2) {
          Text("Apple on-device model").font(.headline)
          Text(appleReady ? "Built in · no download" : appleStatusLine)
            .font(.caption).foregroundStyle(.secondary).lineLimit(2)
        }
        Spacer(minLength: 0)
        if appleReady { fitPill("Built in") }
      }
      .padding(.horizontal, 10).padding(.vertical, 7).frame(minHeight: 36)
      .contentShape(Rectangle())
    }
    .buttonStyle(ConnectionChoiceStyle(selected: chosen))
    .disabled(busy || !appleReady)
    .accessibilityIdentifier("local.model.apple")
    .accessibilityAddTraits(chosen ? .isSelected : [])
  }

  private func modelRow(_ row: [String: Any]) -> some View {
    let chosen = !form.appleSelected && selected == string(row, "id")
    let rating = fitRating(row)
    return Button {
      form.appleSelected = false
      selected = string(row, "id")
      failure = ""
    } label: {
      HStack(spacing: 12) {
        Image(systemName: chosen ? "checkmark.circle.fill" : "circle")
          .foregroundStyle(chosen ? Color.qAccent : Color.secondary).accessibilityHidden(true)
        VStack(alignment: .leading, spacing: 2) {
          Text(string(row, "name", string(row, "model"))).font(.headline).lineLimit(2)
          Text(modelDetail(row, rating: rating)).font(.caption).foregroundStyle(.secondary)
        }
        Spacer(minLength: 0)
        if rating != "Unknown" { fitPill(rating) }
      }
      .padding(.horizontal, 10).padding(.vertical, 7).frame(minHeight: 36)
      .contentShape(Rectangle())
    }
    .buttonStyle(ConnectionChoiceStyle(selected: chosen))
    .disabled(busy)
    .accessibilityIdentifier("local.model." + string(row, "id"))
    .accessibilityAddTraits(chosen ? .isSelected : [])
  }

  private func modelDetail(_ row: [String: Any], rating: String) -> String {
    var parts = [engineName(string(row, "engine"))]
    if let size = row["size_gb"] as? Double, size > 0 { parts.append(String(format: "%.1f GB", size)) }
    if rating == "Too large" { parts.append("May slow down your Mac") }
    return parts.joined(separator: " · ")
  }

  private func fitPill(_ rating: String) -> some View {
    let color: Color
    switch rating {
    case "Fits": color = .green
    case "Tight": color = .orange
    case "Too large": color = .red
    default: color = .secondary
    }
    return Text(rating).font(.caption.weight(.semibold)).foregroundStyle(color)
      .padding(.horizontal, 8).padding(.vertical, 3)
      .background(color.opacity(0.14), in: Capsule())
  }

  // MARK: Footer

  private var startFooter: some View {
    HStack(spacing: 12) {
      if form.appleSelected {
        Label("Harness: Apple on-device", systemImage: "apple.logo").font(.callout).foregroundStyle(.secondary)
      } else if !harnesses.isEmpty {
        Picker("Harness:", selection: $form.harness) {
          ForEach(harnesses, id: \.projectRowID) { row in
            Text(harnessTitle(row)).tag(string(row, "id"))
          }
        }
        .pickerStyle(.menu).fixedSize().disabled(busy)
        .accessibilityIdentifier("local.harnessPicker")
      }
      if let reason = startBlocker {
        Text(reason).font(.callout).foregroundStyle(.secondary).lineLimit(2)
        if project.isEmpty {
          Button("Open project…", action: openProject ?? app.chooseProject)
            .disabled(app.openingProject || !app.connected)
        }
      } else if !failure.isEmpty {
        Text(failure).font(.callout).foregroundStyle(.orange).lineLimit(3).textSelection(.enabled)
      }
      Spacer(minLength: 8)
      if !form.appleSelected && needsInstall {
        Button("Install harness…") { Task { await installSelected() } }
          .buttonStyle(BrandButtonStyle()).disabled(busy || project.isEmpty)
          .accessibilityIdentifier("local.install")
      } else {
        Button("Start coding") { startSelected() }
          .buttonStyle(BrandButtonStyle()).disabled(startBlocker != nil || busy)
          .accessibilityIdentifier("local.startCoding")
      }
    }
  }

  // MARK: Actions

  private func continueWith(_ saved: [String: String]) {
    if saved["engine"] == "apple" {
      form.appleSelected = true
      startSelected()
      return
    }
    let engine = saved["engine"] ?? ""
    let model = saved["model"] ?? ""
    guard let row = models.first(where: { string($0, "engine") == engine && string($0, "model") == model }) else { return }
    form.appleSelected = false
    selected = string(row, "id")
    if let remembered = saved["harness"], !remembered.isEmpty { harness = remembered }
    startSelected()
  }

  private func startSelected() {
    guard startBlocker == nil, !busy else { return }
    if form.appleSelected {
      startApple()
      return
    }
    guard let row = selectedRow else { return }
    if fitRating(row) == "Too large" {
      confirmLarge = true
      return
    }
    beginCoding()
  }

  /// Uses the same startCoding path, warm-up card and progress text as before.
  private func beginCoding() {
    guard let row = selectedRow else { return }
    let engine = string(row, "engine")
    let model = string(row, "model")
    let name = string(row, "name", model)
    let chosen = harness
    let workspace = app
    let draft = form
    Task {
      await startCoding()
      if draft.failure.isEmpty && !workspace.connectionDisconnected && !workspace.model.isEmpty
        && workspace.section == "Workspace" {
        LocalAISetupMemory.save(engine: engine, model: model, name: name, harness: chosen)
      }
    }
  }

  /// Apple's system model needs no server or warm-up, so it connects at once.
  private func startApple() {
    let workspace = app
    workspace.selectJob("", restoreConnection: false)
    workspace.checkingConnection = false
    workspace.chooseAppleModel(development: true)
    workspace.showWelcome = false
    workspace.notice = "Connected Apple's on-device model. Type your request, then press Send."
    LocalAISetupMemory.save(engine: "apple", model: "system-on-device", name: "Apple on-device model", harness: "apple-local")
    if dismissOnUse { dismiss() }
  }

  private func startEngine(_ id: String) async {
    busy = true
    progress = "Starting " + engineName(id) + "…"
    do {
      try await startServer(id, model: "")
      failure = ""
    } catch is CancellationError {
      busy = false
      progress = ""
      return
    } catch {
      failure = error.localizedDescription
    }
    busy = false
    progress = ""
    await load()
    await loadStart()
  }

  private func openDownload(choice: String) {
    if !choice.isEmpty && string(downloadDraft.step, "step") != "working" {
      downloadDraft.selection = choice
    }
    showDownload = true
  }

  // MARK: Loading

  private func loadApple() async {
    guard app.connected else { return }
    do {
      let result = try await app.engine.call("local.apple.status") as? [String: Any] ?? [:]
      if !Task.isCancelled { form.apple = result }
    } catch {
      if !Task.isCancelled {
        form.apple = ["available": false, "state": "unavailable", "guidance": error.localizedDescription]
      }
    }
  }

  func loadStart() async {
    await loadApple()
    do {
      let result = try await app.engine.call("local.models.quickstart.catalog", ["project": project]) as? [String: Any] ?? [:]
      guard !Task.isCancelled else { return }
      form.catalog = result
    } catch {
      if !Task.isCancelled && failure.isEmpty { failure = error.localizedDescription }
    }
    preselect()
  }

  /// Harness: the one chosen first in Connect, then the remembered one, then Core.
  /// Model: the remembered one, then the first that Fits, then Apple when nothing else is installed.
  private func preselect() {
    let saved = LocalAISetupMemory.load()
    let ids = harnesses.map { string($0, "id") }
    if harness.isEmpty || !ids.contains(harness) || (!form.preselected && ids.contains(preferredHarness)) {
      if ids.contains(preferredHarness) {
        harness = preferredHarness
      } else if let remembered = saved["harness"], selectable.contains(where: { string($0, "id") == remembered }) {
        harness = remembered
      } else if let row = harnesses.first(where: { $0["recommended"] as? Bool == true }) ?? selectable.first {
        harness = string(row, "id")
      }
    }
    guard !form.preselected, !models.isEmpty || appleReady else { return }
    form.preselected = true
    guard selectedRow == nil, !form.appleSelected else { return }
    let engine = saved["engine"] ?? ""
    let model = saved["model"] ?? ""
    if let row = models.first(where: { string($0, "engine") == engine && string($0, "model") == model }) {
      selected = string(row, "id")
    } else if engine == "apple" && appleReady {
      form.appleSelected = true
    } else if let row = sortedModels.first(where: { fitRating($0) == "Fits" })
      ?? sortedModels.first(where: { fitRating($0) != "Too large" }) {
      selected = string(row, "id")
    } else if models.isEmpty && appleReady {
      form.appleSelected = true
    }
  }
}

struct RouteReadiness: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    HStack(spacing: 10) {
      Image(
        systemName: app.routeStatus["ready"] as? Bool == true ? "checkmark.circle" : "info.circle"
      ).foregroundStyle(app.routeStatus["ready"] as? Bool == true ? Color.green : .secondary)
      Text(string(app.routeStatus, "message", "Choose a model to get started.")).font(.caption)
        .foregroundStyle(.secondary)
      Spacer()
      Button("Choose connection…") { app.showConnection = true }.font(.caption)
    }.task(id: app.provider + "\n" + app.model + "\n" + app.harness) {
      try? await Task.sleep(for: .milliseconds(350))
      guard !Task.isCancelled else { return }
      await app.checkRoute()
    }
  }
}
