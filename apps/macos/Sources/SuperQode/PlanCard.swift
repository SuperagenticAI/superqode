import SwiftUI

/// One step of an agent's plan or todo list.
struct PlanItem: Identifiable, Equatable {
  let id: String
  let content: String
  /// pending, in_progress, completed or cancelled
  let status: String
}

enum PlanSnapshot {
  /// Latest plan reported in a run: ACP plan updates or a todo tool call.
  /// Returns an empty list when the agent reported no plan.
  static func latest(_ events: [[String: Any]]) -> [PlanItem] {
    for event in events.reversed() where string(event, "type") == "harness_event" {
      let data = event["data"] as? [String: Any] ?? [:]
      let payload = data["payload"] as? [String: Any] ?? [:]
      if string(data, "event") == "plan", let entries = payload["entries"] as? [[String: Any]] {
        let items = parse(entries)
        if !items.isEmpty { return items }
      }
      if let todos = todoArgument(payload) {
        let items = parse(todos)
        if !items.isEmpty { return items }
      }
    }
    return []
  }

  private static func todoArgument(_ payload: [String: Any]) -> [[String: Any]]? {
    let name = (string(payload, "tool_name", string(payload, "name", string(payload, "title")))).lowercased()
    guard name.contains("todo") else { return nil }
    for key in ["rawInput", "raw_input", "arguments", "args", "input"] {
      if let input = payload[key] as? [String: Any], let todos = input["todos"] as? [[String: Any]] { return todos }
    }
    return payload["todos"] as? [[String: Any]]
  }

  private static func parse(_ entries: [[String: Any]]) -> [PlanItem] {
    entries.enumerated().compactMap { index, entry in
      let text = string(entry, "content", string(entry, "title", string(entry, "text")))
        .split(whereSeparator: \.isWhitespace).joined(separator: " ")
      guard !text.isEmpty else { return nil }
      return PlanItem(id: string(entry, "id", String(index + 1)), content: text, status: normalize(string(entry, "status")))
    }
  }

  static func normalize(_ raw: String) -> String {
    let value = raw.lowercased().replacingOccurrences(of: "-", with: "_").replacingOccurrences(of: " ", with: "_")
    if ["completed", "complete", "done", "finished"].contains(value) { return "completed" }
    if ["in_progress", "inprogress", "running", "active", "started"].contains(value) { return "in_progress" }
    if ["cancelled", "canceled", "skipped", "failed"].contains(value) { return "cancelled" }
    return "pending"
  }

  static func progress(_ items: [PlanItem]) -> String {
    let done = items.filter { $0.status == "completed" }.count
    return "\(done) of \(items.count) done"
  }

  /// Compact line for the working card: progress and the current step.
  static func compactLine(_ items: [PlanItem]) -> String {
    guard !items.isEmpty else { return "" }
    let current = items.first { $0.status == "in_progress" } ?? items.first { $0.status == "pending" }
    return "Plan " + progress(items) + (current.map { " · " + $0.content } ?? "")
  }
}

/// Live checklist of the agent's plan, collapsed to "N of M done".
struct PlanCard: View {
  let items: [PlanItem]
  @State private var expanded = false
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Button { withAnimation(.easeInOut(duration: 0.15)) { expanded.toggle() } } label: {
        HStack(spacing: 8) {
          Image(systemName: "checklist").foregroundStyle(.secondary)
          Text("Plan").font(.caption.weight(.semibold))
          Text(PlanSnapshot.progress(items)).font(.caption).foregroundStyle(.secondary)
          ProgressView(value: Double(items.filter { $0.status == "completed" }.count), total: Double(max(items.count, 1)))
            .progressViewStyle(.linear).frame(maxWidth: 120)
          Spacer(minLength: 0)
          Image(systemName: expanded ? "chevron.up" : "chevron.down").font(.caption2).foregroundStyle(.secondary)
        }.contentShape(Rectangle())
      }.buttonStyle(.plain)
        .accessibilityLabel("Plan, " + PlanSnapshot.progress(items))
      if expanded {
        VStack(alignment: .leading, spacing: 5) {
          ForEach(items) { item in
            HStack(alignment: .firstTextBaseline, spacing: 8) {
              Image(systemName: icon(item.status)).font(.system(size: 11)).foregroundStyle(color(item.status))
              Text(item.content).font(.system(size: 12))
                .strikethrough(item.status == "cancelled")
                .foregroundStyle(item.status == "completed" || item.status == "cancelled" ? Color.secondary : Color.primary)
                .fontWeight(item.status == "in_progress" ? .semibold : .regular)
                .textSelection(.enabled)
            }
          }
        }
      } else if let current = items.first(where: { $0.status == "in_progress" }) {
        Text(current.content).font(.caption).foregroundStyle(.secondary).lineLimit(1)
      }
    }
    .padding(12)
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(Color.qPanel.opacity(0.6), in: RoundedRectangle(cornerRadius: 8))
    .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.primary.opacity(0.08), lineWidth: 1))
  }
  private func icon(_ status: String) -> String {
    switch status {
    case "completed": return "checkmark.circle.fill"
    case "in_progress": return "circle.dotted.circle"
    case "cancelled": return "xmark.circle"
    default: return "circle"
    }
  }
  private func color(_ status: String) -> Color {
    switch status {
    case "completed": return .green
    case "in_progress": return Color.qAccent
    default: return .secondary
    }
  }
}
