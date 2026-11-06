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
  @State private var localOnly = true
  @State private var allowOptimization = false
  @State private var profileName = ""
  @State private var reflectionModel = ""
  @State private var optimizerModel = ""
  @State private var selectedProfiles: Set<String> = []
  private var running: Bool { status["running"] as? Bool == true }
  private var profiles: [[String: Any]] { status["profiles"] as? [[String: Any]] ?? [] }
  private var pairings: [[String: Any]] { status["pairings"] as? [[String: Any]] ?? [] }
  private var devices: [[String: Any]] { status["devices"] as? [[String: Any]] ?? [] }

  var body: some View {
    VStack(spacing: 0) {
      HStack(spacing: 14) {
        Image(systemName: "iphone.gen3.radiowaves.left.and.right")
          .font(.system(size: 30)).foregroundStyle(Color.qAccent)
        VStack(alignment: .leading, spacing: 4) {
          Text("Your Mac. Anywhere.").font(.title2.bold())
          Text("Private remote access · iPhone companion preview").foregroundStyle(.secondary)
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
          Text("Companion preview: tasks, approvals, read-only project review, evaluations and supported staged optimization. Provider setup, raw terminals and candidate adoption stay on the Mac. Other apps require a supported protocol; private app sessions are not automatically controllable.")
            .font(.caption).foregroundStyle(.secondary)
        }.padding(24).disabled(working)
      }
      if working { ProgressView().controlSize(.small).padding(8) }
    }.frame(width: 740, height: 760).background(Color.qPanel)
      .onChange(of: string(invitation, "code")) { _, _ in pairingImage = makeQRImage() }
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
        Text("Install Tailscale on your Mac and iPhone and connect both to your private network. Use Serve; public Funnel is refused.")
        HStack {
          Link("Get Tailscale", destination: URL(string: "https://tailscale.com/download")!)
          Link("Private Serve setup", destination: URL(string: "https://tailscale.com/docs/features/tailscale-serve")!)
          Spacer()
          Button("Verify connection") { action { network = try await call("remote.network.check") } }
        }
        if network["installed"] as? Bool == true, network["ready"] as? Bool != true {
          Button("Configure private Serve") { action { network = try await call("remote.network.setup") } }
          Text("Creates the private proxy after you click. Existing Tailscale services are preserved; setup needing vendor approval falls back to the command below.")
            .font(.caption).foregroundStyle(.secondary)
        }
        if !string(network, "issue").isEmpty { Text(string(network, "issue")).foregroundStyle(.secondary) }
        if !string(network, "command").isEmpty {
          HStack {
            Text(string(network, "command")).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
            Spacer()
            Button("Copy command") {
              NSPasteboard.general.clearContents()
              NSPasteboard.general.setString(string(network, "command"), forType: .string)
            }
          }
        }
        if !string(network, "private_url").isEmpty { Text(string(network, "private_url")).textSelection(.enabled) }
        if !app.backgroundEngineMode {
          Text("Enable the background engine to keep phone access available when the Mac app quits.").font(.caption).foregroundStyle(.secondary)
          Button("Enable background engine") { action { try await app.changeBackgroundEngine(true) } }
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
        Text("Only connections you explicitly share are available to paired phones. Configure providers, models and credentials on the Mac.").font(.caption).foregroundStyle(.secondary)
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
          Button("Share current connection") { action {
            _ = try await call("remote.profiles.save", [
              "project": app.projectID, "name": profileName.isEmpty ? app.harness : profileName,
              "harness": app.harness, "provider": app.provider, "model": app.model,
              "local_only": localOnly, "reflection_model": reflectionModel, "optimizer_model": optimizerModel,
            ])
          } }.disabled(app.harness.isEmpty)
        } else { Text("Open a project and select a connection on the Mac first.").foregroundStyle(.secondary) }
        ForEach(profiles, id: \.remoteID) { profile in
          HStack {
            Toggle(isOn: Binding(get: { selectedProfiles.contains(string(profile, "id")) }, set: { selected in
              if selected { selectedProfiles.insert(string(profile, "id")) } else { selectedProfiles.remove(string(profile, "id")) }
            })) {
              VStack(alignment: .leading) {
                Text(string(profile, "name")).fontWeight(.medium)
                Text("\(string(profile, "harness")) · \(profile["local_only"] as? Bool == true ? "Local only" : "Agent/provider managed")").font(.caption).foregroundStyle(.secondary)
              }
            }
            Button("Remove", role: .destructive) { action { _ = try await call("remote.profiles.remove", ["id": string(profile, "id")]) } }
          }
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
          .disabled(network["ready"] as? Bool != true || profiles.isEmpty || !app.backgroundEngineMode)
      }
    }
  }

  private var pairingSection: some View {
    GroupBox("3. Pair your iPhone") {
      VStack(alignment: .leading, spacing: 12) {
        Text("Select shared connections above, create a five-minute invitation, then scan it in the companion. Approve the phone's request here.")
        Toggle("Allow staged optimization", isOn: $allowOptimization)
        Button("Create pairing invitation") { action {
          var permissions = ["read", "tasks", "evaluate", "approve", "cancel", "steer"]
          if allowOptimization { permissions.append("optimize") }
          invitation = try await call("remote.pairing.create", ["profiles": Array(selectedProfiles), "permissions": permissions])
        } }.disabled(!running || selectedProfiles.isEmpty)
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

private extension Dictionary where Key == String, Value == Any {
  var remoteID: String { self["id"] as? String ?? "" }
}
