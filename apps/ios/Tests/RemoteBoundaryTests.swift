import Foundation
import XCTest
@testable import SuperQodeCompanion

final class RemoteBoundaryTests: XCTestCase {
  func testOnlyPrivateHTTPSMacOriginsAreAccepted() throws {
    XCTAssertEqual(try PrivateMacAddress.parse("https://home.tailnet-example.ts.net/").absoluteString,
      "https://home.tailnet-example.ts.net")
    XCTAssertEqual(try PrivateMacAddress.parse("https://home.tailnet-example.ts.net:47832").absoluteString,
      "https://home.tailnet-example.ts.net:47832")
    for value in ["http://home.tailnet-example.ts.net", "https://public.example", "https://127.0.0.1",
      "https://name.ts.net", "https://user:secret@home.tailnet-example.ts.net", "https://home.tailnet-example.ts.net/path",
      "https://home.tailnet-example.ts.net?token=secret", "https://home.tailnet-example.ts.net:8443",
      "https://home.tailnet-example.ts.net.attacker.example"] {
      XCTAssertThrowsError(try PrivateMacAddress.parse(value), value)
    }
  }
  func testInvitationPreservesOriginAndEphemeralCode() throws {
    let url = try XCTUnwrap(URL(string: "superqode-companion://pair?server=https%3A%2F%2Fhome.tailnet-example.ts.net#temporary-code"))
    let invitation = try PrivateMacAddress.invitation(url)
    XCTAssertEqual(invitation.0.absoluteString, "https://home.tailnet-example.ts.net")
    XCTAssertEqual(invitation.1, "temporary-code")
    XCTAssertThrowsError(try PrivateMacAddress.invitation(URL(string: "https://public.example/#code")!))
  }
  func testEventJSONPreservesBooleansNumbersNullAndNestedArguments() throws {
    let raw = Data(#"{"allow":false,"sequence":42,"tool":{"arguments":{"command":"git status"}},"result":null}"#.utf8)
    let value = try JSONDecoder().decode(JSONValue.self, from: raw)
    XCTAssertEqual(value.object["allow"], .bool(false))
    XCTAssertEqual(value.object.number("sequence"), 42)
    XCTAssertEqual(value.object.object("tool").object("arguments").text("command"), "git status")
    XCTAssertEqual(try JSONDecoder().decode(JSONValue.self, from: JSONEncoder().encode(value)), value)
  }
  func testRunIdentityAndActiveStatusRemainStable() {
    let event = RemoteRecord(raw: ["sequence": .number(8)])
    XCTAssertEqual(event.id, "8")
    XCTAssertTrue(RemoteRecord(raw: ["id": .string("job"), "status": .string("needs_approval")]).active)
    XCTAssertFalse(RemoteRecord(raw: ["id": .string("job"), "status": .string("interrupted")]).active)
  }
}
