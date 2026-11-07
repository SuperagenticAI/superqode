import AppKit
import CoreImage.CIFilterBuiltins
import SwiftUI

struct PrivateRemoteAccessControls: View {
  @State private var showing = false
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Button { showing = true } label: {
        Label("Set up iPhone companion…", systemImage: "iphone.and.arrow.forward")
      }
      Text("Reach this Mac over your private Tailscale connection. No hosted SuperQode service. Devices and projects require your approval.")
        .font(.caption).foregroundStyle(.secondary)
    }
    .sheet(isPresented: $showing) { RemoteAccessSettingsView() }
  }
}

struct RemoteAccessSettingsView: View {
  @EnvironmentObject private var app: Workspace
  @Environment(\.dismiss) private var dismiss
  @State private var status: [String: Any] = [:]
  @State private var network: [String: Any] = [:]
  @State private var invitation: [String: Any] = [:]
  @State private var pairingImage: NSImage?
  @State private var error = ""
  @State private var working = false
  @State private var localOnly = false
  @State private var allowOptimization = false
  @State private var allowReview = false
  @State private var extraPermissions: Set<String> = []
  @State private var profileName = ""
  @State private var reflectionModel = ""
  @State private var optimizerModel = ""
  @State private var selectedProfiles: Set<String> = []
  @State private var profileChoices: [String: [[String: Any]]] = [:]
  private var running: Bool { status["running"] as? Bool == true }
  private var profiles: [[String: Any]] { status["profiles"] as? [[String: Any]] ?? [] }
  private var pairings: [[String: Any]] { status["pairings"] as? [[String: Any]] ?? [] }
  private var devices: [[String: Any]] { status["devices"] as? [[String: Any]] ?? [] }
  private var activeDevices: [[String: Any]] {
    devices.filter { !($0["revoked"] is Double) && ($0["expires"] as? Double ?? 0) > Date().timeIntervalSince1970 }
  }

  var body: some View {
    VStack(spacing: 0) {
      HStack(spacing: 14) {
        Image(systemName: "iphone.gen3.radiowaves.left.and.right")
          .font(.system(size: 30)).foregroundStyle(Color.qAccent)
        VStack(alignment: .leading, spacing: 4) {
          Text("Your Mac. Anywhere.").font(.title2.bold())
          Text("Private remote access").foregroundStyle(.secondary)
        }
        Spacer()
        Button("Done") { dismiss() }.keyboardShortcut(.cancelAction)
      }.padding(24)
      Divider()
      ScrollView {
        VStack(alignment: .leading, spacing: 24) {
          if !error.isEmpty {
            Label(error, systemImage: "exclamationmark.triangle.fill")
              .foregroundStyle(.orange).textSelection(.enabled)
          }
          networkSection
          sharingSection
          activationSection
          pairingSection
          devicesSection
          Text("Tasks, approvals, read-only project review, evaluations and supported staged optimization. Provider setup, raw terminals and candidate adoption stay on the Mac. Other apps require a supported protocol; private app sessions are not automatically controllable.")
            .font(.caption).foregroundStyle(.secondary)
        }.padding(24).disabled(working)
      }
      if working { ProgressView().controlSize(.small).padding(8) }
    }.frame(width: 740, height: 760).background(Color.qPanel)
      .onChange(of: string(invitation, "code")) { _, _ in pairingImage = makeQRImage() }
      .onChange(of: running) { _, value in app.remoteAccessRunning = value }
      .task {
        do { status = try await call("remote.status"); network = try await call("remote.network.check") }
        catch { self.error = error.localizedDescription }
        while !Task.isCancelled {
          do { try await Task.sleep(for: .seconds(3)); status = try await call("remote.status") }
          catch is CancellationError { break }
          catch { self.error = error.localizedDescription; break }
        }
      }
  }

