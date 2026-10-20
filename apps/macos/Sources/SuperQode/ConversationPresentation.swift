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

/// Project only one genuinely pending tool. Handle ACP sparse updates and harness events.
func currentAgentActivity(_ events: [[String: Any]]) -> String {
  var pending: [String: [String: Any]] = [:]
  var order: [String: Int] = [:]
  var fallback = ""
  func text(_ value: Any?) -> String {
    if let value = value as? String { return value }
    if let value = value as? [String] { return value.joined(separator: " ") }
    return ""
  }
  for (index, event) in events.enumerated() {
    let data = event["data"] as? [String: Any] ?? [:]
    let name = string(data, "event", string(event, "type"))
    if ["thinking", "reasoning"].contains(name) { fallback = "Thinking through the next step…" }
    if ["delta", "model_delta", "message.delta", "answer"].contains(name) { fallback = "Writing the response…" }
    guard ["tool_call", "tool_start", "tool_update", "tool_call_update", "tool_result", "tool_end"].contains(name) else { continue }
    let payload = data["payload"] as? [String: Any] ?? data
    let id = string(payload, "toolCallId", string(payload, "tool_call_id", string(payload, "id", "anonymous")))
    let status = string(payload, "status").lowercased()
    if ["tool_result", "tool_end"].contains(name)
      || ["completed", "failed", "cancelled", "canceled", "error", "done", "success", "succeeded", "interrupted"].contains(status) {
      pending.removeValue(forKey: id)
      order.removeValue(forKey: id)
      fallback = ""
    } else {
      var merged = pending[id] ?? [:]
      for (key, value) in payload where !(value is NSNull) {
        if let value = value as? String, value.isEmpty { continue }
        if let value = value as? [String: Any], value.isEmpty { continue }
        merged[key] = value
      }
      pending[id] = merged
      if order[id] == nil { order[id] = index }
    }
  }
  guard let id = order.max(by: { $0.value < $1.value })?.key, let tool = pending[id] else { return fallback }
  let input = tool["rawInput"] as? [String: Any] ?? tool["arguments"] as? [String: Any] ?? tool["input"] as? [String: Any] ?? [:]
  let command = text(input["command"]).isEmpty ? text(tool["command"]) : text(input["command"])
  let path = text(input["path"]).isEmpty ? text(input["file_path"]) : text(input["path"])
  let title = string(tool, "title", string(tool, "tool_name", string(tool, "name", "Running tool")))
  let label = !command.isEmpty ? command : path.isEmpty ? title : title + " · " + path
  return String(label.replacingOccurrences(of: "\n", with: " ").replacingOccurrences(of: "\r", with: " ").prefix(300))
}
