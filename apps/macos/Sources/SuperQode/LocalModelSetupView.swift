import AppKit
import SwiftUI

/// Account verification and storage changes never select an inference provider.
struct LocalModelSetupView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  @State private var storage: [String: Any] = [:]
  @State private var hub: [String: Any] = [:]
  @State private var path = ""
  @State private var token = ""
  @State private var remember = false
  @State private var message = ""
  @State private var failure = ""
  @State private var busy = false
  @State private var closed = false

  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      Text("Storage & Hugging Face access").font(.title2.weight(.semibold))
      ScrollView {
        VStack(alignment: .leading, spacing: 16) {
          VStack(alignment: .leading, spacing: 10) {
            Label("Model storage", systemImage: "externaldrive").font(.headline)
            TextField("Hugging Face cache directory", text: $path).textFieldStyle(.roundedBorder)
            HStack {
              Text("Free: " + localBytes(storage["free_bytes"])).font(.caption).foregroundStyle(.secondary)
              Spacer()
              Button("Choose folder…", action: chooseFolder)
              Button("Use default") { saveStorage("") }
              Button("Save location") { saveStorage(path) }
            }
            Text(string(storage, "note")).font(.caption).foregroundStyle(.secondary)
            Text("Changing storage requires a fresh download review. No existing models are moved or deleted.")
              .font(.caption).foregroundStyle(.secondary)
          }.padding(16).brandSurface()
          VStack(alignment: .leading, spacing: 10) {
            HStack {
              Label("Hugging Face", systemImage: "person.crop.circle").font(.headline)
              Spacer(); Pill(title: string(hub, "source", "Public access"))
            }
            Text(string(hub, "note")).font(.caption).foregroundStyle(.secondary)
            SecureField("User access token", text: $token).textFieldStyle(.roundedBorder)
            Toggle("Remember in macOS Keychain", isOn: $remember).toggleStyle(.checkbox)
            HStack {
              Link("Create an access token", destination: URL(string: "https://huggingface.co/settings/tokens")!)
              Spacer()
              if app.savedCredentialProviders.contains("huggingface") || string(hub, "source") == "App session / Keychain" {
                Button("Disconnect app token") { disconnect() }
              }
              Button(token.isEmpty ? "Check existing access" : "Verify & connect") { connect() }
                .disabled(token.isEmpty && hub["configured"] as? Bool != true)
            }
            Text("Verification makes an account request to Hugging Face. Tokens stay out of download plans and job history. This does not select paid inference or start a model download.")
              .font(.caption).foregroundStyle(.secondary)
          }.padding(16).brandSurface()
          if !message.isEmpty { Text(message).foregroundStyle(.green).textSelection(.enabled) }
          if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
        }
      }.disabled(busy)
      HStack {
        if busy { ProgressView().controlSize(.small) }
        Spacer()
        Button("Done") { closed = true; token = ""; dismiss() }.buttonStyle(BrandButtonStyle()).keyboardShortcut(.cancelAction)
      }
    }.padding(24).frame(width: 780, height: 620)
      .task { await refresh() }
      .onDisappear { closed = true; token = "" }
  }

  private func refresh() async {
    do {
      let saved = try await app.engine.call("local.models.storage") as? [String: Any] ?? [:]
      let account = try await app.engine.call("local.models.hub.status") as? [String: Any] ?? [:]
      guard !closed, !Task.isCancelled else { return }
      storage = saved; path = string(saved, "hf_cache"); hub = account
    } catch { failure = error.localizedDescription }
  }
  private func saveStorage(_ value: String) {
    busy = true; failure = ""; message = ""
    Task {
      defer { busy = false }
      do {
        let saved = try await app.engine.call("local.models.storage.set", ["hf_cache": value]) as? [String: Any] ?? [:]
        guard !closed else { return }
        storage = saved; path = string(saved, "hf_cache"); message = "Download location saved. Existing weights were kept."
      } catch { failure = error.localizedDescription }
    }
  }
  private func connect() {
    let entered = token.trimmingCharacters(in: .whitespacesAndNewlines)
    let persist = remember
    busy = true; failure = ""; message = ""
    Task {
      defer { busy = false; token = "" }
      do {
        let result = try await app.engine.call("local.models.hub.verify", entered.isEmpty ? [:] : ["token": entered]) as? [String: Any] ?? [:]
        guard !closed else { return }
        if !entered.isEmpty { try await app.storeProviderCredential("huggingface", key: entered, remember: persist) }
        guard !closed else { return }
        message = "Connected as " + string(result, "name") + ". " + string(result, "note")
        await refresh()
      } catch { failure = error.localizedDescription }
    }
  }
  private func disconnect() {
    busy = true; failure = ""; message = ""
    Task {
      defer { busy = false }
      do {
        try await app.forgetCredential("huggingface")
        guard !closed else { return }; message = "App token removed. Existing Hub environment/store access is unchanged."; await refresh()
      } catch { failure = error.localizedDescription }
    }
  }
  private func chooseFolder() {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = true; panel.canChooseFiles = false; panel.canCreateDirectories = true
    panel.allowsMultipleSelection = false
    if panel.runModal() == .OK, let url = panel.url { path = url.path }
  }
}