  private var networkSection: some View {
    GroupBox("1. Private connection") {
      VStack(alignment: .leading, spacing: 10) {
        Label(running ? "Remote access is running" : "Remote access is off",
          systemImage: running ? "checkmark.shield.fill" : "shield.lefthalf.filled")
          .foregroundStyle(running ? Color.green : Color.secondary)
        Text("Tailscale connects this Mac to your iPhone. Install it on both, sign in to the same account, then SuperQode can start it here. Public Funnel stays off.")
        if network.isEmpty {
          ProgressView().controlSize(.small)
        } else if network["installed"] as? Bool != true {
          Text("Tailscale is not on this Mac yet. Install it here and on the iPhone, sign in on both, then open this screen again.")
            .font(.caption).foregroundStyle(.secondary)
          HStack {
            Link("Get Tailscale for Mac", destination: URL(string: "https://tailscale.com/download")!)
            Link("Get Tailscale for iPhone", destination: URL(string: "https://apps.apple.com/app/tailscale/id1470499037")!)
          }
        } else if network["ready"] as? Bool == true {
          Label("This Mac is ready for your iPhone", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
        } else {
          Button("Connect this Mac") {
            action {
              network = try await call("remote.network.connect")
              if network["ready"] as? Bool == true, status["running"] as? Bool != true {
                status = try await call("remote.start")
              }
            }
          }
          .buttonStyle(.borderedProminent)
          Text("One click starts Tailscale on this Mac. The iPhone still needs the Tailscale app, signed in to the same account.")
            .font(.caption).foregroundStyle(.secondary)
        }
        if !string(network, "issue").isEmpty, network["ready"] as? Bool != true {
          Text(string(network, "issue")).foregroundStyle(.secondary)
        }
        if !string(network, "private_url").isEmpty { Text(string(network, "private_url")).textSelection(.enabled) }
        if !app.backgroundEngineMode {
          Text("Optional. Keep the iPhone connected after you quit SuperQode. Turning this on reconnects the Mac app.")
            .font(.caption).foregroundStyle(.secondary)
          Button("Keep access after quitting") { action { try await app.changeBackgroundEngine(true) } }
            .disabled(app.anyActive || app.busy)
        }
        Text("Keep the Mac awake, signed in and online. Closing the lid or putting the Mac to sleep can interrupt access. Your phone needs Tailscale enabled when away from home.")
          .font(.caption).foregroundStyle(.secondary)
      }.padding(10)
    }
  }

  private var sharingSection: some View {
    GroupBox("2. Share a project connection") {
      VStack(alignment: .leading, spacing: 10) {
        Text("Share a project once. Changing its harness or model on the Mac updates the phone. A phone can switch only to the harnesses you allow below, and only phones you choose can open the project. Credentials stay on the Mac.").font(.caption).foregroundStyle(.secondary)
        if !app.projectID.isEmpty {
          Text("Current selection: \(string(app.project, "name")) · \(app.harness) · \(app.model.isEmpty ? "Agent-managed model" : app.model)")
          TextField("Connection name", text: $profileName)
          Toggle("Local inference only", isOn: $localOnly)
          Text(localOnly
            ? "Choose Core or No-tool and a model bound in Local AI to a verified loopback engine. Opaque agents cannot guarantee local inference."
            : "This connection may use the agent's own tools, permissions and cloud models. Phone access remains private.")
            .font(.caption).foregroundStyle(.secondary)
          if !localOnly {
            DisclosureGroup("Optional staged optimization models") {
              TextField("Reflection model (provider/model)", text: $reflectionModel)
              TextField("Optimizer model", text: $optimizerModel)
              Text("Explicit model routes are required. Optimization can incur provider charges; adoption remains on the Mac.").font(.caption).foregroundStyle(.secondary)
            }
          }
          Button("Share this project") { action {
            _ = try await call("remote.profiles.save", [
              "project": app.projectID, "name": profileName.isEmpty ? app.harness : profileName,
              "harness": app.harness, "provider": app.provider, "model": app.model,
              "local_only": localOnly, "reflection_model": reflectionModel, "optimizer_model": optimizerModel,
            ])
          } }.disabled(app.harness.isEmpty)
        } else { Text("Open a project and select a connection on the Mac first.").foregroundStyle(.secondary) }
        ForEach(profiles, id: \.remoteID) { profile in
          VStack(alignment: .leading, spacing: 8) {
            HStack {
              Toggle(isOn: Binding(get: { selectedProfiles.contains(string(profile, "id")) }, set: { selected in
                if selected { selectedProfiles.insert(string(profile, "id")) } else { selectedProfiles.remove(string(profile, "id")) }
              })) {
                VStack(alignment: .leading) {
                  Text(string(profile, "name")).fontWeight(.medium)
                  Text("Next pairing invitation").font(.caption).foregroundStyle(.secondary)
                  Text("\(string(profile, "harness")) · \(profile["local_only"] as? Bool == true ? "Local only" : "Agent/provider managed")").font(.caption).foregroundStyle(.secondary)
                }
              }.accessibilityIdentifier("remote.share.invite." + string(profile, "id"))
              Button("Remove", role: .destructive) { action { _ = try await call("remote.profiles.remove", ["id": string(profile, "id")]) } }
            }
            SharedProjectAccess(profile: profile, devices: activeDevices, choices: profileChoices[string(profile, "id")],
              loadChoices: { loadChoices(profile) },
              setAllowed: { allowed in action { _ = try await call("remote.profiles.save", allowListParams(profile, allowed)) } },
              setDevice: { device, allow in action {
                _ = try await call("remote.devices.grant", ["id": device, "profile": string(profile, "id"), "allow": allow])
              } })
          }.padding(10).background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 10))
        }
        if !profiles.isEmpty {
          Text("Show on iPhone adds a project to a phone you already paired. The switch beside the name only adds it to the next pairing invitation.").font(.caption).foregroundStyle(.secondary)
        }
      }.padding(10)
    }
  }

  private var activationSection: some View {
    HStack {
      if running {
        Button("Disable remote access", role: .destructive) { action { _ = try await call("remote.stop"); invitation = [:] } }
        Text("Disabling access keeps already running jobs on the Mac.").font(.caption).foregroundStyle(.secondary)
      } else {
        Button("Enable private remote access") { action { _ = try await call("remote.start") } }
          .buttonStyle(.borderedProminent)
          .disabled(network["ready"] as? Bool != true)
        Text("Connect this Mac above, share a project, then pair the iPhone. The Mac app can stay open.")
          .font(.caption).foregroundStyle(.secondary)
      }
    }
  }

  private var pairingSection: some View {
    GroupBox("3. Pair your iPhone") {
      VStack(alignment: .leading, spacing: 12) {
        Text("Choose the shared projects this phone may open, create a five-minute invitation and scan it in the companion. Approve the phone here. Projects shared later reach a phone only when you turn that phone on for them.")
        Toggle("Allow staged optimization", isOn: $allowOptimization)
        Toggle("Allow staging reviewed files", isOn: $allowReview)
        Text("Staging changes the Git index after a review on the phone. It does not commit or merge code.").font(.caption).foregroundStyle(.secondary)
        ForEach([("edit", "Allow file editing and creation"), ("queue", "Allow queue management"), ("restore", "Allow checkpoint restoration")], id: \.0) { permission, title in
          Toggle(title, isOn: Binding(get: { extraPermissions.contains(permission) }, set: { enabled in
            if enabled { extraPermissions.insert(permission) } else { extraPermissions.remove(permission) }
          }))
        }
        Text("Editing and restoration change project files. Queue controls can start work through shared connections. These permissions are off by default.").font(.caption).foregroundStyle(.secondary)
        Button("Create pairing invitation") { action {
          var permissions = ["read", "tasks", "evaluate", "approve", "cancel", "steer"]
          if allowOptimization { permissions.append("optimize") }
          if allowReview { permissions.append("review") }
          permissions.append(contentsOf: extraPermissions.sorted())
          invitation = try await call("remote.pairing.create", ["profiles": Array(selectedProfiles), "permissions": permissions])
        } }.disabled(!running || selectedProfiles.isEmpty)
        if running && selectedProfiles.isEmpty {
          Text("Share a project above and turn it on for this invitation first.").font(.caption).foregroundStyle(.secondary)
        }
        if let expires = invitation["expires"] as? Double, Date(timeIntervalSince1970: expires) > Date() {
          HStack(alignment: .top, spacing: 18) {
            if let image = pairingImage { Image(nsImage: image).interpolation(.none).resizable().frame(width: 150, height: 150).padding(8).background(.white, in: RoundedRectangle(cornerRadius: 12)) }
            VStack(alignment: .leading, spacing: 8) {
              Text("Scan with the SuperQode companion").font(.headline)
              Text(string(invitation, "private_url")).textSelection(.enabled)
              Text("Manual pairing code").font(.caption).foregroundStyle(.secondary)
              Text(string(invitation, "code")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
              Text("Expires \(Date(timeIntervalSince1970: expires).formatted(date: .omitted, time: .shortened))").font(.caption)
            }
          }
        }
        ForEach(pairings, id: \.remoteID) { pending in
          VStack(alignment: .leading, spacing: 8) {
            Label(string(pending, "name"), systemImage: "iphone").font(.headline)
            Text("Tailscale identity: \(string(pending, "principal"))").font(.caption).textSelection(.enabled)
            Text("\((pending["profiles"] as? [String] ?? []).count) shared connections · \((pending["permissions"] as? [String] ?? []).joined(separator: ", "))").font(.caption).foregroundStyle(.secondary)
            HStack {
              Button("Approve this phone") { action { _ = try await call("remote.pairing.approve", ["id": string(pending, "id")]); invitation = [:] } }
                .buttonStyle(.borderedProminent)
              Button("Deny", role: .destructive) { action { _ = try await call("remote.pairing.deny", ["id": string(pending, "id")]) } }
            }
          }.padding(12).background(Color.qAccent.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
        }
      }.padding(10)
    }
  }

  private var devicesSection: some View {
    GroupBox("Paired devices") {
      VStack(alignment: .leading, spacing: 12) {
        if devices.isEmpty { Text("No devices paired yet.").foregroundStyle(.secondary) }
        ForEach(devices, id: \.remoteID) { device in
          HStack {
            Image(systemName: "iphone").foregroundStyle(Color.qAccent)
            VStack(alignment: .leading) {
              Text(string(device, "name"))
              Text(device["revoked"] is Double ? "Revoked" : "Expires \(Date(timeIntervalSince1970: device["expires"] as? Double ?? 0).formatted(date: .abbreviated, time: .omitted))").font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Revoke", role: .destructive) { action { _ = try await call("remote.devices.revoke", ["id": string(device, "id")]) } }
              .disabled(device["revoked"] is Double)
          }
        }
      }.padding(10).frame(maxWidth: .infinity, alignment: .leading)
    }
  }

  private func loadChoices(_ profile: [String: Any]) {
    let id = string(profile, "id")
    Task { @MainActor in
      do {
        let result = try await call("remote.profiles.choices", ["project": string(profile, "project")])
        profileChoices[id] = result["choices"] as? [[String: Any]] ?? []
      } catch { self.error = error.localizedDescription }
    }
  }
  private func allowListParams(_ profile: [String: Any], _ allowed: [String]) -> [String: Any] {
    [
      "project": string(profile, "project"), "name": string(profile, "name"),
      "harness": string(profile, "harness"), "provider": string(profile, "provider"), "model": string(profile, "model"),
      "local_only": profile["local_only"] as? Bool ?? true,
      "reflection_model": string(profile, "reflection_model"), "optimizer_model": string(profile, "optimizer_model"),
      "allowed_harnesses": allowed,
    ]
  }
  private func call(_ method: String, _ params: [String: Any] = [:]) async throws -> [String: Any] {
    try await app.engine.call(method, params) as? [String: Any] ?? [:]
  }
  private func action(_ operation: @escaping @MainActor () async throws -> Void) {
    working = true
    error = ""
    Task { @MainActor in
      defer { working = false }
      do { try await operation(); status = try await call("remote.status") }
      catch { self.error = error.localizedDescription }
    }
  }
  private func makeQRImage() -> NSImage? {
    guard let payload = pairingURL?.data(using: .utf8) else { return nil }
    let filter = CIFilter.qrCodeGenerator()
    filter.message = payload
    guard let image = filter.outputImage,
      let cgImage = CIContext().createCGImage(image, from: image.extent) else { return nil }
    return NSImage(cgImage: cgImage, size: NSSize(width: 150, height: 150))
  }
  private var pairingURL: String? {
    guard !string(invitation, "code").isEmpty else { return nil }
    var url = URLComponents()
    url.scheme = "superqode-companion"
    url.host = "pair"
    url.queryItems = [URLQueryItem(name: "server", value: string(invitation, "private_url"))]
    url.fragment = string(invitation, "code")
    return url.string
  }
}

/// Which phones may open one shared project, and which harnesses they may switch to.
private struct SharedProjectAccess: View {
  let profile: [String: Any]
  let devices: [[String: Any]]
  let choices: [[String: Any]]?
  let loadChoices: () -> Void
  let setAllowed: ([String]) -> Void
  let setDevice: (String, Bool) -> Void
  private var profileID: String { profile["id"] as? String ?? "" }
  private var currentHarness: String { profile["harness"] as? String ?? "" }
  private var allowed: [String] {
    if profile["allowed_mode"] as? String == "all" {
      let listed = (choices ?? []).compactMap { $0["id"] as? String }
      if !listed.isEmpty { return listed }
    }
    let list = profile["allowed_harnesses"] as? [String] ?? []
    return list.isEmpty ? [currentHarness] : list
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      if devices.isEmpty {
        Text("Pair an iPhone first. Sharing a project does not add it to a phone by itself.").font(.caption).foregroundStyle(.secondary)
      } else {
        ForEach(devices, id: \.remoteID) { device in
          let id = device["id"] as? String ?? ""
          let granted = (device["profiles"] as? [String] ?? []).contains(profileID)
          let phone = device["name"] as? String ?? "iPhone"
          Toggle("Show on \(phone)", isOn: Binding(get: { granted }, set: { setDevice(id, $0) }))
            .font(.caption)
            .accessibilityIdentifier("remote.share.device." + id)
        }
      }
      DisclosureGroup("Harnesses the phone may switch to") {
        Text("The phone lists the same harnesses as Connect on this Mac, including ones that still need setup. Turn one off to hide it. SuperQode harnesses use a model already connected on the Mac.")
          .font(.caption).foregroundStyle(.secondary)
        if choices == nil { ProgressView().controlSize(.small).onAppear(perform: loadChoices) }
        else if choices?.isEmpty == true { Text("Connect has no harnesses to list yet.").font(.caption).foregroundStyle(.secondary) }
        ForEach(choices ?? [], id: \.remoteID) { choice in
          let id = choice["id"] as? String ?? ""
          Toggle(choice["name"] as? String ?? id, isOn: Binding(get: { allowed.contains(id) }, set: { on in
            var next = allowed.filter { $0 != id }
            if on { next.append(id) }
            setAllowed(next)
          })).disabled(id == currentHarness)
            .accessibilityIdentifier("remote.share.harness." + id)
        }
      }.font(.caption)
    }
  }
}

private extension Dictionary where Key == String, Value == Any {
  var remoteID: String { self["id"] as? String ?? "" }
}
