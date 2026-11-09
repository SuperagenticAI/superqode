import AppKit

/// Prevents idle system sleep while any agent run is active. The display may
/// still sleep. Controlled by the "Keep Mac awake during runs" setting.
@MainActor final class RunSleepGuard {
  static let shared = RunSleepGuard()
  static let settingKey = "keepMacAwakeDuringRuns"
  private var activity: NSObjectProtocol?
  private var terminateObserver: NSObjectProtocol?

  private init() {
    terminateObserver = NotificationCenter.default.addObserver(
      forName: NSApplication.willTerminateNotification, object: nil, queue: .main
    ) { _ in
      MainActor.assumeIsolated { RunSleepGuard.shared.end() }
    }
  }

  static var enabled: Bool {
    UserDefaults.standard.object(forKey: settingKey) as? Bool ?? true
  }

  var holding: Bool { activity != nil }

  func update(runsActive: Bool) {
    if runsActive && Self.enabled { begin() } else { end() }
  }

  private func begin() {
    guard activity == nil else { return }
    activity = ProcessInfo.processInfo.beginActivity(
      options: [.idleSystemSleepDisabled, .userInitiated],
      reason: "SuperQode agent run in progress")
  }

  private func end() {
    guard let current = activity else { return }
    ProcessInfo.processInfo.endActivity(current)
    activity = nil
  }
}

extension Workspace {
  /// Called whenever jobs or the engine connection change, and when the setting flips.
  func updateRunSleepGuard() {
    RunSleepGuard.shared.update(runsActive: connected && anyActive)
  }
}
