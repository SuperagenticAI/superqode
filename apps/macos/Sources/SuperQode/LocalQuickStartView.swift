import SwiftUI

/// Each action uses an engine-reviewed plan; reopening observes existing jobs.
struct LocalQuickStartView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  @State private var choices: [[String: Any]] = []
  @State private var selection = ""
  @State private var step: [String: Any] = [:]
  @State private var failure = ""
  @State private var busy = false
  @State private var progress: [String: Any] = [:]
  @State private var output = ""
  @State private var command = UUID().uuidString
  @State private var closed = false
  private var state: String { string(step, "step") }
  private var plan: [String: Any] { step["plan"] as? [String: Any] ?? [:] }
  private var validProject: Bool { app.projectID == project && !closed && !app.openingProject }

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Text("Code with a local model").font(.title2.weight(.semibold))
      Text("Choose a model. We’ll guide you through the remaining steps and remember your progress.").foregroundStyle(.secondary)
      Picker("Model", selection: $selection) {
        Text("Choose a model").tag("")
        ForEach(choices, id: \.projectRowID) { row in Text(string(row, "name")).tag(string(row, "id")) }
      }.disabled(busy || state == "working")
      if let row = choices.first(where: { string($0, "id") == selection }) {
        Text(string(row, "detail")).font(.callout).foregroundStyle(.secondary)
        if let context = row["suggested_context"] as? Int {
          Text("Suggested starting context: \(context.formatted()) tokens. Existing server settings are kept; the readiness check reports the loaded context when available.")
            .font(.caption).foregroundStyle(.secondary)
        }
      }
      Text("Suggestions are starting points. Context and other apps also need memory.").font(.caption).foregroundStyle(.secondary)
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          if state == "working" {
            ProgressView("Setting up your local model…")
            if !progress.isEmpty { LocalDownloadProgress(value: progress) }
            Text("You can close this guide and reopen it to check progress. Engine shutdown interrupts active work.").font(.caption).foregroundStyle(.secondary)
          } else if state == "ready" {
            Label("Ready to start coding", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            Text("The model completed a read-tool check on generated data. Editing and full coding quality still depend on the model and task.")
            Text("The primary model uses this machine. Other tools or project configuration may use the network.").font(.caption).foregroundStyle(.secondary)
          } else if !plan.isEmpty {
            Text(stepTitle).font(.headline)
            Text(string(plan, "note", string(plan, "guidance"))).font(.callout)
            if state == "download" {
              Text("Download size is reported during transfer. Free disk: " + localBytes(plan["disk_free_bytes"]))
              Text("Existing cached weights are reused. No coding prompt is sent by downloading.").font(.caption)
            }
            if state == "verify" { Text("Checks loaded context, tool-call shapes and context recall, then runs a Core read-tool check on generated data. No project files are read.").font(.caption) }
            DisclosureGroup("Advanced operation details") {
              Text(string(plan, "command")).font(.caption.monospaced()).textSelection(.enabled)
            }
          } else if !string(step, "message").isEmpty {
            Text(string(step, "message"))
            if let url = URL(string: string(step, "url")), url.scheme == "https" { Link("Open official installation guide", destination: url) }
          }
          if let verification = step["verification"] as? [String: Any], !verification.isEmpty {
            LocalReadinessSummary(verification: verification)
          }
          if !output.isEmpty { DisclosureGroup("Setup output") { Text(output).font(.caption.monospaced()).textSelection(.enabled) } }
          if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
          if choices.isEmpty && !busy { Text("No suitable starter or running model was found. Use Advanced setup to inspect runtimes and model requirements.") }
        }.frame(maxWidth: .infinity, alignment: .leading)
      }
      HStack {
        Button("Close") { closed = true; dismiss() }
        if state == "working" { Button("Cancel setup") { app.perform { _ = try await app.engine.call("jobs.cancel", ["id": string(step, "job")]) } } }
        Spacer()
        Button("Check again") { Task { await refresh() } }.disabled(busy || selection.isEmpty || !validProject)
        if state == "ready" {
          Button("Start coding") { Task { await useModel() } }.buttonStyle(BrandButtonStyle()).disabled(busy || app.anyActive || !validProject)
        } else if !plan.isEmpty {
          Button(stepTitle) { Task { await runStep() } }.buttonStyle(BrandButtonStyle()).disabled(busy || app.anyActive || !validProject)
        } else if state == "retry" {
          Button("Retry remaining setup") { Task { await refresh(retry: true) } }.disabled(busy || !validProject)
        }
      }
    }.padding(24).frame(width: 740, height: 590)
      .task { await load() }
      .task(id: string(step, "job")) {
        guard state == "working" else { return }
        while !Task.isCancelled && validProject && state == "working" {
          do { try await Task.sleep(for: .seconds(1)) } catch { return }
          await refresh()
        }
      }
      .onChange(of: selection) { _, _ in step = [:]; output = ""; progress = [:]; Task { await refresh() } }
      .onDisappear { closed = true }
  }

  private var stepTitle: String {
    switch state {
    case "install": return "Install runtime"
    case "serve": return "Start local server"
    case "download": return "Download model"
    case "verify": return "Run local tool check"
    default: return "Continue"
    }
  }
  private func load() async {
    busy = true
    defer { busy = false }
    do {
      let result = try await app.engine.call("local.models.quickstart.catalog", ["project": project]) as? [String: Any] ?? [:]
      guard validProject, !Task.isCancelled else { return }
      choices = result["choices"] as? [[String: Any]] ?? []
      let saved = string(result, "selected")
      selection = choices.contains(where: { string($0, "id") == saved }) ? saved : choices.first.map { string($0, "id") } ?? ""
    } catch { failure = error.localizedDescription }
  }
  private func refresh(retry: Bool = false) async {
    let selected = selection
    guard validProject, !selected.isEmpty else { return }
    busy = true
    defer { busy = false }
    do {
      let value = try await app.engine.call("local.models.quickstart.prepare", ["project": project, "choice": selected, "retry": retry]) as? [String: Any] ?? [:]
      guard validProject, selected == selection, !Task.isCancelled else { return }
      step = value; failure = ""; command = UUID().uuidString
      if !string(value, "job").isEmpty {
        let job = try await app.engine.call("jobs.get", ["id": string(value, "job")]) as? [String: Any] ?? [:]
        guard validProject, selected == selection else { return }
        let events = job["events"] as? [[String: Any]] ?? []
        progress = events.last(where: { string($0, "type") == "progress" })?["data"] as? [String: Any] ?? [:]
        output = String(events.map { string($0["data"] as? [String: Any] ?? [:], "text", string($0["data"] as? [String: Any] ?? [:], "message")) }.joined(separator: "\n").suffix(20000))
      }
    } catch { if validProject && selected == selection { failure = error.localizedDescription } }
  }
  private func runStep() async {
    guard validProject else { return }
    busy = true
    defer { busy = false }
    do {
      let job = try await app.engine.call("local.models.quickstart.start", ["project": project, "choice": selection, "plan": string(plan, "id"), "expected_digest": string(plan, "digest"), "command_id": command]) as? [String: Any] ?? [:]
      guard validProject else { return }
      step = ["step": "working", "job": string(job, "id")]; output = ""; failure = ""
    } catch { failure = error.localizedDescription }
  }
  private func useModel() async {
    guard validProject else { return }
    busy = true
    defer { busy = false }
    do {
      let result = try await app.engine.call("local.models.use", ["project": project, "engine": string(step, "engine"), "model": string(step, "model"), "harness": "core"]) as? [String: Any] ?? [:]
      guard validProject, !app.anyActive else { return }
      app.chooseHarness("core"); app.chooseModelRoute(string(result, "provider"), string(result, "model"))
      app.section = "Workspace"; closed = true; dismiss()
    } catch { failure = error.localizedDescription }
  }
}


