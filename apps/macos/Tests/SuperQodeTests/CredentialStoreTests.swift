import XCTest

@testable import SuperQode

final class CredentialStoreTests: XCTestCase {
  func testMissingKeyReadsAsEmptyWithoutAPrompt() throws {
    let store = CredentialStore()
    let missing = "missing-" + UUID().uuidString
    XCTAssertNil(try store.read(missing, prompt: false))
    XCTAssertNil(try store.read(missing))
  }
}
