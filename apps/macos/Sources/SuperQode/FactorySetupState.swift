import Foundation

/// Progress is derived from matching evidence, never from the page a user visited.
struct FactorySetupState {
  let hasDraft: Bool
  let validated: Bool
  let saved: Bool
  let committed: Bool
  let trialPrepared: Bool
  init(text: String, review: [String: Any], savedDigest: String,
    sources: [String: Any], runs: [[String: Any]]) {
    hasDraft = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    validated = hasDraft && string(review, "yaml") == text && !string(review, "review").isEmpty
    saved = validated && !savedDigest.isEmpty && string(review, "digest") == savedDigest
    let snapshot = string(review, "snapshot_digest")
    let files = sources["files"] as? [[String: Any]] ?? []
    committed = saved && !snapshot.isEmpty && string(sources, "snapshot_digest") == snapshot
      && !files.isEmpty && files.allSatisfy { $0["changed"] as? Bool == false }
    trialPrepared = saved && !snapshot.isEmpty && runs.contains { string($0, "factory_digest") == snapshot }
  }
  var step: Int { !hasDraft ? 0 : !validated || !saved ? 1 : !committed ? 2 : 3 }
  var action: String {
    !hasDraft ? "Load a starter" : !validated ? "Validate draft" : !saved ? "Review & save"
      : !committed ? "Review source changes" : trialPrepared ? "Open trials" : "Prepare a trial"
  }
}
