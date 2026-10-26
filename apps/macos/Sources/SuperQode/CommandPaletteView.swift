import AppKit
import SwiftUI

struct CommandPaletteView: View {
  @EnvironmentObject var app: Workspace
  @State private var query = ""
  @State private var selection: String?
  @FocusState private var searchFocused: Bool
  private var results: [WorkspaceCommand] { WorkspaceCommand.search(app.workspaceCommands, query: query) }

  var body: some View {
    VStack(spacing: 0) {
      HStack {
        Text("Command Palette").font(.headline)
        Spacer()
        Button { app.showCommandPalette = false } label: { Image(systemName: "xmark") }
          .buttonStyle(.plain).accessibilityLabel("Close command palette")
      }.padding(16)
      HStack {
        Image(systemName: "magnifyingglass").foregroundStyle(.secondary)
        TextField("Search actions, recent runs and projects", text: $query)
          .textFieldStyle(.plain).focused($searchFocused)
          .accessibilityLabel("Search commands")
          .onSubmit { activateSelection() }
          .onKeyPress(keys: [.upArrow, .downArrow]) { press in
            // Keep candidate navigation available to native input methods.
            if let editor = NSApp.keyWindow?.firstResponder as? NSTextView, editor.hasMarkedText() {
              return .ignored
            }
            selection = WorkspaceCommand.moveSelection(selection, by: press.key == .downArrow ? 1 : -1, in: results)
            return .handled
          }
      }.padding(14).background(Color.primary.opacity(0.05))
      Divider()
      if results.isEmpty {
        VStack(spacing: 8) {
          Text("No matching commands").font(.headline)
          Text("Try a project name, run title, or an action such as Terminal.")
            .font(.caption).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, minHeight: 340)
      } else {
        ScrollViewReader { proxy in
          List(results, selection: $selection) { command in
            Button { app.choosePaletteCommand(command.action) } label: {
              HStack(spacing: 12) {
                Image(systemName: command.symbol).frame(width: 20)
                VStack(alignment: .leading, spacing: 3) {
                  Text(command.title).lineLimit(1)
                  Text(command.disabledReason ?? command.detail).font(.caption)
                    .foregroundStyle(.secondary).lineLimit(1)
                }
                Spacer()
                if let key = command.key { Text("⌘" + key.uppercased()).font(.caption.monospaced()) }
              }.padding(.vertical, 5).frame(maxWidth: .infinity, alignment: .leading)
            }.buttonStyle(.plain).disabled(!command.isEnabled)
              .help(command.disabledReason ?? command.detail)
              .accessibilityElement(children: .combine)
              .accessibilityHint(command.disabledReason ?? command.detail)
              .tag(command.id).id(command.id)
          }.listStyle(.plain).frame(height: 340)
            .onChange(of: selection) { _, id in
              if let id { proxy.scrollTo(id) }
            }
        }
      }
      Divider()
      HStack {
        Text("↑↓ Navigate   Return Open   Esc Close")
        Spacer()
        Text("\(results.count) results")
      }.font(.caption).foregroundStyle(.secondary).padding(12)
    }.frame(width: 640).background(Color.qPanel)
      .onAppear { selection = WorkspaceCommand.initialSelection(results); searchFocused = true }
      .onChange(of: query) { _, _ in selection = WorkspaceCommand.initialSelection(results) }
      .onChange(of: results.map(\.id)) { _, ids in
        if !ids.contains(selection ?? "") { selection = WorkspaceCommand.initialSelection(results) }
      }
      .onExitCommand { app.showCommandPalette = false }
  }

  private func activateSelection() {
    guard let command = results.first(where: { $0.id == selection }), command.isEnabled else { return }
    app.choosePaletteCommand(command.action)
  }
}

/// Native menus and palette share action titles, availability, shortcuts and handlers.
struct WorkspaceCommandMenuItem: View {
  @ObservedObject var app: Workspace
  let action: WorkspaceCommandAction

  var body: some View {
    if let command = app.workspaceCommand(action) {
      if let key = command.key, key.count == 1, let character = key.first {
        button(command).keyboardShortcut(KeyEquivalent(character))
      } else { button(command) }
    }
  }

  private func button(_ command: WorkspaceCommand) -> some View {
    Button(command.title) { app.runWorkspaceCommand(command.action) }
      .disabled(!command.isEnabled).help(command.disabledReason ?? command.detail)
  }
}

/// Capture the actual sheet host, which may differ from the key Settings window.
struct CommandPaletteWindowReader: NSViewRepresentable {
  let app: Workspace

  final class Probe: NSView {
    weak var workspace: Workspace?
    override func viewDidMoveToWindow() {
      super.viewDidMoveToWindow()
      workspace?.registerCommandPaletteWindow(window)
    }
  }

  func makeNSView(context: Context) -> Probe {
    let view = Probe()
    view.workspace = app
    return view
  }

  func updateNSView(_ view: Probe, context: Context) {
    view.workspace = app
    app.registerCommandPaletteWindow(view.window)
  }
}
