import AppKit
import SwiftUI
import XCTest
@testable import SuperQode

@MainActor final class CatalogPopupTests: XCTestCase {
  func testProviderCatalogReusesItemsWhenNavigationChangesEnabledState() throws {
    var selection = "provider-50"
    let options = (0..<150).map { CatalogPopupOption(id: "provider-\($0)", title: "Provider \($0)") }
    let view = CatalogPopup(label: "Provider", options: options,
      selection: Binding(get: { selection }, set: { selection = $0 }), placeholder: "Choose a provider")
    let coordinator = CatalogPopup.Coordinator(view)
    let button = NSPopUpButton(frame: .zero, pullsDown: false)
    coordinator.update(button, parent: view, enabled: true)
    let items = button.itemArray
    for enabled in [false, true, false, true] {
      coordinator.update(button, parent: view, enabled: enabled)
      XCTAssertEqual(button.itemArray.count, items.count)
      XCTAssertTrue(zip(button.itemArray, items).allSatisfy { $0 === $1 })
      XCTAssertEqual(button.selectedItem?.representedObject as? String, "provider-50")
    }
    XCTAssertEqual(button.item(at: 0)?.title, "Choose a provider")
    XCTAssertEqual(selection, "provider-50")
  }

  func testAgentDefaultIsAnExplicitSelectableOption() {
    var selection = "coding-model"
    let view = CatalogPopup(label: "Agent model", options: [
      CatalogPopupOption(id: "", title: "Agent default"),
      CatalogPopupOption(id: "coding-model", title: "Coding model"),
    ], selection: Binding(get: { selection }, set: { selection = $0 }), placeholder: "Choose a model")
    let coordinator = CatalogPopup.Coordinator(view)
    let button = NSPopUpButton(frame: .zero, pullsDown: false)
    coordinator.update(button, parent: view, enabled: true)
    button.selectItem(at: 1)
    coordinator.changed(button)
    XCTAssertEqual(selection, "")
    coordinator.update(button, parent: view, enabled: true)
    XCTAssertEqual(button.indexOfSelectedItem, 1, "The default is a selectable choice, not the disabled placeholder")
  }

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
