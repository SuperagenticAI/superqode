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
      chooseRoute(entry.routes[0])
      choice = entry
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
          self.choice = nil
          chooseRoute("")
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

/// Pick one installed local model and one harness, then start coding.
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
  @State private var form: InstalledLocalDraft
  init(project: String, dismissOnUse: Bool = false, active: Bool = true, preferredHarness: String = "",
    showsPrompt: Bool = false, form: InstalledLocalDraft? = nil,
    openProject: (() -> Void)? = nil, browseModels: (() -> Void)? = nil,
    modelFit: [[String: Any]] = []) {
    self.project = project; self.dismissOnUse = dismissOnUse; self.active = active
    self.preferredHarness = preferredHarness; self.showsPrompt = showsPrompt
    self.openProject = openProject; self.browseModels = browseModels; self.modelFit = modelFit
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
        && (inferenceEngine.isEmpty || string(row, "engine") == inferenceEngine)
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
    .frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    .task(id: project + "\n" + String(active) + "\n" + String(form.refreshToken)) {
      guard active else { return }
      await load()
    }
    .onChange(of: inferenceEngine) { _, _ in
      if selectedRow == nil { selected = "" }
      failure = ""
    }
    .centeredDialog(isPresented: $showDownload, title: "Download a local model", onDismiss: {
      Task { await load() }
    }) {
      LocalQuickStartView(project: project, showInstalled: false).environmentObject(app)
    }
    .centeredDialog(
      isPresented: Binding(get: { serverRequest != nil }, set: { if !$0 { serverRequest = nil } }),
      title: "Review local operation"
    ) {
      if let serverRequest { LocalModelActionView(request: serverRequest).environmentObject(app) }
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
    if let entry = modelFit.first(where: { $0.projectRowID == row.projectRowID }),
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
