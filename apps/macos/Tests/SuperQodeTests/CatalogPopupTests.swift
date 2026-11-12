import AppKit
import SwiftUI
import XCTest
@testable import SuperQode

@MainActor final class CatalogPopupTests: XCTestCase {
  func testCatalogRefreshRetainsSelectionAndUnchangedMenuItems() throws {
    var selection = "core"
    let binding = Binding(get: { selection }, set: { selection = $0 })
    let rows = [CatalogPopupOption(id: "core", title: "Core"), CatalogPopupOption(id: "apple-local", title: "Apple on-device")]
    let view = CatalogPopup(label: "Start from", options: rows, selection: binding)
    let coordinator = CatalogPopup.Coordinator(view)
    let button = NSPopUpButton(frame: .zero, pullsDown: false)
    coordinator.update(button, parent: view, enabled: true)
    let item = try XCTUnwrap(button.item(at: 1))
    coordinator.update(button, parent: view, enabled: true)
    XCTAssertTrue(button.item(at: 1) === item)
    XCTAssertEqual(button.selectedItem?.representedObject as? String, "core")
    button.selectItem(at: 2); coordinator.changed(button)
    XCTAssertEqual(selection, "apple-local")
    coordinator.update(button, parent: view, enabled: false)
    button.selectItem(at: 1); coordinator.changed(button)
    XCTAssertEqual(selection, "apple-local", "Hidden or disabled presets cannot change selection")
  }

  func testMissingSelectionNeverSilentlyChoosesAnotherConfiguration() {
    var selection = "removed-preset"
    let view = CatalogPopup(label: "Start from", options: [CatalogPopupOption(id: "core", title: "Core")],
      selection: Binding(get: { selection }, set: { selection = $0 }))
    let coordinator = CatalogPopup.Coordinator(view)
    let button = NSPopUpButton(frame: .zero, pullsDown: false)
    coordinator.update(button, parent: view, enabled: true)
    XCTAssertEqual(button.indexOfSelectedItem, 0)
    XCTAssertEqual(button.item(at: 0)?.isEnabled, false)
    XCTAssertEqual(selection, "removed-preset")
    coordinator.changed(button)
    XCTAssertEqual(selection, "removed-preset")
  }
}
