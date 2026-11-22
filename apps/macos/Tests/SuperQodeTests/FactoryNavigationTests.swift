import AppKit
import XCTest
@testable import SuperQode

final class FactoryNavigationTests: XCTestCase {
  @MainActor func testFiveSidebarSectionsKeepAllToolsDiscoverableWithoutDuplicatingPages() {
    XCTAssertEqual(FactoryNavigation.groups.map(\.id), ["build", "run", "improve", "export", "manage"])
    let destinations = FactoryNavigation.groups.flatMap(\.destinations)
    XCTAssertEqual(Set(destinations), Set(FactoryNavigation.tabs.map(\.id)))
    XCTAssertEqual(Set(destinations).count, destinations.count)
    XCTAssertTrue(FactoryNavigation.buildPages.contains("Configuration"))
    XCTAssertTrue(FactoryNavigation.buildPages.contains("Acceptance"))
    XCTAssertTrue(destinations.contains("ImproveEvidence")); XCTAssertTrue(destinations.contains("Export"))
  }
  @MainActor func testAreaSwitchReturnsToItsLastPageWithinTheSameProject() {
    let navigation = FactoryNavigation(); navigation.enter("first"); navigation.setActive(true)
    navigation.select("Operations"); navigation.selectGroup("build"); navigation.select("Workflow")
    navigation.selectGroup("manage"); XCTAssertEqual(navigation.selection, "Operations")
    navigation.selectGroup("build"); XCTAssertEqual(navigation.selection, "Workflow")
    navigation.enter("second"); navigation.setActive(true); navigation.selectGroup("manage")
    XCTAssertEqual(navigation.selection, "Sources")
    navigation.selectGroup("unknown"); XCTAssertEqual(navigation.selection, "Sources")
  }
  @MainActor func testCompletedActionCannotOverrideALaterTabChoice() {
    let navigation = FactoryNavigation(); navigation.enter("project"); navigation.setActive(true)
    navigation.select("Workflow"); let export = navigation.ticket()
    navigation.select("Operations")
    XCTAssertFalse(navigation.follow(export, to: "Suites"))
    XCTAssertEqual(navigation.selection, "Operations")
    XCTAssertEqual(navigation.mounted, ["Stack", "Workflow", "Operations"])
  }
  @MainActor func testLeavingAndReturningInvalidatesOldActionEvenOnSameTab() {
    let navigation = FactoryNavigation(); navigation.enter("project"); navigation.setActive(true)
    navigation.select("Improve"); let action = navigation.ticket()
    navigation.select("Operations"); navigation.select("Improve")
    XCTAssertFalse(navigation.follow(action, to: "Definition"))
    let next = navigation.ticket()
    navigation.setActive(false); navigation.setActive(true)
    XCTAssertFalse(navigation.follow(next, to: "Definition"))
  }
  @MainActor func testNavigationIsProjectScopedAndSameTabClickDoesNotInvalidate() {
    let navigation = FactoryNavigation(); navigation.enter("first"); navigation.setActive(true)
    navigation.select("Operations"); let action = navigation.ticket()
    navigation.select("Operations")
    XCTAssertTrue(navigation.isCurrent(action))
    navigation.enter("second"); navigation.setActive(true)
    XCTAssertFalse(navigation.follow(action, to: "Runs"))
    navigation.select("Improve")
    navigation.enter("first"); navigation.setActive(true)
    XCTAssertEqual(navigation.selection, "Operations")
    XCTAssertFalse(navigation.isCurrent(action))
  }
  @MainActor func testSuccessfulCurrentActionCanOfferItsNextPage() {
    let navigation = FactoryNavigation(); navigation.enter("project"); navigation.setActive(true)
    let ticket = navigation.ticket()
    XCTAssertTrue(navigation.follow(ticket, to: "Runs"))
    XCTAssertEqual(navigation.selection, "Runs")
    XCTAssertFalse(navigation.follow(ticket, to: "Definition"))
  }

  @MainActor func testDeferredComposerFocusCannotLandInHiddenOrDisabledPane() async {
    _ = NSApplication.shared
    let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 300),
      styleMask: [.titled], backing: .buffered, defer: false)
    defer { window.orderOut(nil) }
    let container = NSView(frame: window.contentView!.bounds)
    let editor = PromptEditor.Editor(frame: container.bounds)
    container.addSubview(editor); window.contentView = container
    window.makeFirstResponder(nil)
    editor.requestKeyboardFocus()
    container.isHidden = true
    await drainMainQueue()
    XCTAssertFalse(window.firstResponder === editor)
    container.isHidden = false
    editor.requestKeyboardFocus()
    editor.interactionEnabled = false; editor.isEditable = false
    await drainMainQueue()
    XCTAssertFalse(window.firstResponder === editor)
  }
  @MainActor func testBlurCancelsPendingComposerFocus() async {
    _ = NSApplication.shared
    let window = NSWindow(contentRect: NSRect(x: 0, y: 0, width: 400, height: 300),
      styleMask: [.titled], backing: .buffered, defer: false)
    defer { window.orderOut(nil) }
    let editor = PromptEditor.Editor(frame: window.contentView!.bounds)
    window.contentView?.addSubview(editor); window.makeFirstResponder(nil)
    editor.requestKeyboardFocus(); editor.cancelPendingFocus()
    await drainMainQueue()
    XCTAssertFalse(window.firstResponder === editor)
  }
  @MainActor func testHiddenEditorsRejectNativeKeyboardFocus() {
    let prompt = PromptEditor.Editor(); prompt.interactionEnabled = false
    let source = SourceEditor.Editor(); source.interactionEnabled = false
    XCTAssertFalse(prompt.acceptsFirstResponder); XCTAssertFalse(prompt.becomeFirstResponder())
    XCTAssertFalse(source.acceptsFirstResponder); XCTAssertFalse(source.becomeFirstResponder())
  }
  @MainActor private func drainMainQueue() async {
    await withCheckedContinuation { continuation in DispatchQueue.main.async { continuation.resume() } }
  }
}
