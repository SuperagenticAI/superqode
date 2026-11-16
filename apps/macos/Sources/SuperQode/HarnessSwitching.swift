import Foundation

/// Harness rows and switching rules shared by the composer, the harness chooser and Local AI.
@MainActor extension Workspace {
  func harnessRow(_ id: String) -> [String: Any]? {
    harnesses.first { string($0, "id") == id }
  }

  /// Harnesses that run with Apple's on-device model: the built-in Apple and Silicon
  /// harnesses and any harness whose profile is silicon, such as one that inherits silicon.
  func harnessIsAppleCompatible(_ id: String) -> Bool {
    if id == "silicon" || id == "apple-local" { return true }
    guard let row = harnessRow(id), string(row, "desktop_kind").isEmpty else { return false }
    return row["apple_compatible"] as? Bool == true
  }

  /// Harness files in this repository: harness.yaml at the root and .superqode/harnesses/.
  var projectHarnesses: [[String: Any]] {
    harnesses.filter { string($0, "source") == "project" && string($0, "desktop_kind").isEmpty }
  }

  /// Project harnesses that can run with Apple's on-device model.
  var appleProjectHarnesses: [[String: Any]] {
    projectHarnesses.filter { $0["apple_compatible"] as? Bool == true && $0["available"] as? Bool != false }
  }

  /// The Silicon Harness unless the id names an Apple-compatible project harness.
  func appleHarnessChoice(_ id: String) -> String {
    appleProjectHarnesses.contains { string($0, "id") == id } ? id : "silicon"
  }

  /// Whether a native harness can take over the current connection without a new model.
  func harnessFitsCurrentRoute(_ id: String) -> Bool {
    // SystemOne has its own decision setup, so it always goes through the Connect steps.
    guard !connectionDisconnected, !isManaged, id != "systemone", !harness.hasPrefix("local-harness:"),
      !id.hasPrefix("local-harness:"), let row = harnessRow(id),
      string(row, "desktop_kind").isEmpty, row["available"] as? Bool != false else { return false }
    if provider == "apple-foundation" { return harnessIsAppleCompatible(id) }
    if model.isEmpty || harnessIsAppleCompatible(id) { return false }
    // A local model binds its endpoint per harness, so Local AI setup handles that change.
    let localEngines: Set<String> = ["ollama", "lmstudio", "mlx", "llama.cpp", "llamacpp", "swift-mlx", "exo"]
    if localEngines.contains(provider)
      || providers.first(where: { string($0, "id") == provider })?["local"] as? Bool == true { return false }
    if let allowed = row["byok_providers"] as? [String], !allowed.contains(provider) { return false }
    return true
  }

  /// Switch the harness for the next message in this conversation and keep the model.
  func switchHarnessKeepingModel(_ id: String) {
    let keptProvider = provider
    let keptModel = model
    chooseHarness(id, restoreRemembered: false)
    provider = keptProvider
    model = keptModel
    if provider == "apple-foundation" && interactionMode == "chat" { interactionMode = "code" }
    savePreferences()
    notice = "Switched to " + string(harnessRow(id) ?? [:], "name", id) + ". It applies from your next message."
  }
}
