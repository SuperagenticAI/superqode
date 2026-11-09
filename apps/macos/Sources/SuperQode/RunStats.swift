import SwiftUI

/// Timing and usage for one turn. Every field is optional: the footer shows
/// only what the engine recorded or the runtime reported.
struct RunStats: Equatable {
  var sent: Date?
  var finished: Date?
  var model = ""
  var tokensIn: Int?
  var tokensOut: Int?
  var cost: Double?
  var costCurrency: String?
  /// Rough output size, used only for completed runs without reported usage.
  var estimatedTokensOut: Int?

  static let terminal: Set<String> = ["completed", "failed", "cancelled", "interrupted", "regressed"]

  /// Stats for the selected run, from `jobs.get` detail and its events.
  init(detail: [String: Any], events: [[String: Any]]) {
    let request = detail["request"] as? [String: Any] ?? [:]
    let result = detail["result"] as? [String: Any] ?? [:]
    let status = string(detail, "status")
    self.init(
      sent: Self.date(detail["started_at"]) ?? Self.date(detail["created"]),
      finished: Self.date(detail["finished_at"])
        ?? (Self.terminal.contains(status) ? Self.date(detail["updated"]) : nil),
      model: Self.model(request),
      usage: result["usage_summary"] as? [String: Any],
      status: status,
      response: status == "completed" ? Self.responseText(events) : "")
  }

  /// Stats for an earlier turn returned by `conversations.get`.
  init(turn: [String: Any]) {
    let status = string(turn, "status")
    self.init(
      sent: Self.date(turn["started_at"]) ?? Self.date(turn["created"]),
      finished: Self.date(turn["finished_at"]),
      model: string(turn, "model"),
      usage: turn["usage"] as? [String: Any],
      status: status,
      response: status == "completed" ? string(turn, "response") : "")
  }

  init(sent: Date?, finished: Date?, model: String, usage: [String: Any]?, status: String,
    response: String) {
    self.sent = sent
    self.finished = finished
    self.model = model
    if let usage {
      tokensIn = Self.number(usage["tokens_in"]).map { Int($0) }
      tokensOut = Self.number(usage["tokens_out"]).map { Int($0) }
      cost = Self.number(usage["cost"])
      costCurrency = usage["cost_currency"] as? String
    }
    if status == "completed", tokensIn == nil, tokensOut == nil, !response.isEmpty {
      // About four characters per token for English prose and code.
      estimatedTokensOut = max(1, response.utf8.count / 4)
    }
  }

  var duration: TimeInterval? {
    guard let sent, let finished, finished >= sent else { return nil }
    return finished.timeIntervalSince(sent)
  }

  /// "Worked for 42s · finished 09:42 · model · 1.2k in / 300 out · $0.0123"
  var summaryParts: [String] {
    var parts: [String] = []
    if let duration { parts.append("Worked for " + RunStatsFormat.duration(duration)) }
    if let finished { parts.append("finished " + RunStatsFormat.time(finished)) }
    if !model.isEmpty { parts.append(model) }
    switch (tokensIn, tokensOut) {
    case let (input?, output?):
      parts.append(RunStatsFormat.tokens(input) + " in / " + RunStatsFormat.tokens(output) + " out")
    case let (input?, nil): parts.append(RunStatsFormat.tokens(input) + " tokens in")
    case let (nil, output?): parts.append(RunStatsFormat.tokens(output) + " tokens out")
    case (nil, nil):
      if let estimatedTokensOut {
        parts.append("about " + RunStatsFormat.tokens(estimatedTokensOut) + " tokens out (estimate)")
      }
    }
    if let cost { parts.append(RunStatsFormat.cost(cost, currency: costCurrency)) }
    return parts
  }

  var helpText: String {
    var lines: [String] = []
    if let sent { lines.append("Sent " + RunStatsFormat.full(sent)) }
    if let finished { lines.append("Finished " + RunStatsFormat.full(finished)) }
    if estimatedTokensOut != nil {
      lines.append("The agent did not report token usage. The estimate counts the response text only.")
    }
    return lines.joined(separator: "\n")
  }

