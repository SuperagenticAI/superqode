import AppKit
import SwiftUI

struct CatalogPopupOption: Equatable {
  let id: String
  let title: String
}

/// A catalog can contain many presets. Build its AppKit menu only when its
/// entries change, rather than constructing a SwiftUI subtree per menu item
/// every time the editor or workspace navigation updates.
struct CatalogPopup: NSViewRepresentable {
  let label: String
  let options: [CatalogPopupOption]
  @Binding var selection: String
  @Environment(\.isEnabled) private var enabled

  final class Coordinator: NSObject {
    var parent: CatalogPopup
    var rendered: [CatalogPopupOption]?
    init(_ parent: CatalogPopup) { self.parent = parent }

    @objc func changed(_ sender: NSPopUpButton) {
      guard sender.isEnabled, let id = sender.selectedItem?.representedObject as? String,
        parent.options.contains(where: { $0.id == id }) else { return }
      parent.selection = id
    }

    func update(_ button: NSPopUpButton, parent: CatalogPopup, enabled: Bool) {
      self.parent = parent
      if rendered != parent.options {
        button.removeAllItems()
        button.addItem(withTitle: "Choose a preset")
        for option in parent.options {
          let item = NSMenuItem(title: option.title, action: nil, keyEquivalent: "")
          item.representedObject = option.id
          button.menu?.addItem(item)
        }
        rendered = parent.options
      }
      let index = parent.options.firstIndex(where: { $0.id == parent.selection }).map { $0 + 1 } ?? 0
      if button.indexOfSelectedItem != index { button.selectItem(at: index) }
      button.isEnabled = enabled && !parent.options.isEmpty
      button.setAccessibilityLabel(parent.label)
    }
  }

  func makeCoordinator() -> Coordinator { Coordinator(self) }
  func makeNSView(context: Context) -> NSPopUpButton {
    let button = NSPopUpButton(frame: .zero, pullsDown: false)
    button.controlSize = .regular
    button.autoenablesItems = false
    button.target = context.coordinator
    button.action = #selector(Coordinator.changed(_:))
    context.coordinator.update(button, parent: self, enabled: enabled)
    return button
  }
  func updateNSView(_ button: NSPopUpButton, context: Context) {
    context.coordinator.update(button, parent: self, enabled: enabled)
  }
}
