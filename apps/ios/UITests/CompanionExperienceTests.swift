import XCTest

final class CompanionExperienceTests: XCTestCase {
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
