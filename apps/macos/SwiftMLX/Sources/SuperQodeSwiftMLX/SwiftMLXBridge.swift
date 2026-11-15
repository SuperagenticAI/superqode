import Foundation
import MLXHuggingFace
import MLXLLM
import MLXLMCommon
import Tokenizers

enum RequestError: String, Error {
  case invalidRequest = "invalid-request"
  case contextFull = "context-full"
  case rejectedTool = "rejected-tool"
  case interrupted = "generation-interrupted"
}

@main final class SwiftMLXBridge {
  private var snapshot: URL?
  private var container: ModelContainer?

  static func emit(_ event: [String: Any]) throws {
    let bytes = try JSONSerialization.data(withJSONObject: event) + Data([10])
    try FileHandle.standardOutput.write(contentsOf: bytes)
  }

  static func main() async throws {
    guard Array(CommandLine.arguments.dropFirst()) == ["--stdio"] else {
      try emit(["event": "error", "code": "invalid-mode", "message": "Use the private stdio model bridge."])
      return
    }
    let bridge = SwiftMLXBridge()
    while let line = readLine() {
      do {
        try await bridge.respond(line)
      } catch let error as RequestError {
        try emit(["event": "error", "code": error.rawValue, "message": error.rawValue])
      } catch {
        try emit(["event": "error", "code": "generation-failed", "message": String(describing: error).prefix(512).description])
      }
    }
  }

  private static func sendable(_ value: Any) throws -> any Sendable {
    switch value {
    case let object as [String: Any]: return try object.mapValues(sendable)
    case let array as [Any]: return try array.map(sendable)
    case let text as String: return text
    case let number as NSNumber: return number
    case is NSNull: return NSNull()
    default: throw RequestError.invalidRequest
    }
  }

  private func respond(_ line: String) async throws {
    guard line.utf8.count <= 524288,
      let request = try JSONSerialization.jsonObject(with: Data(line.utf8)) as? [String: Any],
      let path = request["snapshot"] as? String, path.hasPrefix("/"),
      let messages = request["messages"] as? [[String: Any]], !messages.isEmpty,
      let context = request["context"] as? Int, (512...32768).contains(context),
      let limit = request["max_tokens"] as? Int, (1...4096).contains(limit)
    else { throw RequestError.invalidRequest }

    let directory = URL(fileURLWithPath: path, isDirectory: true)
    if container == nil || snapshot != directory {
      container = nil
      snapshot = nil
      container = try await LLMModelFactory.shared.loadContainer(
        from: directory, using: #huggingFaceTokenizerLoader())
      snapshot = directory
    }
    guard let container else { throw RequestError.invalidRequest }
    let tools = try (request["tools"] as? [[String: Any]] ?? []).map { try $0.mapValues(Self.sendable) }
    let input = try await container.prepare(input: UserInput(
      messages: try messages.map { try $0.mapValues(Self.sendable) },
      tools: tools.isEmpty ? nil : tools, additionalContext: ["enable_thinking": false]))
    let promptTokens = input.text.tokens.size
    guard promptTokens + limit <= context else { throw RequestError.contextFull }
    try Self.emit(["event": "metadata", "prompt_tokens": promptTokens])
    let stream = try await container.generate(
      input: input,
      parameters: GenerateParameters(maxTokens: limit, temperature: (request["temperature"] as? NSNumber)?.floatValue ?? 0),
      tools: tools.isEmpty ? nil : tools)
    var calls: [[String: Any]] = []
    var completion: GenerateCompletionInfo?
    for await event in stream {
      switch event {
      case .chunk(let text):
        if !text.isEmpty { try Self.emit(["event": "text", "text": text]) }
      case .toolCall(let call):
        let arguments = try JSONEncoder().encode(call.function.arguments)
        calls.append([
          "id": UUID().uuidString, "type": "function",
          "function": ["name": call.function.name, "arguments": String(decoding: arguments, as: UTF8.self)],
        ])
      case .rejectedToolCall: throw RequestError.rejectedTool
      case .info(let info): completion = info
      }
    }
    guard let completion, completion.stopReason != .cancelled else {
      throw RequestError.interrupted
    }
    let reason = calls.isEmpty ? (completion.stopReason == .length ? "length" : "stop") : "tool_calls"
    try Self.emit(["event": "done", "finish_reason": reason, "calls": calls,
      "prompt_tokens": completion.promptTokenCount, "completion_tokens": completion.generationTokenCount])
  }
}
