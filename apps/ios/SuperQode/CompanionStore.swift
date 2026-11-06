import Foundation
import SwiftUI

@MainActor final class CompanionStore: ObservableObject {
  @Published private(set) var paired = false
  @Published private(set) var connecting = false
  @Published private(set) var waitingForApproval = false
  @Published private(set) var reachable = false
  @Published private(set) var projects: [RemoteRecord] = []
  @Published private(set) var profiles: [RemoteRecord] = []
  @Published private(set) var suites: [RemoteRecord] = []
  @Published private(set) var jobs: [RemoteRecord] = []
  @Published private(set) var permissions: Set<String> = []
  @Published var message = ""
  @Published var address = ""
  @Published var pairingCode = ""
  @Published var deviceName = "My iPhone"
  private var credential: DeviceCredential?
  private var pairingTask: Task<Void, Never>?
  var api: RemoteAPI? {
    guard let credential, let address = try? PrivateMacAddress.parse(credential.address) else { return nil }
    return RemoteAPI(address: address, token: credential.token)
  }

  func restore() async {
    guard credential == nil, !connecting else { return }
    do {
      let restored = try await Task.detached { try DeviceKeychain.load() }.value
      if let saved = restored {
        _ = try PrivateMacAddress.parse(saved.address)
        credential = saved
        address = saved.address
        paired = true
        await refresh()
      }
    } catch { message = error.localizedDescription }
  }

  func beginPairing() {
    guard !connecting else { return }
    pairingTask = Task { await pair() }
  }
  func cancelPairing() {
    pairingTask?.cancel()
  }
  func acceptInvitation(_ url: URL) {
    do {
      guard !paired else { throw CompanionError("Disconnect from the current Mac before pairing another one.") }
      let invitation = try PrivateMacAddress.invitation(url)
      address = invitation.0.absoluteString
      pairingCode = invitation.1
      message = "Invitation loaded. Connect to request approval on your Mac."
    } catch { message = error.localizedDescription }
  }

  private func pair() async {
    connecting = true
    message = ""
    defer { connecting = false; waitingForApproval = false; pairingTask = nil }
    do {
      let url = try PrivateMacAddress.parse(address)
      let client = RemoteAPI(address: url, token: nil)
      let pending = try await client.post("v1/pair", ["code": .string(pairingCode.trimmingCharacters(in: .whitespacesAndNewlines)), "name": .string(deviceName)]).object
      waitingForApproval = true
      pairingCode = ""
      let deadline = Date(timeIntervalSince1970: pending.number("expires"))
      while Date() < deadline {
        try Task.checkCancellation()
        let response = try await client.post("v1/pair/claim", ["id": .string(pending.text("id")), "claim": .string(pending.text("claim"))]).object
        if response.text("state") == "denied" { throw CompanionError("The Mac declined this request. Create another invitation when you are ready.") }
        if response.text("state") == "approved" {
          try Task.checkCancellation()
          guard !response.text("token").isEmpty, !response.text("device").isEmpty else { throw CompanionError("Pairing did not return device authorization. Create a new invitation on the Mac.") }
          let saved = DeviceCredential(address: url.absoluteString, token: response.text("token"), device: response.text("device"))
          try await Task.detached { try DeviceKeychain.save(saved) }.value
          credential = saved
          paired = true
          await refresh()
          return
        }
        try await Task.sleep(for: .seconds(2))
      }
      throw CompanionError("Pairing expired. Create a new invitation in Mac Settings → Private remote access.")
    } catch is CancellationError { }
    catch { message = error.localizedDescription }
  }

  func refresh() async {
    guard let api else { return }
    do {
      let catalog = try await api.rpc("companion.catalog").object
      guard catalog.number("protocol") == 1 else { throw CompanionError("This Mac uses another companion protocol. Update the Mac and iPhone apps together.") }
      let nextProjects = try await api.rpc("projects.list").array.map { RemoteRecord(raw: $0.object) }
      let nextJobs = try await api.rpc("jobs.list").array.map { RemoteRecord(raw: $0.object) }
      let nextProfiles = catalog.records("profiles")
      if profiles != nextProfiles { profiles = nextProfiles }
      if projects != nextProjects { projects = nextProjects }
      if jobs != nextJobs { jobs = nextJobs }
      suites = catalog.records("suites")
      permissions = Set((catalog["permissions"]?.array ?? []).map(\.text))
      reachable = true
      message = ""
    } catch is CancellationError { }
    catch { reachable = false; message = error.localizedDescription }
  }

  func refreshActivity() async {
    guard let api else { return }
    do {
      let next = try await api.rpc("jobs.list").array.map { RemoteRecord(raw: $0.object) }
      if jobs != next { jobs = next }
      reachable = true
    } catch is CancellationError { }
    catch { reachable = false; message = error.localizedDescription }
  }

  func disconnect() async {
    do {
      try await Task.detached { try DeviceKeychain.remove() }.value
      credential = nil
      paired = false
      reachable = false
      profiles = []; projects = []; jobs = []; suites = []; permissions = []
      message = "Disconnected on this iPhone. Revoke the device in Mac Settings to invalidate its authorization."
    } catch { message = error.localizedDescription }
  }
}