private struct LocalReadinessSummary: View {
  let verification: [String: Any]
  private var readiness: [String: Any] { verification["readiness"] as? [String: Any] ?? [:] }
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Local check results").font(.headline)
      if let window = readiness["context_window"] as? Int {
        Text("Reported context: \(window.formatted()) tokens · " + string(readiness, "context_source")).font(.caption)
      } else {
        Text("Loaded context was not reported. Keep context conservative; no maximum context size was verified.").font(.caption).foregroundStyle(.orange)
      }
      ForEach(verification["checks"] as? [[String: Any]] ?? [], id: \.projectRowID) { check in
        Label(string(check, "name"), systemImage: check["ok"] as? Bool == true ? "checkmark.circle" : "exclamationmark.circle")
          .font(.caption).foregroundStyle(check["ok"] as? Bool == true ? Color.secondary : .orange)
      }
      ForEach(readiness["checks"] as? [[String: Any]] ?? [], id: \.projectRowID) { check in
        Label(string(check, "name") + ": " + string(check, "detail"), systemImage: check["ok"] as? Bool == true ? "checkmark.circle" : "exclamationmark.circle")
          .font(.caption).foregroundStyle(check["ok"] as? Bool == true ? Color.secondary : .orange)
      }
      ForEach(readiness["warnings"] as? [String] ?? [], id: \.self) { warning in
        Text(warning).font(.caption).foregroundStyle(.orange)
      }
    }
  }
}
