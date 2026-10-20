import AppKit
import SwiftUI

func sourceLanguage(for path: String) -> String {
  let ext = URL(fileURLWithPath: path).pathExtension.lowercased()
  return ["md": "markdown", "mdx": "markdown", "py": "python", "pyi": "python", "js": "javascript", "mjs": "javascript", "cjs": "javascript", "ts": "typescript", "h": "c", "hpp": "cpp", "cc": "cpp", "rs": "rust", "rb": "ruby", "kt": "kotlin", "cs": "csharp" ][ext] ?? ext
}

/// Native source selection/editing. Colour changes never replace the buffer or its undo history.
struct SourceEditor: NSViewRepresentable {
  @Binding var text: String
  let path: String
  var editable: Bool
  var documentID = ""
  @Environment(\.isEnabled) private var enabled
  @Environment(\.accessibilityReduceTransparency) private var reduceTransparency
  @Environment(\.colorSchemeContrast) private var contrast

  final class Editor: NSTextView {
    var highContrast = false
    override func drawBackground(in rect: NSRect) {
      super.drawBackground(in: rect)
      guard window?.firstResponder === self, let layout = layoutManager, textContainer != nil else { return }
      var line = NSRect(x: 0, y: textContainerOrigin.y, width: bounds.width, height: (font?.pointSize ?? 13) * 1.5)
      if layout.numberOfGlyphs > 0 {
        let char = min(selectedRange().location, max(0, (string as NSString).length - 1))
        let glyph = layout.glyphIndexForCharacter(at: char)
        let fragment = layout.lineFragmentRect(forGlyphAt: glyph, effectiveRange: nil)
        line.origin.y = fragment.minY + textContainerOrigin.y
        line.size.height = fragment.height
      }
      guard line.intersects(rect) else { return }
      if highContrast {
        NSColor.white.withAlphaComponent(0.25).setStroke()
        NSBezierPath(rect: line.insetBy(dx: 1, dy: 0)).stroke()
      } else {
        NSGradient(starting: NSColor(srgbRed: 0.65, green: 0.25, blue: 1, alpha: 0.18), ending: NSColor(srgbRed: 1, green: 0.54, blue: 0.08, alpha: 0.02))?
          .draw(in: NSBezierPath(rect: line), angle: 0)
      }
    }
    func replaceBuffer(_ source: String) {
      undoManager?.removeAllActions()
      string = source
      setSelectedRange(NSRange(location: 0, length: 0))
      scrollRangeToVisible(selectedRange())
    }
    func applyColours(_ styled: AttributedString, expectedSource: String) {
      guard string == expectedSource, let storage = textStorage else { return }
      let attributed = NSAttributedString(styled)
      storage.beginEditing()
      storage.addAttribute(.foregroundColor, value: NSColor.white, range: NSRange(location: 0, length: storage.length))
      attributed.enumerateAttribute(.foregroundColor, in: NSRange(location: 0, length: attributed.length)) { value, range, _ in
        if let value { storage.addAttribute(.foregroundColor, value: value, range: range) }
      }
      storage.endEditing()
    }
  }
  final class Coordinator: NSObject, NSTextViewDelegate {
    var parent: SourceEditor
    var styling: Task<Void, Never>?
    var documentID = ""
    var lastSource: String?
    var lastLanguage = ""
    var lastContrast = false
    init(_ parent: SourceEditor) { self.parent = parent }
    func textDidChange(_ notification: Notification) {
      guard let editor = notification.object as? Editor else { return }
      parent.text = editor.string
      schedule(editor)
    }
    func textViewDidChangeSelection(_ notification: Notification) {
      (notification.object as? Editor)?.needsDisplay = true
    }
    func schedule(_ editor: Editor) {
      let source = editor.string
      let language = sourceLanguage(for: parent.path)
      let highContrast = parent.contrast == .increased
      guard source != lastSource || language != lastLanguage || highContrast != lastContrast else { return }
      lastSource = source; lastLanguage = language; lastContrast = highContrast
      styling?.cancel()
      styling = Task { @MainActor [weak editor] in
        do { try await Task.sleep(for: .milliseconds(100)) } catch { return }
        let styled = await Task.detached(priority: .userInitiated) {
          highlightedSource(source, language: language, dark: true, highContrast: highContrast)
        }.value
        guard !Task.isCancelled else { return }
        editor?.applyColours(styled, expectedSource: source)
      }
    }
  }
  func makeCoordinator() -> Coordinator { Coordinator(self) }
  func makeNSView(context: Context) -> NSScrollView {
    let scroll = NSScrollView()
    scroll.hasVerticalScroller = true
    scroll.hasHorizontalScroller = true
    scroll.backgroundColor = .black
    let editor = Editor(frame: NSRect(x: 0, y: 0, width: 700, height: 400))
    editor.isRichText = false
    editor.allowsUndo = true
    editor.font = .monospacedSystemFont(ofSize: 13, weight: .regular)
    editor.textColor = .white
    editor.backgroundColor = .black
    editor.insertionPointColor = NSColor(srgbRed: 1, green: 0.60, blue: 0.18, alpha: 1)
    editor.selectedTextAttributes = [.backgroundColor: NSColor(srgbRed: 0.55, green: 0.25, blue: 0.85, alpha: 0.5), .foregroundColor: NSColor.white]
    editor.isAutomaticQuoteSubstitutionEnabled = false
    editor.isAutomaticDashSubstitutionEnabled = false
    editor.isAutomaticSpellingCorrectionEnabled = false
    editor.isContinuousSpellCheckingEnabled = false
    editor.isVerticallyResizable = true
    editor.isHorizontallyResizable = true
    editor.maxSize = NSSize(width: CGFloat.greatestFiniteMagnitude, height: CGFloat.greatestFiniteMagnitude)
    editor.autoresizingMask = [.width]
    editor.layoutManager?.allowsNonContiguousLayout = true
    editor.textContainer?.containerSize = editor.maxSize
    editor.textContainer?.widthTracksTextView = false
    editor.textContainerInset = NSSize(width: 14, height: 14)
    editor.delegate = context.coordinator
    scroll.documentView = editor
    return scroll
  }
  func updateNSView(_ scroll: NSScrollView, context: Context) {
    context.coordinator.parent = self
    guard let editor = scroll.documentView as? Editor else { return }
    editor.isEditable = editable && enabled
    editor.isSelectable = true
    editor.highContrast = contrast == .increased || reduceTransparency
    editor.setAccessibilityLabel((editable ? "Edit " : "Source for ") + path)
    let identity = documentID.isEmpty ? path : documentID
    if context.coordinator.documentID != identity || editor.string != text {
      context.coordinator.documentID = identity
      context.coordinator.styling?.cancel()
      context.coordinator.lastSource = nil
      editor.replaceBuffer(text)
    }
    context.coordinator.schedule(editor)
  }
  static func dismantleNSView(_ scroll: NSScrollView, coordinator: Coordinator) { coordinator.styling?.cancel() }
}
