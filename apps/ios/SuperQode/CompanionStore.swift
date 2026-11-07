import Foundation
import SwiftUI

enum MacConnectionPhase: Equatable {
  case unpaired, connecting, waitingForApproval, connected, offline, authorizationExpired
}

@MainActor final class CompanionStore: ObservableObject {
  typealias TransportFactory = @Sendable (URL, String?) -> any CompanionTransport
  @Published private(set) var paired = false
  @Published private(set) var restoring = true
  @Published private(set) var connecting = false
  @Published private(set) var phase = MacConnectionPhase.unpaired
  @Published private(set) var projects: [RemoteRecord] = []
  @Published private(set) var profiles: [RemoteRecord] = []
  @Published private(set) var suites: [RemoteRecord] = []
  @Published private(set) var jobs: [RemoteRecord] = []
  @Published private(set) var permissions: Set<String> = []
  @Published private(set) var features: [String: JSONValue] = [:]
  @Published private(set) var deviceExpires: Date?
  @Published private(set) var lastConnected: Date?
  @Published private(set) var isPreview = false
  @Published var message = ""
  @Published var address = ""
  @Published var pairingCode = ""
  @Published var deviceName = "My iPhone"
  @Published var selectedTab = 0
  @Published var activityFilter = "All"
  let drafts: DraftRepository
  private let vault: any DeviceCredentialVault
  private let makeTransport: TransportFactory
  private var credential: DeviceCredential?
  private var pairingTask: Task<Void, Never>?
  private var generation = 0
  private var refreshing = false
  private var missedConnections = 0
  var reachable: Bool { phase == .connected }
  var waitingForApproval: Bool { phase == .waitingForApproval }
  var canMutate: Bool { reachable && !isPreview }
  var macName: String {
    (URLComponents(string: address)?.host?.components(separatedBy: ".").first ?? "Your Mac")
      .replacingOccurrences(of: "-", with: " ").capitalized
  }
  var api: (any CompanionTransport)? {
    if isPreview { return ExploreTransport() }
    guard let credential, let url = try? PrivateMacAddress.parse(credential.address) else { return nil }
    return makeTransport(url, credential.token)
  }

  init(vault: any DeviceCredentialVault = KeychainCredentialVault(), drafts: DraftRepository = DraftRepository(),
    makeTransport: @escaping TransportFactory = { RemoteAPI(address: $0, token: $1) }) {
    self.vault = vault
    self.drafts = drafts
    self.makeTransport = makeTransport
  }

  func restore() async {
    defer { restoring = false }
    guard !isPreview, credential == nil, !connecting else { return }
    let request = generation
    do {
      let restored = try await vault.load()
      guard request == generation, credential == nil, !connecting else { return }
      if let saved = restored {
        _ = try PrivateMacAddress.parse(saved.address)
        credential = saved
        address = saved.address
        paired = true
        phase = .connecting
        await refresh()
      }
    } catch { if request == generation { message = error.localizedDescription } }
  }

  func beginPairing() {
    guard !connecting, !paired else { return }
    connecting = true
    phase = .connecting
    generation += 1
    pairingTask = Task { await pair() }
  }
  func cancelPairing() { pairingTask?.cancel() }
  func acceptInvitation(_ url: URL) {
    do {
      guard !paired, !connecting else { throw CompanionError("Finish the current connection before pairing another Mac.") }
      let invitation = try PrivateMacAddress.invitation(url)
      address = invitation.0.absoluteString
      pairingCode = invitation.1
      message = "Invitation ready. Request approval to connect."
    } catch { message = error.localizedDescription }
  }

  private func pair() async {
    message = ""
    var savedCredential = false
    defer { connecting = false; pairingTask = nil; if !paired { phase = .unpaired } }
    do {
      let url = try PrivateMacAddress.parse(address)
      let client = makeTransport(url, nil)
      let pending = try await client.post("v1/pair", ["code": .string(pairingCode.trimmingCharacters(in: .whitespacesAndNewlines)), "name": .string(deviceName)]).object
      phase = .waitingForApproval
      pairingCode = ""
      let deadline = Date(timeIntervalSince1970: pending.number("expires"))
      while Date() < deadline {
        try Task.checkCancellation()
        let response = try await client.post("v1/pair/claim", ["id": .string(pending.text("id")), "claim": .string(pending.text("claim"))]).object
        if response.text("state") == "denied" { throw CompanionError("Your Mac declined the request. Create another invitation when you are ready.") }
        if response.text("state") == "approved" {
          try Task.checkCancellation()
          guard !response.text("token").isEmpty, !response.text("device").isEmpty else { throw CompanionError("Pairing returned incomplete authorization. Create a new invitation on your Mac.") }
          let saved = DeviceCredential(address: url.absoluteString, token: response.text("token"), device: response.text("device"))
          try await vault.save(saved)
          savedCredential = true
          try Task.checkCancellation()
          credential = saved
          paired = true
          phase = .connecting
          await refresh()
          return
        }
        try await Task.sleep(for: .seconds(2))
      }
      throw CompanionError("The invitation expired. Create a new one in your Mac's Private remote access settings.")
    } catch is CancellationError {
      if savedCredential { try? await vault.remove() }
      message = "Pairing cancelled. Create a new invitation on the Mac to try again."
    } catch { message = error.localizedDescription }
  }

