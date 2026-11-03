import SwiftUI

/// Keep the native Window menu and app reopening pointed at the same scene.
struct WorkspaceWindowCommands: Commands {
  @Environment(\.openWindow) private var openWindow
  let delegate: ApplicationDelegate
  private func register() { delegate.openWorkspace = { openWindow(id: "main") } }
  var body: some Commands {
    let _ = register()
    CommandGroup(after: .windowArrangement) {
      Button("SuperQode Workspace") { openWindow(id: "main") }
    }
  }
}
