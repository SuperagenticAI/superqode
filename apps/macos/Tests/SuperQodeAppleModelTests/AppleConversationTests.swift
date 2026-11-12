import XCTest
@testable import SuperQodeAppleModel
#if canImport(FoundationModels)
import FoundationModels

final class AppleConversationTests: XCTestCase {
  func testStreamingDeltasPreserveUnicodeScalarsAcrossGraphemeChanges() throws {
    let snapshots = ["👩", "👩\u{200D}", "👩\u{200D}💻", "👩\u{200D}💻 葛", "👩\u{200D}💻 葛\u{E0100}", "👩\u{200D}💻 葛\u{E0100} e", "👩\u{200D}💻 葛\u{E0100} e\u{301}"]
    var previous = ""
    var delivered = ""
    for snapshot in snapshots {
      delivered += try AppleRequestContract.delta(previous: previous, current: snapshot)
      XCTAssertEqual(Array(delivered.unicodeScalars), Array(snapshot.unicodeScalars))
      previous = snapshot
    }
    XCTAssertThrowsError(try AppleRequestContract.delta(previous: "earlier", current: "revised"))
  }

  func testTemperatureIsFiniteAndBoundedForTheNativeSDK() throws {
    XCTAssertNil(try AppleRequestContract.temperature(nil))
    XCTAssertNil(try AppleRequestContract.temperature(NSNull()))
    XCTAssertEqual(try AppleRequestContract.temperature(-1.0), 0)
    XCTAssertEqual(try AppleRequestContract.temperature(2.0), 1)
    XCTAssertEqual(try AppleRequestContract.temperature(0.6), 0.6)
    for invalid in [true, "warm", Double.nan, Double.infinity] as [Any] {
      XCTAssertThrowsError(try AppleRequestContract.temperature(invalid))
    }
    XCTAssertEqual(AppleRequestContract.finishReason(outputTokens: 128, limit: 128), "length")
    XCTAssertEqual(AppleRequestContract.finishReason(outputTokens: 32, limit: 128), "stop")
  }

  func testLegacySDKErrorsAndEmptyResponsesHaveSpecificGuidance() throws {
    guard #available(macOS 26.0, *) else { throw XCTSkip("Foundation Models needs macOS 26") }
    let context = LanguageModelSession.GenerationError.Context(debugDescription: "private prompt")
    let cases: [(Error, String)] = [
      (LanguageModelSession.GenerationError.assetsUnavailable(context), "model-not-ready"),
      (LanguageModelSession.GenerationError.exceededContextWindowSize(context), "context-full"),
      (LanguageModelSession.GenerationError.guardrailViolation(context), "refused"),
      (LanguageModelSession.GenerationError.rateLimited(context), "busy"),
      (BridgeInput.emptyResponse, "empty-response"),
      (BridgeInput.revisedSnapshot, "stream-revised"),
    ]
    for (error, expected) in cases {
      let result = AppleConversation.error(error)
      XCTAssertEqual(result.0, expected)
      XCTAssertFalse(result.1.contains("private prompt"))
    }
    #if compiler(>=6.4)
    if #available(macOS 27.0, *) {
      XCTAssertEqual(AppleConversation.error(LanguageModelSession.Error.concurrentRequests).0, "busy")
    }
    #endif
  }

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