  static func date(_ value: Any?) -> Date? {
    guard let seconds = number(value), seconds > 0 else { return nil }
    return Date(timeIntervalSince1970: seconds)
  }

  static func number(_ value: Any?) -> Double? {
    if let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() {
      let double = number.doubleValue
      return double.isFinite ? double : nil
    }
    return nil
  }

  static func model(_ request: [String: Any]) -> String {
    let model = string(request, "model")
    if !model.isEmpty { return model }
    return string(request["acp_options"] as? [String: Any] ?? [:], "model")
  }

  /// Response text as recorded in events, matching the engine's history view.
  static func responseText(_ events: [[String: Any]]) -> String {
    var text = ""
    for event in events {
      let data = event["data"] as? [String: Any] ?? [:]
      switch string(event, "type") {
      case "answer": text += string(data, "text")
      case "harness_event":
        if ["delta", "model_delta", "message.delta"].contains(string(data, "event")) {
          let payload = data["payload"] as? [String: Any] ?? [:]
          text += string(payload, "text", string(payload, "content"))
        }
      default: break
      }
    }
    return text
  }
}

enum RunStatsFormat {
  /// Time only for today, otherwise day, month and time.
  static func time(_ date: Date, now: Date = Date()) -> String {
    if Calendar.current.isDate(date, inSameDayAs: now) {
      return date.formatted(date: .omitted, time: .shortened)
    }
    let sameYear = Calendar.current.component(.year, from: date) == Calendar.current.component(.year, from: now)
    let style: Date.FormatStyle = sameYear
      ? .dateTime.day().month(.abbreviated).hour().minute()
      : .dateTime.day().month(.abbreviated).year().hour().minute()
    return date.formatted(style)
  }

  static func full(_ date: Date) -> String {
    date.formatted(date: .complete, time: .standard)
  }

  static func duration(_ seconds: TimeInterval) -> String {
    let total = max(0, Int(seconds.rounded()))
    if total < 60 { return "\(total)s" }
    if total < 3600 { return "\(total / 60)m \(total % 60)s" }
    return "\(total / 3600)h \((total % 3600) / 60)m"
  }

  static func tokens(_ count: Int) -> String {
    if count < 1000 { return String(count) }
    if count < 1_000_000 { return String(format: "%.1fk", Double(count) / 1000) }
    return String(format: "%.1fM", Double(count) / 1_000_000)
  }

  static func cost(_ value: Double, currency: String?) -> String {
    let code = (currency?.isEmpty == false ? currency! : "USD").uppercased()
    let digits = value < 0.01 ? 4 : 2
    return value.formatted(.currency(code: code).precision(.fractionLength(digits)))
  }
}

/// Muted "Sent 09:41" under a prompt, with the full date on hover.
struct SentTimeLabel: View {
  let date: Date?
  var body: some View {
    if let date {
      Text("Sent " + RunStatsFormat.time(date))
        .font(.caption2).foregroundStyle(.tertiary)
        .help(RunStatsFormat.full(date))
    }
  }
}

/// Footer under a response: a live timer while the agent works, then the
/// recorded duration, finish time, model, tokens and cost that are known.
struct RunStatsFooter: View {
  let stats: RunStats
  var active = false
  var body: some View {
    if active, let sent = stats.sent {
      TimelineView(.periodic(from: .now, by: 1)) { context in
        Label(
          "Working for " + RunStatsFormat.duration(context.date.timeIntervalSince(sent)),
          systemImage: "clock")
      }
      .font(.caption).foregroundStyle(.secondary)
      .help("Sent " + RunStatsFormat.full(sent))
    } else if !active, !stats.summaryParts.isEmpty {
      Text(stats.summaryParts.joined(separator: " · "))
        .font(.caption).foregroundStyle(.secondary).lineLimit(2)
        .textSelection(.enabled)
        .help(stats.helpText)
    }
  }
}
