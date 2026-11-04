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
  @State private var attempt = 0
  @State private var browserIssue = ""
  private var subscription: Bool { string(request, "action") == "subscription" }
  private var codex: Bool { subscription && string(request, "vendor") == "codex" }
  private var loginURL: URL? {
    guard let detector = try? NSDataDetector(types: NSTextCheckingResult.CheckingType.link.rawValue) else { return nil }
    let range = NSRange(messages.startIndex..., in: messages)
    return detector.matches(in: messages, range: range).compactMap(\.url).first { $0.scheme == "https" }
  }
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
      ScrollView {
        VStack(alignment: .leading, spacing: 14) {
          if state == "running" { ProgressView("Waiting for the agent…") }
          if subscription {
            Text("Complete sign-in in your browser using the address and device code below. If no browser opens, open the sign-in page yourself." + (codex ? " Codex SDK uses the installed Codex CLI’s account login." : ""))
              .font(.callout).foregroundStyle(.secondary)
            if let url = loginURL {
              Button("Open sign-in page") {
                if !NSWorkspace.shared.open(url) { browserIssue = "The browser could not open. Copy the address from the output below and open it manually." }
              }
            }
            if !browserIssue.isEmpty { Text(browserIssue).font(.caption).foregroundStyle(.orange) }
          }
          CodeBlock(text: messages).frame(minHeight: 130, maxHeight: 230)
          if state == "failed" || state == "cancelled" {
            Text(subscription
              ? "Sign-in did not finish. Check the agent output above for an expired code, network error or missing CLI. Try again for a new code." + (codex ? " You can also run codex login --device-auth in Terminal, then return and check the connection." : "")
              : "Setup did not finish. Review the output and try again.")
              .font(.callout).foregroundStyle(.orange)
          }
        }.frame(maxWidth: .infinity, alignment: .leading)
      }
      HStack {
        nativeButton("dialog.cancel", action: {
          cancel()
          dismiss()
        }, title: state == "running" ? "Cancel operation" : "Close") {
          Text(state == "running" ? "Cancel operation" : "Close")
        }
        Spacer()
        if state == "failed" || state == "cancelled" {
          Button("Try again") { state = "running"; attempt += 1 }.buttonStyle(BrandButtonStyle())
        }
      }
    }.padding(28).frame(width: 700, height: 620).background { BrandBackdrop() }
      .task(id: attempt) {
        identity = ""; state = "running"; messages = "Starting agent setup…"
        browserIssue = ""; dismissRequested = false; cancellationSent = false
        do {
          let response =
            try await app.engine.call("connect.auth.start", request) as? [String: Any] ?? [:]
          identity = string(response, "id")
          guard !identity.isEmpty else { throw EngineError(message: "The agent did not return a sign-in operation. Check the engine connection and try again.") }
          if dismissRequested || Task.isCancelled { cancel(); return }
          while !Task.isCancelled && !dismissRequested {
            let result =
              try await app.engine.call("connect.auth.poll", ["id": identity]) as? [String: Any]
              ?? [:]
            if dismissRequested || Task.isCancelled { cancel(); return }
            state = string(result, "state", "failed")
            let output = (result["messages"] as? [String] ?? []).joined(separator: "\n")
            if !output.isEmpty { messages = output }
            if state == "completed" {
              complete(result["result"] as? [String: Any] ?? [:])
              return
            }
            if state != "running" { return }
            try await Task.sleep(for: .milliseconds(500))
          }
          cancel()
        } catch is CancellationError { cancel() } catch {
          cancel()
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
        guard !arguments.isEmpty else {
          failure = "The agent did not provide a sign-in command. Close this window, refresh connections and try again."
          return
        }
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
