import AppKit
import SwiftUI

/// Keep Connect's navigation on AppKit's standard target/action event path.
/// The SwiftUI label remains visual; the native button owns the whole hit area.
func nativeButton<Label: View>(
  _ identifier: String, action: @escaping () -> Void, padded: Bool = true, title: String? = nil,
  @ViewBuilder label: () -> Label
) -> some View {
  label()
    .padding(.horizontal, padded ? 10 : 0)
    .padding(.vertical, padded ? 7 : 0)
    .background(padded ? Color.qPanel : .clear, in: RoundedRectangle(cornerRadius: 6))
    .overlay(RoundedRectangle(cornerRadius: 6).stroke(Color.primary.opacity(padded ? 0.2 : 0), lineWidth: 1).allowsHitTesting(false))
    .overlay {
      NativeConnectionAction(identifier: identifier, title: title ?? [
        "connect.back": "Back", "connect.root": "All connections", "connect.close": "Close",
        "connect.subscriptions": "Existing subscription", "connect.acp": "ACP agent",
        "connect.models": "Local model or API key", "connect.use": "Use this connection",
      ][identifier] ?? identifier, action: action)
    }
}

private struct NativeConnectionAction: NSViewRepresentable {
  let identifier: String
  let title: String
  let action: () -> Void
  @Environment(\.isEnabled) private var enabled
  final class Coordinator: NSObject {
    var action: () -> Void = {}
    @objc func invoke(_ sender: NSButton) { action() }
  }
  func makeCoordinator() -> Coordinator { Coordinator() }
  final class Control: NSButton {
    override func acceptsFirstMouse(for event: NSEvent?) -> Bool { true }
  }
  func makeNSView(context: Context) -> NSButton {
    let button = Control(title: "", target: context.coordinator, action: #selector(Coordinator.invoke(_:)))
    button.isBordered = false
    button.setButtonType(.momentaryChange)
    return button
  }
  func updateNSView(_ button: NSButton, context: Context) {
    context.coordinator.action = action
    if button.identifier?.rawValue != identifier {
      button.identifier = NSUserInterfaceItemIdentifier(identifier)
      button.setAccessibilityIdentifier(identifier)
    }
    if button.accessibilityLabel() != title { button.setAccessibilityLabel(title) }
    if button.toolTip != title { button.toolTip = title }
    if button.isEnabled != enabled { button.isEnabled = enabled }
    if ["dialog.close", "dialog.done", "dialog.cancel", "options.close"].contains(identifier) {
      button.keyEquivalent = "\u{1b}"
      button.keyEquivalentModifierMask = []
    } else if identifier == "dialog.done.default" {
      button.keyEquivalent = "\r"
      button.keyEquivalentModifierMask = []
    }
  }
  func sizeThatFits(_ proposal: ProposedViewSize, nsView: NSButton, context: Context) -> CGSize? {
    CGSize(width: proposal.width ?? 100, height: proposal.height ?? 32)
  }
}

/// Use refreshed executable detection, including after an installation completes.
func connectionInstallPlan(_ selection: [String: Any], routes: [[String: Any]]) -> [String: Any]? {
  let initial = selection["route"] as? [String: Any] ?? selection
  let current = routes.first { string($0, "id") == string(initial, "id") && !string(initial, "id").isEmpty } ?? initial
  guard current["available"] as? Bool != true else { return nil }
  return current["install"] as? [String: Any] ?? selection["install"] as? [String: Any]
}

/// A native rendering of the same ownership ladder and profiles used by :connect.
struct ConnectionView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  @State private var path = ["menu:root"]
  @State private var menu: [String: Any] = [:]
  @State private var menuCache: [String: [String: Any]] = [:]
  @State private var details: [String: [String: Any]] = [:]
  private var selected: [String: Any] { details[page] ?? [:] }
  @State private var loading = false
  @State private var failure = ""
  @State private var search = ""
  @State private var pendingHarness = ""
  @State private var builderPreset = "core"
  @State private var builderBackend = ""
  @State private var runtimes: [[String: Any]] = []
  @State private var registry: [String: Any] = [:]
  @State private var customEditing: [String: Any] = [:]
  @State private var authentication: [String: Any]?
  @State private var terminalError = ""
  @State private var terminalLogin: [String]?
  @State private var loginNotice = ""
  init(initialPage: String = "menu:root") {
    _path = State(
      initialValue: initialPage == "menu:root" ? ["menu:root"] : ["menu:root", initialPage])
  }
  private var page: String { path.last ?? "menu:root" }
  var body: some View {
    VStack(spacing: 0) {
      HStack(spacing: 12) {
        nativeButton("connect.back", action: back) {
          Label("Back", systemImage: "chevron.left")
        }
        .disabled(path.count == 1)
        nativeButton("connect.root", action: {
          path = ["menu:root"]
          search = ""
        }) { Text("All connections") }
        if page != "menu:root" {
          Text("/").foregroundStyle(.secondary)
          Text(title).lineLimit(1).font(.headline)
        }
        Spacer()
        if !app.connectionDisconnected {
          nativeButton("connect.disconnect", action: { app.disconnectConnection(); dismiss() }, title: "Disconnect current connection") {
            Text("Disconnect")
          }.disabled(app.anyActive || app.busy)
            .help("Detach the selected connection. Saved sign-ins and history stay on your Mac.")
        }
        nativeButton("connect.close", action: { dismiss() }) { Text("Close") }
      }.buttonStyle(.bordered).padding(20).background(Color.qPanel)
      Divider()
      Group {
        if page.hasPrefix("source:") {
          ConnectionSourcesView(mode: page == "source:local" ? "Local model" : "Provider API key")
        } else if page.hasPrefix("configure:") {
          HarnessConfigurationView(mode: String(page.dropFirst(10))) { id in
            app.chooseHarness(id)
            push("menu:models")
          }
        } else if page == "systemone" {
          SystemOneConnectionView {
            app.chooseHarness("systemone")
            push("menu:models")
          }
        } else if page.hasPrefix("vendor-key:") {
          VendorKeyConnectionView(entry: String(page.dropFirst(11)))
        } else if page == "builder" {
          HarnessBuilderView(initialPreset: builderPreset, initialBackend: builderBackend) { id in
            app.chooseHarness(id)
            push("menu:models")
          }
        } else if page == "custom-acp" {
          CustomACPAgentView(project: app.projectID, initial: customEditing, removed: { path = ["menu:root", "acp"] }) { route in
            showDetail(["name": string(route, "name"), "route": route])
          }
        } else if page.hasPrefix("protocol:") {
          ProtocolConnectionView(kind: String(page.dropFirst(9))) { route in
            app.chooseConnection(route)
            dismiss()
          }
        } else {
          ScrollView {
            VStack(alignment: .leading, spacing: 18) {
              PageTitle(eyebrow: "Connect", title: title, subtitle: subtitle)
              if page == "menu:root" {
                HStack {
                  nativeButton("connect.subscriptions", action: { push("menu:vendors") }) { Text("Existing subscription") }
                  nativeButton("connect.acp", action: { push("acp") }) { Text("ACP agent") }
                  nativeButton("connect.models", action: { push("menu:harness") }) { Text("Local model / API key") }
                }.controlSize(.large)
                HStack {
                  Button("Build your own harness…") { push("builder") }
                  Button("Browse all agent runtimes…") { push("runtimes") }
                }
              }
              if page == "menu:root", let chips = menu["detected"] as? [[String: Any]],
                !chips.isEmpty
              {
                VStack(alignment: .leading, spacing: 10) {
                  Text("DETECTED ON THIS MAC").font(
                    .system(size: 11, weight: .semibold, design: .monospaced)
                  ).foregroundStyle(.secondary)
                  ScrollView(.horizontal) {
                    HStack {
                      ForEach(Array(chips.enumerated()), id: \.offset) { _, chip in
                        Button(string(chip, "label")) {
                          if let route = chip["route"] as? [String: Any] {
                            showDetail([
                              "name": string(route, "name"),
                              "description": string(route, "description"), "route": route,
                            ])
                          } else if string(chip, "kind") == "menu" {
                            push("menu:" + string(chip, "target"))
                          } else if string(chip, "kind") == "local" {
                            push("menu:harness")
                          }
                        }.disabled(string(chip, "kind") == "info")
                      }
                    }
                  }
                }
              }
              if loading { ProgressView("Loading connections…") }
              if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
              if page.hasPrefix("leaf:") {
                leaf
              } else if ["acp", "acp-clients"].contains(page) {
                agentRows
              } else if page == "harnesses" {
                harnessRows
              } else if page == "runtimes" {
                runtimeRows
              } else {
                ForEach(menu["rows"] as? [[String: Any]] ?? [], id: \.projectRowID) { row in
                  choice(row) { activate(row) }
                }
              }
            }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
          }.defaultScrollAnchor(.top).id(page)
        }
      }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
      Divider()
      Label(
        "Your connection owns its authentication. Remote protocol tasks go directly to the server you select.",
        systemImage: "lock.shield"
      )
      .font(.caption).foregroundStyle(.secondary).padding(16)
    }.frame(
      width: min(860, (NSScreen.main?.visibleFrame.width ?? 960) - 100),
      height: min(740, (NSScreen.main?.visibleFrame.height ?? 840) - 100)
    ).background { BrandBackdrop() }
      .task(id: page) { await loadMenu() }
      .onExitCommand { if path.count > 1 { back() } else { dismiss() } }
      .onChange(of: app.projectID) { _, _ in dismiss() }
      .centeredDialog(
        isPresented: Binding(
          get: { terminalLogin != nil }, set: { if !$0 { terminalLogin = nil } }),
        title: "Sign in", onDismiss: {
          if loginNotice.hasPrefix("Starting sign-in") {
            loginNotice = "Sign-in closed before completion. Try again or follow the agent’s sign-in instructions."
          }
        }
      ) {
        if let arguments = terminalLogin {
          TerminalLoginView(terminals: app.terminals, arguments: arguments) {
            loginNotice = "Sign-in completed. Check the connection before starting a task."
            menuCache = [:]
            app.perform { try await app.refreshDefinitions() }
          }.environmentObject(app)
        }
      }
      .centeredDialog(
        isPresented: Binding(
          get: { authentication != nil }, set: { if !$0 { authentication = nil } }),
        title: "Authentication", onDismiss: {
          if loginNotice.hasPrefix("Starting sign-in") {
            loginNotice = "Sign-in closed before completion. Try signing in again, or complete the agent’s sign-in in Terminal and check the connection."
          }
        }
      ) {
        if let request = authentication {
          AuthenticationProgressView(request: request) { result in
            if result["signed_in"] as? Bool == true {
              loginNotice = "Sign-in completed. Choose Use this connection to continue. Model access is verified by the agent when you start a task."
              app.notice = loginNotice
            }
            authentication = nil
            menuCache = [:]
            app.perform {
              let definitions =
                try await app.engine.call("harnesses.list", ["project": app.projectID])
                as? [[String: Any]] ?? []
              let routes =
                try await app.engine.call("routes.list", ["project": app.projectID])
                as? [[String: Any]] ?? []
              app.harnesses = definitions + routes
              registry = (try? await app.engine.call("connect.acp.registry.status")) as? [String: Any] ?? [:]
            }
          }
        }
      }
  }
  private var title: String {
    if page == "configure:wizard" { return "Harness wizard" }
    if page == "configure:rlm" { return "RLM profile" }
    if page == "configure:rlm-routing" { return "A2A routing" }
    if page == "systemone" { return "SystemOne" }
    if page.hasPrefix("vendor-key:") { return "Vendor API key" }
    if page.hasPrefix("leaf:") { return string(selected, "name", "Connection") }
    if page == "builder" { return "Build your own harness" }
    if ["acp", "acp-clients"].contains(page) { return "ACP connections" }
    if page == "harnesses" { return "Choose an existing HarnessSpec" }
    if page == "runtimes" { return "Agent runtimes" }
    if page.hasPrefix("protocol:") {
      return page.hasSuffix("uhp") ? "Unified Harness Protocol (UHP)" : "Agent2Agent (A2A)"
    }
    if page == "source:local" { return "Local model" }
    if page.hasPrefix("source:") { return "Connect a model to your harness" }
    return string(menu, "title", "Connect")
  }
  private var subtitle: String {
    if page == "configure:wizard" { return "Harness wizard" }
    if page == "configure:rlm" { return "RLM profile" }
    if page == "configure:rlm-routing" { return "A2A routing" }
    if page == "systemone" { return "SystemOne" }
    if page.hasPrefix("vendor-key:") { return "Vendor API key" }
    if page.hasPrefix("leaf:") { return string(selected, "description") }
    if ["acp", "acp-clients"].contains(page) {
      return "Choose a local coding agent. It keeps its own harness, model and sign-in."
    }
    if page == "harnesses" { return "Choose the harness first. Connect its model next." }
    if page == "runtimes" {
      return "Explore all registered agent runtimes and harness backends. Each entry shows its setup status and supported selection path."
    }
    return string(menu, "subtitle")
  }
  private func showDetail(_ row: [String: Any]) {
    let id = "leaf:" + UUID().uuidString
    var enriched = row
    if let route = row["route"] as? [String: Any] {
      if let install = route["install"] { enriched["install"] = install }
    }
    details[id] = enriched
    push(id)
  }
  private func push(_ destination: String) {
    failure = ""
    search = ""
    path.append(destination)
  }
  private func back() {
    if path.count > 1 {
      path.removeLast()
      search = ""
      failure = ""
    }
  }
  private func loadMenu() async {
    if ["acp", "acp-clients"].contains(page) {
      registry = (try? await app.engine.call("connect.acp.registry.status")) as? [String: Any] ?? [:]
      return
    }
    if page == "runtimes" {
      do {
        runtimes = try await app.engine.call("connect.runtimes") as? [[String: Any]] ?? []
      } catch { failure = error.localizedDescription }
      return
    }
    guard page.hasPrefix("menu:") else { return }
    let target = page
    if let cached = menuCache[target] {
      menu = cached
      loading = false
      return
    }
    loading = true
    menu = [:]
    failure = ""
    do {
      let result =
        try await app.engine.call(
          "connect.menu", ["project": app.projectID, "menu": String(target.dropFirst(5))])
        as? [String: Any] ?? [:]
      guard page == target else { return }
      menu = result
      menuCache[target] = result
    } catch { if page == target { failure = error.localizedDescription } }
    if page == target { loading = false }
  }
  private func choice(_ row: [String: Any], action: @escaping () -> Void) -> some View {
    nativeButton("connect.row." + row.projectRowID, action: action, padded: false, title: string(row, "name")) {
      HStack(spacing: 16) {
        Image(systemName: "arrow.triangle.branch").font(.title2).foregroundStyle(Brand.gradient)
          .frame(width: 30)
        VStack(alignment: .leading, spacing: 7) {
          Text(string(row, "name")).font(.system(size: 15, weight: .semibold))
          Text(string(row, "description")).font(.callout).foregroundStyle(.secondary).fixedSize(
            horizontal: false, vertical: true)
        }
        Spacer()
        Image(systemName: "chevron.right").foregroundStyle(.secondary)
      }.padding(18).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
        .contentShape(Rectangle())
    }
  }
  private var agentRows: some View {
    ACPAgentCatalogView(registry: registry, search: $search,
      refreshRegistry: { authentication = ["action": "registry-refresh"] },
      addCustom: { customEditing = [:]; push("custom-acp") },
      open: { row in
        showDetail(["name": string(row, "name"), "description": string(row, "description"), "route": row])
      }, initialTab: page == "acp-clients" ? "clients" : "agents")
  }
  private var runtimeRows: some View {
    VStack(alignment: .leading, spacing: 14) {
      TextField("Find a runtime or harness", text: $search).textFieldStyle(.roundedBorder)
      Text("\(runtimes.count) runtimes and harness backends · optional dependencies and sign-in may be required")
        .font(.caption).foregroundStyle(.secondary)
      ForEach(runtimes.filter { row in
        search.isEmpty || ["display_name", "backend", "description"].map { string(row, $0) }
          .joined(separator: " ").localizedCaseInsensitiveContains(search)
      }, id: \.runtimeRowID) { row in
        VStack(alignment: .leading, spacing: 8) {
          Text(string(row, "display_name", string(row, "backend"))).font(.headline)
          Text(string(row, "backend") + " · " + string(row, "availability", "unknown"))
            .font(.caption).foregroundStyle(.secondary)
          Text(string(row, "description")).foregroundStyle(.secondary)
          if !string(row, "install_hint").isEmpty {
            Text(string(row, "install_hint")).font(.caption).textSelection(.enabled)
          }
          if row["harness_backend"] as? Bool == true {
            if row["supports_coding"] as? Bool == true {
              Text(row["agent_runtime"] as? Bool == true ? "Direct agent runtime and HarnessSpec backend" : "HarnessSpec backend")
                .font(.caption).foregroundStyle(.secondary)
              Button("Build with this runtime…") {
                builderPreset = "core"
                builderBackend = string(row, "backend")
                push("builder")
              }
            } else {
              Text("Decision backend · evaluates structured state rather than running a coding loop.")
                .font(.caption).foregroundStyle(.secondary)
              Button("Configure SystemOne…") { push("systemone") }
            }
          } else {
            Text("Direct runtime in CLI/TUI. Native connection options vary by agent.")
              .font(.caption).foregroundStyle(.secondary)
          }
          if row["agent_runtime"] as? Bool == true {
            Text("superqode --runtime " + string(row, "backend"))
              .font(.system(.caption, design: .monospaced)).textSelection(.enabled)
          }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
      }
      Text("Harness definitions").font(.headline)
      ForEach(app.harnesses.filter { row in
        string(row, "desktop_kind").isEmpty && (search.isEmpty ||
          ["name", "runtime", "description"].map { string(row, $0) }.joined(separator: " ").localizedCaseInsensitiveContains(search))
      }, id: \.projectRowID) { row in
        VStack(alignment: .leading, spacing: 8) {
          Text(string(row, "name")).font(.headline)
          Text(string(row, "runtime") + " · " + string(row, "description")).foregroundStyle(.secondary)
          if !string(row, "issue").isEmpty { Text(string(row, "issue")).font(.caption).textSelection(.enabled) }
          HStack {
            Button("Use runtime") { app.chooseHarness(string(row, "id")); push("menu:models") }
              .disabled(row["available"] as? Bool != true)
            Button("Customize harness…") { builderPreset = string(row, "id"); builderBackend = ""; push("builder") }
          }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
      }
    }
  }
  private var harnessRows: some View {
    VStack(spacing: 12) {
      ForEach(app.harnesses.filter { string($0, "desktop_kind").isEmpty }, id: \.projectRowID) {
        row in
        choice(row) {
          pendingHarness = string(row, "id")
          app.chooseHarness(pendingHarness)
          push("menu:models")
        }
      }
    }
  }
  private var leaf: some View {
    VStack(alignment: .leading, spacing: 16) {
      if let route = selected["route"] as? [String: Any], string(route, "desktop_kind") == "acp" {
        ACPSetupView(initialRoute: route, project: app.projectID, use: { verifiedRoute, metadata in
          app.chooseConnection(verifiedRoute, verified: metadata)
          dismiss()
        }, edit: { customEditing = route; push("custom-acp") })
      } else {
        if let requirements = selected["requirements"] as? [[String: Any]], !requirements.isEmpty {
          ConnectionRequirementsView(requirements: requirements)
          Button("Check installation again") { Task { await recheckPrerequisites() } }
            .disabled(loading || app.busy || app.anyActive)
        }
        if let login = selected["login"] as? [String: Any] {
          Button("Sign in to " + string(login, "label")) {
            terminalError = ""
            loginNotice = "Starting sign-in. Follow the instructions in the sign-in window."
            if login["interactive"] as? Bool == true {
              terminalLogin = login["command"] as? [String] ?? []
            } else {
              authentication = ["action": "subscription", "vendor": string(login, "id")]
            }
          }.disabled(login["available"] as? Bool != true || loading || app.busy || app.anyActive)
          if !terminalError.isEmpty { Text(terminalError).foregroundStyle(.orange) }
          if !loginNotice.isEmpty { Text(loginNotice).font(.callout).textSelection(.enabled) }
          if string(selected, "id") == "codex-sdk" {
            Text("Codex SDK signs in through the installed Codex CLI. If SDK setup is unavailable, choose Codex CLI from Existing subscription to use the same account without the optional SDK.")
              .font(.caption).foregroundStyle(.secondary)
          }
        }
        if let initialRoute = selected["route"] as? [String: Any] {
          let route =
            app.harnesses.first { string($0, "id") == string(initialRoute, "id") } ?? initialRoute
          Pill(title: string(route, "auth", "Agent-managed authentication"), color: .qAccent)
          Text(
            "Use the vendor’s existing local sign-in. The agent owns its model and coding loop; no separate model or harness configuration is needed."
          ).foregroundStyle(.secondary)
          Text(
            "Subscription access and billing remain unverified until the vendor connects. SuperQode removes known API-key overrides for explicit subscription routes."
          ).font(.caption).foregroundStyle(.secondary)
          if route["available"] as? Bool != true {
            Text(
              string(route, "issue", "Install and sign in to this agent in Terminal, then reconnect.")
            ).textSelection(.enabled)
          }
          nativeButton("connect.use", action: {
            app.chooseConnection(route)
            dismiss()
          }) { Text("Use this connection") }
            .disabled(route["available"] as? Bool != true || selected["setup_ready"] as? Bool == false || loading || app.busy || app.anyActive)
        } else {
          let issue = string(selected, "issue")
          Text(
            issue.isEmpty
              ? "This catalog entry does not expose an executable connection. Review its setup notes or choose another connection."
              : issue
          ).textSelection(.enabled)
          if !string(selected, "setup_note").isEmpty {
            Text(string(selected, "setup_note")).font(.caption).foregroundStyle(.secondary)
          }
          if string(selected, "connector") == "plan-guidance" {
            Text(
              "This model subscription integration is experimental and unavailable in the terminal too. Use a vendor subscription agent from Existing harnesses → Subscriptions instead."
            ).font(.callout).foregroundStyle(.secondary)
            Button("Browse subscription agents") { push("menu:vendors") }
          }
          Button("Choose an existing HarnessSpec") { push("harnesses") }
        }
        if let plan = connectionInstallPlan(selected, routes: app.harnesses) {
          Divider().padding(.top, 8)
          Label("Installation required", systemImage: "arrow.down.circle").font(.headline)
          Text("Install this agent on your Mac, then use the connection above.")
            .font(.callout).foregroundStyle(.secondary)
          CodeBlock(text: string(plan, "command")).frame(height: 70)
          if let requirements = plan["requirements"] as? [[String: Any]], !requirements.isEmpty {
            ConnectionRequirementsView(requirements: requirements)
          }
          Button("Install this agent…") {
            if app.confirm(
              "Install this coding agent?",
              "Run the reviewed package-manager command on this Mac:\n" + string(plan, "command"),
              button: "Install")
            {
              authentication = [
                "action": "install", "project": app.projectID, "reference": string(plan, "reference"),
              ]
            }
          }.disabled((plan["requirements"] as? [[String: Any]] ?? []).contains(where: { $0["installed"] as? Bool != true }) || loading || app.busy || app.anyActive)
        }
      }
    }
  }
  private func recheckPrerequisites() async {
    let identity = page
    let project = app.projectID
    let reference = string(selected, "id")
    loading = true
    defer { loading = false }
    do {
      let refreshed = try await app.engine.call("connect.menu", ["project": project, "menu": string(selected, "menu", "vendors")]) as? [String: Any] ?? [:]
      try await app.refreshDefinitions()
      guard page == identity, app.projectID == project else { return }
      if let row = (refreshed["rows"] as? [[String: Any]])?.first(where: { string($0, "id") == reference }) {
        details[identity] = row
      }
      menuCache = [:]; failure = ""
    } catch { if page == identity { failure = error.localizedDescription } }
  }
  private func activate(_ row: [String: Any]) {
    if let vendor = row["vendor_key"] as? [String: Any], string(row, "harness_ref").isEmpty,
      row["attachment"] == nil
    {
      push("vendor-key:" + string(vendor, "entry_id"))
      return
    }
    let next = string(row, "next")
    if !next.isEmpty {
      push("menu:" + next)
      return
    }
    switch string(row, "connector") {
    case "systemone": push("systemone")
    case "acp-picker": push("acp")
    case "a2a-picker": push("protocol:a2a")
    case "uhp-picker": push("protocol:uhp")
    case "harness-use":
      pendingHarness = string(row, "runtime")
      app.chooseHarness(pendingHarness)
      push("menu:models")
    case "local": push("source:local")
    case "byok": push("source:key")
    case "harness-catalog", "harness-picker": push("harnesses")
    case "harness-wizard": push("configure:wizard")
    case "rlm-settings": push("configure:rlm")
    case "rlm-routing": push("configure:rlm-routing")
    case "harness-import", "harness-preset", "harness-blank": push("builder")
    case "key-harness", "vendor-key", "harness-account":
      if !string(row, "harness_ref").isEmpty {
        pendingHarness = string(row, "harness_ref")
        app.chooseHarness(pendingHarness)
        push("menu:key-models")
      } else if let attachment = row["attachment"] as? [String: Any] {
        let id = string(attachment, "id")
        if !app.harnesses.contains(where: { string($0, "id") == id }) {
          app.harnesses.append(attachment)
        }
        app.chooseHarness(id)
        app.model = ""
        push("menu:key-models")
      } else {
        showDetail(row)
      }
    default:
      showDetail(row)
    }
  }
}

struct ProtocolConnectionView: View {
  @EnvironmentObject var app: Workspace
  let kind: String
  let select: ([String: Any]) -> Void
  @State private var url = ""
  @State private var token = ""
  @State private var headers = ""
  @State private var cert = ""
  @State private var key = ""
  @State private var discovery: [String: Any] = [:]
  @State private var oauth = false
  @State private var clientID = ""
  @State private var clientSecret = ""
  @State private var authorization: [String: Any]?
  @State private var busy = false
  @State private var failure = ""
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(
          eyebrow: kind.uppercased(), title: "Connect directly to your server",
          subtitle:
            "The remote agent owns its workspace, model, tools and permissions. This does not upload your local project. Only the task you send goes to this server."
        )
        Text(
          "Responses stream when supported. Continue session reuses the remote conversation. Cancellation waits for acknowledgement from the server."
        ).font(.caption).foregroundStyle(.secondary)
        TextField("https://your-server", text: $url).textFieldStyle(.roundedBorder).disabled(busy)
        SecureField("Bearer token (optional, this app session only)", text: $token).textFieldStyle(
          .roundedBorder
        ).disabled(busy)
        if kind == "a2a" {
          Toggle("Sign in with OAuth in your browser", isOn: $oauth).disabled(busy)
          if oauth {
            TextField(
              "OAuth client ID (optional if dynamic registration is supported)", text: $clientID
            ).textFieldStyle(.roundedBorder)
            SecureField("OAuth client secret (optional)", text: $clientSecret).textFieldStyle(
              .roundedBorder)
            Text(
              "OAuth uses the existing local SuperQode credential store. Browser sign-in never goes through a SuperQode cloud relay."
            ).font(.caption).foregroundStyle(.secondary)
          }
          DisclosureGroup("Additional authentication") {
            VStack(spacing: 12) {
              SecureField("Headers: X-API-Key:value; Authorization:Basic …", text: $headers)
                .textFieldStyle(.roundedBorder)
              TextField("Client certificate PEM path (optional)", text: $cert).textFieldStyle(
                .roundedBorder)
              TextField("Client private key PEM path (optional)", text: $key).textFieldStyle(
                .roundedBorder)
              Text(
                "Use a provider-issued bearer token, API key, Basic authentication headers or a client certificate. OAuth can obtain and refresh a token through the browser."
              ).font(.caption).foregroundStyle(.secondary)
            }.padding(.top, 10)
          }.disabled(busy)
        }
        Button(busy ? "Discovering…" : (kind == "uhp" ? "Discover harnesses" : "Read Agent Card")) {
          discover()
        }
        .buttonStyle(BrandButtonStyle()).disabled(busy || url.isEmpty)
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
        if !discovery.isEmpty {
          Text(string(discovery, "name")).font(.title2)
          Text("Discovered at " + string(discovery, "url")).font(.caption).foregroundStyle(
            .secondary)
          if kind == "a2a" {
            ForEach(discovery["items"] as? [[String: Any]] ?? [], id: \.projectRowID) { item in
              VStack(alignment: .leading, spacing: 6) {
                Text(string(item, "name")).font(.headline)
                Text(string(item, "description")).font(.caption)
              }.padding(14).brandSurface()
            }
            Button("Use this agent") { use("") }.buttonStyle(BrandButtonStyle()).disabled(busy)
          } else {
            ForEach(discovery["items"] as? [[String: Any]] ?? [], id: \.projectRowID) { item in
              HStack {
                Text(string(item, "name", string(item, "id")))
                Spacer()
                Button("Use harness") { use(string(item, "id")) }.buttonStyle(BrandButtonStyle())
                  .disabled(busy)
              }.padding(14).brandSurface()
            }
          }
        }
      }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
    }.defaultScrollAnchor(.top)
      .onAppear { url = UserDefaults.standard.string(forKey: "nativeProtocolURL:" + kind) ?? "" }
      .onChange(of: url) { _, _ in discovery = [:] }
      .onChange(of: token) { _, _ in discovery = [:] }
      .onChange(of: headers) { _, _ in discovery = [:] }
      .onChange(of: cert) { _, _ in discovery = [:] }
      .onChange(of: key) { _, _ in discovery = [:] }
      .centeredDialog(
        isPresented: Binding(
          get: { authorization != nil }, set: { if !$0 { authorization = nil } }),
        title: "Authorization"
      ) {
        if let request = authorization {
          AuthenticationProgressView(request: request) { result in
            discovery = result
            authorization = nil
          }
        }
      }
  }
  private func discover() {
    failure = ""
    discovery = [:]
    if oauth && kind == "a2a" {
      authorization = [
        "action": "oauth", "project": app.projectID, "protocol": kind, "url": url, "token": token,
        "headers": headers, "cert": cert, "key": key, "oauth": true, "client_id": clientID,
        "client_secret": clientSecret,
      ]
      return
    }
    busy = true
    Task {
      defer { busy = false }
      do {
        discovery =
          try await app.engine.call(
            "connect.protocol",
            [
              "project": app.projectID, "protocol": kind, "url": url, "token": token,
              "headers": headers, "cert": cert, "key": key,
            ]) as? [String: Any] ?? [:]
      } catch { failure = error.localizedDescription }
    }
  }
  private func use(_ harness: String) {
    busy = true
    Task {
      defer { busy = false }
      do {
        let route =
          try await app.engine.call(
            "connect.protocol.select",
            [
              "project": app.projectID, "connection": string(discovery, "connection"),
              "harness": harness,
            ]) as? [String: Any] ?? [:]
        UserDefaults.standard.set(url, forKey: "nativeProtocolURL:" + kind)
        select(route)
      } catch { failure = error.localizedDescription }
    }
  }
}

