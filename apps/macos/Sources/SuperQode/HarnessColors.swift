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
    return HarnessIdentity(harnesses.first { string($0, "id") == harness } ?? ["id": harness])
  }
}
