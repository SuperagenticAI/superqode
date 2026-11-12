import Foundation
#if canImport(FoundationModels)
import FoundationModels

@available(macOS 26.0, *)
enum AppleSchema {
  static func dynamic(_ value: [String: Any], name: String = "Result") throws -> DynamicGenerationSchema {
    switch value["type"] as? String {
    case "object":
      let properties = value["properties"] as? [String: [String: Any]] ?? [:]
      let required = Set(value["required"] as? [String] ?? [])
      let fields = try properties.keys.sorted().map { key in
        DynamicGenerationSchema.Property(
          name: key, description: properties[key]?["description"] as? String,
          schema: try dynamic(properties[key]!, name: name + "_" + key),
          isOptional: !required.contains(key))
      }
      return DynamicGenerationSchema(name: name, description: value["description"] as? String, properties: fields)
    case "array":
      guard let items = value["items"] as? [String: Any] else { throw BridgeInput.invalid }
      return DynamicGenerationSchema(arrayOf: try dynamic(items, name: name + "Item"),
        minimumElements: value["minItems"] as? Int, maximumElements: value["maxItems"] as? Int)
    case "string":
      if let choices = value["enum"] as? [String], !choices.isEmpty {
        return DynamicGenerationSchema(type: String.self, guides: [.anyOf(choices)])
      }
      return DynamicGenerationSchema(type: String.self)
    case "integer": return DynamicGenerationSchema(type: Int.self)
    case "number": return DynamicGenerationSchema(type: Double.self)
    case "boolean": return DynamicGenerationSchema(type: Bool.self)
    default: throw BridgeInput.invalid
    }
  }

  static func make(_ value: [String: Any], name: String = "Result") throws -> GenerationSchema {
    try GenerationSchema(root: dynamic(value, name: name), dependencies: [])
  }
}

enum BridgeInput: Error { case invalid, contextFull }
struct HostToolHandoff: Error {}

/// Only records requests. It never opens files, executes commands or calls the
/// network. Throwing exits native orchestration before any host-side effect.
final class HostToolRequests: @unchecked Sendable {
  private let lock = NSLock()
  private var values: [[String: Any]] = []

  func add(name: String, arguments: String) {
    lock.lock(); defer { lock.unlock() }
    guard values.count < 5 else { return }
    values.append(["id": UUID().uuidString, "type": "function",
      "function": ["name": name, "arguments": arguments]])
  }

  var calls: [[String: Any]] {
    lock.lock(); defer { lock.unlock() }
    return values
  }
}

@available(macOS 26.0, *)
struct HostTool: Tool {
  typealias Arguments = GeneratedContent
  typealias Output = String
  let name: String
  let description: String
  let parameters: GenerationSchema
  let requests: HostToolRequests

  func call(arguments: GeneratedContent) async throws -> String {
    try Task.checkCancellation()
    requests.add(name: name, arguments: arguments.jsonString)
    throw HostToolHandoff()
  }
}

@available(macOS 26.0, *)
enum AppleTranscript {
  static func text(_ value: String) -> [Transcript.Segment] {
    [.text(Transcript.TextSegment(content: value))]
  }

  static func build(_ messages: [[String: Any]], tools: [HostTool]) throws -> (Transcript, String) {
    var entries: [Transcript.Entry] = []
    let instructions = messages.filter { ["system", "developer"].contains($0["role"] as? String ?? "") }
      .compactMap { $0["content"] as? String }.joined(separator: "\n\n")
    entries.append(.instructions(Transcript.Instructions(segments: text(instructions),
      toolDefinitions: tools.map { Transcript.ToolDefinition(tool: $0) })))
    var prompt = "Continue using the tool results."
    var callNames: [String: String] = [:]
    for (index, message) in messages.enumerated() {
      let content = message["content"] as? String ?? ""
      switch message["role"] as? String {
      case "system", "developer": break
      case "user":
        if index == messages.count - 1 { prompt = content }
        else { entries.append(.prompt(Transcript.Prompt(segments: text(content)))) }
      case "assistant":
        if !content.isEmpty {
          entries.append(.response(Transcript.Response(assetIDs: [], segments: text(content))))
        }
        if let calls = message["tool_calls"] as? [[String: Any]], !calls.isEmpty {
          let native = try calls.map { call -> Transcript.ToolCall in
            guard let id = call["id"] as? String,
              let function = call["function"] as? [String: Any],
              let name = function["name"] as? String else { throw BridgeInput.invalid }
            let arguments: String
            if let encoded = function["arguments"] as? String { arguments = encoded }
            else {
              let data = try JSONSerialization.data(withJSONObject: function["arguments"] ?? [:], options: [.sortedKeys])
              arguments = String(decoding: data, as: UTF8.self)
            }
            callNames[id] = name
            return Transcript.ToolCall(id: id, toolName: name, arguments: try GeneratedContent(json: arguments))
          }
          entries.append(.toolCalls(Transcript.ToolCalls(native)))
        }
      case "tool":
        guard let id = message["tool_call_id"] as? String, let name = callNames.removeValue(forKey: id) else {
          throw BridgeInput.invalid
        }
        entries.append(.toolOutput(Transcript.ToolOutput(id: id, toolName: name, segments: text(content))))
      default: throw BridgeInput.invalid
      }
    }
    guard callNames.isEmpty else { throw BridgeInput.invalid }
    return (Transcript(entries: entries), prompt)
  }
}

@available(macOS 26.0, *)
struct AppleCachedSession {
  let id: String
  let messages: Data
  let session: LanguageModelSession
}

@available(macOS 26.0, *)
enum AppleConversation {
  static var cached: AppleCachedSession?

