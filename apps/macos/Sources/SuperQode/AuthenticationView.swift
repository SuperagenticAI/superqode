import AppKit
import SwiftUI

/// The vendor retains credential ownership; the app only displays login progress.
struct AuthenticationProgressView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let request: [String: Any]
  let complete: ([String: Any]) -> Void
  @State private var identity = ""
  @State private var state = "running"
  @State private var messages = "Starting sign-in…"
  @State private var dismissRequested = false
  @State private var cancellationSent = false
  private var heading: String {
    switch string(request, "action") {
    case "registry-refresh": return "Refresh ACP registry"
    case "install", "acp-install": return "Install coding agent"
    case "probe": return "Check agent connection"
    case "acp-terminal": return "Prepare agent sign-in"
    default: return "Complete sign-in"
    }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      PageTitle(
          eyebrow: "Agent setup", title: heading,
        subtitle:
          "Review progress below. Sign-in stays with the selected agent. You can cancel this operation."
      )
      if state == "running" { ProgressView() }
      CodeBlock(text: messages).frame(height: 260)
      HStack {
        nativeButton("dialog.cancel", action: {
          cancel()
          dismiss()
        }, title: state == "running" ? "Cancel operation" : "Close") {
          Text(state == "running" ? "Cancel operation" : "Close")
        }
        Spacer()
        if state == "failed" { Text("Operation did not complete").foregroundStyle(.orange) }
      }
    }.padding(28).frame(width: 650, height: 480).background { BrandBackdrop() }
      .task {
        do {
          let response =
            try await app.engine.call("connect.auth.start", request) as? [String: Any] ?? [:]
          identity = string(response, "id")
          if dismissRequested || Task.isCancelled { cancel(); return }
          while !Task.isCancelled && !dismissRequested {
            let result =
              try await app.engine.call("connect.auth.poll", ["id": identity]) as? [String: Any]
              ?? [:]
            if dismissRequested || Task.isCancelled { cancel(); return }
            state = string(result, "state")
            messages = (result["messages"] as? [String] ?? []).joined(separator: "\n")
            if state == "completed" {
              complete(result["result"] as? [String: Any] ?? [:])
              return
            }
            if state != "running" { return }
            try await Task.sleep(for: .milliseconds(500))
          }
          cancel()
        } catch is CancellationError { cancel() } catch {
          state = "failed"
          messages = error.localizedDescription
        }
      }
      .onDisappear { cancel() }
  }
  private func cancel() {
    dismissRequested = true
    guard !identity.isEmpty, state == "running", !cancellationSent else { return }
    cancellationSent = true
    app.perform { _ = try await app.engine.call("connect.auth.cancel", ["id": identity]) }
  }
}

struct TerminalLoginView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var terminals: ProjectTerminals
  @DialogDismiss private var dismiss
  let arguments: [String]
  var environment: [String: String] = [:]
  var unsetEnvironment: [String] = []
  let complete: () -> Void
  @State private var identity = "sign-in-" + UUID().uuidString
  @State private var failure = ""
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Text("Sign in with your existing account").font(.title2.weight(.semibold))
        Spacer()
        nativeButton("dialog.done", action: { dismiss() }, title: "Close") { Text("Close") }
      }
      Text(arguments.joined(separator: " ")).font(.caption.monospaced()).textSelection(.enabled)
      Text(
        "Complete the vendor’s interactive sign-in here. Credentials remain in the vendor’s local store. Closing this window stops this sign-in process."
      ).font(.callout).foregroundStyle(.secondary)
      if let terminal = terminals.view(identity) { ProjectTerminalHost(terminal: terminal) }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
    }.padding(24).frame(width: 820, height: 550).background { BrandBackdrop() }
      .task {
        guard !arguments.isEmpty else { return }
        terminals.start(identity, path: string(app.project, "path"), arguments: arguments,
          environment: environment, unset: unsetEnvironment)
        while terminals.running.contains(identity) && !Task.isCancelled {
          try? await Task.sleep(for: .milliseconds(500))
        }
        if !Task.isCancelled {
          if terminals.exitCodes[identity] == 0 { complete() }
          else { failure = "Sign-in exited without success. Close this window and try again." }
        }
      }.onDisappear { terminals.stop(identity) }
  }
}
