import SwiftUI

/// Native settings and read-only inventories alongside the vendor's full interactive CLI.
struct AgentCLIControlsView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  var onSetup: (String) -> Void = { _ in }
  @State private var catalog: [String: Any] = [:]
  @State private var selectedCommand = ""
  @State private var operation = ""
  @State private var running = false
  @State private var commandGeneration = UUID()
  @State private var failure = ""
  @State private var output: [String: Any] = [:]
  @State private var showDetails = false
  @State private var cliOpen = false
  @State private var helpOutput: [String: Any] = [:]
  @State private var showHelp = false
  @State private var commandSearch = ""
  @State private var extraArguments = ""
  @State private var launching = false
  @State private var visible = false
  @State private var identity = "agent-cli-" + UUID().uuidString
  private var connectionKey: String { app.projectID + "\n" + app.harness }
  private var commands: [[String: Any]] { catalog["commands"] as? [[String: Any]] ?? [] }
  private var cli: [String: Any] { catalog["cli"] as? [String: Any] ?? [:] }
  private var helpPath: [String] { helpOutput["path"] as? [String] ?? [] }
  private var vendorName: String { ((cli["argv"] as? [String])?.first as NSString?)?.lastPathComponent ?? "CLI" }
  private var canRun: Bool {
    !launching && !running && !app.busy && !app.anyActive && !app.checkingConnection
  }

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
            HStack(spacing: 12) {
              if !app.agentModels.isEmpty {
                AgentModelPicker().frame(maxWidth: 340, alignment: .leading)
              }
              AgentEffortPicker()
            }
            AgentControlsView(showModelAndEffort: false)
            HStack {
              Button(app.checkingConnection ? "Loading models…" : "Refresh models and settings") {
                app.perform { await app.checkManagedConnection() }
              }.disabled(app.checkingConnection || app.active || running)
              Button("Sign in or set up…") { onSetup("menu:root") }
                .disabled(running)
              if string(cli, "family") == "antigravity" {
                Button("Managed Agent…") { onSetup("vendor-key:antigravity-managed") }
                  .disabled(running || app.anyActive)
              }
            }
            if string(catalog, "runtime") == "antigravity-cli" {
              Text("This list comes from agy models for your current account. Gemini 4 Carbon and Argon require eligible Google access.")
                .font(.caption).foregroundStyle(.secondary)
              Link("Google model availability", destination: URL(string: "https://antigravity.google/docs/models")!)
                .font(.caption)
            }
            if !cli.isEmpty { vendorCommands }
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
            if cli.isEmpty && !catalog.isEmpty {
              Text("This connection exposes its supported models, modes and slash commands through ACP. It has no known interactive CLI launcher; use the agent’s setup documentation for terminal-only features.")
                .font(.caption).foregroundStyle(.secondary)
            }
            if !string(catalog, "issue").isEmpty { Text(string(catalog, "issue")).foregroundStyle(.orange) }
            if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
          }.frame(maxWidth: .infinity, alignment: .leading)
        }
      }
    }.padding(24).frame(width: 820, height: 670).background { BrandBackdrop() }
      .task(id: connectionKey) {
        cancelCommand()
        app.terminals.stop(identity); cliOpen = false
        catalog = [:]; output = [:]; failure = ""; helpOutput = [:]
        showHelp = false; commandSearch = ""; extraArguments = ""
        let key = connectionKey
        do {
          let result = try await app.engine.call("connect.controls", [
            "project": app.projectID, "reference": app.harness,
          ]) as? [String: Any] ?? [:]
          guard !Task.isCancelled, key == connectionKey else { return }
          catalog = result
          selectedCommand = string(commands.first ?? [:], "id")
          if !string(cli, "family").isEmpty { startCommand(cursor: nil, vendorPath: []) }
        } catch {
          if !Task.isCancelled && key == connectionKey { failure = error.localizedDescription }
        }
      }
      .onChange(of: selectedCommand) { _, _ in output = [:]; showDetails = false }
      .onChange(of: app.checkingConnection) { _, checking in
        if !checking && !cliOpen && helpOutput.isEmpty && !string(cli, "family").isEmpty {
          startCommand(cursor: nil, vendorPath: [])
        }
      }
      .onAppear { visible = true }
      .onDisappear { visible = false; cancelCommand(); app.terminals.stop(identity) }
  }

  private var vendorCommands: some View {
    let rows = helpOutput["subcommands"] as? [[String: Any]] ?? []
    let matches = rows.filter {
      commandSearch.isEmpty || (string($0, "name") + " " + string($0, "description"))
        .localizedCaseInsensitiveContains(commandSearch)
    }
    return VStack(alignment: .leading, spacing: 10) {
      Divider()
      HStack {
        Text("Vendor CLI").font(.headline)
        Spacer()
        Button("Open interactive CLI…") {
          openCLI(path: [], arguments: "", useAgentSelection: true)
        }.disabled(!canRun)
      }
      if !string(cli, "family").isEmpty {
        Text("Interactive startup uses the selected model and effort. Type /help in the CLI to see its session commands.")
          .font(.caption).foregroundStyle(.secondary)
        HStack {
          if !helpPath.isEmpty {
            Button("Back", systemImage: "chevron.left") {
              startCommand(cursor: nil, vendorPath: Array(helpPath.dropLast()))
            }.disabled(!canRun)
          }
          Text(([vendorName] + helpPath).joined(separator: " ")).font(.system(.callout, design: .monospaced))
          Spacer()
          if running { ProgressView().controlSize(.small) }
          Button(helpOutput.isEmpty ? "Load commands" : "Refresh help") {
            startCommand(cursor: nil, vendorPath: helpPath)
          }.disabled(!canRun)
        }
        if !rows.isEmpty {
          TextField("Search commands", text: $commandSearch).textFieldStyle(.roundedBorder)
          LazyVStack(alignment: .leading, spacing: 3) {
            ForEach(matches, id: \.projectRowID) { row in
              Button {
                startCommand(cursor: nil, vendorPath: helpPath + [string(row, "id")])
              } label: {
                HStack {
                  Text(string(row, "name")).font(.system(.callout, design: .monospaced))
                  Text(string(row, "description")).font(.caption).foregroundStyle(.secondary)
                  Spacer()
                  Image(systemName: "chevron.right").font(.caption).foregroundStyle(.secondary)
                }.padding(5).contentShape(Rectangle())
              }.buttonStyle(.plain).disabled(!canRun)
            }
          }
        }
        if !helpOutput.isEmpty {
          DisclosureGroup("Usage and flags", isExpanded: $showHelp) {
            Text(string(helpOutput, "text")).font(.caption.monospaced()).textSelection(.enabled)
          }
          HStack {
            TextField(helpPath.isEmpty ? "Command or startup flags" : "Command arguments", text: $extraArguments)
              .textFieldStyle(.roundedBorder)
            if let flags = helpOutput["flags"] as? [String], !flags.isEmpty {
              Menu("Add flag") {
                ForEach(flags, id: \.self) { flag in
                  Button(flag) {
                    extraArguments = [extraArguments.trimmingCharacters(in: .whitespaces), flag]
                      .filter { !$0.isEmpty }.joined(separator: " ") + " "
                  }
                }
              }.fixedSize().disabled(!canRun)
            }
            Button("Run in terminal…") { openCLI(path: helpPath, arguments: extraArguments) }
              .disabled(!canRun || (helpPath.isEmpty && extraArguments.trimmingCharacters(in: .whitespaces).isEmpty))
          }
        }
      }
    }
  }

  private func startCommand(cursor: String?, vendorPath: [String]? = nil) {
    guard canRun, vendorPath != nil || catalog["available"] as? Bool == true else { return }
    running = true; failure = ""
    if vendorPath == nil { output = [:]; showDetails = false }
    commandGeneration = UUID()
    let generation = commandGeneration
    let key = connectionKey
    let command = vendorPath == nil ? selectedCommand : "vendor-help"
    app.perform {
      guard running, generation == commandGeneration, key == connectionKey else { return }
      var started = ""
      do {
        var params: [String: Any] = [
          "project": app.projectID, "reference": app.harness,
          "expected_digest": string(catalog, "digest"), "command": command,
        ]
        if let cursor { params["cursor"] = cursor }
        if let vendorPath { params["path"] = vendorPath }
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
            let value = result["result"] as? [String: Any] ?? [:]
            if vendorPath != nil {
              helpOutput = value; commandSearch = ""; extraArguments = ""
              showHelp = (value["subcommands"] as? [[String: Any]] ?? []).isEmpty
            } else { output = value }
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

  private func openCLI(path: [String], arguments: String, useAgentSelection: Bool = false) {
    guard canRun else { return }
    let key = connectionKey
    let applySelection = useAgentSelection && !string(cli, "family").isEmpty
    let model = applySelection ? app.selectedAgentModel : ""
    let effort = applySelection ? app.selectedAgentEffort : ""
    launching = true
    app.perform {
      defer { launching = false }
      do {
        var plan = cli
        if !path.isEmpty || !arguments.isEmpty || !model.isEmpty || !effort.isEmpty {
          plan = try await app.engine.call("connect.cli.arguments", [
            "project": app.projectID, "reference": app.harness, "expected_digest": string(catalog, "digest"),
            "path": path, "arguments": arguments, "model": model, "effort": effort,
          ]) as? [String: Any] ?? [:]
        }
        guard visible, key == connectionKey, let argv = plan["argv"] as? [String], !argv.isEmpty else { return }
        let preview = argv.dropFirst().map { $0.debugDescription }.joined(separator: " ")
        guard app.confirm("Run \(vendorName) in the project terminal?",
          preview.isEmpty ? "The vendor CLI opens an interactive session with its own tools and permissions."
            : "\(vendorName) \(preview)", button: "Open terminal") else { return }
        app.terminals.start(identity, path: string(app.project, "path"), arguments: argv,
          unset: plan["unset_env"] as? [String] ?? [])
        cliOpen = true
      } catch { if key == connectionKey { failure = error.localizedDescription } }
    }
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
