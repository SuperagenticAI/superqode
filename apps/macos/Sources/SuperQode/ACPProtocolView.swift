import SwiftUI

enum ACPProtocolPolicy: String, CaseIterable, Identifiable {
  case automatic = "auto", v1, v2
  var id: String { rawValue }
  var requestedVersion: Int { self == .v1 ? 1 : 2 }
  var title: String {
    switch self {
    case .automatic: return "Auto · Prefer v2"
    case .v1: return "ACP v1 · Compatibility"
    case .v2: return "ACP v2 · Preview (required)"
    }
  }
  var explanation: String {
    switch self {
    case .automatic: return "Requests v2 and permits one v1 fallback during protocol negotiation. A submitted task is never resent through another version."
    case .v1: return "Requests v1 for this agent in this project."
    case .v2: return "Requires v2. Connection checks report unsupported agents without falling back."
    }
  }
  static func recorded(in options: [String: Any]) -> Self {
    if let policy = Self(rawValue: string(options, "protocol_policy")) { return policy }
    return (options["protocol_version"] as? Int ?? 1) == 1 ? .v1 : .automatic
  }
}

struct ACPProtocolStatus {
  let requested: Int?
  let negotiated: Int?
  let policy: ACPProtocolPolicy?
  let fallback: Bool
  let reason: String
  let resumed: Bool
  let agent: String
  let version: String
  let context: String

  init(_ payload: [String: Any], context: String = "Connection check") {
    let info = payload["initialization"] as? [String: Any] ?? payload
    requested = info["requested_protocol_version"] as? Int
    let actual = info["negotiated_protocol_version"] as? Int ?? info["protocol_version"] as? Int
    negotiated = [1, 2].contains(actual ?? 0) ? actual : nil
    policy = ACPProtocolPolicy(rawValue: string(info, "protocol_policy"))
    fallback = info["fallback"] as? Bool == true && actual == 1
    reason = string(info, "fallback_reason")
    resumed = info["resumed_protocol"] as? Int != nil
    let identity = info["agent"] as? [String: Any] ?? [:]
    agent = string(identity, "title", string(identity, "name"))
    version = string(identity, "version")
    self.context = context
  }
  var label: String {
    if negotiated == 2 { return "ACP v2 · Preview" }
    if negotiated == 1 {
      if fallback { return "ACP v1 · Fallback" }
      return resumed ? "ACP v1 · Resumed" : "ACP v1 · Compatibility"
    }
    return "ACP · Not checked"
  }
}

extension Workspace {
  func acpPolicy(for reference: String, project selectedProject: String? = nil) -> ACPProtocolPolicy {
    let project = selectedProject ?? projectID
    let key = project + "\n" + reference
    if let cached = acpProtocolChoices[key] {
      return ACPProtocolPolicy(rawValue: cached) ?? .automatic
    }
    let stored = preferences.dictionary(forKey: "nativeACPProtocols:" + project) ?? [:]
    let raw = stored[reference] as? String ?? "auto"
    return ACPProtocolPolicy(rawValue: raw) ?? .automatic
  }

  func setACPPolicy(_ policy: ACPProtocolPolicy, for reference: String, project selectedProject: String? = nil) {
    let project = selectedProject ?? projectID
    guard !reference.isEmpty, project == projectID else { return }
    guard !active, !hasActiveWork(project: project), !busy else {
      notice = "Finish or close the active agent session before changing its protocol."
      return
    }
    guard policy != acpPolicy(for: reference, project: project) else { return }
    acpProtocolChoices[project + "\n" + reference] = policy.rawValue
    var stored = preferences.dictionary(forKey: "nativeACPProtocols:" + project) ?? [:]
    stored[reference] = policy.rawValue
    preferences.set(stored, forKey: "nativeACPProtocols:" + project)
    var metadata = connectionMetadata[reference] ?? [:]
    metadata["connected"] = false
    metadata["last_check_error"] = "Protocol selection changed. Check this connection again."
    connectionMetadata[reference] = metadata
    if reference == harness {
      cancelConnectionCheck()
      routeStatus = ["state": "check-required", "message": "Check the selected ACP protocol before the next session."]
    }
    notice = "Protocol saved for this agent and project. It applies to the next agent session; the conversation remains visible."
  }

  var acpProtocolStatus: ACPProtocolStatus {
    let request = detail["request"] as? [String: Any] ?? [:]
    if string(request, "harness") == harness {
      if let event = events.last(where: {
        string($0["data"] as? [String: Any] ?? [:], "event") == "acp_session"
      }), let payload = (event["data"] as? [String: Any])?["payload"] as? [String: Any] {
        return ACPProtocolStatus(payload, context: active ? "Current session" : "Recorded session")
      }
      let result = detail["result"] as? [String: Any] ?? [:]
      if let status = result["protocol_status"] as? [String: Any] {
        return ACPProtocolStatus(status, context: "Recorded session")
      }
      if active { return ACPProtocolStatus([:], context: "Connecting") }
    }
    let metadata = connectionMetadata[harness] ?? [:]
    let route = harnesses.first { string($0, "id") == harness } ?? [:]
    if verifiedACPConnection(route: route, metadata: metadata, policy: acpProtocolPolicy, project: projectID) {
      return ACPProtocolStatus(metadata["initialization"] as? [String: Any] ?? [:])
    }
    return ACPProtocolStatus([:])
  }

