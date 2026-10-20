import SwiftUI

struct RoutingPeer: Identifiable {
  let id = UUID()
  var name = ""
  var url = ""
  var description = ""
  var credential = ""
  var skill = ""
  var hosted = false
  var credits = "0"
  var subscription = "GET"
  var data: [String: Any] {
    [
      "name": name, "url": url, "description": description, "credential_env": credential,
      "skill": skill, "hosted": hosted, "credits": Int(credits) ?? -1,
      "subscription_method": subscription,
    ]
  }
}

struct HarnessConfigurationView: View {
  @EnvironmentObject var app: Workspace
  let mode: String
  let complete: (String) -> Void
  @State private var options: [String: Any] = [:]
  @State private var name = "my-harness"
  @State private var starter = "coding"
  @State private var approval = "balanced"
  @State private var format = "auto"
  @State private var workflow = "single"
  @State private var allowWrite = true
  @State private var allowShell = true
  @State private var allowNetwork = false
  @State private var surface = "python"
  @State private var sandbox = "host"
  @State private var observations = "transcript"
  @State private var calls = "0"
  @State private var tokens = "0"
  @State private var cost = "0"
  @State private var routing = false
  @State private var paid = false
  @State private var credits = "0"
  @State private var tasks = "8"
  @State private var parallel = "2"
  @State private var peers: [RoutingPeer] = []
  @State private var yaml = ""
  @State private var failure = ""
  @State private var busy = false
  private var signature: String { pretty(parameters) }
  private var harness: String {
    let row = app.harnesses.first { string($0, "id") == app.harness } ?? [:]
    return string(row, "runtime") == "rlm" ? app.harness : "rlm"
  }
  private var parameters: [String: Any] {
    if mode == "wizard" {
      return [
        "mode": mode,
        "answers": [
          "name": name, "starter": starter, "approval_profile": approval,
          "tool_call_format": format, "workflow_preset": workflow, "allow_write": allowWrite,
          "allow_shell": allowShell, "allow_network": allowNetwork,
        ],
      ]
    }
    let policy: [String: Any] = [
      "enabled": routing, "hosted_enabled": paid, "max_hosted_credits": Int(credits) ?? -1,
      "max_tasks": Int(tasks) ?? -1, "max_parallel": Int(parallel) ?? -1,
      "peers": peers.map(\.data),
    ]
    let budget: [String: Any] = [
      "max_calls": Int(calls) ?? -1, "max_tokens": Int(tokens) ?? -1,
      "max_cost_usd": Double(cost) ?? -1,
    ]
    let profile: [String: Any] = [
      "tool_surface": surface, "sandbox": sandbox, "observations": observations,
      "allow_network": allowNetwork, "allow_write": allowWrite, "allow_shell": allowShell,
      "budget": budget,
    ]
    return ["mode": mode, "harness": harness, "config": mode == "rlm-routing" ? policy : profile]
  }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(
          eyebrow: "Your coding loop",
          title: mode == "wizard"
            ? "Build a harness" : mode == "rlm" ? "RLM profile and budgets" : "RLM agent routing",
          subtitle:
            "Review and save a new project harness. Existing sessions keep their current profile; saving starts no model calls."
        )
        TextField("New harness name", text: $name).textFieldStyle(.roundedBorder)
        if mode == "wizard" {
          catalogPicker("Model family starter", field: "starters", selection: $starter)
          catalogPicker("Approval policy", field: "approvals", selection: $approval)
          catalogPicker("Tool call format", field: "formats", selection: $format)
          catalogPicker("Workflow", field: "workflows", selection: $workflow)
          Toggle("Allow repository writes", isOn: $allowWrite)
          Toggle("Allow shell commands", isOn: $allowShell)
          Toggle("Allow network access", isOn: $allowNetwork)
        } else if mode == "rlm" {
          Picker("Tool profile", selection: $surface) {
            Text("Persistent Python").tag("python")
            Text("Python + Bash · experimental").tag("python-bash")
          }
          Picker("Execution environment", selection: $sandbox) {
            Text("Host").tag("host")
            Text("Docker").tag("docker")
            Text("Monty").tag("monty")
          }
          Picker("Observations", selection: $observations) {
            Text("Transcript").tag("transcript")
            Text("Selective · experimental").tag("selective")
          }
          field("Shared model calls (0 = unlimited)", $calls)
          field("Reported token threshold (0 = unlimited)", $tokens)
          field("Reported USD threshold (0 = unlimited)", $cost)
          Toggle("Allow network access", isOn: $allowNetwork)
          Toggle("Allow repository writes", isOn: $allowWrite)
          Toggle("Allow shell commands", isOn: $allowShell)
          Text(
            "Token and cost thresholds stop subsequent requests after reported usage. A request can cross a threshold. Host execution uses process permissions; Monty does not permit shell or repository writes."
          ).font(.caption).foregroundStyle(.secondary)
        } else {
          Toggle("Enable outbound A2A routing", isOn: $routing)
          Toggle("Allow hosted peers", isOn: $paid)
          field("Hosted credit allowance", $credits)
          field("Maximum delegated tasks", $tasks)
          field("Maximum parallel tasks", $parallel)
          ForEach($peers) { $peer in
            VStack(alignment: .leading, spacing: 10) {
              TextField("Peer name", text: $peer.name)
              TextField("https://agent-server", text: $peer.url)
              TextField("Description", text: $peer.description)
              TextField("Credential environment variable (not the secret)", text: $peer.credential)
              TextField("Skill ID", text: $peer.skill)
              Toggle("Hosted peer", isOn: $peer.hosted)
              field("Credits per task", $peer.credits)
              Picker("Subscription transport", selection: $peer.subscription) {
                Text("GET").tag("GET")
                Text("POST").tag("POST")
              }
              Button("Remove peer", role: .destructive) { peers.removeAll { $0.id == peer.id } }
            }.textFieldStyle(.roundedBorder).padding(16).brandSurface()
          }
          Button("Add peer") { peers.append(RoutingPeer()) }
        }
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
        Button("Review definition") { review() }.disabled(busy)
        if !yaml.isEmpty {
          CodeBlock(text: yaml).frame(height: 220)
          Button("Save harness and choose model") { save() }.buttonStyle(BrandButtonStyle())
            .disabled(busy)
        }
      }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
    }.defaultScrollAnchor(.top)
      .onChange(of: signature) { _, _ in yaml = "" }
      .task {
        name =
          (mode == "wizard" ? "my-harness-" : "rlm-profile-")
          + UUID().uuidString.prefix(6).lowercased()
        do {
          options = try await app.engine.call("connect.options") as? [String: Any] ?? [:]
          if mode != "wizard" {
            let inspected =
              try await app.engine.call(
                "harnesses.inspect", ["project": app.projectID, "reference": harness])
              as? [String: Any] ?? [:]
            let spec = inspected["spec"] as? [String: Any] ?? [:]
            let runtime = spec["runtime"] as? [String: Any] ?? [:]
            let config = runtime["config"] as? [String: Any] ?? [:]
            let execution = spec["execution_policy"] as? [String: Any] ?? [:]
            surface = string(config, "tool_surface", "python")
            sandbox = string(config, "sandbox", "host")
            observations = string(config, "observations", "transcript")
            allowNetwork =
              config["allow_network"] as? Bool ?? execution["allow_network"] as? Bool ?? false
            allowWrite = config["allow_write"] as? Bool ?? execution["allow_write"] as? Bool ?? true
            allowShell = config["allow_shell"] as? Bool ?? execution["allow_shell"] as? Bool ?? true
            let budget = config["budget"] as? [String: Any] ?? [:]
            calls = String(describing: budget["max_calls"] ?? 0)
            tokens = String(describing: budget["max_tokens"] ?? 0)
            cost = String(describing: budget["max_cost_usd"] ?? 0)
            let policy = config["a2a"] as? [String: Any] ?? [:]
            routing = policy["enabled"] as? Bool ?? false
            paid = policy["hosted_enabled"] as? Bool ?? false
            credits = String(describing: policy["max_hosted_credits"] ?? 0)
            tasks = String(describing: policy["max_tasks"] ?? 8)
            parallel = String(describing: policy["max_parallel"] ?? 2)
            peers = (policy["peers"] as? [[String: Any]] ?? []).map { row in
              var peer = RoutingPeer()
              peer.name = string(row, "name")
              peer.url = string(row, "url")
              peer.description = string(row, "description")
              peer.credential = string(row, "credential_env")
              peer.skill = string(row, "skill")
              peer.hosted = row["hosted"] as? Bool ?? false
              peer.credits = String(describing: row["credits"] ?? 0)
              peer.subscription = string(row, "subscription_method", "GET")
              return peer
            }
          }
        } catch { failure = error.localizedDescription }
      }
  }
  private func catalogPicker(_ title: String, field: String, selection: Binding<String>)
    -> some View
  {
    Picker(title, selection: selection) {
      ForEach(options[field] as? [[String: Any]] ?? [], id: \.projectRowID) { row in
        Text(string(row, "label")).tag(string(row, "id"))
      }
    }
  }
  private func field(_ title: String, _ value: Binding<String>) -> some View {
    HStack {
      Text(title)
      Spacer()
      TextField(title, text: value).textFieldStyle(.roundedBorder).frame(width: 140)
    }
  }
  private func review() {
    busy = true
    failure = ""
    Task {
      defer { busy = false }
      do {
        let result =
          try await app.engine.call(
            "connect.harness.configure",
            parameters.merging(["project": app.projectID]) { _, new in new }) as? [String: Any]
          ?? [:]
        yaml = string(result, "yaml")
      } catch { failure = error.localizedDescription }
    }
  }
  private func save() {
    busy = true
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
        app.harnesses = definitions + app.harnesses.filter { !string($0, "desktop_kind").isEmpty }
        complete(string(result, "id"))
      } catch { failure = error.localizedDescription }
    }
  }
}

