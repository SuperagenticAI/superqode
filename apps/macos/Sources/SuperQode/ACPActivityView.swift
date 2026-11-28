import SwiftUI

/// ACP entities retain their session identity and explicit null patch semantics.
struct ACPActivitySnapshot {
  var children: [String: [String: Any]] = [:]
  var tools: [String: [String: Any]] = [:]
  var terminals: [String: [String: Any]] = [:]
  var messages: [String: String] = [:]
  var messageOrder: [String] = []
  var states: [String: [String: Any]] = [:]
  var terminalData: [String: Data] = [:]
  var rootSessionID = ""

  init(_ events: [[String: Any]]) {
    for event in events {
      let data = event["data"] as? [String: Any] ?? [:]
      if string(data, "event") == "acp_session", let payload = data["payload"] as? [String: Any] {
        rootSessionID = string(payload, "session_id")
      }
      guard string(data, "event") == "acp_update",
        let payload = data["payload"] as? [String: Any],
        let update = payload["update"] as? [String: Any] else { continue }
      let session = string(payload, "sessionId")
      let kind = string(update, "sessionUpdate")
      func patched(_ previous: [String: Any]?) -> [String: Any] {
        var value = previous ?? [:]
        for (key, item) in update {
          if item is NSNull { value.removeValue(forKey: key) }
          else { value[key] = item }
        }
        value["ownerSessionId"] = session
        return value
      }
      switch kind {
      case "subagent_update":
        let id = string(update, "sessionId")
        children[id] = patched(children[id])
        if let state = update["state"] as? [String: Any] { states[id] = state }
        else if update["state"] is NSNull { states[id] = ["state": "unknown"] }
      case "state_update": states[session] = patched(states[session])
      case "tool_call_update":
        let key = session + ":" + string(update, "toolCallId")
        tools[key] = patched(tools[key])
      case "terminal_update", "terminal_output_chunk":
        let key = session + ":" + string(update, "terminalId")
        var terminal = patched(terminals[key])
        let output = update["output"] as? [String: Any] ?? [:]
        let encoded = kind == "terminal_output_chunk" ? string(update, "data") : string(output, "data")
        if kind == "terminal_output_chunk" || update.keys.contains("output"), let decoded = Data(base64Encoded: encoded) {
          if kind == "terminal_output_chunk" { terminalData[key, default: Data()].append(decoded) }
          else { terminalData[key] = decoded }
          terminal["displayOutput"] = String(decoding: terminalData[key] ?? Data(), as: UTF8.self)
        }
        terminals[key] = terminal
      case "agent_message", "agent_message_chunk", "session_message", "session_message_chunk":
        let key = session + ":" + string(update, "messageId")
        if !messageOrder.contains(key) { messageOrder.append(key) }
        let content = update["content"] as? [[String: Any]] ?? (update["content"] as? [String: Any]).map { [$0] } ?? []
        let text = content.map { string($0, "text") }.joined()
        if kind.hasSuffix("_chunk") { messages[key, default: ""] += text }
        else if update.keys.contains("content") { messages[key] = text }
      default: break
      }
    }
  }
  var root: String { rootSessionID.isEmpty ? states.keys.sorted().first(where: { children[$0] == nil }) ?? "" : rootSessionID }
  var foreground: String { string(states[root] ?? [:], "state", "unknown") }
  var background: [[String: Any]]? { states[root]?["background"] as? [[String: Any]] }
  var summary: String {
    let response: String
    switch foreground {
    case "idle":
      let reason = string(states[root] ?? [:], "stopReason")
      response = reason == "error" ? "Response failed" : reason == "cancelled" ? "Response stopped" : "Response finished"
    case "running": response = "Response running"
    case "requires_action": response = "Waiting for your approval"
    default: response = "Activity unconfirmed"
    }
    guard let background else { return response + " · Background status unconfirmed" }
    if background.isEmpty { return response }
    return response + " · \(background.count) background \(background.count == 1 ? "task" : "tasks") running"
  }
}

struct ACPActivityView: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    let snapshot = ACPActivitySnapshot(app.events)
    let active = ["running", "needs_approval"].contains(string(app.detail, "status"))
    VStack(alignment: .leading, spacing: 10) {
      Text(active ? snapshot.summary : "Session closed").font(.callout.weight(.medium))
      if !active { Text("Last reported: " + snapshot.summary).font(.caption).foregroundStyle(.secondary) }
      ForEach(snapshot.children.keys.sorted(), id: \.self) { id in
        let child = snapshot.children[id] ?? [:]
        DisclosureGroup(string(child, "title", id)) {
          Text(string(snapshot.states[id] ?? [:], "state", "unknown")).font(.caption)
          ForEach(snapshot.messageOrder.filter { $0.hasPrefix(id + ":") }, id: \.self) { key in
            Text(snapshot.messages[key] ?? "").textSelection(.enabled)
          }
          if active, let caps = child["capabilities"] as? [String: Any], caps["cancel"] is [String: Any] {
            Button("Stop subagent") { app.acpControl("cancel", session: id) }
          }
        }
      }
      ForEach(snapshot.tools.keys.sorted(), id: \.self) { key in
        let tool = snapshot.tools[key] ?? [:]
        if ["pending", "in_progress", "paused"].contains(string(tool, "status")) {
          DisclosureGroup(string(tool, "title", "Background tool")) {
            Text(string(tool, "status", "unknown")).font(.caption)
            if let output = tool["rawOutput"] { Text(pretty(output)).textSelection(.enabled) }
            if active, let caps = tool["capabilities"] as? [String: Any], caps["cancel"] is [String: Any] {
              Button("Stop this tool") { app.acpControl("tool", session: string(tool, "ownerSessionId"), item: string(tool, "toolCallId")) }
            }
          }
        }
      }
      ForEach(snapshot.terminals.keys.sorted(), id: \.self) { key in
        let terminal = snapshot.terminals[key] ?? [:]
        DisclosureGroup(string(terminal, "command", "Agent terminal")) {
          Text(String(string(terminal, "displayOutput").suffix(100_000)))
            .font(.system(.caption, design: .monospaced)).textSelection(.enabled)
          if active, let caps = terminal["capabilities"] as? [String: Any], caps["cancel"] is [String: Any] {
            Button("Stop terminal") { app.acpControl("terminal", session: string(terminal, "ownerSessionId"), item: string(terminal, "terminalId")) }
          }
        }
      }
      if active, !snapshot.root.isEmpty {
        HStack {
          if ["running", "requires_action"].contains(snapshot.foreground) {
            Button("Stop response") { app.acpControl("cancel", session: snapshot.root) }
              .help("Stops the foreground response and leaves independent background tasks running.")
          }
          Button("Close agent session") { app.acpControl("close", session: snapshot.root) }
            .help("Stops this session's response, background tools and child agents.")
        }
        if snapshot.foreground == "idle" {
          Text(snapshot.background?.isEmpty == true ? "Finalizing this turn…"
            : "Close this session or stop its remaining tasks before starting another turn in this project.")
            .font(.caption).foregroundStyle(.secondary)
        }
      }
    }.font(.callout).padding(10)
  }
}
