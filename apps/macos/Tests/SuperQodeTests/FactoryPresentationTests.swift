import XCTest
import SwiftUI
import AppKit
@testable import SuperQode

final class FactoryPresentationTests: XCTestCase {
  func testAutoplayStopsAtHumanReviewAndCannotSkipIt() {
    var state = FactoryPresentationState()
    state.play()
    XCTAssertTrue(state.playing)
    XCTAssertTrue(state.advance())
    XCTAssertTrue(state.advance())
    XCTAssertTrue(state.advance())
    XCTAssertEqual(state.stage, .review)
    XCTAssertTrue(state.waitingForReview)
    XCTAssertFalse(state.playing)
    XCTAssertFalse(state.advance())
    state.play()
    XCTAssertFalse(state.playing)
    state.approveReview()
    XCTAssertEqual(state.stage, .verify)
    XCTAssertTrue(state.reviewApproved)
    XCTAssertTrue(state.advance())
    XCTAssertEqual(state.stage, .complete)
    XCTAssertFalse(state.playing)
    XCTAssertFalse(state.advance())
  }

  func testBackAndRestartInvalidatePlaybackAndRequireReviewAgain() {
    var state = FactoryPresentationState()
    for _ in 0..<3 { state.advance() }
    state.approveReview()
    let beforeBack = state.playbackID
    state.back()
    XCTAssertGreaterThan(state.playbackID, beforeBack)
    XCTAssertEqual(state.stage, .review)
    XCTAssertFalse(state.reviewApproved)
    XCTAssertFalse(state.canAdvance)
    let beforeReset = state.playbackID
    state.reset()
    XCTAssertEqual(state.stage, .request)
    XCTAssertFalse(state.playing)
    XCTAssertFalse(state.reviewApproved)
    XCTAssertGreaterThan(state.playbackID, beforeReset)
  }

  func testPlayingAtTheEndDoesNotRestartOrInventNewProgress() {
    var state = FactoryPresentationState()
    for _ in 0..<3 { state.advance() }
    state.approveReview(); state.advance()
    let complete = state
    state.play()
    XCTAssertEqual(state, complete)
  }

  func testGuidedSuggestionRequiresRealEvidenceToSuggestVerification() {
    XCTAssertEqual(FactoryJourneyStep.suggested(saved: false, trialPrepared: false, verified: false), .intent)
    XCTAssertEqual(FactoryJourneyStep.suggested(saved: true, trialPrepared: false, verified: false), .review)
    XCTAssertEqual(FactoryJourneyStep.suggested(saved: true, trialPrepared: true, verified: false), .trial)
    XCTAssertEqual(FactoryJourneyStep.suggested(saved: true, trialPrepared: true, verified: true), .evidence)
  }

  @MainActor func testEveryPresentationSceneRendersWithoutAnEngine() throws {
    _ = NSApplication.shared
    var state = FactoryPresentationState()
    for stage in FactoryPresentationState.Stage.allCases {
      XCTAssertEqual(state.stage, stage)
      for scheme in [ColorScheme.light, .dark] {
        try render(FactoryPresentationScene(state: state).environment(\.colorScheme, scheme),
                   name: "presentation-\(stage.rawValue)-\(scheme == .dark ? "dark" : "light")", width: 900, height: 430)
      }
      if state.waitingForReview { state.approveReview() } else { state.advance() }
    }
  }

  @MainActor func testPresentationPlayerRendersAtCompactWindowSize() throws {
    _ = NSApplication.shared
    try render(FactoryPresentationView(), name: "presentation-player", width: 920, height: 680)
  }

  @MainActor func testGuidedScreensRenderAtNarrowAndWideWidthsWithoutRequests() throws {
    _ = NSApplication.shared
    let pipe = Pipe(); let engine = Engine(input: pipe.fileHandleForWriting)
    let suite = "factory-preview-" + UUID().uuidString
    let preferences = try XCTUnwrap(UserDefaults(suiteName: suite))
    defer { engine.stop(); preferences.removePersistentDomain(forName: suite) }
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: preferences, engine: engine)
    let studio = FactoryStudioLibrary(); studio.enter("preview")
    studio.text = "preview-definition"
    studio.description = "Fix bugs and verify every repair"
    studio.review = ["review": "preview", "yaml": studio.text, "digest": "saved", "snapshot_digest": "snapshot",
                     "stages": [["id": "investigate"], ["id": "implement"], ["id": "verify"]],
                     "acceptance_checks": ["regression"], "application_checks": ["regression": ["evaluator": "probes"]]]
    let setup = FactorySetupState(text: studio.text, review: studio.review, savedDigest: "saved",
                                 sources: ["snapshot_digest": "snapshot", "files": [["changed": false]]], runs: [])
    for step in FactoryJourneyStep.allCases {
      for width: CGFloat in [560, 820] {
        let view = FactoryGuidedBuilderView(studio: studio, step: .constant(step), trialGoal: .constant("Repair checkout totals"),
          setup: setup, idle: true, onBuild: {}, onStarter: { _ in }, onValidate: {}, onSave: {}, onTrial: {}, onDemo: {}, inspectAutomatically: false)
          .environmentObject(app)
        try render(view, name: "guided-\(step.rawValue)-\(Int(width))", width: width, height: 730)
      }
    }
    XCTAssertEqual(engine.pendingRequestCount, 0)
  }

  @MainActor private func render<V: View>(_ view: V, name: String, width: CGFloat, height: CGFloat) throws {
    let content = view.frame(width: width, height: height, alignment: .topLeading)
      .background(Color(nsColor: .windowBackgroundColor))
    // ImageRenderer omits AppKit-backed text fields and scroll content. Capture the
    // actual hosted native view so previews include the controls people use.
    let bounds = NSRect(x: 0, y: 0, width: width, height: height)
    let window = NSWindow(contentRect: bounds, styleMask: [.borderless], backing: .buffered, defer: false)
    window.appearance = NSAppearance(named: name.hasSuffix("-dark") ? .darkAqua : .aqua)
    let hosting = NSHostingView(rootView: content)
    hosting.frame = bounds
    window.contentView = hosting
    window.orderFront(nil)
    defer { window.orderOut(nil) }
    RunLoop.main.run(until: Date().addingTimeInterval(0.05))
    hosting.layoutSubtreeIfNeeded()
    hosting.displayIfNeeded()
    let bitmap = try XCTUnwrap(hosting.bitmapImageRepForCachingDisplay(in: bounds), "Could not render " + name)
    hosting.cacheDisplay(in: bounds, to: bitmap)
    XCTAssertGreaterThan(bitmap.pixelsWide, 0)
    if let directory = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_PREVIEW_DIR"] {
      let folder = URL(fileURLWithPath: directory)
      try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
      let png = try XCTUnwrap(bitmap.representation(using: .png, properties: [:]))
      try png.write(to: folder.appendingPathComponent(name + ".png"))
    }
  }
}