struct VendorKeyConnectionView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let entry: String
  @State private var key = ""
  @State private var remember = true
  @State private var failure = ""
  @State private var busy = false
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        PageTitle(
          eyebrow: "Vendor-owned harness", title: "Connect your vendor key",
          subtitle:
            "The vendor owns the model and coding loop. This is its API-key route, separate from subscription sign-in."
        )
        SecureField("Vendor API key", text: $key).textFieldStyle(.roundedBorder)
        Toggle("Remember in this Mac’s Keychain", isOn: $remember)
        if (UserDefaults.standard.stringArray(forKey: "nativeVendorKeys") ?? []).contains(entry) {
          Button("Forget saved vendor key", role: .destructive) {
            Task {
              do {
                try app.credentialStore.remove("vendor:" + entry)
                UserDefaults.standard.set(
                  (UserDefaults.standard.stringArray(forKey: "nativeVendorKeys") ?? []).filter {
                    $0 != entry
                  }, forKey: "nativeVendorKeys")
                _ = try await app.engine.call(
                  "connect.vendor.key", ["project": app.projectID, "entry": entry, "key": NSNull()])
                key = ""
              } catch { failure = error.localizedDescription }
            }
          }
        }
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
        Button("Connect and start coding") {
          busy = true
          Task {
            defer { busy = false }
            do {
              let route =
                try await app.engine.call(
                  "connect.vendor.key", ["project": app.projectID, "entry": entry, "key": key])
                as? [String: Any] ?? [:]
              if remember {
                try app.credentialStore.save("vendor:" + entry, key: key)
                var saved = UserDefaults.standard.stringArray(forKey: "nativeVendorKeys") ?? []
                if !saved.contains(entry) { saved.append(entry) }
                UserDefaults.standard.set(saved, forKey: "nativeVendorKeys")
              }
              key = ""
              app.chooseConnection(route)
              dismiss()
            } catch { failure = error.localizedDescription }
          }
        }.buttonStyle(BrandButtonStyle()).disabled(busy || key.isEmpty)
      }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
    }.defaultScrollAnchor(.top)
      .task { key = (try? app.credentialStore.read("vendor:" + entry)) ?? "" }
  }
}

