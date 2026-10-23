import Foundation

/// One recent row per task lineage. Individual run records remain available to the engine.
func groupedRecentRuns(_ jobs: [[String: Any]]) -> [[String: Any]] {
  var seen = Set<String>()
  return jobs.sorted {
    ($0["updated"] as? Double ?? 0) > ($1["updated"] as? Double ?? 0)
  }.filter { row in
    let identity = string(row, "kind") == "task"
      ? string(row, "conversation_id", string(row, "id")) : string(row, "id")
    return seen.insert(identity).inserted
  }
}

/// Presentation is derived from reported events; elapsed time is never a completion estimate.
struct AgentProgress {
  var title = "Waiting for the agent"
  var detail = "Request sent. Waiting for the first activity update."
  var symbol = "antenna.radiowaves.left.and.right"
  var currentTool = ""
  var completedTools = 0
  var failedTools = 0
  var planCompleted = 0
  var planTotal = 0
  var planStep = ""
  var lastUpdate: Date?
}

func agentActivityLabel(_ tool: [String: Any]) -> String {
  func text(_ value: Any?) -> String {
    if let value = value as? String { return value }
    if let value = value as? [String] { return value.joined(separator: " ") }
    return ""
  }
  let input = tool["rawInput"] as? [String: Any] ?? tool["arguments"] as? [String: Any]
    ?? tool["args"] as? [String: Any] ?? tool["input"] as? [String: Any] ?? [:]
  let command = text(input["command"]).isEmpty ? text(tool["command"]) : text(input["command"])
  let path = text(input["path"]).isEmpty ? text(input["file_path"]) : text(input["path"])
  let title = string(tool, "title", string(tool, "tool_name", string(tool, "name", "Running tool")))
  let target = path.isEmpty ? text(input["query"]) : path
  let label = !command.isEmpty ? command : target.isEmpty ? title : title + " · " + target
  return String(label.replacingOccurrences(of: "\n", with: " ").replacingOccurrences(of: "\r", with: " ").prefix(300))
}

func agentProgress(_ events: [[String: Any]]) -> AgentProgress {
  var progress = AgentProgress()
  var pending: [String: [String: Any]] = [:]
  var order: [String: Int] = [:]
  var completed = Set<String>()
  var failed = Set<String>()
  for (index, event) in events.enumerated() {
    let data = event["data"] as? [String: Any] ?? [:]
    let rawName = string(data, "event", string(event, "type"))
    let name = ["tool.requested": "tool_call", "tool.completed": "tool_result",
      "model.thinking": "thinking"][rawName] ?? rawName
    let payload = data["payload"] as? [String: Any] ?? data
    if let time = event["received_at"] as? Double { progress.lastUpdate = Date(timeIntervalSince1970: time) }
    switch name {
    case "stage":
      progress.title = "Preparing the task"
      progress.detail = string(data, "message", "Starting the agent")
      progress.symbol = "gearshape.2"
    case "model_request", "model.requested", "acp_session":
      progress.title = "Waiting for the model"
      progress.detail = "The agent is connected. Waiting for its next update."
      progress.symbol = "antenna.radiowaves.left.and.right"
    case "remote_state", "a2a.update":
      let remote = payload["status"] as? [String: Any] ?? [:]
      let state = string(payload, "state", string(remote, "state"))
      if ["working", "submitted", "input-required", "input_required"].contains(state) {
        progress.title = state.hasPrefix("input") ? "Remote agent needs input" : "Remote agent is working"
        progress.detail = "Server reported: " + state.replacingOccurrences(of: "_", with: " ")
        progress.symbol = "network"
      }
    case "thinking", "reasoning":
      progress.title = "Reasoning"
      progress.detail = "The agent is working through the task."
      progress.symbol = "sparkles"
    case "delta", "model_delta", "message.delta", "answer":
      progress.title = "Writing the response"
      progress.detail = "New response text is arriving in the conversation."
      progress.symbol = "text.alignleft"
    case "plan", "plan_update":
      let steps = payload["entries"] as? [[String: Any]] ?? payload["todos"] as? [[String: Any]] ?? []
      progress.planTotal = steps.count
      progress.planCompleted = steps.filter { string($0, "status") == "completed" }.count
      let step = steps.first { ["in_progress", "inProgress"].contains(string($0, "status")) } ?? [:]
      progress.planStep = string(step, "content", string(step, "step"))
    default: break
    }
    guard ["tool_call", "tool_start", "tool_update", "tool_call_update", "tool_result", "tool_end"].contains(name) else { continue }
    let id = string(payload, "toolCallId", string(payload, "tool_call_id", string(payload, "id", string(payload, "tool_name", "anonymous"))))
    let status = string(payload, "status").lowercased()
    let finished = ["tool_result", "tool_end"].contains(name)
      || ["completed", "failed", "cancelled", "canceled", "error", "done", "success", "succeeded", "interrupted"].contains(status)
    if finished {
      let label = agentActivityLabel(pending[id] ?? payload)
      pending.removeValue(forKey: id)
      order.removeValue(forKey: id)
      completed.insert(id)
      let didFail = payload["success"] as? Bool == false || ["failed", "error"].contains(status)
      if didFail { failed.insert(id) }
      progress.title = didFail ? "Tool reported a failure" : "Waiting for the next agent update"
      progress.detail = (didFail ? "Failed: " : "Finished: ") + label
      progress.symbol = didFail ? "exclamationmark.triangle" : "checkmark.circle"
    } else {
      // Runtimes without tool IDs reuse the tool name; each new call is distinct.
      if name == "tool_call" || name == "tool_start" {
        if completed.remove(id) != nil { progress.completedTools += 1 }
        if failed.remove(id) != nil { progress.failedTools += 1 }
      }
      var merged = pending[id] ?? [:]
      for (key, value) in payload where !(value is NSNull) {
        if let value = value as? String, value.isEmpty { continue }
        if let value = value as? [String: Any], value.isEmpty { continue }
        merged[key] = value
      }
      pending[id] = merged
      order[id] = index
    }
  }
  progress.completedTools += completed.count
  progress.failedTools += failed.count
  if let id = order.max(by: { $0.value < $1.value })?.key, let tool = pending[id] {
    progress.title = "Running a tool"
    progress.detail = agentActivityLabel(tool)
    progress.currentTool = progress.detail
    progress.symbol = "terminal"
  }
  return progress
}

/// Compatibility for compact activity surfaces that only need the pending command.
func currentAgentActivity(_ events: [[String: Any]]) -> String {
  let progress = agentProgress(events)
  if !progress.currentTool.isEmpty { return progress.currentTool }
  if progress.title == "Reasoning" { return "Thinking through the next step…" }
  if progress.title == "Writing the response" { return "Writing the response…" }
  return ""
}

/// Skip tool logs, permissions and errors when positioning the completed answer.
func finalResponseIndex(_ messages: [[String: Any]]) -> Int? {
  messages.lastIndex { row in
    row["coalesced"] as? Bool == true || string(row, "type") == "answer"
  }
}
