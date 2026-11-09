import AppKit
import SwiftUI

struct ConnectionSourcesView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  @State private var mode = "Local model"
  @State private var selectedProvider = "openai"
  @State private var selectedModel = ""
  @State private var key = ""
  @State private var remember = true
  @State private var saving = false
  @State private var message = ""
  init(mode: String) { _mode = State(initialValue: mode) }
  private var cloudProviders: [[String: Any]] {
    app.providers.filter { provider in
      guard provider["key_supported"] as? Bool == true else { return false }
      let selected = app.harnesses.first { string($0, "id") == app.harness } ?? [:]
      if let allowed = selected["byok_providers"] as? [String] {
        return allowed.contains(string(provider, "id"))
      }
      return true
    }
  }
  private var featuredProviders: [[String: Any]] {
    cloudProviders.filter { ["deepseek", "qwen-cn", "qwen-intl", "alibaba", "moonshot", "zai", "zhipu", "minimax", "doubao", "siliconflow", "openrouter"].contains(string($0, "id")) }
  }
  private var cloud: [String: Any] {
    cloudProviders.first { string($0, "id") == selectedProvider } ?? [:]
  }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        Picker("Model source", selection: $mode) {
          Text("Local model").tag("Local model")
          Text("Provider API key").tag("Provider API key")
        }.pickerStyle(.segmented)
        PageTitle(
          eyebrow: "Connect a model",
          title: mode == "Local model" ? "Choose a local model" : "Use your API key",
          subtitle: "For "
            + string(
              app.harnesses.first { string($0, "id") == app.harness } ?? [:], "name", app.harness))
        if mode == "Local model" {
          localContent
        } else if cloudProviders.isEmpty {
          EmptyState(
            icon: "info.circle", title: "This model source needs different setup",
            detail:
              "This harness does not declare an API provider supported by this picker. Go Back to choose another source, or use its terminal setup workflow."
          ).frame(height: 200)
        } else {
          cloudContent
        }
        if !message.isEmpty {
          Label(message, systemImage: "info.circle").font(.callout).foregroundStyle(.secondary)
            .textSelection(.enabled)
        }
        if saving { ProgressView().controlSize(.small) }
      }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
    }.defaultScrollAnchor(.top)
      .task(id: mode) {
        if mode == "Local model" { await app.refreshModels() }
      }
      .onAppear {
        if !cloudProviders.contains(where: { string($0, "id") == selectedProvider }),
          let first = cloudProviders.first
        {
          selectedProvider = string(first, "id")
        }
      }
      .onChange(of: mode) { _, _ in
        key = ""
        message = ""
      }
      .onChange(of: selectedProvider) { _, _ in
        key = ""
        selectedModel = selectedProvider == app.provider ? app.model : ""
        message = ""
      }
  }

  private var localContent: some View {
    LocalQuickStartView(project: app.projectID).id(app.projectID).environmentObject(app)
  }

  private var cloudContent: some View {
    VStack(alignment: .leading, spacing: 16) {
      if !featuredProviders.isEmpty {
        Text("Chinese models and aggregators").font(.headline)
        Text("Choose a provider to see its key type, model examples and official setup guide. API keys and coding-plan subscriptions use different routes.")
          .font(.caption).foregroundStyle(.secondary)
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 150))], alignment: .leading) {
          ForEach(featuredProviders, id: \.projectRowID) { provider in
            Button(string(provider, "name")) {
              selectedProvider = string(provider, "id")
            }.disabled(saving)
          }
        }
      }
      Picker("Provider", selection: $selectedProvider) {
        ForEach(cloudProviders, id: \.projectRowID) { row in
          Text(string(row, "name")).tag(string(row, "id"))
        }
      }
      if !string(cloud, "notes").isEmpty { Text(string(cloud, "notes")).font(.callout).foregroundStyle(.secondary) }
      if !string(cloud, "default_base_url").isEmpty {
        Text("Default endpoint: " + string(cloud, "default_base_url")).font(.caption.monospaced()).textSelection(.enabled)
      }
      Text("Key environment variable: " + (cloud["credential_variables"] as? [String] ?? []).joined(separator: " or "))
        .font(.caption).foregroundStyle(.secondary)
      if let url = URL(string: string(cloud, "docs_url")), url.scheme == "https", url.user == nil, url.password == nil {
        Link("Official provider setup and pricing", destination: url)
      }
      HStack {
        TextField("Model ID", text: $selectedModel).textFieldStyle(.roundedBorder)
        Menu("Catalog examples") {
          ForEach(cloud["example_models"] as? [String] ?? [], id: \.self) { model in
            Button(model) { selectedModel = model }
          }
        }
      }
      Text(
        "Examples come from the installed engine catalog. You can enter another model ID supported by this provider."
      ).font(.caption).foregroundStyle(.secondary)
      SecureField(
        cloud["credential_configured"] as? Bool == true
          ? "Credential configured · enter a key to replace it" : "API key", text: $key
      ).textFieldStyle(.roundedBorder)
      Toggle("Remember new key in macOS Keychain", isOn: $remember).disabled(key.isEmpty)
      Text(
        "Saved keys stay in this Mac’s Keychain. Session-only keys are discarded when the local engine exits. Saving a key does not verify it or send a model request."
      ).font(.caption).foregroundStyle(.secondary)
      if cloud["credential_configured"] as? Bool == true {
        Pill(title: "CREDENTIAL CONFIGURED · NOT VERIFIED", color: .orange)
      }
      HStack {
        Spacer()
        if app.savedCredentialProviders.contains(selectedProvider) {
          Button("Forget saved key", role: .destructive) {
            guard
              app.confirm(
                "Forget this provider key?",
                "Remove only the key saved by the native SuperQode app. Existing terminal credentials remain available.",
                button: "Forget key")
            else { return }
            saving = true
            Task {
              do {
                try await app.forgetCredential(selectedProvider)
                message = "App-owned key removed."
              } catch { message = error.localizedDescription }
              saving = false
            }
          }.disabled(saving)
        }
        Button("Use provider") { connect() }.buttonStyle(BrandButtonStyle())
          .disabled(
            saving || cloudProviders.isEmpty
              || selectedModel.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
              || (key.isEmpty && cloud["credential_configured"] as? Bool != true))
      }
    }
  }

  private func connect() {
    saving = true
    message = ""
    let supplied = key
    Task {
      defer {
        key = ""
        saving = false
      }
      do {
        try await app.configureConnection(
          provider: selectedProvider, model: selectedModel, key: supplied, remember: remember)
        app.section = "Workspace"
        app.notice =
          "Provider selected. Credentials are configured; use Test model to verify execution."
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
  identifier.hasPrefix("ollama:") ? String(identifier.dropFirst(7)) : identifier
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
