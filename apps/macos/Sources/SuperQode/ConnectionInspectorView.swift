import SwiftUI

struct ConnectionEvidence: Identifiable {
  let id: String
  let title: String
  let state: String
  let explanation: String
}

func acpConnectionEvidence(metadata: [String: Any], session: [String: Any], digest: String) -> [ConnectionEvidence] {
  let savedDigest = string(metadata, "route_digest")
  let current = savedDigest.isEmpty || digest.isEmpty || savedDigest == digest
  let failure = string(metadata, "last_check_error")
  let verified = current && failure.isEmpty && metadata["connected"] as? Bool == true
  let advertised = current && failure.isEmpty && !session.isEmpty
  let capabilities = advertised ? session["capabilities"] as? [String: Any] ?? [:] : [:]
  let prompts = capabilities["promptCapabilities"] as? [String: Any] ?? [:]
  func capability(_ id: String, _ title: String, _ value: Any?, _ explanation: String) -> ConnectionEvidence {
    ConnectionEvidence(id: id, title: title,
      state: !advertised ? "Not checked" : value as? Bool == true ? "Advertised" : "Not advertised",
      explanation: explanation)
  }
  let models = (session["models"] as? [String: Any])?["availableModels"] as? [[String: Any]] ?? []
  let modes = (session["modes"] as? [String: Any])?["availableModes"] as? [[String: Any]] ?? []
  return [
    ConnectionEvidence(id: "startup", title: "Agent startup and session", state: !failure.isEmpty ? "Failed last check" : verified ? "Verified" : "Not checked",
      explanation: !failure.isEmpty ? failure : current ? "A connection check initializes the agent and creates a session without sending a coding prompt." : "The launch configuration changed. Run a new connection check."),
    capability("resume", "Native session resume", capabilities["loadSession"], "Advertised support allows an exact session resume to be attempted. A failed resume remains an error."),
    capability("images", "Image context", prompts["image"], "Only agents advertising image support can receive image attachments."),
    capability("models", "Agent model catalog", !models.isEmpty, "Models listed: \(models.count). Availability and billing remain owned by the agent."),
    capability("modes", "Agent modes", !modes.isEmpty, "Modes listed: \(modes.count). Changes apply to the next message."),
    capability("configuration", "Session configuration", !(session["config_options"] as? [[String: Any]] ?? []).isEmpty, "Only settings returned by this agent are shown in connection options."),
    ConnectionEvidence(id: "coding", title: "Coding and tool execution", state: "Not tested by this check",
      explanation: "Startup checks do not run a task, test permission handling, or establish provider billing entitlement."),
  ]
}

struct ConnectionInspectorView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  private var route: [String: Any] { app.harnesses.first { string($0, "id") == app.harness } ?? [:] }
  private var metadata: [String: Any] { app.connectionMetadata[app.harness] ?? [:] }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack {
        VStack(alignment: .leading, spacing: 5) {
          Text("Connection details").font(.title2)
          Text(string(route, "name", app.harness)).font(.headline).foregroundStyle(.secondary)
        }
        Spacer()
        nativeButton("dialog.done", action: { dismiss() }, title: "Done") { Text("Done") }
      }
      HStack {
        Label(app.isACP ? "Agent Client Protocol" : "Agent-managed connection", systemImage: "link")
        Spacer()
        if app.checkingConnection {
          ProgressView().controlSize(.small)
          nativeButton("connection.check.cancel", action: { app.cancelConnectionCheck() }, title: "Cancel connection check") { Text("Cancel check") }
        } else {
          nativeButton("connection.check", action: { app.perform { await app.checkManagedConnection() } }, title: "Check connection") { Text("Check connection") }
            .disabled(app.active || app.busy || app.openingProject)
        }
      }
      Text(string(app.routeStatus, "message", "Check the agent before starting your task."))
        .font(.callout).foregroundStyle(.secondary).textSelection(.enabled)
      if let timestamp = metadata["checked_at"] as? Double {
        Text("Last successful startup check: " + Date(timeIntervalSince1970: timestamp).formatted(date: .abbreviated, time: .shortened))
          .font(.caption).foregroundStyle(.secondary)
      }
      ScrollView {
        VStack(alignment: .leading, spacing: 12) {
          if app.isACP {
            let initialization = metadata["initialization"] as? [String: Any] ?? [:]
            let agent = initialization["agent"] as? [String: Any] ?? [:]
            if let version = initialization["protocol_version"] as? Int {
              Text("Protocol v\(version) · " + [string(agent, "title", string(agent, "name")), string(agent, "version")].filter { !$0.isEmpty }.joined(separator: " "))
                .font(.caption.monospaced()).textSelection(.enabled)
            }
            ForEach(acpConnectionEvidence(metadata: metadata, session: app.agentSession, digest: string(route, "digest"))) { item in
              VStack(alignment: .leading, spacing: 6) {
                HStack {
                  Text(item.title).font(.headline)
                  Spacer()
                  Text(item.state).font(.caption).foregroundStyle(item.state == "Verified" ? Color.green : Color.secondary)
                }
                Text(item.explanation).font(.callout).foregroundStyle(.secondary)
              }.padding(14).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
            }
          } else {
            Text("This agent owns its models, tools and session behavior. The check result above describes the evidence available for this route.")
              .foregroundStyle(.secondary)
          }
          if !string(route, "command").isEmpty {
            Text("Agent launch command").font(.headline)
            Text(string(route, "command")).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
          }
        }
      }
      Text("Startup checks send no coding prompt. Sign-in and model access remain owned by the agent.")
        .font(.caption).foregroundStyle(.secondary)
    }.padding(24).frame(width: 720, height: 650).background(Color.qPanel)
  }
}
