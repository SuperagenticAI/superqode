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
  static func latest(_ events: [RemoteRecord]) -> [PlanItem] {
    for event in events.reversed() where event.text("type") == "harness_event" {
      let data = event.raw.object("data")
      let payload = data.object("payload")
      if data.text("event") == "plan", let entries = payload["entries"]?.array {
        let items = parse(entries.map(\.object))
        if !items.isEmpty { return items }
      }
      if let todos = todoArgument(payload) {
        let items = parse(todos)
        if !items.isEmpty { return items }
      }
    }
    return []
  }

  private static func todoArgument(_ payload: [String: JSONValue]) -> [[String: JSONValue]]? {
    let name = payload.text("tool_name", payload.text("name", payload.text("title"))).lowercased()
    guard name.contains("todo") else { return nil }
    for key in ["rawInput", "raw_input", "arguments", "args", "input"] {
      let input = payload.object(key)
      if let todos = input["todos"]?.array { return todos.map(\.object) }
    }
    if let todos = payload["todos"]?.array { return todos.map(\.object) }
    return nil
  }

  private static func parse(_ entries: [[String: JSONValue]]) -> [PlanItem] {
    entries.enumerated().compactMap { index, entry in
      let text = entry.text("content", entry.text("title", entry.text("text")))
        .split(whereSeparator: \.isWhitespace).joined(separator: " ")
      guard !text.isEmpty else { return nil }
      return PlanItem(
        id: entry.text("id", String(index + 1)),
        content: text,
        status: normalize(entry.text("status")))
    }
  }

  static func normalize(_ raw: String) -> String {
    let value = raw.lowercased()
      .replacingOccurrences(of: "-", with: "_")
      .replacingOccurrences(of: " ", with: "_")
    if ["completed", "complete", "done", "finished"].contains(value) { return "completed" }
    if ["in_progress", "inprogress", "running", "active", "started"].contains(value) { return "in_progress" }
    if ["cancelled", "canceled", "skipped", "failed"].contains(value) { return "cancelled" }
    return "pending"
  }

  static func progress(_ items: [PlanItem]) -> String {
    let done = items.filter { $0.status == "completed" }.count
    return "\(done) of \(items.count) done"
  }

  static func compactLine(_ items: [PlanItem]) -> String {
    guard !items.isEmpty else { return "" }
    let current = items.first { $0.status == "in_progress" } ?? items.first { $0.status == "pending" }
    return "Plan " + progress(items) + (current.map { " · " + $0.content } ?? "")
  }
}

/// Collapsible live checklist of the agent's plan inside a conversation.
struct CompanionPlanCard: View {
  let items: [PlanItem]
  @State private var expanded = false

  var body: some View {
    CompanionCard {
      Button {
        withAnimation(.easeInOut(duration: 0.16)) { expanded.toggle() }
      } label: {
        HStack(spacing: 8) {
          Image(systemName: "checklist").foregroundStyle(CompanionTheme.accent)
          Text("Plan").font(.subheadline.weight(.semibold)).foregroundStyle(.primary)
          Text(PlanSnapshot.progress(items)).font(.caption).foregroundStyle(.secondary)
          Spacer(minLength: 4)
          Image(systemName: expanded ? "chevron.up" : "chevron.down")
            .font(.caption.weight(.semibold))
            .foregroundStyle(.secondary)
        }
        .contentShape(Rectangle())
      }
      .buttonStyle(.plain)
      .accessibilityIdentifier("plan.toggle")
      .accessibilityLabel("Plan, " + PlanSnapshot.progress(items))

      ProgressView(
        value: Double(items.filter { $0.status == "completed" }.count),
        total: Double(max(items.count, 1))
      )
      .tint(CompanionTheme.accent)

      if expanded {
        VStack(alignment: .leading, spacing: 8) {
          ForEach(items) { item in
            HStack(alignment: .firstTextBaseline, spacing: 10) {
              Image(systemName: icon(item.status))
                .font(.caption)
                .foregroundStyle(color(item.status))
              Text(item.content)
                .font(.subheadline)
                .strikethrough(item.status == "cancelled")
                .foregroundStyle(
                  item.status == "completed" || item.status == "cancelled"
                    ? Color.secondary : Color.primary
                )
                .fontWeight(item.status == "in_progress" ? .semibold : .regular)
                .textSelection(.enabled)
            }
          }
        }
      } else if let current = items.first(where: { $0.status == "in_progress" }) {
        Text(current.content)
          .font(.caption)
          .foregroundStyle(.secondary)
          .lineLimit(2)
      }
    }
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
    case "in_progress": return CompanionTheme.accent
    default: return .secondary
    }
  }
}