  static func error(_ error: Error) -> (String, String) {
    if let input = error as? BridgeInput, case .contextFull = input {
      return ("context-full", "Apple's conversation context is full. Start a new thread or shorten the prompt and tool output. Nothing was silently removed or sent to another model.")
    }
    if error is BridgeInput { return ("invalid-request", "Apple could not read this text, tool or schema request. Use the Apple on-device configuration or a supported simple schema.") }
    if let native = error as? LanguageModelSession.GenerationError {
      switch native {
      case .exceededContextWindowSize:
        return ("context-full", "Apple's conversation context is full. Start a new thread or shorten the prompt and tool output. Nothing was retried or sent to another model.")
      case .assetsUnavailable:
        return ("model-not-ready", "Apple's model is not ready. Check Apple Intelligence in System Settings and let the system model finish downloading.")
      case .guardrailViolation, .refusal:
        return ("refused", "Apple's on-device model declined this request. Rephrase it or explicitly choose another model. Nothing was sent to the cloud.")
      case .unsupportedLanguageOrLocale:
        return ("unsupported-language", "Apple's model does not support this language or locale. Check Apple's supported languages or choose another local model.")
      case .rateLimited:
        return ("busy", "Apple's model is busy. Wait for the current request to finish, then try again.")
      case .decodingFailure, .unsupportedGuide:
        return ("structured-output-failed", "Apple could not produce this structured output. Simplify the schema or try another model; no tool was executed.")
      default: break
      }
    }
    return ("generation-failed", "Apple could not complete this request. Check availability, shorten the conversation or choose another local model. Nothing was replayed or sent to the cloud.")
  }

  static func respond(_ line: String, emit: ([String: Any]) -> Void) async {
    let requests = HostToolRequests()
    do {
      guard line.utf8.count <= 524288, let data = line.data(using: .utf8),
        let request = try JSONSerialization.jsonObject(with: data) as? [String: Any],
        let messages = request["messages"] as? [[String: Any]], !messages.isEmpty else { throw BridgeInput.invalid }
      let definitions = request["tools"] as? [[String: Any]] ?? []
      guard definitions.count <= 5 else { throw BridgeInput.invalid }
      let tools = try definitions.map { definition -> HostTool in
        guard let name = definition["name"] as? String,
          let parameters = definition["parameters"] as? [String: Any] else { throw BridgeInput.invalid }
        return HostTool(name: name, description: definition["description"] as? String ?? "",
          parameters: try AppleSchema.make(parameters, name: name + "Arguments"), requests: requests)
      }
      let schema = request["schema"] as? [String: Any]
      guard schema == nil || tools.isEmpty else { throw BridgeInput.invalid }
      let id = request["session_id"] as? String ?? ""
      let prefix = try JSONSerialization.data(withJSONObject: Array(messages.dropLast()), options: [.sortedKeys])
      let reuse = tools.isEmpty && schema == nil && !id.isEmpty && messages.last?["role"] as? String == "user"
        && cached?.id == id && cached?.messages == prefix
      let session: LanguageModelSession
      let prompt: String
      if reuse, let previous = cached {
        session = previous.session; prompt = messages.last?["content"] as? String ?? ""
      } else {
        let (transcript, last) = try AppleTranscript.build(messages, tools: tools)
        session = LanguageModelSession(model: .default, tools: tools, transcript: transcript)
        prompt = last
        session.prewarm()
      }
      // Never retain a failed or interrupted native session.
      cached = nil
      let limit = min(2048, max(1, request["max_tokens"] as? Int ?? 512))
      let options = GenerationOptions(sampling: nil, temperature: request["temperature"] as? Double, maximumResponseTokens: limit)
      var metadata: [String: Any] = ["event": "metadata", "protocol": 2, "session_reused": reuse, "on_device": true]
      #if compiler(>=6.3)
      if #available(macOS 26.4, *) {
        let current = Transcript.Entry.prompt(Transcript.Prompt(segments: AppleTranscript.text(prompt), options: options))
        let model = SystemLanguageModel.default
        var count = try await model.tokenCount(for: Array(session.transcript) + [current])
        if let schema { count += try await model.tokenCount(for: AppleSchema.make(schema)) }
        guard count + limit + 128 <= min(4096, model.contextSize) else { throw BridgeInput.contextFull }
        metadata["sdk_prompt_tokens"] = count
      }
      #endif
      emit(metadata)
      var previous = ""
      if let schema {
        let response = try await session.respond(to: Prompt { prompt }, schema: AppleSchema.make(schema), options: options)
        previous = response.content.jsonString
        emit(["event": "text", "text": previous])
      } else {
        for try await snapshot in session.streamResponse(to: Prompt { prompt }, options: options) {
          try Task.checkCancellation()
          let text = snapshot.content
          guard text.hasPrefix(previous) else { throw BridgeInput.invalid }
          let delta = String(text.dropFirst(previous.count))
          if !delta.isEmpty { emit(["event": "text", "text": delta]) }
          previous = text
        }
      }
      guard !previous.isEmpty else { throw BridgeInput.invalid }
      if tools.isEmpty && schema == nil && !id.isEmpty {
        let history = messages + [["role": "assistant", "content": previous]]
        cached = AppleCachedSession(id: id,
          messages: try JSONSerialization.data(withJSONObject: history, options: [.sortedKeys]), session: session)
      }
      emit(["event": "done", "finish_reason": "stop"])
    } catch {
      cached = nil
      if !requests.calls.isEmpty {
        emit(["event": "tool_calls", "calls": requests.calls])
        emit(["event": "done", "finish_reason": "tool_calls"])
      } else {
        let (code, message) = self.error(error)
        emit(["event": "error", "code": code, "message": message])
      }
    }
  }
}
#endif
