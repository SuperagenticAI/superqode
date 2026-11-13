import Foundation
import Observation

// In-memory drafts outlive hidden views; credentials are never serialized here.

@MainActor @Observable final class LocalQuickStartDraft {
  var hardware: [String: Any] = [:]
  var engines: [[String: Any]] = []
  var warnings: [String] = []
  var operationJob: String = ""
  var operationStatus: String = ""
  var choices: [[String: Any]] = []
  var presets: [[String: Any]] = []
  var selection: String = ""
  var step: [String: Any] = [:]
  var failure: String = ""
  var progress: [String: Any] = [:]
  var output: String = ""
  var command: String = UUID().uuidString
  var showSetup: Bool = false
  let runtime = LocalRuntimeDraft()
  let installed = InstalledLocalDraft()
}

@MainActor @Observable final class InstalledLocalDraft {
  var models: [[String: Any]] = []
  var engines: [[String: Any]] = []
  var harnesses: [[String: Any]] = []
  var harness: String = ""
  var selected: String = ""
  var inferenceEngine: String = ""
  var failure: String = ""
  var step = "model"
  var preparedModel: (engine: String, model: String)?
  var refreshToken = 0
  var prompt: String = ""
  /// Start tab data: quick start catalog (hardware, engines, capacity, starter, fit) and Apple status.
  var catalog: [String: Any] = [:]
  var apple: [String: Any] = [:]
  var appleSelected = false
  var preselected = false
}

/// The last local setup that connected, so returning users can continue in one tap.
/// Only identifiers are stored here, never credentials.
enum LocalAISetupMemory {
  static let key = "localAI.lastSetup"
  static func load() -> [String: String] {
    UserDefaults.standard.dictionary(forKey: key) as? [String: String] ?? [:]
  }
  static func save(engine: String, model: String, name: String, harness: String) {
    guard !engine.isEmpty else { return }
    UserDefaults.standard.set(
      ["engine": engine, "model": model, "name": name, "harness": harness], forKey: key)
  }
}

@MainActor @Observable final class LocalRuntimeDraft {
  var template: String = "vllm-metal"
  var identity: String = UUID().uuidString.lowercased()
  var name: String = "vLLM Metal"
  var endpoint: String = "http://127.0.0.1:8000/v1"
  var context: Int = 8192
  var capability: String = "unknown"
  var apiKey: String = ""
  var rememberKey: Bool = false
  var includeUsage: Bool = true
  var models: [[String: Any]] = []
  var model: String = ""
  var coding: Bool = false
  var harness: String = "core"
  /// Survives a recreated view so an in-flight save cannot switch profiles.
  var saving: Bool = false
}