  var acpProtocolWillSwitch: Bool {
    let request = detail["request"] as? [String: Any] ?? [:]
    guard !selectedJob.isEmpty, string(request, "harness") == harness else { return false }
    let recorded = ACPProtocolPolicy.recorded(in: request["acp_options"] as? [String: Any] ?? [:])
    if recorded != acpProtocolPolicy { return true }
    if acpProtocolPolicy != .automatic, let version = acpProtocolStatus.negotiated {
      return version != acpProtocolPolicy.requestedVersion
    }
    return false
  }
  var acpForegroundIdle: Bool {
    active && acpProtocolStatus.negotiated == 2 && ACPActivitySnapshot(events).foreground == "idle"
  }
  var acpBackgroundPending: Bool {
    guard acpForegroundIdle else { return false }
    return ACPActivitySnapshot(events).background?.isEmpty != true
  }
}

struct ACPProtocolFallbackNotice: View {
  @EnvironmentObject var app: Workspace
  @State private var dismissed = false
  var body: some View {
    let status = app.acpProtocolStatus
    if status.fallback && !dismissed {
      HStack(alignment: .top, spacing: 8) {
        Image(systemName: "arrow.turn.down.right").foregroundStyle(.orange)
        VStack(alignment: .leading, spacing: 4) {
          Text("Using ACP v1 for this session").font(.caption.weight(.medium))
          Text(status.reason).font(.caption).foregroundStyle(.secondary)
          Button("Use v1 for future sessions") { app.acpProtocolPolicy = .v1 }
          .font(.caption).disabled(app.active || app.hasActiveWork(project: app.projectID) || app.busy)
        }
        Spacer()
        Button { dismissed = true } label: { Image(systemName: "xmark") }
          .buttonStyle(.plain).help("Dismiss fallback notice")
      }.padding(8).background(Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 6))
    }
  }
}

struct ACPProtocolPicker: View {
  @EnvironmentObject var app: Workspace
  let reference: String
  let project: String
  var body: some View {
    let policy = app.acpPolicy(for: reference, project: project)
    VStack(alignment: .leading, spacing: 5) {
      Picker("ACP protocol", selection: Binding(
        get: { app.acpPolicy(for: reference, project: project) },
        set: { app.setACPPolicy($0, for: reference, project: project) })) {
          ForEach(ACPProtocolPolicy.allCases) { Text($0.title).tag($0) }
        }.disabled(app.active || app.hasActiveWork(project: project) || app.busy)
      Text(policy.explanation).font(.caption).foregroundStyle(.secondary)
      Text("Saved for this agent and project. Changes start a new agent session; visible conversation context can be handed over.")
        .font(.caption).foregroundStyle(.secondary)
    }
  }
}

struct ACPProtocolMenu: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    Menu {
      ForEach(ACPProtocolPolicy.allCases) { policy in
        Button { app.acpProtocolPolicy = policy } label: {
          if app.acpProtocolPolicy == policy { Label(policy.title, systemImage: "checkmark") }
          else { Text(policy.title) }
        }
      }
      Divider()
      Text("Applies to the next agent session")
    } label: {
      Label(app.acpProtocolPolicy.title, systemImage: "arrow.triangle.branch")
    }.menuStyle(.borderlessButton).fixedSize()
      .disabled(app.active || app.hasActiveWork(project: app.projectID) || app.busy)
      .help(app.acpProtocolPolicy.explanation)
  }
}

struct ACPProtocolStatusView: View {
  let status: ACPProtocolStatus
  @State private var details = false
  var body: some View {
    Button { details.toggle() } label: {
      Label(status.label, systemImage: status.fallback ? "arrow.turn.down.right" : "network")
        .font(.caption).foregroundStyle(status.fallback ? Color.orange : Color.secondary)
    }.buttonStyle(.borderless)
      .accessibilityLabel(status.context + ": " + status.label)
      .popover(isPresented: $details) {
        VStack(alignment: .leading, spacing: 10) {
          Text(status.label).font(.headline)
          Text(status.context).font(.caption).foregroundStyle(.secondary)
          LabeledContent("Policy", value: status.policy?.title ?? "Not recorded")
          LabeledContent("Requested", value: status.requested.map { "ACP v\($0)" } ?? "Not recorded")
          LabeledContent("Negotiated", value: status.negotiated.map { "ACP v\($0)" } ?? "Not checked")
          if !status.agent.isEmpty { LabeledContent("Agent", value: status.agent) }
          if !status.version.isEmpty { LabeledContent("Adapter version", value: status.version) }
          if status.fallback { Text(status.reason).font(.callout).foregroundStyle(.orange) }
          if status.resumed { Text("Resumed using the original session's protocol.").font(.caption) }
          Text("The negotiated version stays fixed for this connection.")
            .font(.caption).foregroundStyle(.secondary)
        }.padding(18).frame(width: 380).textSelection(.enabled)
      }
  }
}
