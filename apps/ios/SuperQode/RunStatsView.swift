import SwiftUI
import UIKit

/// Device-aware naming so iPad users and reviewers see iPad instead of iPhone.
@MainActor enum CompanionDevice {
  static var isPad: Bool { UIDevice.current.userInterfaceIdiom == .pad }
  static var name: String { isPad ? "iPad" : "iPhone" }
  static var defaultDeviceName: String { isPad ? "My iPad" : "My iPhone" }
  static var onThisDeviceTitle: String { isPad ? "On this iPad" : "On this iPhone" }
  static var whatYouCanDoTitle: String { isPad ? "What you can do on iPad" : "What you can do on iPhone" }
}

/// Subtle native haptics for key mobile actions.
@MainActor enum CompanionHaptics {
  static func impact(_ style: UIImpactFeedbackGenerator.FeedbackStyle = .light) {
    let generator = UIImpactFeedbackGenerator(style: style)
    generator.impactOccurred()
  }
  static func notify(_ type: UINotificationFeedbackGenerator.FeedbackType) {
    let generator = UINotificationFeedbackGenerator()
    generator.notificationOccurred(type)
  }
}

/// Timing and usage for one coding turn. Every field is optional: the footer
/// shows only what the engine recorded or the runtime reported.
struct CompanionRunStats: Equatable {
  var sent: Date?
  var finished: Date?
  var model = ""
  var tokensIn: Int?
  var tokensOut: Int?
  var cost: Double?
  var costCurrency: String?
  var estimatedTokensOut: Int?

  static let terminal: Set<String> = ["completed", "failed", "cancelled", "interrupted", "regressed"]

  init(detail: [String: JSONValue], response: String) {
    let request = detail.object("request")
    let result = detail.object("result")
    let status = detail.text("status")
    let usage = result["usage_summary"]?.object ?? result["usage"]?.object
    self.init(
      sent: Self.date(detail["started_at"]) ?? Self.date(detail["created"]),
      finished: Self.date(detail["finished_at"])
        ?? (Self.terminal.contains(status) ? Self.date(detail["updated"]) : nil),
      model: request.text("model"),
      usage: usage?.isEmpty == false ? usage : nil,
      status: status,
      response: status == "completed" ? response : "")
  }

  init(turn: RemoteRecord) {
    let status = turn.text("status")
    let usage = turn.raw["usage"]?.object
    self.init(
      sent: Self.date(turn.raw["started_at"]) ?? Self.date(turn.raw["created"]),
      finished: Self.date(turn.raw["finished_at"]),
      model: turn.text("model"),
      usage: usage?.isEmpty == false ? usage : nil,
      status: status,
      response: status == "completed" ? turn.text("response") : "")
  }

  init(
    sent: Date?, finished: Date?, model: String, usage: [String: JSONValue]?, status: String,
    response: String
  ) {
    self.sent = sent
    self.finished = finished
    self.model = model
    if let usage {
      tokensIn = Self.number(usage["tokens_in"]).map { Int($0) }
      tokensOut = Self.number(usage["tokens_out"]).map { Int($0) }
      cost = Self.number(usage["cost"])
      let currency = usage.text("cost_currency")
      costCurrency = currency.isEmpty ? nil : currency
    }
    if status == "completed", tokensIn == nil, tokensOut == nil, !response.isEmpty {
      estimatedTokensOut = max(1, response.utf8.count / 4)
    }
  }

  var duration: TimeInterval? {
    guard let sent, let finished, finished >= sent else { return nil }
    return finished.timeIntervalSince(sent)
  }

  var summaryParts: [String] {
    var parts: [String] = []
    if let duration { parts.append("Worked for " + RunStatsFormat.duration(duration)) }
    if let finished { parts.append("finished " + RunStatsFormat.time(finished)) }
    if !model.isEmpty { parts.append(model) }
    switch (tokensIn, tokensOut) {
    case let (input?, output?):
      parts.append(RunStatsFormat.tokens(input) + " in / " + RunStatsFormat.tokens(output) + " out")
    case let (input?, nil):
      parts.append(RunStatsFormat.tokens(input) + " tokens in")
    case let (nil, output?):
      parts.append(RunStatsFormat.tokens(output) + " tokens out")
    case (nil, nil):
      if let estimatedTokensOut {
        parts.append("about " + RunStatsFormat.tokens(estimatedTokensOut) + " tokens out (est.)")
      }
    }
    if let cost { parts.append(RunStatsFormat.cost(cost, currency: costCurrency)) }
    return parts
  }

