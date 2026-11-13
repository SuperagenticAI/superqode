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
  var step: String = "harness"
  var prompt: String = ""
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
