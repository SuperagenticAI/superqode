import AppKit
import SwiftUI

func verifiedACPConnection(route: [String: Any], metadata: [String: Any]) -> Bool {
  let digest = string(route, "digest")
  return route["available"] as? Bool == true && !digest.isEmpty && metadata["connected"] as? Bool == true
    && string(metadata, "last_check_error").isEmpty && string(metadata, "route_digest") == digest
}

struct ACPSetupView: View {
  @EnvironmentObject var app: Workspace
  let initialRoute: [String: Any]
  let project: String
  let use: ([String: Any], [String: Any]) -> Void
  var edit: () -> Void = {}
  @State private var metadata: [String: Any] = [:]
  @State private var install: [String: Any] = [:]
  @State private var knownLogin: [String: Any] = [:]
  @State private var operation: [String: Any]?
  @State private var operationResult: [String: Any]?
  @State private var terminalPlan: [String: Any]?
  @State private var pendingTerminal: [String: Any]?
  @State private var recheck = false
  @State private var failure = ""
  private var route: [String: Any] {
    app.harnesses.first { string($0, "id") == string(initialRoute, "id") } ?? initialRoute
  }
  private var identity: String { string(route, "id") }
  private var ready: Bool { verifiedACPConnection(route: route, metadata: metadata) }

  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack(spacing: 12) {
        HarnessIcon(identity: HarnessIdentity(route), size: 44)
        VStack(alignment: .leading, spacing: 3) {
          Text(string(route, "name")).font(.headline)
          Text("ACP agent · local connection").font(.caption).foregroundStyle(.secondary)
        }
      }
      HStack {
        step("1", "Install", done: route["available"] as? Bool == true)
        step("2", "Sign in", done: ready)
        step("3", "Verify", done: ready)
      }
      if !string(route, "registry_source").isEmpty {
        Text(string(route, "registry_source") + (string(route, "registry_version").isEmpty ? "" : " · " + string(route, "registry_version")))
          .font(.caption).foregroundStyle(.secondary)
      }
      Text("Launch command").font(.headline)
      Text(string(route, "command")).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
      if let url = URL(string: string(route, "website")), url.scheme == "https", url.user == nil, url.password == nil {
        Link("Vendor setup documentation", destination: url)
      }
      if route["available"] as? Bool != true {
        Text(string(route, "issue", "Install the agent before connecting.")).foregroundStyle(.secondary)
        Button("Check installation again") {
          Task {
            do { try await app.refreshDefinitions(); await loadInstall() }
            catch { failure = error.localizedDescription }
          }
        }.disabled(app.busy || app.anyActive)
      }
      if route["custom"] as? Bool == true { Button("Edit configuration…", action: edit) }
      if !install.isEmpty && route["available"] as? Bool != true {
        DisclosureGroup("Review installation") {
          VStack(alignment: .leading, spacing: 12) {
            Text(string(install, "command")).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
            Text("This package-manager command installs third-party software on your Mac. Review the named package before continuing.")
              .font(.caption).foregroundStyle(.secondary)
            if let requirements = install["requirements"] as? [[String: Any]], !requirements.isEmpty {
              ConnectionRequirementsView(requirements: requirements)
            }
            Button("Install agent…") {
              if app.confirm("Install this coding agent?", string(install, "command"), button: "Install") {
                begin("acp-install", extra: ["expected_digest": string(install, "digest")])
              }
            }.disabled((install["requirements"] as? [[String: Any]] ?? []).contains(where: { $0["installed"] as? Bool != true }) || app.busy || app.anyActive)
          }.padding(.top, 10)
        }
      } else if !string(route, "setup_note").isEmpty {
        DisclosureGroup("Vendor setup instructions") {
          Text(string(route, "setup_note")).font(.callout).textSelection(.enabled).padding(.top, 8)
        }
      }
      Button(ready ? "Check again" : "Check connection") { begin("probe") }
        .disabled(route["available"] as? Bool != true || app.hasActiveWork(project: project) || app.busy)
      Text("Checks start the agent without sending a coding prompt or granting project tools.")
        .font(.caption).foregroundStyle(.secondary)
      if !string(metadata, "message").isEmpty {
        Label(string(metadata, "message"), systemImage: ready ? "checkmark.circle" : "person.crop.circle.badge.questionmark")
          .font(.callout).foregroundStyle(ready ? Color.primary : .secondary).textSelection(.enabled)
      }
      ForEach(metadata["auth_methods"] as? [[String: Any]] ?? [], id: \.projectRowID) { method in
        if ["agent", "terminal"].contains(string(method, "type", "agent")) {
          Button("Sign in · " + string(method, "name", string(method, "id"))) {
            begin(string(method, "type") == "terminal" ? "acp-terminal" : "acp-auth",
              extra: ["method": string(method, "id"), "expected_digest": string(route, "digest")])
          }.disabled(route["available"] as? Bool != true || app.anyActive || app.busy)
        }
      }
      if !ready && !knownLogin.isEmpty {
        Button("Vendor sign-in · " + string(knownLogin, "name")) {
          if knownLogin["interactive"] as? Bool == true { terminalPlan = knownLogin }
          else { begin("subscription", extra: ["vendor": string(knownLogin, "vendor")]) }
        }.disabled(route["available"] as? Bool != true || app.anyActive || app.busy)
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      nativeButton("connect.use", action: { use(route, metadata) }, title: "Use this connection") {
        Text(ready ? "Use verified connection" : "Use this connection")
      }.disabled(route["available"] as? Bool != true || !ready || app.active || app.busy || app.projectID != project)
      if ready {
        Text("Startup and session creation succeeded. Model entitlement, billing and task execution remain owned by the agent.")
          .font(.caption).foregroundStyle(.secondary)
      }
    }
    .task(id: identity) { metadata = app.connectionMetadata[identity] ?? [:]; await loadInstall() }
    .centeredDialog(isPresented: Binding(get: { operation != nil }, set: { if !$0 { operation = nil } }), title: "Agent setup", onDismiss: {
      if let pending = pendingTerminal { pendingTerminal = nil; terminalPlan = pending }
      else if operationResult?["signed_in"] as? Bool == true { begin("probe") }
      else if operationResult == nil { failure = "Setup did not complete. Check the connection again when ready." }
    }) {
      if let request = operation {
        AuthenticationProgressView(request: request) { result in
          operationResult = result
          operation = nil
          if result["argv"] != nil { pendingTerminal = result }
          else if result["installed"] as? Bool == true {
            Task { try? await app.refreshDefinitions(); await loadInstall() }
          } else {
            metadata = result
            if result["connected"] != nil && app.projectID == project {
              app.connectionMetadata[identity] = result
            }
          }
        }.environmentObject(app)
      }
    }
    .centeredDialog(isPresented: Binding(get: { terminalPlan != nil }, set: { if !$0 { terminalPlan = nil } }), title: "Agent terminal sign-in", onDismiss: {
      if recheck { recheck = false; begin("probe") }
    }) {
      if let plan = terminalPlan {
        ACPInteractiveSignIn(plan: plan) { recheck = true; terminalPlan = nil }.environmentObject(app)
      }
    }
  }

  private func step(_ number: String, _ name: String, done: Bool) -> some View {
    Label(name, systemImage: done ? "checkmark.circle.fill" : number + ".circle")
      .font(.callout).padding(10).frame(maxWidth: .infinity).brandSurface()
  }
  private func begin(_ action: String, extra: [String: Any] = [:]) {
    guard app.projectID == project else { failure = "Return to the original project before setting up this agent."; return }
    failure = ""
    if ["probe", "acp-auth", "acp-terminal"].contains(action) {
      metadata["connected"] = false
      app.connectionMetadata[identity] = metadata
    }
    operationResult = nil
    operation = ["action": action, "project": project, "reference": identity].merging(extra) { _, value in value }
  }
  private func loadInstall() async {
    knownLogin = (try? await app.engine.call("connect.acp.login.plan", ["project": project, "reference": identity])) as? [String: Any] ?? [:]
    do {
      install = try await app.engine.call("connect.acp.install.plan", ["project": project, "reference": identity]) as? [String: Any] ?? [:]
    } catch { install = [:] }
  }
}

