import AppKit
import SwiftUI

/// A Copy button revealed on hover over a whole message, with brief
/// "Copied" feedback. The text is read when clicked, so streaming responses
/// copy what has arrived so far.
struct HoverCopyButton: ViewModifier {
  let label: String
  let text: () -> String
  @State private var hovered = false
  @State private var copied = false

  func body(content: Content) -> some View {
    content
      .overlay(alignment: .topTrailing) {
        if hovered || copied {
          Button(action: copy) {
            Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
              .labelStyle(.titleAndIcon).font(.caption)
          }
          .buttonStyle(.borderless)
          .padding(.horizontal, 7).padding(.vertical, 4)
          .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 6))
          .padding(8)
          .help(label)
          .accessibilityLabel(label)
          .transition(.opacity)
        }
      }
      .onHover { hovered = $0 }
      .accessibilityAction(named: Text(label)) { copy() }
  }

  private func copy() {
    let value = text()
    guard !value.isEmpty else { return }
    let board = NSPasteboard.general
    board.clearContents()
    board.setString(value, forType: .string)
    copied = true
    Task { @MainActor in
      try? await Task.sleep(for: .seconds(1.5))
      copied = false
    }
  }
}

extension View {
  /// Adds a hover-revealed Copy button for the whole message.
  func hoverCopy(_ label: String, text: @escaping () -> String) -> some View {
    modifier(HoverCopyButton(label: label, text: text))
  }
}
