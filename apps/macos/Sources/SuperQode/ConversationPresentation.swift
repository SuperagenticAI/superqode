import Foundation

/// One recent row per task lineage. Individual run records remain available to the engine.
func groupedRecentRuns(_ jobs: [[String: Any]]) -> [[String: Any]] {
  var seen = Set<String>()
  let recent = jobs.filter { $0["archived"] as? Bool != true }.sorted {
    let left = $0["updated"] as? Double ?? 0
    let right = $1["updated"] as? Double ?? 0
    return left == right ? string($0, "id") < string($1, "id") : left > right
  }.filter { row in
    let identity = string(row, "kind") == "task"
      ? string(row, "conversation_id", string(row, "id")) : string(row, "id")
    return seen.insert(identity).inserted
  }
  return recent.sorted {
    if ($0["pinned"] as? Bool == true) != ($1["pinned"] as? Bool == true) { return $0["pinned"] as? Bool == true }
    let left = $0["updated"] as? Double ?? 0
    let right = $1["updated"] as? Double ?? 0
    return left == right ? string($0, "id") < string($1, "id") : left > right
  }
}

/// Parse the supported runtime argument shapes without dropping command details.
private func activityObject(_ value: Any?) -> [String: Any] {
  if let object = value as? [String: Any] { return object }
  if let text = value as? String, text.utf8.count <= 64_000,
    let bytes = text.data(using: .utf8), let object = try? JSONSerialization.jsonObject(with: bytes) as? [String: Any] { return object }
  return [:]
}

private func activityText(_ value: Any?) -> String {
  if let text = value as? String { return text }
  if let parts = value as? [String] { return parts.joined(separator: " ") }
  return ""
}

/// Shared by the live card and the recorded activity list.
func agentToolAction(_ tool: [String: Any]) -> String {
  var inputs = [tool]
  for key in ["rawInput", "raw_input", "arguments", "args", "input"] {
    let object = activityObject(tool[key])
    if !object.isEmpty {
      inputs.insert(object, at: 0)
      for nested in ["parameters", "arguments", "input"] {
        let parameters = activityObject(object[nested])
        if !parameters.isEmpty { inputs.insert(parameters, at: 0) }
      }
    }
  }
  func value(_ keys: [String]) -> String {
    for input in inputs {
      for key in keys {
        let text = activityText(input[key])
        if !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty { return text }
      }
    }
    return ""
  }
  let command = value(["command", "cmd", "command_line", "shell_command", "script", "argv"])
  if !command.isEmpty { return command }
  let title = value(["title", "tool_name", "name"])
  var path = value(["path", "file_path", "filePath", "target_file", "notebook_path"])
  if path.isEmpty, let locations = tool["locations"] as? [[String: Any]] {
    path = locations.map { string($0, "path") }.filter { !$0.isEmpty }.joined(separator: ", ")
  }
  if path.isEmpty {
    let patch = value(["patch", "patch_text", "diff"])
    path = patch.components(separatedBy: .newlines).compactMap { line -> String? in
      for prefix in ["*** Update File: ", "*** Add File: ", "*** Delete File: "] where line.hasPrefix(prefix) { return String(line.dropFirst(prefix.count)) }
      return nil
    }.joined(separator: ", ")
  }
  if !path.isEmpty { return (title.isEmpty ? "File" : title) + " · " + path }
  let query = value(["query", "pattern", "url"])
  if !query.isEmpty { return title.isEmpty ? query : title + " · " + query }
  return title
}

/// Keep one pending action, including sparse updates, and label finished work accurately.
func currentAgentActivity(_ events: [[String: Any]]) -> String {
  var pending: [String: [String: Any]] = [:]
  var order: [String: Int] = [:]
  var fallback = ""
  let terminal = ["completed", "failed", "cancelled", "canceled", "error", "done", "success", "succeeded", "interrupted"]
  let starts = ["tool_call", "tool_start", "tool.requested", "tool.started", "tool.start", "tool_execution_start"]
  let updates = ["tool_update", "tool_call_update", "tool.updated", "tool.update", "tool_execution_update"]
  let ends = ["tool_result", "tool_end", "tool.completed", "tool.result", "tool.end", "tool_execution_end"]
  for (index, event) in events.enumerated() {
    let data = event["data"] as? [String: Any] ?? [:]
    let name = string(data, "event", string(event, "type"))
    if ["thinking", "reasoning", "model.thinking", "model.reasoning"].contains(name) { fallback = "" }
    if ["delta", "model_delta", "message.delta", "answer"].contains(name) { fallback = "" }
    guard (starts + updates + ends).contains(name) else { continue }
    let payload = data["payload"] as? [String: Any] ?? data
    let id = string(payload, "toolCallId", string(payload, "tool_call_id", string(payload, "call_id", string(payload, "id", string(payload, "tool_name", "anonymous")))))
    let status = string(payload, "status").lowercased()
    var merged = pending[id] ?? [:]
    for (key, value) in payload where !(value is NSNull) {
      if let value = value as? String, value.isEmpty { continue }
      if let value = value as? [String: Any] {
        if value.isEmpty { continue }
        var nested = activityObject(merged[key])
        for (name, entry) in value where !(entry is NSNull) { nested[name] = entry }
        merged[key] = nested
      } else { merged[key] = value }
    }
    // Some canonical adapters call every sparse update tool.completed.
    let finished = terminal.contains(status) || (ends.contains(name) && (name != "tool.completed" || status.isEmpty))
    if finished {
      pending.removeValue(forKey: id); order.removeValue(forKey: id)
      let action = agentToolAction(merged)
      let failed = ["failed", "error"].contains(status) || payload["success"] as? Bool == false
      if !action.isEmpty { fallback = (failed ? "Failed · " : ["cancelled", "canceled", "interrupted"].contains(status) ? "Stopped · " : "Finished · ") + action }
    } else {
      pending[id] = merged
      if order[id] == nil { order[id] = index }
    }
  }
  guard let id = order.max(by: { $0.value < $1.value })?.key, let tool = pending[id] else { return fallback }
  let action = agentToolAction(tool)
  return action
}
