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
  private var cloud: [String: Any] {
    cloudProviders.first { string($0, "id") == selectedProvider } ?? [:]
  }
  private var supportsOllama: Bool {
    let selected = app.harnesses.first { string($0, "id") == app.harness } ?? [:]
    return (selected["local_providers"] as? [String])?.contains("ollama") ?? true
  }
  private var localModels: [[String: Any]] {
    let selected = app.harnesses.first { string($0, "id") == app.harness } ?? [:]
    if let allowed = selected["local_providers"] as? [String], !allowed.contains("ollama") {
      return []
    }
    return app.models.filter {
      string($0, "source") == "ollama" && codingModel(string($0, "model_id"))
    }
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
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
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Label("Ollama", systemImage: "desktopcomputer").font(.headline)
        Spacer()
        Button("Refresh") { app.perform { await app.refreshModels() } }
        Button("Open Ollama") { openOllama() }.disabled(!supportsOllama)
      }
      Text(
        "Choose a chat or coding model already installed on your Ollama server. Cached weights from other engines remain visible in Models."
      ).font(.callout).foregroundStyle(.secondary)
      if localModels.isEmpty {
        EmptyState(
          icon: "cpu",
          title: supportsOllama
            ? "No coding models available yet" : "This harness does not support Ollama",
          detail: supportsOllama
            ? "Open Ollama and install a chat or coding model, then refresh this list. No weights are downloaded automatically."
            : "Go Back to choose a model source declared by this harness. Installing more models will not change its supported providers."
        ).frame(height: 190)
      } else {
        ScrollView {
          LazyVStack(spacing: 8) {
            ForEach(localModels, id: \.projectRowID) { row in
              HStack {
                VStack(alignment: .leading, spacing: 5) {
                  Text(modelName(string(row, "model_id"))).font(.headline)
                  Text(String(format: "%.1f GB", row["size_gb"] as? Double ?? 0)).font(
                    .caption.monospaced()
                  ).foregroundStyle(.secondary)
                }
                Spacer()
                if row["loaded"] as? Bool == true { Pill(title: "LOADED", color: .green) }
                Button("Use model") {
                  app.chooseModelRoute("ollama", modelName(string(row, "model_id")))
                  app.section = "Workspace"
                  app.selectJob("")
                  app.perform { await app.checkRoute() }
                  app.notice =
                    "Local model selected. Run a task or test the connection from Models."
                  dismiss()
                }.buttonStyle(BrandButtonStyle())
              }.padding(14).background(
                .primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 9))
            }
          }
        }.frame(height: 280).defaultScrollAnchor(.top)
      }
    }
  }

  private var cloudContent: some View {
    VStack(alignment: .leading, spacing: 16) {
      Picker("Provider", selection: $selectedProvider) {
        ForEach(cloudProviders, id: \.projectRowID) { row in
          Text(string(row, "name")).tag(string(row, "id"))
        }
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
        if let url = URL(string: string(cloud, "docs_url")), url.scheme == "https" {
          Link("Provider setup", destination: url)
        }
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
        app.selectJob("")
        app.notice =
          "Provider selected. Credentials are configured; use Test model to verify execution."
        dismiss()
      } catch { message = error.localizedDescription }
    }
  }

  private func openOllama() {
    let candidates = ["/Applications/Ollama.app", NSHomeDirectory() + "/Applications/Ollama.app"]
    if let path = candidates.first(where: { FileManager.default.fileExists(atPath: $0) }) {
      NSWorkspace.shared.openApplication(
        at: URL(fileURLWithPath: path), configuration: NSWorkspace.OpenConfiguration()
      ) { _, _ in }
    } else {
      message = "Ollama is not installed in Applications. Install and open it, then return here."
      if let url = URL(string: "https://ollama.com/download/mac") { NSWorkspace.shared.open(url) }
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
