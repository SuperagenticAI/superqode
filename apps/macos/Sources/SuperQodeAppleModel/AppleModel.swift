import Foundation
#if canImport(FoundationModels)
import FoundationModels
#endif

/// Private stdio bridge. No HTTP listener, subscription or cloud fallback.
@main struct AppleModelBridge {
  static func emit(_ value: [String: Any]) {
    guard let data = try? JSONSerialization.data(withJSONObject: value, options: [.sortedKeys]) else { return }
    FileHandle.standardOutput.write(data)
    FileHandle.standardOutput.write(Data([10]))
  }

  static let guide = "https://support.apple.com/en-us/121115"
  static func unavailable(_ state: String, _ message: String) -> [String: Any] {
    ["available": false, "state": state, "guidance": message, "docs_url": guide,
     "model": "system-on-device", "supports_tools": true, "supports_structured_output": true, "supports_images": false, "on_device": true, "protocol": 2]
  }

  static func status() -> [String: Any] {
    #if canImport(FoundationModels)
    if #available(macOS 26.0, *) {
      let model = SystemLanguageModel.default
      #if compiler(>=6.3)
      let context = model.contextSize
      #else
      let context = 4096 // Conservative cap for SDKs predating contextSize.
      #endif
      switch model.availability {
      case .available:
        return ["available": true, "state": "ready", "guidance": "Apple's on-device model is ready for chat, summaries and lightweight tasks.",
                "model": "system-on-device", "supports_tools": true, "on_device": true,
                "context": context, "docs_url": guide, "supports_structured_output": true, "supports_images": false, "protocol": 2, "runtime_version": ProcessInfo.processInfo.operatingSystemVersionString,
                "current_locale_supported": model.supportsLocale()]
      case .unavailable(let reason):
        switch reason {
        case .deviceNotEligible:
          return unavailable("device-ineligible", "This Mac is not eligible for Apple Intelligence. Use Ollama, MLX or llama.cpp instead.")
        case .appleIntelligenceNotEnabled:
          return unavailable("intelligence-disabled", "Enable Apple Intelligence in System Settings, then check again. No API key is needed.")
        case .modelNotReady:
          return unavailable("model-not-ready", "Apple's system model is not ready. Keep your Mac connected to power while Apple Intelligence finishes setup, then check again.")
        @unknown default:
          return unavailable("unavailable", "Apple's on-device model is unavailable. Review Apple Intelligence settings and supported languages, then check again.")
        }
      @unknown default:
        return unavailable("unavailable", "Apple's on-device model is unavailable on this Mac.")
      }
    }
    #endif
    return unavailable("unsupported-system", "Apple on-device support needs macOS 26 or later and an app build containing the Foundation Models SDK. Other local runtimes remain available.")
  }

  static func main() async {
    if CommandLine.arguments.contains("--status") { emit(status()); return }
    guard CommandLine.arguments.contains("--stdio") else {
      emit(["event": "error", "code": "invalid-mode", "message": "Use --status or the app's private --stdio protocol."]); return
    }
    // One exclusively checked-out request at a time. EOF or parent termination
    // destroys every in-memory transcript; there is no listener or disk cache.
    while let line = readLine() {
      let availability = status()
      guard availability["available"] as? Bool == true else {
        emit(["event": "error", "code": availability["state"] ?? "unavailable", "message": availability["guidance"] ?? "Apple model unavailable"])
        continue
      }
      #if canImport(FoundationModels)
      if #available(macOS 26.0, *) {
        await AppleConversation.respond(line, emit: emit)
      }
      #endif
    }
  }
}
