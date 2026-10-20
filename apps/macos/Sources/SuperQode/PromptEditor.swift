import AppKit
import SwiftUI

/// Preserve native text editing and IME composition, with chat-style Return.
struct PromptEditor: NSViewRepresentable {
  @Binding var text: String
  let submit: () -> Void

  final class Editor: NSTextView {
    var submit: () -> Void = {}
    override func keyDown(with event: NSEvent) {
      if (event.keyCode == 36 || event.keyCode == 76), !hasMarkedText(),
        event.modifierFlags.intersection([.shift, .option, .control]).isEmpty {
        submit()
      } else {
        super.keyDown(with: event)
      }
    }
  }
  final class Coordinator: NSObject, NSTextViewDelegate {
    var parent: PromptEditor
    init(_ parent: PromptEditor) { self.parent = parent }
    func textDidChange(_ notification: Notification) {
      guard let editor = notification.object as? NSTextView else { return }
      parent.text = editor.string
    }
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
    editor.submit = submit
    if editor.string != text { editor.string = text }
  }
}
