import SwiftUI

struct TaskCompletionView: View {
  @EnvironmentObject var app: Workspace
  @State private var summary: [String: Any] = [:]
  @State private var failure = ""
  private var checks: [[String: Any]] { summary["checks"] as? [[String: Any]] ?? [] }
  private var checkRevision: String {
    app.projectJobs.filter { string($0, "kind") == "check" }.map { string($0, "id") + ":" + string($0, "status") }.joined(separator: ",")
  }
  private var changes: [[String: Any]] { summary["changes"] as? [[String: Any]] ?? [] }
  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Label(string(app.detail, "status") == "completed" ? "Agent run finished" : "Agent run " + string(app.detail, "status"),
          systemImage: string(app.detail, "status") == "completed" ? "checkmark.circle" : "exclamationmark.circle")
          .font(.system(size: 13, weight: .semibold))
        Spacer()
        Button("Review changes & checks") { app.showReview = true }
      }
      if !failure.isEmpty {
        Text("Summary unavailable: " + failure).font(.caption).foregroundStyle(.secondary)
      } else if summary.isEmpty {
        Text("Loading recorded evidence…").font(.caption).foregroundStyle(.secondary)
      } else {
        Text(summary["changes_recorded"] as? Bool == true
          ? "\(changes.count) file\(changes.count == 1 ? "" : "s") changed in this task’s checkpoint."
          : "No sealed task checkpoint is available. Review project changes before accepting the result.")
          .font(.caption).foregroundStyle(.secondary)
        if checks.isEmpty {
          Label("No independent project checks recorded since this task started.", systemImage: "circle.dashed")
            .font(.caption).foregroundStyle(.secondary)
        } else {
          DisclosureGroup("Project checks since task start · \(checks.count)") {
            ForEach(checks, id: \.projectRowID) { check in
              let result = check["result"] as? [String: Any] ?? [:]
              let passed = string(check, "status") == "completed" && result["exit_code"] as? Int == 0
              HStack {
                Image(systemName: passed ? "checkmark.circle" : "exclamationmark.circle").foregroundStyle(passed ? .green : .orange)
                Text(string(result, "command", string(check, "title"))).font(.caption.monospaced()).lineLimit(2)
                Spacer()
                Button("Open") { app.selectJob(string(check, "id")) }
              }
            }
          }.font(.caption)
        }
        HStack {
          Text("Agent completion does not establish that tests pass.").font(.caption).foregroundStyle(.secondary)
          Spacer()
          Button("Evaluate harness") { app.section = "Evaluations" }.font(.caption)
        }
      }
    }.padding(14).frame(maxWidth: .infinity, alignment: .leading).outlinedSurface(radius: 10)
      .task(id: "\(app.selectedJob):\(string(app.detail, "status")):\(checkRevision)") {
        summary = [:]; failure = ""
        do {
          let value = try await app.engine.call("jobs.summary", ["id": app.selectedJob]) as? [String: Any] ?? [:]
          if !Task.isCancelled { summary = value }
        } catch { if !Task.isCancelled { failure = error.localizedDescription } }
      }
  }
}

struct ConnectionHealthView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  private var route: [String: Any] { app.harnesses.first { string($0, "id") == app.harness } ?? [:] }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack {
        Label("Connection health", systemImage: "stethoscope").font(.title2.weight(.semibold))
        Spacer()
        nativeButton("health.done", action: { dismiss() }, title: "Close connection health") { Text("Done") }
      }
      Text(app.connectionDisconnected ? "Choose an agent or model to start coding." : string(route, "name", app.harness))
        .font(.headline)
      Grid(alignment: .leading, horizontalSpacing: 24, verticalSpacing: 14) {
        diagnostic("Local engine", app.connected ? "Running on your Mac" : "Unavailable")
        diagnostic("Execution route", app.connectionDisconnected ? "Disconnected" : app.isACP ? "ACP agent" : app.isRemote ? "Remote agent" : app.isManaged ? "Installed coding agent" : "Bundled harness with your model")
        diagnostic("Runtime", app.connectionDisconnected ? "Not selected" : !app.isManaged ? "Included with SuperQode" : route["available"] as? Bool == true ? "Available" : "Not confirmed; refresh detection")
        diagnostic("Connection", app.checkingConnection ? "Checking…" : string(app.routeStatus, "state", "Not checked"))
        diagnostic("Model", app.isManaged ? (app.agentModel.isEmpty ? "Agent default" : app.agentModel) : (app.model.isEmpty ? "Not selected" : app.model))
        if app.isACP { diagnostic("Advertised models", "\(app.agentModels.count)") }
        diagnostic("Authentication", app.isManaged ? "Managed by the selected agent" : "Provider credential or local model")
      }.font(.system(size: 13))
      Text(privateConnectionMessage(string(app.routeStatus, "message", "Choose Refresh status to check this connection.")))
        .font(.callout).textSelection(.enabled)
      if !string(route, "issue").isEmpty { Text(string(route, "issue")).font(.callout).foregroundStyle(.orange) }
      if app.checkingConnection { ProgressView().controlSize(.small) }
      HStack {
        Button("Refresh status") {
          app.perform {
            try await app.refreshDefinitions()
            if app.isManaged { await app.checkManagedConnection() } else { await app.checkRoute() }
          }
        }.disabled(app.checkingConnection || app.projectActive || app.connectionDisconnected)
        Button("Connection setup…") { dismiss(); app.openConnectionAfterHealth() }.disabled(app.projectActive)
      }
      Text("Status checks inspect configuration and agent connectivity. They do not prove that a paid coding request will succeed. Account identities and credentials stay hidden here.")
        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }.padding(24).frame(width: 620).background(Color.qPanel)
  }
  private func diagnostic(_ title: String, _ value: String) -> some View {
    GridRow { Text(title).foregroundStyle(.secondary); Text(value).textSelection(.enabled) }
  }
}

func privateConnectionMessage(_ message: String) -> String {
  message.replacingOccurrences(of: #"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}"#, with: "[hidden account]", options: [.regularExpression, .caseInsensitive])
}