struct HarnessBuilderView: View {
  @EnvironmentObject var app: Workspace
  let select: (String) -> Void
  @State private var name = "my-harness"
  @State private var preset = "core"
  @State private var yaml = ""
  @State private var message = ""
  @State private var busy = false
  let initialBackend: String
  init(initialPreset: String = "core", initialBackend: String = "", select: @escaping (String) -> Void) {
    self.select = select
    self.initialBackend = initialBackend
    _preset = State(initialValue: initialPreset)
  }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(
          eyebrow: "Repository-owned HarnessSpec", title: "Make the coding loop yours",
          subtitle:
            "Start with an existing harness or import a definition. Review its tools and execution policy before saving a new project harness. No run starts when you save."
        )
        TextField("New harness name", text: $name).textFieldStyle(.roundedBorder)
        if !initialBackend.isEmpty {
          Text("Runtime: " + initialBackend + ". Review runtime configuration and provider requirements in the definition below.")
            .font(.callout).foregroundStyle(.secondary)
        }
        HStack {
          Picker("Start from", selection: $preset) {
            ForEach(app.harnesses.filter { string($0, "desktop_kind").isEmpty }, id: \.projectRowID)
            { row in Text(string(row, "name")).tag(string(row, "id")) }
          }
          Button("Load preset") { loadPreset() }.disabled(busy)
          Button("Import YAML…") { importYAML() }.disabled(busy)
        }
        TextEditor(text: $yaml).font(.system(size: 12, design: .monospaced))
          .scrollContentBackground(.hidden).padding(12).frame(height: 320).brandSurface()
        Text(
          "Saved under .superqode/harnesses. Existing definitions are never overwritten. The model is selected after this step."
        ).font(.caption).foregroundStyle(.secondary)
        if !message.isEmpty { Text(message).foregroundStyle(.orange).textSelection(.enabled) }
        Button("Save harness and choose model") { save() }.buttonStyle(BrandButtonStyle()).disabled(
          busy || yaml.isEmpty || name.isEmpty)
      }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
    }.defaultScrollAnchor(.top).task { if yaml.isEmpty { loadPreset() } }
  }
  private func loadPreset() {
    busy = true
    message = ""
    Task {
      defer { busy = false }
      do {
        let result =
          try await app.engine.call(
            "connect.harness.draft", ["project": app.projectID, "harness": preset, "backend": initialBackend])
          as? [String: Any] ?? [:]
        yaml = string(result, "yaml")
      } catch { message = error.localizedDescription }
    }
  }
  private func importYAML() {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = false
    panel.allowsMultipleSelection = false
    if panel.runModal() == .OK, let url = panel.url {
      do {
        let attributes = try FileManager.default.attributesOfItem(atPath: url.path)
        guard (attributes[.size] as? NSNumber)?.intValue ?? 0 <= 250_000 else {
          message = "Choose a definition smaller than 250 KB."
          return
        }
        yaml = try String(contentsOf: url, encoding: .utf8)
      } catch { message = error.localizedDescription }
    }
  }
  private func save() {
    busy = true
    message = ""
    Task {
      defer { busy = false }
      do {
        let result =
          try await app.engine.call(
            "connect.harness.save", ["project": app.projectID, "name": name, "yaml": yaml])
          as? [String: Any] ?? [:]
        let definitions =
          try await app.engine.call("harnesses.list", ["project": app.projectID])
          as? [[String: Any]] ?? []
        let routes = app.harnesses.filter { !string($0, "desktop_kind").isEmpty }
        app.harnesses = definitions + routes
        select(string(result, "id"))
      } catch { message = error.localizedDescription }
    }
  }
}

extension Dictionary where Key == String, Value == Any {
  var runtimeRowID: String { string(self, "backend") }
}
