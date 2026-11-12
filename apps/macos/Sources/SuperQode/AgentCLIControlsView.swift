import SwiftUI

/// Native settings and read-only inventories alongside the vendor's full interactive CLI.
struct AgentCLIControlsView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  var onSetup: () -> Void = {}
  @State private var catalog: [String: Any] = [:]
  @State private var selectedCommand = ""
  @State private var operation = ""
  @State private var running = false
  @State private var commandGeneration = UUID()
  @State private var failure = ""
  @State private var output: [String: Any] = [:]
  @State private var showDetails = false
  @State private var cliOpen = false
  @State private var identity = "agent-cli-" + UUID().uuidString
  private var connectionKey: String { app.projectID + "\n" + app.harness }
  private var commands: [[String: Any]] { catalog["commands"] as? [[String: Any]] ?? [] }
  private var cli: [String: Any] { catalog["cli"] as? [String: Any] ?? [:] }

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        VStack(alignment: .leading, spacing: 4) {
          Text(app.connectionDisplayName).font(.title2.weight(.semibold))
          Text("Models, settings and CLI commands").foregroundStyle(.secondary)
        }
        Spacer()
        nativeButton("agent-controls.close", action: { dismiss() }, title: "Close agent controls") { Text("Done") }
      }
      if cliOpen {
        Text("Full vendor CLI · separate from this SuperQode conversation")
          .font(.headline)
        Text("Use the CLI’s own slash commands, plugins, sessions and account controls here. Settings changed here follow the vendor’s persistence rules; they do not change this thread’s model override. Closing stops this CLI process.")
          .font(.caption).foregroundStyle(.secondary)
        AgentCLITerminal(terminals: app.terminals, identity: identity)
        Button("Close CLI") { app.terminals.stop(identity); cliOpen = false }
      } else {
        ScrollView {
          VStack(alignment: .leading, spacing: 16) {
            AgentControlsView()
            HStack {
              Button(app.checkingConnection ? "Loading models…" : "Refresh models and settings") {
                app.perform { await app.checkManagedConnection() }
              }.disabled(app.checkingConnection || app.active || running)
              Button("Sign in or set up…", action: onSetup)
                .disabled(running)
            }
            if !app.agentCommands.isEmpty {
              Text("Agent slash commands").font(.headline)
              ForEach(app.agentCommands, id: \.projectRowID) { command in
                Button {
                  if app.stageAgentCommand(string(command, "name")) { dismiss() }
                } label: {
                  HStack {
                    Text("/" + string(command, "name")).font(.system(.body, design: .monospaced))
                    Text(string(command, "description")).font(.caption).foregroundStyle(.secondary)
                  }
                }.disabled(app.active || running)
              }
              Text("Selecting a command adds it to your draft. Review it before sending.")
                .font(.caption).foregroundStyle(.secondary)
            }
            if !commands.isEmpty {
              Divider()
              Text("CLI information").font(.headline)
              Text("Read from the installed agent without sending a coding prompt.")
                .font(.caption).foregroundStyle(.secondary)
              HStack {
                Picker("Command", selection: $selectedCommand) {
                  ForEach(commands, id: \.projectRowID) { command in
                    Text(string(command, "name")).tag(string(command, "id"))
                  }
                }.disabled(running)
                Button("Run") { startCommand(cursor: nil) }
                  .disabled(selectedCommand.isEmpty || running || app.busy || app.anyActive || app.checkingConnection || catalog["available"] as? Bool != true)
                if running {
                  ProgressView().controlSize(.small)
                  Button("Cancel") { cancelCommand() }
                }
              }
              if !output.isEmpty {
                Text(String(string(output, "text").prefix(4000))).font(.callout).textSelection(.enabled)
                if let data = output["data"] {
                  DisclosureGroup("Show detailed result", isExpanded: $showDetails) {
                    if showDetails {
                      Text(jsonText(data)).font(.caption.monospaced()).textSelection(.enabled)
                        .frame(maxWidth: .infinity, alignment: .leading)
                    }
                  }
                } else if string(output, "text").count > 4000 {
                  DisclosureGroup("Show complete output", isExpanded: $showDetails) {
                    if showDetails { Text(string(output, "text")).font(.caption.monospaced()).textSelection(.enabled) }
                  }
                }
                if !string(output, "next_cursor").isEmpty {
                  Button("Next page") { startCommand(cursor: string(output, "next_cursor")) }
                    .disabled(running)
                }
              }
            }
            if !cli.isEmpty {
              Divider()
              Text("All vendor CLI commands").font(.headline)
              Text("Open the installed CLI inside SuperQode for its full command tree, including interactive features that are not available through ACP or the app-server. Your vendor account continues to own authentication and billing.")
                .font(.callout).foregroundStyle(.secondary)
              Button("Open full CLI…", action: openCLI)
                .disabled(app.busy || app.anyActive || running || app.checkingConnection || catalog["available"] as? Bool != true)
            } else if !catalog.isEmpty {
              Text("This connection exposes its supported models, modes and slash commands through ACP. It has no known interactive CLI launcher; use the agent’s setup documentation for terminal-only features.")
                .font(.caption).foregroundStyle(.secondary)
            }
            if !string(catalog, "issue").isEmpty { Text(string(catalog, "issue")).foregroundStyle(.orange) }
            if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
          }.frame(maxWidth: .infinity, alignment: .leading)
        }
      }
    }.padding(24).frame(width: 760, height: 620).background { BrandBackdrop() }
      .task(id: connectionKey) {
        cancelCommand()
        app.terminals.stop(identity); cliOpen = false
        catalog = [:]; output = [:]; failure = ""
        let key = connectionKey
        do {
          let result = try await app.engine.call("connect.controls", [
            "project": app.projectID, "reference": app.harness,
          ]) as? [String: Any] ?? [:]
          guard !Task.isCancelled, key == connectionKey else { return }
          catalog = result
          selectedCommand = string(commands.first ?? [:], "id")
        } catch {
          if !Task.isCancelled && key == connectionKey { failure = error.localizedDescription }
        }
      }
      .onChange(of: selectedCommand) { _, _ in output = [:]; showDetails = false }
      .onDisappear { cancelCommand(); app.terminals.stop(identity) }
  }

  private func startCommand(cursor: String?) {
    guard !running, !app.busy, !app.anyActive, !app.checkingConnection else { return }
    running = true; failure = ""; output = [:]; showDetails = false
    commandGeneration = UUID()
    let generation = commandGeneration
    let key = connectionKey
    let command = selectedCommand
    app.perform {
      guard running, generation == commandGeneration, key == connectionKey else { return }
      var started = ""
      do {
        var params: [String: Any] = [
          "project": app.projectID, "reference": app.harness,
          "expected_digest": string(catalog, "digest"), "command": command,
        ]
        if let cursor { params["cursor"] = cursor }
        let response = try await app.engine.call("connect.command.start", params) as? [String: Any] ?? [:]
        started = string(response, "id")
        guard !started.isEmpty else { throw EngineError(message: "The CLI command could not start.") }
        guard running, generation == commandGeneration, key == connectionKey else {
          _ = try? await app.engine.call("connect.auth.cancel", ["id": started]); return
        }
        operation = started
        for _ in 0..<240 {
          guard running, generation == commandGeneration, operation == started, key == connectionKey else { break }
          let result = try await app.engine.call("connect.auth.poll", ["id": started]) as? [String: Any] ?? [:]
          guard running, generation == commandGeneration, operation == started, key == connectionKey else { break }
          if string(result, "state") == "completed" {
            output = result["result"] as? [String: Any] ?? [:]
            running = false; operation = ""; return
          }
          if string(result, "state") != "running" {
            throw EngineError(message: (result["messages"] as? [String] ?? []).last ?? "The CLI command did not complete.")
          }
          try await Task.sleep(for: .milliseconds(250))
        }
        _ = try? await app.engine.call("connect.auth.cancel", ["id": started])
        if generation == commandGeneration && operation == started { failure = "CLI command timed out or was cancelled." }
      } catch {
        if !started.isEmpty { _ = try? await app.engine.call("connect.auth.cancel", ["id": started]) }
        if generation == commandGeneration && key == connectionKey && running { failure = error.localizedDescription }
      }
      if generation == commandGeneration { operation = ""; running = false }
    }
  }

  private func cancelCommand() {
    let id = operation
    operation = ""; running = false
    commandGeneration = UUID()
    if !id.isEmpty { app.perform { _ = try? await app.engine.call("connect.auth.cancel", ["id": id]) } }
  }

  private func jsonText(_ value: Any) -> String {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.prettyPrinted, .sortedKeys, .fragmentsAllowed]) else { return "No detailed result." }
    return String(decoding: data, as: UTF8.self)
  }

  private func openCLI() {
    guard !running, !app.busy, !app.anyActive, !app.checkingConnection,
      let arguments = cli["argv"] as? [String], !arguments.isEmpty,
      app.confirm("Open the vendor CLI?", "This starts a separate interactive agent in the selected project. It can use the vendor’s own tools and permissions. This SuperQode conversation stays unchanged.", button: "Open CLI") else { return }
    app.terminals.start(identity, path: string(app.project, "path"), arguments: arguments,
      unset: cli["unset_env"] as? [String] ?? [])
    cliOpen = true
  }
}

private struct AgentCLITerminal: View {
  @ObservedObject var terminals: ProjectTerminals
  let identity: String
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      if let terminal = terminals.view(identity) { ProjectTerminalHost(terminal: terminal) }
      if let code = terminals.exitCodes[identity] {
        Text(code == 0 ? "CLI closed." : "CLI exited with status \(code). Review the terminal output, then check installation or sign-in in Connect.")
          .font(.caption).foregroundStyle(code == 0 ? Color.secondary : Color.orange)
      }
    }
  }
}