struct SystemOneConnectionView: View {
  @EnvironmentObject var app: Workspace
  let complete: () -> Void
  @State private var key = ""
  @State private var remember = true
  @State private var failure = ""
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        PageTitle(
          eyebrow: "SystemOne · Jev", title: "Connect the decision plane",
          subtitle:
            "Use Jev for typed decisions and tool discovery alongside your coding model. Configure the TypeSafe key here, then choose the coding model for the SystemOne harness."
        )
        SecureField("TypeSafe API key", text: $key).textFieldStyle(.roundedBorder)
        Toggle("Remember in this Mac’s Keychain", isOn: $remember)
        Text("Live decisions contact TypeSafe directly. Saving this key makes no model request.")
          .font(.caption).foregroundStyle(.secondary)
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
        Button("Connect and choose coding model") {
          Task {
            do {
              _ = try await app.engine.call("connect.systemone.key", ["key": key])
              if remember {
                try app.credentialStore.save("systemone", key: key)
                UserDefaults.standard.set(true, forKey: "nativeSystemOneKey")
              }
              key = ""
              complete()
            } catch { failure = error.localizedDescription }
          }
        }.buttonStyle(BrandButtonStyle()).disabled(key.isEmpty)
      }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
    }.defaultScrollAnchor(.top)
      .task { key = (try? app.credentialStore.read("systemone")) ?? "" }
  }
}

