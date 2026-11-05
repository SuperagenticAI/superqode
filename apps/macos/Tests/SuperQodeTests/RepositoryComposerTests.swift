import AppKit
import SwiftUI
import XCTest
@testable import SuperQode

final class RepositoryComposerTests: XCTestCase {
  @MainActor func testTypingAndCursorCallbacksOnlyInvalidateComposer() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.files = ["src/app.swift"]
    var workspaceChanges = 0
    var composerChanges = 0
    let workspaceSubscription = app.objectWillChange.sink { workspaceChanges += 1 }
    let composerSubscription = app.draftStore.objectWillChange.sink { composerChanges += 1 }
    let prompt = PromptEditor(
      text: Binding(get: { app.draftStore.text }, set: { app.draftStore.text = $0 }),
      onCursorPrefix: app.noteComposerCursor) {}
    let coordinator = PromptEditor.Coordinator(prompt)
    let editor = PromptEditor.Editor()
    for index in 0..<100 {
      editor.string = "Draft \(index) @src/ap"
      editor.setSelectedRange(NSRange(location: (editor.string as NSString).length, length: 0))
      coordinator.textDidChange(Notification(name: NSText.didChangeNotification, object: editor))
      coordinator.textViewDidChangeSelection(Notification(name: NSTextView.didChangeSelectionNotification, object: editor))
    }
    XCTAssertEqual(workspaceChanges, 0, "Keystrokes must not redraw the sidebar, transcript and inspectors")
    XCTAssertGreaterThanOrEqual(composerChanges, 100)
    XCTAssertEqual(app.mentionQuery, "src/ap")
    XCTAssertEqual(app.mentionMatches, ["src/app.swift"])
    XCTAssertEqual(app.draft, "Draft 99 @src/ap")
    workspaceSubscription.cancel()
    composerSubscription.cancel()
  }

  @MainActor func testDisabledComposerCannotSubmitBehindAnExpandedPanel() throws {
    let editor = PromptEditor.Editor()
    var submissions = 0
    var intercepted = 0
    editor.submit = { submissions += 1 }
    editor.onInterceptReturn = { intercepted += 1; return false }
    let event = try XCTUnwrap(NSEvent.keyEvent(with: .keyDown, location: .zero,
      modifierFlags: [], timestamp: 0, windowNumber: 0, context: nil,
      characters: "\r", charactersIgnoringModifiers: "\r", isARepeat: false, keyCode: 36))
    editor.isEditable = false
    editor.keyDown(with: event)
    XCTAssertEqual(submissions, 0)
    XCTAssertEqual(intercepted, 0)
    editor.isEditable = true
    editor.keyDown(with: event)
    XCTAssertEqual(submissions, 1)
  }

  func testMentionQueryUsesTheTokenAtTheCursor() {
    XCTAssertEqual(ComposerMentions.query(in: "see @src/app"), "src/app")
    XCTAssertEqual(ComposerMentions.query(in: "mail a@b.com"), nil)
    XCTAssertEqual(ComposerMentions.query(in: "hello "), nil)
    let inserted = ComposerMentions.insert(text: "fix @src extra", prefix: "fix @src", path: "src/app.swift")
    XCTAssertEqual(inserted, "fix @src/app.swift extra")
  }

  @MainActor func testReturnCompletesPartialMentionsButSendsCompletePaths() {
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil))
    app.files = ["src/app.swift", "src/app.swift.bak"]
    app.draft = "Review @src/app.swift"
    app.noteComposerCursor(app.draft)
    XCTAssertFalse(app.acceptTopMentionIfNeeded())
    app.noteComposerCursor("Review @src/ap")
    XCTAssertFalse(app.acceptTopMentionIfNeeded())
    XCTAssertEqual(app.draft, "Review @src/app.swift")
    app.draft = "Review @src/ap"
    app.noteComposerCursor(app.draft)
    XCTAssertTrue(app.acceptTopMentionIfNeeded())
    XCTAssertEqual(app.draft, "Review @src/app.swift ")
    XCTAssertEqual(app.contextFiles, ["src/app.swift"])
    app.noteComposerCursor("Review @src/app.swift")
    XCTAssertFalse(app.acceptTopMentionIfNeeded())
  }

  func testIsolationAcceptsDoubleDotsInFilenamesButRejectsParentComponents() {
    let moved = TaskIsolation.handoff(
      files: ["notes..md", "docs/v1..v2.md", "../escape", "docs/../escape", "docs/..", "/absolute"]
    ) { _ in true }
    XCTAssertEqual(moved.files, ["notes..md", "docs/v1..v2.md"])
    XCTAssertEqual(moved.dropped, ["../escape", "docs/../escape", "docs/..", "/absolute"])
  }

  func testConfiguredCodingDestinationsKeepTheirWorkspaceHost() {
    for section in ["Workspace", "Review", "Files", "Terminal", "Checkpoints", "Project custom panel"] {
      XCTAssertTrue(WorkspaceNavigationGroup.usesCodingWorkspace(section), section)
    }
    for section in ["Models", "Threads", "Agent activity", "Harness Hub", "Harness Studio", "Super Agent", "Evaluations", "Optimization", "Tools"] {
      XCTAssertFalse(WorkspaceNavigationGroup.usesCodingWorkspace(section), section)
    }
  }

  func testFeatureNavigationExposesEverySectionExactlyOnce() {
    let sections = WorkspaceNavigationGroup.all.flatMap(\.sections)
    XCTAssertEqual(Set(sections), Set(Sections.names))
    XCTAssertEqual(sections.count, Set(sections).count)
    for section in Sections.names {
      XCTAssertTrue(WorkspaceNavigationGroup.containing(section).sections.contains(section))
      XCTAssertTrue(WorkspaceNavigationGroup.available(section, hasProject: true))
    }
    XCTAssertTrue(WorkspaceNavigationGroup.available("Models", hasProject: false))
    XCTAssertTrue(WorkspaceNavigationGroup.available("Agent activity", hasProject: false))
    XCTAssertFalse(WorkspaceNavigationGroup.available("Review", hasProject: false))
  }

  func testThreadFiltersSearchHarnessesAndHumanReadableApprovalStatus() {
    let row: [String: Any] = ["title": "Fix tests", "status": "needs_approval", "pinned": true,
      "harnesses_used": [["id": "acp:claude", "name": "Claude"]]]
    XCTAssertTrue(ThreadListFilter.needsYou.matches(row))
    XCTAssertTrue(ThreadListFilter.pinned.matches(row))
    XCTAssertFalse(ThreadListFilter.working.matches(row))
    XCTAssertTrue(ThreadListFilter.search("  CLAUDE  ", in: row))
    XCTAssertTrue(ThreadListFilter.search("Needs you", in: row))
    XCTAssertFalse(ThreadListFilter.search("Codex", in: row))
    XCTAssertTrue(ThreadListFilter.working.matches(["status": "queued"]))
    XCTAssertFalse(ThreadListFilter.working.matches(["status": "completed"]))
  }

  func testNativeAccentColorsStayReadableOnBothSurfaces() throws {
    for hex in ["#000000", "#FFFFFF", "#777777", "#9C6ADE", "#4D8DDF", "#2F9D92", "#FFFF00"] {
      let rgb = try XCTUnwrap(NativeAccent.parse(hex))
      XCTAssertGreaterThanOrEqual((rgb.readable(dark: true).luminance + 0.05) / 0.05, 4.5, hex)
      XCTAssertGreaterThanOrEqual(1.05 / (rgb.readable(dark: false).luminance + 0.05), 4.5, hex)
    }
    XCTAssertNil(NativeAccent.parse("#123"))
    XCTAssertNil(NativeAccent.parse("#GG0000"))
    XCTAssertNil(NativeAccent.parse("#12345678"))
  }

  @MainActor func testNativeAccentDefaultsToGraphiteAndPersistsCustomChoice() {
    let suite = "superqode.accent.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defer { defaults.removePersistentDomain(forName: suite) }
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: defaults)
    XCTAssertEqual(app.accentChoice, "graphite")
    app.accentChoice = "custom"
    app.customAccentHex = "#4080A0"
    let restored = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: defaults)
    XCTAssertEqual(restored.accentChoice, "custom")
    XCTAssertEqual(restored.customAccentHex, "#4080A0")
    defaults.set("unknown-theme", forKey: NativeAccent.preferenceKey)
    let fallback = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: defaults)
    XCTAssertEqual(fallback.accentChoice, "graphite")
  }

  func testSendingFullReturnsTheNextNewConversationToAsk() {
    let suite = "superqode.permission.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defaults.removePersistentDomain(forName: suite)
    let draft = WorkspaceRecoverySnapshot.key(project: "project", conversation: "")
    let created = WorkspaceRecoverySnapshot.key(project: "project", conversation: "job-1")
    PermissionMemory.store("full", composerKey: draft, defaults: defaults)
    PermissionMemory.commitNewConversation(
      "full", project: "project", conversation: "job-1", defaults: defaults)
    XCTAssertEqual(PermissionMemory.mode(for: created, defaults: defaults), "full")
    XCTAssertEqual(PermissionMemory.mode(for: draft, defaults: defaults), "ask")
    defaults.removePersistentDomain(forName: suite)
  }

  func testIsolationHandoffKeepsThePromptFilesThatExistInTheWorktree() {
    let moved = TaskIsolation.handoff(files: ["src/app.swift", "notes.txt", "/tmp/outside", "../escape"]) {
      $0 == "src/app.swift"
    }
    XCTAssertEqual(moved.files, ["src/app.swift"])
    XCTAssertEqual(moved.dropped, ["notes.txt", "/tmp/outside", "../escape"])
  }

  func testPermissionMemoryStaysAskUntilAConversationChoosesOtherwise() {
    let suite = "superqode.permission.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defaults.removePersistentDomain(forName: suite)
    XCTAssertEqual(PermissionMemory.mode(for: "draft", defaults: defaults), "ask")
    PermissionMemory.store("full", composerKey: "draft", defaults: defaults)
    PermissionMemory.store("host", composerKey: "draft", defaults: defaults)
    XCTAssertEqual(PermissionMemory.mode(for: "draft", defaults: defaults), "full")
    XCTAssertEqual(PermissionMemory.mode(for: "other", defaults: defaults), "ask")
    defaults.removePersistentDomain(forName: suite)
  }

  func testRepositoryPinsKeepKnownSectionsAndDropDuplicates() {
    XCTAssertEqual(
      RepositoryLayout.pinned(["Files", "Tools", "Files", "Not a screen", "Workspace"]),
      ["Files", "Tools", "Workspace"])
  }

  func testIsolationTitleIsBoundedAndChangeSummaryPrefersTheDiffStat() {
    XCTAssertEqual(TaskIsolation.title(from: ""), "Isolated task")
    XCTAssertEqual(TaskIsolation.title(from: String(repeating: "a", count: 200)), String(repeating: "a", count: 120))
    XCTAssertEqual(
      ChangeSummary.line(stat: " hello.txt | 1 +\n 1 file changed, 1 insertion(+)", status: " M hello.txt", diff: "diff", error: ""),
      "1 file changed, 1 insertion(+)")
    XCTAssertEqual(ChangeSummary.line(stat: "", status: "", diff: "", error: ""), nil)
    XCTAssertEqual(ChangeSummary.line(stat: "", status: " M a\n M b", diff: "", error: ""), "2 changed files")
  }

  @MainActor func testCreatorStaysInTheCatalogAndPermissionIsNotRecoveryState() throws {
    XCTAssertEqual(Sections.names.last, "Super Agent")
    XCTAssertEqual(Sections.names.count, Sections.icons.count)
    XCTAssertEqual(Sections.names.first, "Workspace")
    XCTAssertTrue(Sections.names.contains("Tools"))
    let data = try JSONEncoder().encode(ComposerRecovery(text: "draft"))
    let object = try JSONSerialization.jsonObject(with: data) as? [String: Any]
    XCTAssertNil(object?["permissionMode"])
    XCTAssertEqual(object?["mode"] as? String, "code")

    let suite = "superqode.permission.\(UUID().uuidString)"
    let defaults = UserDefaults(suiteName: suite)!
    defaults.removePersistentDomain(forName: suite)
    let app = Workspace(recoveryStore: WorkspaceRecoveryStore(directory: nil), preferences: defaults)
    app.project = ["id": "project"]
    app.restoreComposer(conversationID: "")
    XCTAssertEqual(app.permissionMode, "ask")
    app.permissionMode = "auto-edit"
    app.restoreComposer(conversationID: "other")
    XCTAssertEqual(app.permissionMode, "ask")
    app.restoreComposer(conversationID: "")
    XCTAssertEqual(app.permissionMode, "auto-edit")
    XCTAssertFalse(app.inspectorVisible)
    defaults.removePersistentDomain(forName: suite)
  }
}
