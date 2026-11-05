import XCTest
@testable import SuperQode

final class ResponseRenderingTests: XCTestCase {
  func testPreparedDocumentRetainsRichContent() async throws {
    let text = "# Heading\n\nHello **world**\n\n- Item\n\n> Quote\n\n| A | B |\n| --- | --- |\n| one | two |\n\n```swift\nlet x = 1\n```\n\n---"
    let result = await prepareResponseDocument(text)
    let document = try XCTUnwrap(result)
    XCTAssertEqual(document.source, text)
    XCTAssertEqual(document.blocks.count, 7)
    guard case .heading(1, let heading) = document.blocks[0],
      case .paragraph(let paragraph) = document.blocks[1],
      case .item("•", let item) = document.blocks[2],
      case .quote(let quote) = document.blocks[3],
      case .table(let rows) = document.blocks[4],
      case .code("swift", "let x = 1") = document.blocks[5],
      case .rule = document.blocks[6] else { return XCTFail("Rich response content was lost") }
    XCTAssertEqual(String(heading.characters), "Heading")
    XCTAssertEqual(String(paragraph.characters), "Hello world")
    XCTAssertEqual(String(item.characters), "Item")
    XCTAssertEqual(String(quote.characters), "Quote")
    XCTAssertEqual(rows.map { $0.map { String($0.characters) } }, [["A", "B"], ["one", "two"]])
  }

  func testStreamingSuffixNeverLeaksReplacedConversation() {
    let document = PreparedResponseDocument(source: "你好 👩🏽‍💻", blocks: [])
    XCTAssertEqual(document.remainingText(in: "你好 👩🏽‍💻\nMore tokens"), "\nMore tokens")
    XCTAssertEqual(document.remainingText(in: document.source), "")
    XCTAssertNil(document.remainingText(in: "Another conversation"))
    XCTAssertNil(document.remainingText(in: "你好"))
    let composed = PreparedResponseDocument(source: "é", blocks: [])
    XCTAssertNil(composed.remainingText(in: "e\u{301} different encoding"))
    // A token can extend the last grapheme. Falling back to the full new text
    // is preferable to slicing at an invalid String index.
    let extended = PreparedResponseDocument(source: "e", blocks: [])
    _ = extended.remainingText(in: "e\u{301} suffix")
  }

  func testCancelledPreparationDoesNotPublishLargeStaleResponse() async {
    let text = String(repeating: "**Large response** with `code`.\n\n", count: 20_000)
    let preparation = Task { await prepareResponseDocument(text) }
    preparation.cancel()
    let result = await preparation.value
    XCTAssertNil(result)
  }

  @MainActor func testMainActorCanProgressDuringLargeResponsePreparation() async throws {
    let text = String(repeating: "## Result\n\nHello **world** with `code`.\n\n", count: 10_000)
    let start = Date()
    let preparation = Task { await prepareResponseDocument(text) }
    // This heartbeat is scheduled after the formatting request on the UI actor.
    // Formatting on that actor would delay it until the whole document finished.
    await Task.yield()
    let heartbeat = Date().timeIntervalSince(start)
    let document = await preparation.value
    let total = Date().timeIntervalSince(start)
    XCTAssertEqual(document?.blocks.count, 20_000)
    XCTAssertLessThan(heartbeat, 0.25, "Response formatting stalled the UI actor")
    print("Response preparation: \(text.utf8.count) bytes, UI heartbeat \(heartbeat * 1000) ms, formatted \(total * 1000) ms")
  }

  func testCodeHighlightPreservesExactSourceAndContrast() async throws {
    let code = "let greeting = \"你好 👩🏽‍💻\"\n// comment"
    for highContrast in [false, true] {
      let value = await prepareHighlightedSource(SourceHighlightKey(code: code, language: "swift", highContrast: highContrast))
      XCTAssertEqual(value.map { String($0.characters) }, code)
    }
  }
}
