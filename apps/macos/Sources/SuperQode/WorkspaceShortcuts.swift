import AppKit
import SwiftTerm
import SwiftUI

/// Keyboard handling for the coding workspace that menus cannot express
/// safely: plain Esc and Return. A local event monitor sees keys before the
/// focused view, so every rule below declines unless the workspace itself
/// (the message box or the conversation) has focus and nothing modal is open.
@MainActor extension Workspace {
  /// The approval request shown above the conversation, if any.
  var pendingApprovalRequestID: String? {
    guard string(detail, "status") == "needs_approval",
      let latest = events.last(where: { string($0, "type") == "approval" })
    else { return nil }
    let id = string(latest["data"] as? [String: Any] ?? [:], "request_id")
    return id.isEmpty ? nil : id
  }

  func toggleTerminalDrawer() {
    if !WorkspaceNavigationGroup.usesCodingWorkspace(section) || showWelcome {
      showWelcome = false
      section = "Workspace"
    }
    toggleWorkbenchDrawer("Terminal")
  }

  func toggleReviewPanel() {
    showWelcome = false
    section = section == "Review" ? "Workspace" : "Review"
  }

  func focusThreadSearch() {
    threadSearchFocusRequest += 1
  }

  /// Up arrow in an empty message box: bring back the last prompt sent in this thread.
  func recallLastPrompt() -> Bool {
    guard draftStore.text.isEmpty else { return false }
    var prompt = ""
    if !selectedJob.isEmpty {
      prompt = string(detail["request"] as? [String: Any] ?? [:], "prompt")
    }
    if prompt.isEmpty, let last = conversationHistory.last { prompt = string(last, "prompt") }
    guard !prompt.isEmpty else { return false }
    draft = prompt
    return true
  }

  /// Returns true when the key was handled and must not reach the focused view.
  func handleWorkspaceKey(_ event: NSEvent, in window: NSWindow) -> Bool {
    let escape = event.keyCode == 53
    let enter = event.keyCode == 36 || event.keyCode == 76
    guard escape || enter else { return false }
    guard event.window === window, window.isKeyWindow, window.attachedSheet == nil,
      event.modifierFlags.intersection([.command, .option, .control, .shift]).isEmpty,
      !showCommandPalette, !showWelcome, !drawerExpanded,
      WorkspaceNavigationGroup.usesCodingWorkspace(section)
    else { return false }
    let responder = window.firstResponder
    let inComposer = responder is PromptEditor.Editor
    if let text = responder as? NSTextView, text.hasMarkedText() { return false }
    // Leave Esc and Return to search fields, other editors, buttons and the terminal.
    let neutral: Bool = {
      guard let responder else { return true }
      if responder === window { return true }
      if let text = responder as? NSTextView { return !text.isEditable }
      if responder is NSControl || responder is NSText { return false }
      if responder is SwiftTerm.TerminalView { return false }
      return responder is NSView
    }()
    guard inComposer || neutral else { return false }
    // An open mention list owns Esc and Return in the message box.
    if inComposer && mentionQuery != nil { return false }
    let composerEmpty = draftStore.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    if let request = pendingApprovalRequestID {
      // Never act on an approval while the user is typing a message.
      guard !inComposer || composerEmpty, !busy else { return false }
      approve(request, allow: enter)
      return true
    }
    if escape, active, activityStatus != "cancelling", !busy {
      cancel()
      return true
    }
    return false
  }
}

/// Installs the workspace key monitor for the window that hosts it.
struct WorkspaceKeyMonitor: NSViewRepresentable {
  let app: Workspace

  final class MonitorView: NSView {
    weak var app: Workspace?
    private var monitor: Any?
    override func viewDidMoveToWindow() {
      super.viewDidMoveToWindow()
      if let monitor { NSEvent.removeMonitor(monitor); self.monitor = nil }
      guard window != nil else { return }
      monitor = NSEvent.addLocalMonitorForEvents(matching: .keyDown) { [weak self] event in
        guard let self, let window = self.window, let app = self.app else { return event }
        let handled = MainActor.assumeIsolated { app.handleWorkspaceKey(event, in: window) }
        return handled ? nil : event
      }
    }
    deinit {
      if let monitor { NSEvent.removeMonitor(monitor) }
    }
  }

  func makeNSView(context: Context) -> MonitorView {
    let view = MonitorView()
    view.app = app
    return view
  }
  func updateNSView(_ view: MonitorView, context: Context) { view.app = app }
}