  static func date(_ value: JSONValue?) -> Date? {
    guard let seconds = number(value), seconds > 0 else { return nil }
    return Date(timeIntervalSince1970: seconds)
  }

  static func number(_ value: JSONValue?) -> Double? {
    guard case .number(let n) = value, n.isFinite, n >= 0 else { return nil }
    return n
  }

  static func startDate(_ raw: [String: JSONValue]) -> Date? {
    date(raw["started_at"]) ?? date(raw["created"])
  }

  static func waitingSince(_ raw: [String: JSONValue]) -> Date? {
    raw.text("status") == "needs_approval" ? date(raw["updated"]) : nil
  }
}

enum RunStatsFormat {
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

  static func duration(_ seconds: TimeInterval) -> String {
    let total = max(0, Int(seconds.rounded()))
    if total < 60 { return "\(total)s" }
    if total < 3600 { return "\(total / 60)m \(total % 60)s" }
    return "\(total / 3600)h \((total % 3600) / 60)m"
  }

  static func elapsed(_ seconds: TimeInterval) -> String {
    let total = max(0, Int(seconds))
    if total < 60 { return "\(total)s" }
    if total < 3600 { return "\(total / 60)m " + String(format: "%02ds", total % 60) }
    return "\(total / 3600)h " + String(format: "%02dm", (total % 3600) / 60)
  }

  static func compactElapsed(_ seconds: TimeInterval) -> String {
    let total = max(0, Int(seconds))
    if total < 60 { return "\(total)s" }
    if total < 3600 { return "\(total / 60)m" }
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

/// Scoped ticking timer so surrounding transcript cards are not re-rendered.
struct LiveElapsedText: View {
  let prefix: String
  let since: Date
  var compact = false
  var body: some View {
    TimelineView(.periodic(from: .now, by: 1)) { context in
      let seconds = context.date.timeIntervalSince(since)
      Text(prefix + (compact ? RunStatsFormat.compactElapsed(seconds) : RunStatsFormat.elapsed(seconds)))
        .monospacedDigit()
    }
  }
}

struct SentTimeLabel: View {
  let date: Date?
  var body: some View {
    if let date {
      Text("Sent " + RunStatsFormat.time(date))
        .font(.caption2)
        .foregroundStyle(.secondary)
    }
  }
}

struct CompanionRunStatsFooter: View {
  let stats: CompanionRunStats
  var active = false
  var body: some View {
    if active, let sent = stats.sent {
      TimelineView(.periodic(from: .now, by: 1)) { context in
        Label(
          "Working for " + RunStatsFormat.duration(context.date.timeIntervalSince(sent)),
          systemImage: "clock")
      }
      .font(.caption)
      .foregroundStyle(.secondary)
    } else if !active, !stats.summaryParts.isEmpty {
      Text(stats.summaryParts.joined(separator: " · "))
        .font(.caption)
        .foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
    }
  }
}

/// One-tap private clipboard copy for whole prompts and agent responses.
struct PrivateCopyButton: View {
  let label: String
  let text: () -> String
  @State private var copied = false

  var body: some View {
    Button {
      let value = text()
      guard !value.isEmpty else { return }
      PrivateClipboard.copy(value)
      CompanionHaptics.impact(.light)
      copied = true
      Task { @MainActor in
        try? await Task.sleep(for: .seconds(1.5))
        copied = false
      }
    } label: {
      Label(copied ? "Copied" : "Copy", systemImage: copied ? "checkmark" : "doc.on.doc")
        .font(.caption.weight(.medium))
        .foregroundStyle(copied ? CompanionTheme.accent : Color.secondary)
    }
    .buttonStyle(.plain)
    .accessibilityLabel(copied ? "Copied" : label)
  }
}
