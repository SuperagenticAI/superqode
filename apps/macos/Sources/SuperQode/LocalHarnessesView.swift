import SwiftUI

/// Advanced only. The newcomer Local AI path has no harness choices.
struct LocalHarnessesView: View {
  @EnvironmentObject var app: Workspace
  @State private var catalog: [String: Any] = [:]
  @State private var harness = "superqode"
  @State private var modelID = ""
  @State private var plan: [String: Any] = [:]
  @State private var message = ""
  @State private var failure = ""
  @State private var loading = false
  @State private var checking = false
  @State private var launching = false
  @State private var commandID = UUID().uuidString
  @State private var generation = 0

  private var harnesses: [[String: Any]] { catalog["harnesses"] as? [[String: Any]] ?? [] }
  private var models: [[String: Any]] { catalog["models"] as? [[String: Any]] ?? [] }
  private var selection: [String: Any] { models.first { string($0, "id") == modelID } ?? [:] }
  private var contract: [String: Any] { plan["contract"] as? [String: Any] ?? [:] }
  private var blocked: Bool { loading || launching || app.busy || app.anyActive || app.projectID.isEmpty }
  private var pair: String { app.projectID + ":" + harness + ":" + modelID }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        PageTitle(eyebrow: "Advanced users", title: "Harnesses on local models",
          subtitle: "Choose how the agent works, then use a model already running on this Mac.")
        Text("Getting started? Local AI is the simpler path for downloading and running a model.")
          .font(.callout).foregroundStyle(.secondary)
        Button("Open Local AI") { app.section = "Models" }
        if app.projectID.isEmpty { Text("Open a project first.").foregroundStyle(.secondary) }
        HStack {
          Picker("Harness", selection: $harness) {
            ForEach(harnesses, id: \.projectRowID) { row in
              Text(string(row, "name") + " · " + (string(row, "status") == "Configured" ? "Installed" : string(row, "status"))).tag(string(row, "id"))
            }
          }
          Picker("Running model", selection: $modelID) {
            Text("Choose a loaded model").tag("")
            ForEach(models, id: \.projectRowID) { row in
              Text(string(row, "engine") + " · " + string(row, "model")).tag(string(row, "id"))
            }
          }
          Button("Refresh") { Task { await refresh() } }
        }.disabled(blocked)
        if loading || checking { ProgressView(loading ? "Detecting running models…" : "Checking this pair…") }
        if !loading && models.isEmpty {
          Text("No loaded models found. Start a model in Local AI, then return and refresh.")
            .foregroundStyle(.secondary)
        }
        ForEach(harnesses.filter { string($0, "id") == harness }, id: \.projectRowID) { row in
          if let url = URL(string: string(row, "install_url")), url.scheme == "https" {
            Link("Installation and documentation", destination: url)
          }
          if !string(row, "reason").isEmpty { Text(string(row, "reason")).font(.callout).foregroundStyle(.secondary) }
        }
        if !plan.isEmpty {
          VStack(alignment: .leading, spacing: 10) {
            Label(string(plan, "status"), systemImage: plan["ready"] as? Bool == true ? "checkmark.circle" : "exclamationmark.triangle")
              .font(.headline)
            Text(string(plan, "endpoint")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
            if !contract.isEmpty {
              let fit = contract["fit"] as? [String: Any] ?? [:]
              Text(string(fit, "verdict"))
              Text("Requested: \(contract["requested_context"] ?? "Unknown") · Loaded: \(contract["actual_context"] ?? "Unknown") · Use: \(contract["context"] ?? "Unknown") tokens")
              Text("Maximum output: \(contract["max_tokens"] ?? "Unknown") tokens. Fit assumes an unquantized loaded KV cache.")
            }
            if !string(plan, "reason").isEmpty { Text(string(plan, "reason")).foregroundStyle(.orange) }
            Text("Configured means the launch settings and preflight passed, not that tool quality was tested. External harness tools, extensions and commands can use the network and edit project files. Review their permissions.")
              .font(.caption).foregroundStyle(.secondary)
            DisclosureGroup("Per-launch configuration. No global config edits.") {
              Text(configurationPreview).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
                .frame(maxWidth: .infinity, alignment: .leading).padding(8)
            }
          }.padding(16).brandSurface()
        }
        Text("First message").font(.headline)
        TextEditor(text: $message).font(.body).frame(minHeight: 100, maxHeight: 180)
          .padding(8).brandSurface().disabled(launching)
        Button(launching ? "Starting thread…" : "Start thread") { Task { await launch() } }
          .buttonStyle(BrandButtonStyle())
          .disabled(blocked || checking || plan["ready"] as? Bool != true || message.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
        Text("Nothing is installed or sent by opening this page. Start thread sends only the message you wrote. Missing, unloaded, unknown-fit or too-large models are not launched.")
          .font(.caption).foregroundStyle(.secondary)
      }.padding(28)
    }
    .task(id: app.projectID) { await refresh() }
    .task(id: pair) { await preflight() }
    .onChange(of: message) { _, _ in commandID = UUID().uuidString }
  }

  private var configurationPreview: String {
    guard let data = try? JSONSerialization.data(withJSONObject: plan["config"] as? [String: Any] ?? [:], options: [.prettyPrinted, .sortedKeys]),
      let text = String(data: data, encoding: .utf8) else { return "" }
    return text
  }

  @MainActor private func refresh() async {
    generation += 1
    let token = generation
    let project = app.projectID
    plan = [:]; failure = ""; catalog = [:]; modelID = ""
    guard !project.isEmpty else { return }
    loading = true
    defer { if token == generation { loading = false } }
    do {
      let value = try await app.engine.call("local.harnesses.catalog", ["project": project]) as? [String: Any] ?? [:]
      guard project == app.projectID, token == generation, !Task.isCancelled else { return }
      catalog = value
    } catch { if token == generation { failure = error.localizedDescription } }
  }

  @MainActor private func preflight() async {
    let selectedPair = pair
    plan = [:]; checking = false; commandID = UUID().uuidString
    guard !modelID.isEmpty, !app.projectID.isEmpty else { return }
    checking = true
    defer { if pair == selectedPair { checking = false } }
    do {
      let value = try await app.engine.call("local.harnesses.preflight", parameters) as? [String: Any] ?? [:]
      guard pair == selectedPair, !Task.isCancelled else { return }
      plan = value; failure = ""
    } catch { if pair == selectedPair { failure = error.localizedDescription } }
  }

  private var parameters: [String: Any] {
    ["project": app.projectID, "harness": harness, "engine": string(selection, "engine"), "model": string(selection, "model")]
  }

  @MainActor private func launch() async {
    guard !blocked, !checking, plan["ready"] as? Bool == true else { return }
    let project = app.projectID
    var params = parameters
    params["digest"] = string(plan, "digest"); params["prompt"] = message; params["command_id"] = commandID
    launching = true; failure = ""
    defer { launching = false }
    do {
      let value = try await app.engine.call("local.harnesses.launch", params) as? [String: Any] ?? [:]
      let id = string(value, "id")
      guard !id.isEmpty else { throw EngineError(message: "The engine did not accept the thread.") }
      guard project == app.projectID else { return }
      // Acceptance is durable even if a subsequent catalog refresh fails.
      message = ""
      try await app.refreshDefinitions()
      await app.refreshJobs()
      app.selectJob(id, targetSection: "Workspace")
    } catch { failure = error.localizedDescription }
  }
}
