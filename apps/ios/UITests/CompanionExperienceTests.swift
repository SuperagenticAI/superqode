import XCTest

final class CompanionExperienceTests: XCTestCase {
  func testHomePromotesDeveloperWorkflowsAndLabelsTerminalAsMacOnly() {
    let app = XCUIApplication()
    app.launchArguments = ["--design-preview", "projects", "-companionAppearance", "dark"]
    app.launch()
    for action in ["code", "review", "evaluate", "optimize"] {
      XCTAssertTrue(app.buttons["workflow." + action].waitForExistence(timeout: 10))
    }
    app.buttons["All features"].tap()
    let search = app.searchFields.firstMatch
    XCTAssertTrue(search.waitForExistence(timeout: 5))
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
    let baseline = app.staticTexts["Baseline cost"]
    for _ in 0..<4 { if baseline.isHittable { break }; app.swipeUp() }
    XCTAssertTrue(baseline.exists)
    XCTAssertTrue(app.staticTexts["$0.0000"].exists)
    XCTAssertTrue(app.staticTexts.matching(identifier: "Unknown").firstMatch.exists)
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
    XCTAssertTrue(app.staticTexts["SuperQode Studio"].waitForExistence(timeout: 10))
    app.staticTexts["SuperQode Studio"].tap()
    app.buttons["New conversation"].tap()
    let connection = app.buttons["composer.connection"]
    XCTAssertTrue(connection.waitForExistence(timeout: 5))
    XCTAssertTrue((connection.label + String(describing: connection.value)).contains("Choose a connection"))
    connection.tap()
    app.buttons["Qwen · Local"].tap()
    let prompt = app.textViews["composer.prompt"]
    prompt.tap()
    prompt.typeText("Check reconnect handling")
    XCTAssertFalse(app.buttons["composer.send"].isEnabled)
    app.buttons["composer.close"].tap()
    app.buttons["New conversation"].tap()
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
}
