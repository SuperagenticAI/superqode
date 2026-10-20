import AppKit
import Darwin
import SwiftTerm
import SwiftUI

/// Explicitly started local shells, retained when navigating between native pages.
@MainActor final class ProjectTerminals: ObservableObject {
  @Published private(set) var running: Set<String> = []
  private var views: [String: LocalProcessTerminalView] = [:]
  private var delegates: [String: TerminalDelegate] = [:]
  func view(_ project: String) -> LocalProcessTerminalView? { views[project] }
  func start(_ project: String, path: String, smoke: Bool = false, arguments: [String]? = nil) {
    guard !running.contains(project) else { return }
    let terminal = LocalProcessTerminalView(frame: NSRect(x: 0, y: 0, width: 900, height: 500))
    terminal.font = .monospacedSystemFont(ofSize: 13, weight: .regular)
    terminal.nativeBackgroundColor = .black
    terminal.wantsLayer = true
    terminal.layer?.backgroundColor = NSColor.black.cgColor
    terminal.nativeForegroundColor = NSColor(red: 0.92, green: 0.89, blue: 0.96, alpha: 1)
    let delegate = TerminalDelegate { [weak self] in self?.running.remove(project) }
    delegates[project] = delegate
    let io = TerminalIOProxy(terminal)
    delegate.io = io
    terminal.terminalDelegate = io
    terminal.processDelegate = delegate
    views[project] = terminal
    running.insert(project)
    var environment = ProcessInfo.processInfo.environment
    environment["TERM"] = "xterm-256color"
    environment["COLORTERM"] = "truecolor"
    environment["PATH"] =
      NSHomeDirectory() + "/.local/bin:/opt/homebrew/bin:/usr/local/bin:"
      + (environment["PATH"] ?? "/usr/bin:/bin")
    terminal.startProcess(
      executable: arguments == nil ? "/bin/zsh" : "/usr/bin/env",
      args: arguments ?? (smoke ? ["-c", "printf native-project-pty"] : ["-l"]),
      environment: environment.map { $0.key + "=" + $0.value }, currentDirectory: path)
  }
  func stop(_ project: String) {
    guard running.contains(project), let terminal = views[project] else { return }
    let foreground = tcgetpgrp(terminal.process.childfd)
    if foreground > 0 && foreground != getpgrp() { kill(-foreground, SIGHUP) }
    let pid = terminal.process.shellPid
    if pid > 0 { kill(pid, SIGHUP) }
    terminal.terminate()
  }
  func stopAll() { for project in Array(running) { stop(project) } }
  func output(_ project: String) -> String {
    guard let view = views[project] else { return "" }
    return String(decoding: view.getTerminal().getBufferAsData(), as: UTF8.self)
  }
}
private final class TerminalIOProxy: TerminalViewDelegate {
  weak var terminal: LocalProcessTerminalView?
  init(_ terminal: LocalProcessTerminalView) { self.terminal = terminal }
  func sizeChanged(source: SwiftTerm.TerminalView, newCols: Int, newRows: Int) {
    terminal?.sizeChanged(source: source, newCols: newCols, newRows: newRows)
  }
  func setTerminalTitle(source: SwiftTerm.TerminalView, title: String) {
    terminal?.setTerminalTitle(source: source, title: title)
  }
  func hostCurrentDirectoryUpdate(source: SwiftTerm.TerminalView, directory: String?) {
    terminal?.hostCurrentDirectoryUpdate(source: source, directory: directory)
  }
  func send(source: SwiftTerm.TerminalView, data: ArraySlice<UInt8>) {
    terminal?.send(source: source, data: data)
  }
  func scrolled(source: SwiftTerm.TerminalView, position: Double) {
    terminal?.scrolled(source: source, position: position)
  }
  func requestOpenLink(source: SwiftTerm.TerminalView, link: String, params: [String: String]) {
    terminal?.requestOpenLink(source: source, link: link, params: params)
  }
  func bell(source: SwiftTerm.TerminalView) { NSSound.beep() }
  func clipboardCopy(source: SwiftTerm.TerminalView, content: Data) {}
  func clipboardRead(source: SwiftTerm.TerminalView) -> Data? { nil }
  func iTermContent(source: SwiftTerm.TerminalView, content: ArraySlice<UInt8>) {}
  func rangeChanged(source: SwiftTerm.TerminalView, startY: Int, endY: Int) {
    terminal?.rangeChanged(source: source, startY: startY, endY: endY)
  }
}
private final class TerminalDelegate: LocalProcessTerminalViewDelegate {
  var io: TerminalIOProxy?
  let ended: () -> Void
  init(ended: @escaping () -> Void) { self.ended = ended }
  func sizeChanged(source: LocalProcessTerminalView, newCols: Int, newRows: Int) {}
  func setTerminalTitle(source: LocalProcessTerminalView, title: String) {}
  func hostCurrentDirectoryUpdate(source: SwiftTerm.TerminalView, directory: String?) {}
  func processTerminated(source: SwiftTerm.TerminalView, exitCode: Int32?) { ended() }
}
struct ProjectTerminalHost: NSViewRepresentable {
  let terminal: LocalProcessTerminalView
  func makeNSView(context: Context) -> LocalProcessTerminalView { terminal }
  func updateNSView(_ view: LocalProcessTerminalView, context: Context) {}
}
struct ProjectTerminalView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var terminals: ProjectTerminals
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      PageTitle(
        eyebrow: "Stay in the flow", title: "Project terminal",
        subtitle: "An interactive shell on your Mac, alongside your Agent Space.")
      HStack {
        Text(string(app.project, "path")).font(.caption.monospaced()).textSelection(.enabled)
        Spacer()
        Button("Start shell") { terminals.start(app.projectID, path: string(app.project, "path")) }
          .buttonStyle(BrandButtonStyle()).disabled(terminals.running.contains(app.projectID))
        Button("Stop shell", role: .destructive) {
          if app.confirm(
            "Stop this shell?",
            "The shell and its foreground command receive a hangup signal. Detached background services may keep running.",
            button: "Stop shell")
          {
            terminals.stop(app.projectID)
          }
        }.disabled(!terminals.running.contains(app.projectID))
      }
      if let terminal = terminals.view(app.projectID) {
        ProjectTerminalHost(terminal: terminal).id(ObjectIdentifier(terminal)).clipShape(
          RoundedRectangle(cornerRadius: 12))
      } else {
        EmptyState(
          icon: "terminal", title: "Your shell, in your Agent Space",
          detail:
            "Start a shell to run project commands, development servers or interactive tools. Shells keep running when you switch pages."
        )
      }
    }.padding(26)
  }
}