struct AgentControlsView: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    DisclosureGroup("Agent settings") {
      VStack(alignment: .leading, spacing: 10) {
        let models = app.agentSession["models"] as? [String: Any] ?? [:]
        let modes = app.agentSession["modes"] as? [String: Any] ?? [:]
        let availableModels = models["availableModels"] as? [[String: Any]] ?? []
        let availableModes = modes["availableModes"] as? [[String: Any]] ?? []
        if !availableModels.isEmpty {
          Picker("Agent model", selection: $app.agentModel) {
            Text("Keep agent selection").tag("")
            ForEach(availableModels, id: \.agentModelID) { row in
              Text(string(row, "name", row.agentModelID)).tag(row.agentModelID)
            }
          }
        }
        if !availableModes.isEmpty {
          Picker("Agent mode", selection: $app.agentMode) {
            Text("Keep agent selection").tag("")
            ForEach(availableModes, id: \.projectRowID) { row in
              Text(string(row, "name", string(row, "id"))).tag(string(row, "id"))
            }
          }
        }
        ForEach(app.agentSession["config_options"] as? [[String: Any]] ?? [], id: \.projectRowID) {
          option in
          if string(option, "type") == "select" {
            Picker(
              string(option, "name", string(option, "id")),
              selection: Binding(
                get: { app.agentConfig[string(option, "id")] ?? "" },
                set: { app.agentConfig[string(option, "id")] = $0 })
            ) {
              Text("Keep agent selection").tag("")
              ForEach(
                (option["options"] as? [[String: Any]] ?? []).flatMap {
                  ($0["options"] as? [[String: Any]]) ?? [$0]
                }, id: \.agentOptionID
              ) { value in
                Text(string(value, "name", string(value, "value"))).tag(string(value, "value"))
              }
            }
          }
        }
        Text(
          "Changes apply to the next message. Continue session keeps the same agent conversation."
        ).font(.caption).foregroundStyle(.secondary)
      }.padding(.top, 10).disabled(app.active)
    }.font(.caption)
  }
}
extension Dictionary where Key == String, Value == Any {
  var agentModelID: String { string(self, "modelId", string(self, "id")) }
  var agentOptionID: String { string(self, "value", string(self, "group", string(self, "name"))) }
}
