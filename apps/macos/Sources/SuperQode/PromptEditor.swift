import AppKit
import SwiftUI

/// Preserve native text editing and IME composition, with chat-style Return.
struct PromptEditor: NSViewRepresentable {
  @Binding var text: String
  @Environment(\.isEnabled) private var enabled
  var onCursorPrefix: (String) -> Void = { _ in }
  var onImagePaste: () -> Void = {}
  var onInterceptReturn: () -> Bool = { false }
  /// Up arrow in an empty editor. Returns true when it restored a prompt.
  var onRecallPrevious: () -> Bool = { false }
  /// Reports whether the text view itself is the window's first responder.
  var onFocusChange: (Bool) -> Void = { _ in }
  /// Increment to move keyboard focus into the editor.
  var focusRequest = 0
  /// Increment to release keyboard focus if the editor holds it.
  var blurRequest = 0
  /// Prose is set in the system font for comfortable reading while writing.
  var fontSize: CGFloat = 15
  let submit: () -> Void

  final class Editor: NSTextView {
    var interactionEnabled = true
    private var focusGeneration = 0
    func cancelPendingFocus() { focusGeneration += 1 }
    func requestKeyboardFocus() {
      focusGeneration += 1
      let generation = focusGeneration
      DispatchQueue.main.async { [weak self] in
        guard let self, self.focusGeneration == generation, self.interactionEnabled,
          self.isEditable, !self.isHiddenOrHasHiddenAncestor,
          let window = self.window, window.firstResponder !== self,
          window.attachedSheet == nil else { return }
        if let current = window.firstResponder as? NSTextView, current.isEditable { return }
        window.makeFirstResponder(self)
      }
    }
    var submit: () -> Void = {}
    var onImagePaste: () -> Void = {}
    var onInterceptReturn: () -> Bool = { false }
    var onFocusChange: (Bool) -> Void = { _ in }
    var onRecallPrevious: () -> Bool = { false }
    override var acceptsFirstResponder: Bool { interactionEnabled && super.acceptsFirstResponder }
    override func becomeFirstResponder() -> Bool {
      guard interactionEnabled else { return false }
      let accepted = super.becomeFirstResponder()
      if accepted { onFocusChange(true) }
      return accepted
    }
    override func resignFirstResponder() -> Bool {
      let resigned = super.resignFirstResponder()
      if resigned { onFocusChange(false) }
      return resigned
    }
    override func keyDown(with event: NSEvent) {
      guard interactionEnabled, isEditable else { return }
      if event.keyCode == 126, string.isEmpty, !hasMarkedText(),
        event.modifierFlags.intersection([.shift, .option, .control, .command]).isEmpty,
        onRecallPrevious() {
        return
      }
      if (event.keyCode == 36 || event.keyCode == 76), !hasMarkedText(),
        event.modifierFlags.intersection([.shift, .option, .control]).isEmpty {
        if !onInterceptReturn() { submit() }
      } else {
        super.keyDown(with: event)
      }
    }
    override func paste(_ sender: Any?) {
      guard isEditable else { return }
      let board = NSPasteboard.general
      let hasText = !(board.string(forType: .string) ?? "").isEmpty
      if !hasText, NSImage(pasteboard: board) != nil {
        onImagePaste()
        return
      }
      super.paste(sender)
    }
  }
  final class Coordinator: NSObject, NSTextViewDelegate {
    var parent: PromptEditor
    var appliedFocusRequest = 0
    var appliedBlurRequest = 0
    /// Set when the editor held focus as it became read-only, so focus returns afterwards.
    var restoreFocusWhenEditable = false
    init(_ parent: PromptEditor) {
      self.parent = parent
      appliedFocusRequest = parent.focusRequest
      appliedBlurRequest = parent.blurRequest
    }
    func textDidChange(_ notification: Notification) {
      guard let editor = notification.object as? NSTextView else { return }
      parent.text = editor.string
      parent.report(editor)
    }
    func textViewDidChangeSelection(_ notification: Notification) {
      guard let editor = notification.object as? NSTextView else { return }
      parent.report(editor)
    }
  }
  private func report(_ editor: NSTextView) {
    let value = editor.string as NSString
    let location = min(max(editor.selectedRange().location, 0), value.length)
    onCursorPrefix(value.substring(to: location))
  }
  func makeCoordinator() -> Coordinator { Coordinator(self) }
  func makeNSView(context: Context) -> NSScrollView {
    let scroll = NSScrollView()
    scroll.drawsBackground = false
    scroll.hasVerticalScroller = true
    let editor = Editor()
    editor.isRichText = false
    editor.drawsBackground = false
    editor.font = .systemFont(ofSize: fontSize)
    editor.textColor = .labelColor
    editor.insertionPointColor = .labelColor
    editor.isVerticallyResizable = true
    editor.isHorizontallyResizable = false
    editor.autoresizingMask = [.width]
    editor.textContainer?.widthTracksTextView = true
    editor.textContainerInset = NSSize(width: 4, height: 4)
    editor.isAutomaticQuoteSubstitutionEnabled = false
    editor.isAutomaticDashSubstitutionEnabled = false
    editor.delegate = context.coordinator
    editor.setAccessibilityLabel("Message your coding agent")
    scroll.documentView = editor
    return scroll
  }
  func updateNSView(_ scroll: NSScrollView, context: Context) {
    context.coordinator.parent = self
    guard let editor = scroll.documentView as? Editor else { return }
    let coordinator = context.coordinator
    editor.interactionEnabled = enabled
    let focused = editor.window?.firstResponder === editor
    if editor.isEditable != enabled {
      editor.cancelPendingFocus()
      // Becoming read-only can drop keyboard focus. Remember it and give it back
      // when the composer is editable again, unless the user moved elsewhere.
      if !enabled { coordinator.restoreFocusWhenEditable = focused }
      editor.isEditable = enabled
      if enabled, coordinator.restoreFocusWhenEditable {
        coordinator.restoreFocusWhenEditable = false
        Self.focus(editor)
      }
    }
    editor.submit = submit
    editor.onImagePaste = onImagePaste
    editor.onInterceptReturn = onInterceptReturn
    editor.onFocusChange = onFocusChange
    editor.onRecallPrevious = onRecallPrevious
    if editor.font?.pointSize != fontSize { editor.font = .systemFont(ofSize: fontSize) }
    // Replacing the string resets the cursor and any IME composition. Only do
    // it when the bound text really changed outside the editor.
    if editor.string != text, !editor.hasMarkedText() { editor.string = text }
    if focusRequest != coordinator.appliedFocusRequest {
      coordinator.appliedFocusRequest = focusRequest
      if enabled { Self.focus(editor) }
    }
    if blurRequest != coordinator.appliedBlurRequest {
      editor.cancelPendingFocus()
      coordinator.restoreFocusWhenEditable = false
      coordinator.appliedBlurRequest = blurRequest
      if editor.window?.firstResponder === editor { editor.window?.makeFirstResponder(nil) }
    }
  }
  /// AppKit focus for the text view itself, deferred until it is in a window.
  private static func focus(_ editor: Editor) {
    editor.requestKeyboardFocus()
  }
}
