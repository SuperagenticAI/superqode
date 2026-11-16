import SwiftUI

extension HarnessIdentity {
  static func current(in row: [String: Any]) -> HarnessIdentity? {
    let identities = used(in: row)
    return identities.first { $0.id == string(row, "harness") } ?? identities.last
  }
}

@MainActor extension Workspace {
  /// A blank thread has no badge until the user explicitly selects a connection.
  var composerHarnessIdentity: HarnessIdentity? {
    guard !connectionDisconnected, !harness.isEmpty else { return nil }
    var row = harnesses.first { string($0, "id") == harness } ?? ["id": harness]
    if provider == "apple-foundation" || harness == "apple-local" {
      row["provider"] = "apple-foundation"
      row["name"] = "Apple on-device"
      row["icon_key"] = "apple-device"
    }
    return HarnessIdentity(row)
  }
  /// Agent and model shown for the next message, in the composer and on a new thread.
  var connectionDisplayName: String {
    if connectionDisconnected { return "Not connected" }
    if provider == "apple-foundation" {
      if interactionMode == "chat" { return "Apple on-device · chat" }
      // Name the active harness when it is not the default Apple development harness.
      if harness.isEmpty || harness == "apple-local" { return "Apple on-device · development" }
      return "Apple on-device · " + string(harnessRow(harness) ?? [:], "name", harness)
    }
    let route = harnesses.first { string($0, "id") == harness } ?? [:]
    let name = string(route, "name", harness)
    if model.isEmpty { return isManaged ? name : name + " · Choose model" }
    return name + " · " + model
  }
  /// Connection pickers are unavailable while the engine is offline or a run is in flight.
  var connectionPickerDisabled: Bool { !connected || active || busy }
}
