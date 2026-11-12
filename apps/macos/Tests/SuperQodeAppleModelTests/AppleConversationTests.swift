import XCTest
@testable import SuperQodeAppleModel
#if canImport(FoundationModels)
import FoundationModels

final class AppleConversationTests: XCTestCase {
  func testNativeSchemasAndTranscriptsWithoutLoadingTheModel() throws {
    guard #available(macOS 26.0, *) else { throw XCTSkip("Foundation Models needs macOS 26") }
    let schema: [String: Any] = ["type": "object", "properties": [
      "name": ["type": "string", "enum": ["read", "write"]],
      "count": ["type": "integer"], "ok": ["type": "boolean"],
      "items": ["type": "array", "items": ["type": "number"]]], "required": ["name"]]
    _ = try AppleSchema.make(schema)
    let messages: [[String: Any]] = [
      ["role": "system", "content": "Stay local"],
      ["role": "user", "content": "Read a file"],
      ["role": "assistant", "content": "", "tool_calls": [["id": "call-1", "function": ["name": "read", "arguments": "{\"path\":\"a.py\"}"]]]],
      ["role": "tool", "tool_call_id": "call-1", "content": "print(1)"],
      ["role": "user", "content": "Explain it"]]
    let (transcript, prompt) = try AppleTranscript.build(messages, tools: [])
    XCTAssertEqual(prompt, "Explain it")
    XCTAssertEqual(transcript.count, 4)
    XCTAssertThrowsError(try AppleTranscript.build([["role": "tool", "tool_call_id": "unknown", "content": "x"]], tools: []))
  }

  func testNativeToolOnlyHandsOffArgumentsAndPerformsNoEffects() async throws {
    guard #available(macOS 26.0, *) else { throw XCTSkip("Foundation Models needs macOS 26") }
    let requests = HostToolRequests()
    let schema = try AppleSchema.make(["type": "object", "properties": ["path": ["type": "string"]], "required": ["path"]])
    let tool = HostTool(name: "read", description: "Read", parameters: schema, requests: requests)
    do {
      _ = try await tool.call(arguments: GeneratedContent(json: "{\"path\":\"nonexistent-file\"}"))
      XCTFail("Native tools must hand off to SuperQode before execution")
    } catch is HostToolHandoff { }
    let calls = requests.calls
    XCTAssertEqual(calls.count, 1)
    let function = try XCTUnwrap(calls.first?["function"] as? [String: String])
    XCTAssertEqual(function["name"], "read")
    let arguments = try XCTUnwrap(function["arguments"]?.data(using: .utf8))
    XCTAssertEqual((try JSONSerialization.jsonObject(with: arguments) as? [String: String])?["path"], "nonexistent-file")
  }

  func testActionableErrorsDoNotExposeRawPrompts() throws {
    guard #available(macOS 26.0, *) else { throw XCTSkip("Foundation Models needs macOS 26") }
    let (code, message) = AppleConversation.error(BridgeInput.invalid)
    XCTAssertEqual(code, "invalid-request")
    XCTAssertTrue(message.contains("schema"))
    XCTAssertEqual(AppleConversation.error(BridgeInput.contextFull).0, "context-full")
  }
}
#endif