private struct ACPInteractiveSignIn: View {
  @EnvironmentObject var app: Workspace
  let plan: [String: Any]
  let complete: () -> Void
  @State private var started = false
  var body: some View {
    if started {
      TerminalLoginView(terminals: app.terminals, arguments: plan["argv"] as? [String] ?? [],
        environment: plan["env"] as? [String: String] ?? [:], unsetEnvironment: plan["unset_env"] as? [String] ?? [], complete: complete)
    } else {
      VStack(alignment: .leading, spacing: 18) {
        Text("Review terminal sign-in").font(.title2)
        Text("The agent advertised these arguments and environment values. The configured agent executable owns this login process.").foregroundStyle(.secondary)
        CodeBlock(text: pretty(["arguments": plan["argv"] ?? [], "environment": plan["env"] ?? [:]])).frame(height: 230)
        Button("Start sign-in", action: { started = true }).buttonStyle(BrandButtonStyle())
      }.padding(24).frame(width: 700)
    }
  }
}

struct CustomACPAgentView: View {
  @EnvironmentObject var app: Workspace
  let saved: ([String: Any]) -> Void
  let project: String
  let initial: [String: Any]
  let removed: () -> Void
  @State private var name = ""
  @State private var executable = ""
  @State private var arguments = ""
  @State private var busy = false
  @State private var failure = ""
  init(project: String, initial: [String: Any] = [:], removed: @escaping () -> Void = {}, saved: @escaping ([String: Any]) -> Void) {
    self.project = project
    self.initial = initial
    self.saved = saved
    self.removed = removed
    let argv = initial["command_argv"] as? [String] ?? []
    _name = State(initialValue: string(initial, "name"))
    _executable = State(initialValue: argv.first ?? "")
    _arguments = State(initialValue: argv.dropFirst().joined(separator: "\n"))
  }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(eyebrow: "Your project", title: initial.isEmpty ? "Add a custom ACP agent" : "Edit custom ACP agent", subtitle: "Connect a local executable that speaks ACP over standard input and output.")
        TextField("Agent name", text: $name).textFieldStyle(.roundedBorder)
        TextField("Executable name or absolute path", text: $executable).textFieldStyle(.roundedBorder)
        Text("Arguments · one argument per line").font(.headline)
        TextEditor(text: $arguments).font(.system(.callout, design: .monospaced)).frame(height: 160).brandSurface()
        Text("Arguments are passed directly to the executable. Keep credentials in the agent’s sign-in store. Package launchers use offline mode so checking a connection cannot download an agent.")
          .font(.callout).foregroundStyle(.secondary)
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
        Button("Save configuration") {
          busy = true
          Task {
            defer { busy = false }
            do {
              let argv = [executable.trimmingCharacters(in: .whitespacesAndNewlines)] + arguments.components(separatedBy: "\n").filter { !$0.isEmpty }
              var params: [String: Any] = ["project": project, "name": name, "argv": argv]
              if !initial.isEmpty { params["id"] = string(initial, "id"); params["expected_digest"] = string(initial, "digest") }
              let route = try await app.engine.call("connect.acp.custom.save", params) as? [String: Any] ?? [:]
              guard app.projectID == project else { failure = "Configuration saved to the original project. Reopen that project to continue."; return }
              try await app.refreshDefinitions()
              saved(route)
            } catch { failure = error.localizedDescription }
          }
        }.buttonStyle(BrandButtonStyle()).disabled(busy || name.isEmpty || executable.isEmpty || app.anyActive || app.projectID != project)
        if !initial.isEmpty {
          Button("Remove configuration…", role: .destructive) {
            guard app.confirm("Remove this agent configuration?", "The saved launch command will be removed. Recorded conversations and project files remain available.", button: "Remove") else { return }
            busy = true
            Task {
              defer { busy = false }
              do {
                _ = try await app.engine.call("connect.acp.custom.remove", ["project": project, "id": string(initial, "id"), "expected_digest": string(initial, "digest")])
                try await app.refreshDefinitions()
                removed()
              } catch { failure = error.localizedDescription }
            }
          }.disabled(busy || app.anyActive || app.projectID != project)
        }
      }.padding(28)
    }
  }
}
