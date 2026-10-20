import AppKit
import SwiftUI

/// A native rendering of the same ownership ladder and profiles used by :connect.
struct ConnectionView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  @State private var path = ["menu:root"]
  @State private var menu: [String: Any] = [:]
  @State private var details: [String: [String: Any]] = [:]
  private var selected: [String: Any] { details[page] ?? [:] }
  @State private var loading = false
  @State private var failure = ""
  @State private var search = ""
  @State private var pendingHarness = ""
  @State private var authentication: [String: Any]?
  @State private var terminalError = ""
  @State private var terminalLogin: [String]?
  init(initialPage: String = "menu:root") {
    _path = State(
      initialValue: initialPage == "menu:root" ? ["menu:root"] : ["menu:root", initialPage])
  }
  private var page: String { path.last ?? "menu:root" }
  var body: some View {
    VStack(spacing: 0) {
      HStack(spacing: 12) {
        Button {
          back()
        } label: {
          Label("Back", systemImage: "chevron.left")
        }
        .disabled(path.count == 1)
        Button("Connect") {
          path = ["menu:root"]
          search = ""
        }.buttonStyle(.plain)
        if page != "menu:root" {
          Text("/").foregroundStyle(.secondary)
          Text(title).lineLimit(1).font(.headline)
        }
        Spacer()
        Button("Close") { dismiss() }
      }.padding(20).modifier(NavigationGlass()).padding(10)
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
          HarnessBuilderView { id in
            app.chooseHarness(id)
            push("menu:models")
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
              } else if page == "acp" {
                agentRows
              } else if page == "harnesses" {
                harnessRows
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
      .centeredDialog(
        isPresented: Binding(get: { terminalLogin != nil }, set: { if !$0 { terminalLogin = nil } })
      ) {
        if let arguments = terminalLogin {
          TerminalLoginView(terminals: app.terminals, arguments: arguments) {
            app.perform { try await app.refreshDefinitions() }
          }.environmentObject(app)
        }
      }
      .centeredDialog(
        isPresented: Binding(
          get: { authentication != nil }, set: { if !$0 { authentication = nil } })
      ) {
        if let request = authentication {
          AuthenticationProgressView(request: request) { _ in
            authentication = nil
            app.perform {
              let definitions =
                try await app.engine.call("harnesses.list", ["project": app.projectID])
                as? [[String: Any]] ?? []
              let routes =
                try await app.engine.call("routes.list", ["project": app.projectID])
                as? [[String: Any]] ?? []
              app.harnesses = definitions + routes
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
    if page == "acp" { return "Agent Client Protocol (ACP)" }
    if page == "harnesses" { return "Choose an existing HarnessSpec" }
    if page.hasPrefix("protocol:") {
      return page.hasSuffix("uhp") ? "Unified Harness Protocol (UHP)" : "Agent2Agent (A2A)"
    }
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
    if page == "acp" {
      return "Choose a local coding agent. It keeps its own harness, model and sign-in."
    }
    if page == "harnesses" { return "Choose the harness first. Connect its model next." }
    return string(menu, "subtitle")
  }
  private func showDetail(_ row: [String: Any]) {
    let id = "leaf:" + UUID().uuidString
    details[id] = row
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
    guard page.hasPrefix("menu:") else { return }
    let target = page
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
    } catch { if page == target { failure = error.localizedDescription } }
    if page == target { loading = false }
  }
  private func choice(_ row: [String: Any], action: @escaping () -> Void) -> some View {
    Button(action: action) {
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
    }.buttonStyle(.plain)
  }
  private var agentRows: some View {
    VStack(alignment: .leading, spacing: 12) {
      TextField("Find an ACP agent", text: $search).textFieldStyle(.roundedBorder)
      ForEach(
        app.harnesses.filter {
          string($0, "desktop_kind") == "acp"
            && (search.isEmpty || string($0, "name").localizedCaseInsensitiveContains(search))
        }.sorted { string($0, "name") < string($1, "name") }, id: \.projectRowID
      ) { row in
        choice(row) {
          showDetail([
            "name": string(row, "name"), "description": string(row, "description"), "route": row,
          ])
        }
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
      if let plan = selected["install"] as? [String: Any] {
        CodeBlock(text: string(plan, "command")).frame(height: 70)
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
        }
      }
      if let login = selected["login"] as? [String: Any] {
        Button("Sign in to " + string(login, "label")) {
          if login["interactive"] as? Bool == true {
            terminalLogin = login["command"] as? [String] ?? []
          } else {
            authentication = ["action": "subscription", "vendor": string(login, "id")]
          }
        }
        if !terminalError.isEmpty { Text(terminalError).foregroundStyle(.orange) }
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
        Button("Use this connection") {
          app.chooseConnection(route)
          dismiss()
        }.buttonStyle(BrandButtonStyle()).disabled(route["available"] as? Bool != true)
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
    }
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
        isPresented: Binding(get: { authorization != nil }, set: { if !$0 { authorization = nil } })
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
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(
          eyebrow: "Repository-owned HarnessSpec", title: "Make the coding loop yours",
          subtitle:
            "Start with an existing harness or import a definition. Review its tools and execution policy before saving a new project harness. No run starts when you save."
        )
        TextField("New harness name", text: $name).textFieldStyle(.roundedBorder)
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
            "connect.harness.draft", ["project": app.projectID, "harness": preset])
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
