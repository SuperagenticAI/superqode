import XCTest

@testable import SuperQode

final class ACPActivityTests: XCTestCase {
  private func event(_ session: String, _ kind: String, _ fields: [String: Any]) -> [String: Any] {
    let update = fields.merging(["sessionUpdate": kind]) { _, new in new }
    return ["type": "harness_event", "data": ["event": "acp_update", "payload": ["sessionId": session, "update": update]]]
  }

  func testMessageReplacementsKeepChildIsolationAndWireOrder() {
    let snapshot = ACPActivitySnapshot([
      event("root", "subagent_update", ["sessionId": "child", "state": ["state": "running"], "capabilities": ["cancel": [:]]]),
      event("root", "agent_message", ["messageId": "same", "content": [["type": "text", "text": "root"]]]),
      event("child", "agent_message", ["messageId": "z", "content": [["type": "text", "text": "old"]]]),
      event("child", "agent_message_chunk", ["messageId": "a", "content": ["type": "text", "text": "second"]]),
      event("child", "agent_message", ["messageId": "z", "content": NSNull()]),
      event("child", "agent_message_chunk", ["messageId": "z", "content": ["type": "text", "text": "replacement"]]),
      event("root", "subagent_update", ["sessionId": "child", "capabilities": NSNull(), "state": NSNull()])
    ])
    XCTAssertEqual(snapshot.messages["root:same"], "root")
    XCTAssertEqual(snapshot.messages["child:z"], "replacement")
    XCTAssertEqual(snapshot.messageOrder, ["root:same", "child:z", "child:a"])
    XCTAssertNil(snapshot.children["child"]?["capabilities"])
    XCTAssertEqual(snapshot.states["child"]?["state"] as? String, "unknown")
  }

  func testTerminalChunksRetainBytesAcrossUTF8BoundariesAndSnapshotsReplace() {
    let prefix = Data([0xE2, 0x82])
    let suffix = Data([0xAC])
    var events = [
      event("s", "terminal_update", ["terminalId": "t", "output": ["data": prefix.base64EncodedString()]]),
      event("s", "terminal_output_chunk", ["terminalId": "t", "data": suffix.base64EncodedString()]),
      event("s", "terminal_update", ["terminalId": "t", "capabilities": ["cancel": [:]]])
    ]
    XCTAssertEqual(ACPActivitySnapshot(events).terminals["s:t"]?["displayOutput"] as? String, "€")
    events.append(event("s", "terminal_update", ["terminalId": "t", "output": ["data": Data("new".utf8).base64EncodedString()]]))
    XCTAssertEqual(ACPActivitySnapshot(events).terminals["s:t"]?["displayOutput"] as? String, "new")
  }
}
