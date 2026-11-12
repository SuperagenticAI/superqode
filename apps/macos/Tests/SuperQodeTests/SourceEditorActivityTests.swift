import AppKit
import SwiftUI
import XCTest
@testable import SuperQode

@MainActor final class SourceEditorActivityTests: XCTestCase {
  func testHiddenEditorCancelsPendingColoursWithoutReplacingItsBuffer() throws {
    let source = "print('preserve the draft')"
    let view = SourceEditor(text: .constant(source), path: "sample.py", editable: true)
    let coordinator = SourceEditor.Coordinator(view)
    let editor = SourceEditor.Editor(frame: .zero)
    editor.string = source
    coordinator.schedule(editor)
    let pending = try XCTUnwrap(coordinator.styling)
    editor.interactionEnabled = false
    coordinator.schedule(editor)
    XCTAssertTrue(pending.isCancelled)
    XCTAssertNil(coordinator.styling)
    XCTAssertNil(coordinator.lastSource)
    XCTAssertEqual(editor.string, source)
  }
}
