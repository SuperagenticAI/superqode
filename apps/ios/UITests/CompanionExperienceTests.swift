import XCTest

final class CompanionExperienceTests: XCTestCase {
  func testFileEditingIsInspectableButCannotSaveSampleData() {
    let app = XCUIApplication()
    app.launchArguments = ["--design-preview", "projects"]
    app.launch()
    XCTAssertTrue(app.buttons["workflow.code"].waitForExistence(timeout: 10))
    openSampleWorkspace(app)
    let files = app.buttons["project.files"]
    XCTAssertTrue(files.waitForExistence(timeout: 5))
    files.tap()
    let readme = app.buttons["project.file.README.md"]
    XCTAssertTrue(reveal(readme, in: app))
    readme.tap()
    app.buttons["Edit"].tap()
    XCTAssertTrue(app.textViews["file.editor"].waitForExistence(timeout: 5))
    XCTAssertFalse(app.buttons["Review save"].isEnabled)
  }

  func testHomePromotesDeveloperWorkflowsAndLabelsTerminalAsMacOnly() {
    let app = XCUIApplication()
    app.launchArguments = ["--design-preview", "projects", "-companionAppearance", "dark"]
    app.launch()
    for action in ["code", "review", "evaluate", "optimize"] {
      let shortcut = element(app, "workflow." + action)
      XCTAssertTrue(reveal(shortcut, in: app))
    }
    app.buttons["All features"].tap()
    let search = app.searchFields.firstMatch
    XCTAssertTrue(app.navigationBars["All features"].waitForExistence(timeout: 10))
    XCTAssertTrue(search.waitForExistence(timeout: 10))
    search.tap(); search.typeText("Terminal")
    app.staticTexts["Terminal"].tap()
    XCTAssertTrue(app.staticTexts["On Mac"].waitForExistence(timeout: 5))
    XCTAssertFalse(app.buttons["Start terminal"].exists)
  }
  func testEvaluationComparisonShowsReportedZeroAndUnknownCost() {
    let app = XCUIApplication()
    app.launchArguments = ["--design-preview", "evaluation", "-companionAppearance", "dark"]
    app.launch()
    let compare = app.buttons["Compare task outcomes"]
    XCTAssertTrue(app.staticTexts["Evaluation evidence"].waitForExistence(timeout: 10))
    for _ in 0..<4 { if compare.isHittable { break }; app.swipeUp() }
    XCTAssertTrue(compare.exists)
    compare.tap()
    let baseline = element(app, "comparison.baseline_cost_usd")
    XCTAssertTrue(reveal(baseline, in: app))
    XCTAssertEqual(shown(baseline), "$0.0000")
    XCTAssertEqual(shown(element(app, "comparison.candidate_cost_usd")), "Unknown")
  }
  func testFailedRunExplainsTheRepairWithoutExpandingActivity() {
    let app = XCUIApplication()
    app.launchArguments = ["--design-preview", "failed", "-companionAppearance", "dark"]
    app.launch()
    XCTAssertTrue(app.staticTexts["The agent could not complete this run"].waitForExistence(timeout: 10))
    XCTAssertTrue(app.staticTexts["The local model server is unavailable. Start Ollama on your Mac, then check this connection."].exists)
    XCTAssertEqual(app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "\"error\"")).count, 0)
  }
  func testNewConversationStartsBlankAndCannotSubmitSampleData() {
    let app = XCUIApplication()
    app.launchArguments = ["--design-preview", "projects", "-companionAppearance", "dark"]
    app.launch()
    XCTAssertTrue(app.buttons["workflow.code"].waitForExistence(timeout: 10))
    openSampleWorkspace(app)
    app.buttons["New thread"].tap()
    let connection = app.buttons["composer.connection"]
    XCTAssertTrue(connection.waitForExistence(timeout: 5))
    XCTAssertTrue((connection.label + String(describing: connection.value)).contains("Choose a connection"))
    connection.tap()
    app.buttons["Qwen · Local"].tap()
    let prompt = app.textViews["composer.prompt"]
    prompt.tap()
    prompt.typeText("Check reconnect handling")
    XCTAssertFalse(app.buttons["composer.send"].isEnabled)
    if app.buttons["Done"].exists { app.buttons["Done"].tap() }
    let close = element(app, "composer.close")
    XCTAssertTrue(close.waitForExistence(timeout: 5))
    close.tap()
    app.buttons["New thread"].tap()
    XCTAssertTrue(connection.waitForExistence(timeout: 5))
    XCTAssertEqual(app.textViews["composer.prompt"].value as? String ?? "", "")
    XCTAssertTrue((connection.label + String(describing: connection.value)).contains("Choose a connection"))
  }
  func testApprovalDetailsStayCollapsedUntilRequested() {
    let app = XCUIApplication()
    app.launchArguments = ["--design-preview", "approval", "-companionAppearance", "dark"]
    app.launch()
    let details = app.buttons["Action details"]
    for _ in 0..<5 {
      if details.isHittable { break }
      app.swipeUp()
    }
    XCTAssertTrue(details.waitForExistence(timeout: 5))
    let raw = app.staticTexts.matching(NSPredicate(format: "label CONTAINS %@", "\"arguments\""))
    XCTAssertEqual(raw.count, 0)
    details.tap()
    XCTAssertTrue(raw.firstMatch.waitForExistence(timeout: 5))
    XCTAssertFalse(app.buttons["Approve once"].isEnabled)
  }

  private func openSampleWorkspace(_ app: XCUIApplication) {
    let workspace = app.buttons["workspace.sample-workspace"]
    XCTAssertTrue(workspace.waitForExistence(timeout: 5))
    for _ in 0..<8 {
      if workspace.isHittable { break }
      app.swipeUp()
    }
    XCTAssertTrue(workspace.isHittable)
    workspace.tap()
  }

  private func element(_ app: XCUIApplication, _ identifier: String) -> XCUIElement {
    app.descendants(matching: .any)[identifier]
  }

  @discardableResult
  private func reveal(_ element: XCUIElement, in app: XCUIApplication) -> Bool {
    if element.waitForExistence(timeout: 2) { return true }
    for _ in 0..<6 {
      app.swipeUp()
      if element.exists { return true }
    }
    return element.waitForExistence(timeout: 3)
  }

  private func shown(_ element: XCUIElement) -> String {
    if let value = element.value as? String, !value.isEmpty { return value }
    return element.label
  }
}
