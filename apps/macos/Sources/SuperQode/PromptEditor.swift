import AppKit
import SwiftUI

/// Preserve native text editing and IME composition, with chat-style Return.
struct PromptEditor: NSViewRepresentable {
  @Binding var text: String
  @Environment(\.isEnabled) private var enabled
  var onCursorPrefix: (String) -> Void = { _ in }
  var onImagePaste: () -> Void = {}
  var onInterceptReturn: () -> Bool = { false }
  let submit: () -> Void

  final class Editor: NSTextView {
    var submit: () -> Void = {}
    var onImagePaste: () -> Void = {}
    var onInterceptReturn: () -> Bool = { false }
    override func keyDown(with event: NSEvent) {
      guard isEditable else { return }
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
    init(_ parent: PromptEditor) { self.parent = parent }
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
    editor.font = .monospacedSystemFont(ofSize: 14, weight: .regular)
    editor.textColor = .labelColor
    editor.insertionPointColor = .labelColor
    editor.isVerticallyResizable = true
    editor.isHorizontallyResizable = false
    editor.autoresizingMask = [.width]
    editor.textContainer?.widthTracksTextView = true
    editor.textContainerInset = NSSize(width: 4, height: 4)
    editor.delegate = context.coordinator
    editor.setAccessibilityLabel("Message your coding agent")
    scroll.documentView = editor
    return scroll
  }
  func updateNSView(_ scroll: NSScrollView, context: Context) {
    context.coordinator.parent = self
    guard let editor = scroll.documentView as? Editor else { return }
    if editor.isEditable != enabled { editor.isEditable = enabled }
    editor.submit = submit
    editor.onImagePaste = onImagePaste
    editor.onInterceptReturn = onInterceptReturn
    if editor.string != text { editor.string = text }
  }
}
