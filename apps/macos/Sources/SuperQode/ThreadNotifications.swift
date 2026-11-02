import AppKit
import UserNotifications
import SwiftUI

func threadNotificationText(_ status: String) -> (title: String, body: String)? {
  switch status {
  case "needs_approval": return ("Approval needed", "A coding thread is waiting for your review.")
  case "completed": return ("Task completed", "A coding thread finished. Open it to review the result.")
  case "failed", "interrupted": return ("Task needs attention", "A coding thread stopped without completing. Its recorded history is available.")
  default: return nil
  }
}

@MainActor final class ThreadNotifications: NSObject, ObservableObject, UNUserNotificationCenterDelegate {
  @Published private(set) var enabled: Bool
  @Published private(set) var issue = ""
  private let preferences: UserDefaults
  private(set) var cursor: Int
  var openThread: ((String, String) -> Void)?
  init(preferences: UserDefaults) {
    self.preferences = preferences
    enabled = preferences.bool(forKey: "threadAlertsEnabled")
    cursor = preferences.object(forKey: "threadAlertCursor") as? Int ?? -1
    super.init()
  }
  func toggle() {
    if enabled {
      enabled = false
      preferences.set(false, forKey: "threadAlertsEnabled")
      NSApp.dockTile.badgeLabel = nil
      return
    }
    guard Bundle.main.bundleIdentifier != nil else { issue = "Enable alerts from the packaged macOS app."; return }
    Task {
      do {
        let center = UNUserNotificationCenter.current()
        let allowed = try await center.requestAuthorization(options: [.alert, .sound, .badge])
        enabled = allowed
        preferences.set(allowed, forKey: "threadAlertsEnabled")
        issue = allowed ? "" : "Allow SuperQode notifications in macOS System Settings to receive alerts."
        if allowed { center.delegate = self }
      } catch { issue = error.localizedDescription }
    }
  }
  func consume(_ result: [String: Any], selected: String) {
    let next = result["cursor"] as? Int ?? cursor
    if next != cursor { cursor = next; preferences.set(cursor, forKey: "threadAlertCursor") }
    guard enabled, Bundle.main.bundleIdentifier != nil, !ProcessInfo.processInfo.arguments.contains("--smoke-test") else { return }
    let count = result["attention_count"] as? Int ?? 0
    NSApp.dockTile.badgeLabel = count > 0 ? String(count) : nil
    let center = UNUserNotificationCenter.current()
    center.delegate = self
    for row in result["items"] as? [[String: Any]] ?? [] {
      if NSApp.isActive && string(row, "job") == selected { continue }
      guard let text = threadNotificationText(string(row, "status")) else { continue }
      let content = UNMutableNotificationContent()
      content.title = "SuperQode · " + text.title
      content.body = text.body
      content.sound = .default
      content.userInfo = ["job": string(row, "job"), "project": string(row, "project")]
      let request = UNNotificationRequest(identifier: "superqode-thread-" + String(row["seq"] as? Int ?? 0), content: content, trigger: nil)
      center.add(request) { [weak self] error in
        if let error { Task { @MainActor in self?.issue = "Thread alert could not be delivered: " + error.localizedDescription } }
      }
    }
  }
  nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
    let info = response.notification.request.content.userInfo
    let job = info["job"] as? String ?? ""
    let project = info["project"] as? String ?? ""
    Task { @MainActor in self.openThread?(project, job) }
    completionHandler()
  }
  nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification, withCompletionHandler completionHandler: @escaping (UNNotificationPresentationOptions) -> Void) {
    completionHandler([.banner, .sound])
  }
}

struct ThreadAlertControls: View {
  @ObservedObject var alerts: ThreadNotifications
  var body: some View {
    HStack {
      Button(alerts.enabled ? "Turn off thread alerts" : "Enable thread alerts", systemImage: alerts.enabled ? "bell.fill" : "bell") { alerts.toggle() }
      if !alerts.issue.isEmpty { Text(alerts.issue).font(.caption).foregroundStyle(.secondary) }
    }
  }
}
