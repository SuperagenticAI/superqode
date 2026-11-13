import AppKit
import SwiftUI
import XCTest
@testable import SuperQode

@MainActor final class LocalRuntimeEndpointFieldTests: XCTestCase {
  func testNativeURLDraftSurvivesHiddenUpdatesAndRestoresBinding() {
    var draft = "http://127.0.0.1:8000/v1"
    let view = LocalRuntimeEndpointField(value: Binding(get: { draft }, set: { draft = $0 }))
    let coordinator = LocalRuntimeEndpointField.Coordinator(view)
    let field = NSTextField()
    coordinator.update(field, parent: view, enabled: true)
    field.stringValue = "http://127.0.0.1:49321/v1"
    coordinator.controlTextDidChange(Notification(name: NSControl.textDidChangeNotification, object: field))
    XCTAssertEqual(draft, "http://127.0.0.1:49321/v1")
    coordinator.update(field, parent: view, enabled: false)
    XCTAssertFalse(field.isEnabled)
    XCTAssertEqual(field.stringValue, draft)
    coordinator.update(field, parent: view, enabled: true)
    XCTAssertEqual(field.stringValue, "http://127.0.0.1:49321/v1")
    draft = "http://127.0.0.1:8080/v1"
    coordinator.update(field, parent: view, enabled: true)
    XCTAssertEqual(field.stringValue, draft)
  }

  func testDisabledEndpointCannotChangeItsDraft() {
    var draft = "http://127.0.0.1:8000/v1"
    let view = LocalRuntimeEndpointField(value: Binding(get: { draft }, set: { draft = $0 }))
    let coordinator = LocalRuntimeEndpointField.Coordinator(view)
    let field = NSTextField()
    coordinator.update(field, parent: view, enabled: false)
    field.stringValue = "http://127.0.0.1:49321/v1"
    coordinator.controlTextDidChange(Notification(name: NSControl.textDidChangeNotification, object: field))
    XCTAssertEqual(draft, "http://127.0.0.1:8000/v1")
  }
}