  func refresh() async {
    guard let api, !refreshing else { return }
    refreshing = true
    defer { refreshing = false }
    let request = generation
    do {
      let catalog = try await api.rpc("companion.catalog").object
      guard catalog.number("protocol") == 1 else { throw CompanionError("Update the Mac and iPhone apps together to use this connection.") }
      async let projectPage = api.rpc("projects.list")
      async let jobPage = api.rpc("jobs.list")
      let (projectResult, jobResult) = try await (projectPage, jobPage)
      try Task.checkCancellation()
      guard request == generation, paired else { return }
      let nextProfiles = catalog.records("profiles")
      let nextProjects = projectResult.array.map { RemoteRecord(raw: $0.object) }
      let nextJobs = jobResult.array.map { RemoteRecord(raw: $0.object) }
      if profiles != nextProfiles { profiles = nextProfiles }
      if projects != nextProjects { projects = nextProjects }
      if jobs != nextJobs { jobs = nextJobs }
      let nextSuites = catalog.records("suites")
      if suites != nextSuites { suites = nextSuites }
      permissions = Set((catalog["permissions"]?.array ?? []).map(\.text))
      features = catalog.object("features")
      let expiry = catalog.object("device").number("expires")
      deviceExpires = expiry > 0 ? Date(timeIntervalSince1970: expiry) : nil
      phase = .connected
      lastConnected = Date()
      message = ""
      missedConnections = 0
    } catch is CancellationError { }
    catch { if request == generation { connectionFailed(error) } }
  }

  func refreshActivity() async {
    guard let api else { return }
    let request = generation
    do {
      let next = try await api.rpc("jobs.list").array.map { RemoteRecord(raw: $0.object) }
      try Task.checkCancellation()
      guard request == generation, paired else { return }
      if jobs != next { jobs = next }
      missedConnections = 0
      if phase != .connected { await refresh() }
    } catch is CancellationError { }
    catch { if request == generation { connectionFailed(error) } }
  }

  private func connectionFailed(_ error: Error) {
    let value = error.localizedDescription
    let lower = value.lowercased()
    if (error as? CompanionError)?.status == 403 && (lower.contains("expired") || lower.contains("revoked")) {
      phase = .authorizationExpired
      message = value
      missedConnections = 0
      return
    }
    // The Mac answered with a real error, such as a project that is no longer shared
    // or a missing permission. Show it as it is; the connection itself is fine.
    let transport = (error as? CompanionError)?.transport ?? (error is URLError)
    if !transport {
      missedConnections = 0
      if phase == .connecting { phase = .offline }
      message = value
      return
    }
    // Only transport failures count as a missed connection. One slow request is not
    // a lost pairing, so keep the session and retry.
    missedConnections += 1
    guard missedConnections >= 2 || phase != .connected else { return }
    phase = .offline
    message = "Reconnecting to your Mac…"
  }

  func disconnect() async {
    if isPreview { exitExploreMode(); return }
    generation += 1
    pairingTask?.cancel()
    do {
      try await vault.remove()
      credential = nil
      paired = false
      phase = .unpaired
      profiles = []; projects = []; jobs = []; suites = []; permissions = []
      features = [:]
      deviceExpires = nil
      message = "Disconnected. Revoke this device on the Mac to invalidate its authorization."
    } catch { message = error.localizedDescription }
  }

  func enterExploreMode() {
    guard !paired, !connecting else { return }
    generation += 1
    address = ExploreWorkspace.address
    paired = true
    isPreview = true
    restoring = false
    phase = .connected
    profiles = [ExploreWorkspace.profileRecord]
    projects = [RemoteRecord(raw: ["id": .string(ExploreWorkspace.project), "name": .string("SuperQode Studio")])]
    jobs = ExploreWorkspace.jobs
    suites = ExploreWorkspace.catalog.object.records("suites")
    permissions = Set(ExploreWorkspace.permissions)
    features = ExploreWorkspace.catalog.object.object("features")
    message = ""
  }
  func exitExploreMode() {
    guard isPreview else { return }
    generation += 1
    isPreview = false
    paired = false
    phase = .unpaired
    address = ""; pairingCode = ""; message = ""
    projects = []; profiles = []; jobs = []; suites = []; permissions = []; features = [:]
    selectedTab = 0
  }
}
