import SwiftUI

/// Reported provider health for the selected thread. Never estimates: each
/// field appears only when the engine or agent reported it.
struct ProviderHealth: Equatable {
  var contextUsed: Int?
  var contextSize: Int?
  var limitPercent: Double?
  var authFailure = ""

  var contextPercent: Int? {
    guard let used = contextUsed, let size = contextSize, size > 0 else { return nil }
    return min(100, Int((Double(used) / Double(size) * 100).rounded()))
  }

  static func from(events: [[String: Any]], status: String) -> ProviderHealth {
    var health = ProviderHealth()
    for event in events.reversed() {
      let data = event["data"] as? [String: Any] ?? [:]
      if string(event, "type") == "harness_event", string(data, "event") == "usage", health.contextSize == nil {
        let payload = data["payload"] as? [String: Any] ?? [:]
        health.contextUsed = number(payload["used"])
        health.contextSize = number(payload["size"])
        if health.limitPercent == nil { health.limitPercent = limit(payload) }
      }
      if health.limitPercent == nil, string(event, "type") == "harness_event" {
        health.limitPercent = limit(data["payload"] as? [String: Any] ?? [:])
      }
      if status == "failed", health.authFailure.isEmpty, string(event, "type") == "error" {
        let message = string(data, "message", string(data, "error"))
        let lower = message.lowercased()
        let needles = ["unauthorized", "401", "not logged in", "login required", "sign in", "authentication", "invalid api key", "api key", "expired token", "auth required"]
        if needles.contains(where: { lower.contains($0) }) { health.authFailure = message }
      }
    }
    return health
  }

  private static func number(_ value: Any?) -> Int? {
    if let int = value as? Int { return int }
    if let double = value as? Double { return Int(double) }
    return nil
  }

  /// Rate limit usage when an agent reports one (for example rate_limits.primary.used_percent).
  private static func limit(_ payload: [String: Any]) -> Double? {
    for key in ["rate_limits", "rateLimits"] {
      guard let limits = payload[key] as? [String: Any] else { continue }
      var values: [Double] = []
      for value in limits.values {
        if let window = value as? [String: Any] {
          for name in ["used_percent", "usedPercent"] {
            if let percent = window[name] as? Double { values.append(percent) }
            else if let percent = window[name] as? Int { values.append(Double(percent)) }
          }
        }
      }
      if let worst = values.max() { return worst }
    }
    return nil
  }
}

/// Slim line above the composer. Quiet when healthy, prominent when broken.
struct ProviderHealthStrip: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    let health = app.selectedProviderHealth
    Group {
      if !app.connected {
        broken("Local engine offline. Your draft is kept.", action: "Reconnect") {
          app.perform { try await app.engine.stopAndWait(); await app.boot() }
        }
      } else if app.connectionDisconnected && !app.selectedJob.isEmpty {
        // A new thread already shows the connection grid above the composer.
        broken("No agent or model connected for this thread.", action: "Connect…") { app.openConnections("menu:root") }
      } else if !health.authFailure.isEmpty && !app.active {
        broken("The last run could not sign in to " + app.connectionDisplayName + ".", action: "Fix connection…") {
          app.openConnections("menu:root")
        }.help(health.authFailure)
      } else if health.contextPercent != nil || health.limitPercent != nil {
        healthy(health)
      }
    }
  }

  private func broken(_ text: String, action: String, perform: @escaping () -> Void) -> some View {
    HStack(spacing: 8) {
      Image(systemName: "exclamationmark.triangle.fill").foregroundStyle(.orange)
      Text(text).font(.caption).lineLimit(2)
      Spacer(minLength: 0)
      Button(action, action: perform).font(.caption)
    }
    .padding(.horizontal, 10).padding(.vertical, 6)
    .background(Color.orange.opacity(0.1), in: RoundedRectangle(cornerRadius: 6))
    .accessibilityElement(children: .combine)
  }

  private func healthy(_ health: ProviderHealth) -> some View {
    HStack(spacing: 10) {
      Circle().fill(Color.green).frame(width: 6, height: 6)
      Text(app.connectionDisplayName).lineLimit(1)
      if let percent = health.contextPercent, let used = health.contextUsed, let size = health.contextSize {
        HStack(spacing: 4) {
          Text("Context \(percent)%")
          ProgressView(value: Double(used), total: Double(size)).progressViewStyle(.linear).frame(width: 60)
            .tint(percent >= 85 ? Color.orange : Color.secondary)
        }
        .foregroundStyle(percent >= 85 ? Color.orange : Color.secondary)
        .help("\(RunStatsFormat.tokens(used)) of \(RunStatsFormat.tokens(size)) tokens in the agent's context window, as reported by the agent")
      }
      if let limit = health.limitPercent {
        Text("Limit \(Int(limit.rounded()))% used").foregroundStyle(limit >= 85 ? Color.orange : Color.secondary)
          .help("Usage limit reported by the agent")
      }
      Spacer(minLength: 0)
    }
    .font(.caption).foregroundStyle(.secondary)
  }
}
