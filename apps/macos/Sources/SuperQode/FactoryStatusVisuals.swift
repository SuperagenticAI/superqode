import AppKit
import SwiftUI

/// Unified semantic status model for Factory runs, stages, tasks and WorkOrders.
enum FactoryStatus: Equatable, Hashable {
  case draft
  case queued
  case pending
  case running
  case verifying
  case waitingHuman
  case readyToShip
  case succeeded
  case shipped
  case blocked
  case failed
  case cancelled
  case skipped

  init(raw: String) {
    switch raw.trimmingCharacters(in: .whitespacesAndNewlines).lowercased() {
    case "draft":
      self = .draft
    case "queued":
      self = .queued
    case "pending", "ready", "submitted":
      self = .pending
    case "running", "in_progress", "leased", "working", "merging", "cancelling":
      self = .running
    case "checking", "reviewing", "verifying":
      self = .verifying
    case "waiting_for_human", "needs_approval", "input_required", "auth_required":
      self = .waitingHuman
    case "ready_to_merge":
      self = .readyToShip
    case "succeeded", "completed", "passed", "pass", "ship":
      self = .succeeded
    case "accepted", "merged":
      self = .shipped
    case "blocked", "hold":
      self = .blocked
    case "failed", "rejected", "reject", "rolled_back", "error":
      self = .failed
    case "cancelled", "canceled":
      self = .cancelled
    case "skipped":
      self = .skipped
    default:
      self = .pending
    }
  }

  var label: String {
    switch self {
    case .draft: return "Draft"
    case .queued: return "Queued"
    case .pending: return "Pending"
    case .running: return "Running"
    case .verifying: return "Verifying"
    case .waitingHuman: return "Needs Gate"
    case .readyToShip: return "Ready to Ship"
    case .succeeded: return "Completed"
    case .shipped: return "Shipped"
    case .blocked: return "Blocked"
    case .failed: return "Failed"
    case .cancelled: return "Cancelled"
    case .skipped: return "Skipped"
    }
  }

  var symbol: String {
    switch self {
    case .draft: return "doc.text"
    case .queued: return "tray.full"
    case .pending: return "clock"
    case .running: return "bolt.circle.fill"
    case .verifying: return "gauge.with.dots.needle.67percent"
    case .waitingHuman: return "hand.raised.fill"
    case .readyToShip: return "checkmark.seal.fill"
    case .succeeded: return "checkmark.circle.fill"
    case .shipped: return "shippingbox.fill"
    case .blocked: return "exclamationmark.octagon.fill"
    case .failed: return "xmark.circle.fill"
    case .cancelled: return "minus.circle"
    case .skipped: return "forward.end.circle"
    }
  }

  var color: Color {
    switch self {
    case .draft, .cancelled, .skipped:
      return Color.secondary
    case .queued, .pending:
      return Color(red: 0.36, green: 0.46, blue: 0.88)
    case .running:
      return Brand.purple
    case .verifying:
      return Color(red: 0.12, green: 0.60, blue: 0.68)
    case .waitingHuman:
      return Brand.orange
    case .readyToShip, .succeeded, .shipped:
      return Color(red: 0.14, green: 0.64, blue: 0.42)
    case .blocked:
      return Color(red: 0.88, green: 0.44, blue: 0.14)
    case .failed:
      return Color(red: 0.86, green: 0.24, blue: 0.28)
    }
  }

  var isActive: Bool {
    switch self {
    case .running, .verifying, .waitingHuman:
      return true
    default:
      return false
    }
  }

  var isPulsing: Bool {
    switch self {
    case .running, .verifying, .waitingHuman:
      return true
    default:
      return false
    }
  }

  var isComplete: Bool {
    switch self {
    case .succeeded, .shipped, .readyToShip, .skipped:
      return true
    default:
      return false
    }
  }
}

/// Subtle, tasteful macOS soundscape and Trackpad haptics for Factory state transitions.
@MainActor enum FactorySoundEngine {
  nonisolated static let preferenceKey = "factorySoundsEnabled"
  private static var lastPlayedAt: Date = .distantPast
  private static var activeSound: NSSound?

  enum Cue: String, Equatable, Hashable {
    case started
    case stageCompleted
    case needsAttention
    case succeeded
    case failed
    case cancelled

    var systemSoundName: String {
      switch self {
      case .started: return "Tink"
      case .stageCompleted: return "Pop"
      case .needsAttention: return "Submarine"
      case .succeeded: return "Glass"
      case .failed: return "Basso"
      case .cancelled: return "Morse"
      }
    }

    var volume: Float {
      switch self {
      case .started: return 0.22
      case .stageCompleted: return 0.26
      case .needsAttention: return 0.34
      case .succeeded: return 0.32
      case .failed: return 0.28
      case .cancelled: return 0.20
      }
    }

    var haptic: NSHapticFeedbackManager.FeedbackPattern {
      switch self {
      case .started, .stageCompleted, .cancelled:
        return .alignment
      case .needsAttention:
        return .levelChange
      case .succeeded, .failed:
        return .generic
      }
    }
  }

  static var isEnabled: Bool {
    get {
      if UserDefaults.standard.object(forKey: preferenceKey) == nil { return true }
      return UserDefaults.standard.bool(forKey: preferenceKey)
    }
    set {
      UserDefaults.standard.set(newValue, forKey: preferenceKey)
    }
  }

  private static var isAutomatedTest: Bool {
    let args = ProcessInfo.processInfo.arguments
    if args.contains("--smoke-test") { return true }
    if ProcessInfo.processInfo.environment["XCTestConfigurationFilePath"] != nil { return true }
    return false
  }

  static func play(_ cue: Cue, force: Bool = false) {
    guard !isAutomatedTest else { return }
    guard force || isEnabled else { return }
    let now = Date()
    if !force && now.timeIntervalSince(lastPlayedAt) < 0.18 { return }
    lastPlayedAt = now

    NSHapticFeedbackManager.defaultPerformer.perform(cue.haptic, performanceTime: .now)

    if let sound = NSSound(named: NSSound.Name(cue.systemSoundName)) {
      sound.volume = cue.volume
      activeSound = sound
      sound.play()
    }
  }

  /// Determine the sound cue for a single status transition.
  static func cueForTransition(from previousRaw: String, to currentRaw: String) -> Cue? {
    let previous = FactoryStatus(raw: previousRaw)
    let current = FactoryStatus(raw: currentRaw)
    guard previous != current else { return nil }
    switch current {
    case .failed, .blocked:
      return .failed
    case .waitingHuman:
      return .needsAttention
    case .succeeded, .shipped, .readyToShip:
      return .stageCompleted
    case .running, .verifying:
      return .started
    case .cancelled:
      return .cancelled
    default:
      return nil
    }
  }

  /// Determine the single highest-priority sound cue across a batch of stage status updates.
  static func cueForTaskTransitions(previous: [String: String], current: [[String: Any]]) -> Cue? {
    var priority: Cue?
    func promote(_ candidate: Cue) {
      let rank: [Cue: Int] = [
        .started: 1,
        .cancelled: 2,
        .stageCompleted: 3,
        .succeeded: 4,
        .needsAttention: 5,
        .failed: 6,
      ]
      if let existing = priority, (rank[existing] ?? 0) >= (rank[candidate] ?? 0) {
        return
      }
      priority = candidate
    }

    for task in current {
      let id = string(task, "task_id")
      guard !id.isEmpty, let oldStatus = previous[id] else { continue }
      let newStatus = string(task, "status")
      if let cue = cueForTransition(from: oldStatus, to: newStatus) {
        promote(cue)
      }
    }
    return priority
  }
}

/// Compact header toggle for Factory Studio sounds.
struct FactorySoundToggleButton: View {
  @AppStorage(FactorySoundEngine.preferenceKey) private var soundsEnabled = true

  var body: some View {
    Button {
      soundsEnabled.toggle()
      if soundsEnabled {
        FactorySoundEngine.play(.started, force: true)
      }
    } label: {
      Image(systemName: soundsEnabled ? "speaker.wave.2.fill" : "speaker.slash")
        .font(.system(size: 12, weight: .semibold))
        .foregroundStyle(soundsEnabled ? Brand.purple : Color.secondary)
        .frame(width: 26, height: 26)
        .background(
          (soundsEnabled ? Brand.purple.opacity(0.11) : Color.primary.opacity(0.05)),
          in: RoundedRectangle(cornerRadius: 7, style: .continuous)
        )
    }
    .buttonStyle(.plain)
    .help(soundsEnabled ? "Factory sounds on (click to mute)" : "Factory sounds muted (click to enable)")
    .accessibilityLabel(soundsEnabled ? "Mute Factory sounds" : "Enable Factory sounds")
  }
}

/// Crisp status indicator dot with a gentle breathing halo when active.
struct FactoryStatusDot: View {
  let status: FactoryStatus
  var size: CGFloat = 8
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @Environment(\.colorSchemeContrast) private var contrast
  @AppStorage("animatedInterface") private var animated = true

  private var shouldPulse: Bool { status.isPulsing && animated && !reduceMotion }
  private var dotColor: Color { contrast == .increased ? Color.primary : status.color }

  var body: some View {
    ZStack {
      if shouldPulse {
        TimelineView(.animation(minimumInterval: 1.0 / 24)) { timeline in
          let t = timeline.date.timeIntervalSinceReferenceDate
          let phase = (t / 1.6).truncatingRemainder(dividingBy: 1)
          Circle()
            .stroke(dotColor.opacity((1 - phase) * 0.65), lineWidth: 1.5)
            .frame(width: size + phase * size * 1.35, height: size + phase * size * 1.35)
        }
      }
      Circle()
        .fill(dotColor)
        .frame(width: size, height: size)
    }
    .frame(width: size * 2.1, height: size * 2.1)
    .accessibilityHidden(true)
  }
}

/// Clear, color-coded semantic status pill replacing raw flat gray status strings.
struct FactoryStatusBadge: View {
  let status: FactoryStatus
  var detail: String = ""
  @Environment(\.colorSchemeContrast) private var contrast

  init(raw: String, detail: String = "") {
    self.status = FactoryStatus(raw: raw)
    self.detail = detail
  }

  init(status: FactoryStatus, detail: String = "") {
    self.status = status
    self.detail = detail
  }

  private var accent: Color { contrast == .increased ? Color.primary : status.color }

  var body: some View {
    HStack(spacing: 5) {
      if status.isPulsing {
        FactoryStatusDot(status: status, size: 6)
      } else {
        Image(systemName: status.symbol)
          .font(.system(size: 10, weight: .semibold))
          .foregroundStyle(accent)
      }
      Text(detail.isEmpty ? status.label : "\(status.label) · \(detail)")
        .font(.system(size: 11, weight: .semibold))
        .foregroundStyle(contrast == .increased ? Color.primary : accent)
        .lineLimit(1)
    }
    .padding(.horizontal, 8)
    .padding(.vertical, 4)
    .background(accent.opacity(contrast == .increased ? 0.14 : 0.12), in: Capsule())
    .overlay(
      Capsule()
        .strokeBorder(accent.opacity(contrast == .increased ? 0.45 : 0.24), lineWidth: 0.75)
        .allowsHitTesting(false)
    )
  }
}

/// Sidebar status summary badges for FactoryNavigationHeader.
struct FactorySidebarBadges: Equatable {
  var isRunning: Bool = false
  var pendingGates: Int = 0
  var readyToShip: Bool = false
  var hasUnappliedControls: Bool = false
  var hasUnsavedDraft: Bool = false
}

/// Calm 4-step visual lifecycle bar: Prepare -> Run -> Verify -> Ship.
struct FactoryPipelineStepper: View {
  enum StepState {
    case pending
    case active
    case attention
    case done
    case failed
  }

  let orderStatus: FactoryStatus
  let tasks: [[String: Any]]
  let gaugeVerdict: SuperGaugeVerdict
  let hasCandidate: Bool
  let isBusy: Bool
  let activeAction: String

  private var completedTaskCount: Int {
    tasks.filter { FactoryStatus(raw: string($0, "status")).isComplete }.count
  }

  private var anyRunningTask: Bool {
    tasks.contains { FactoryStatus(raw: string($0, "status")) == .running }
      || (isBusy && activeAction == "worker")
  }

  private var anyWaitingGate: Bool {
    tasks.contains { FactoryStatus(raw: string($0, "status")) == .waitingHuman }
  }

  private var anyFailedTask: Bool {
    tasks.contains { FactoryStatus(raw: string($0, "status")) == .failed }
      || orderStatus == .failed
  }

  private var allTasksDone: Bool {
    !tasks.isEmpty && completedTaskCount == tasks.count
  }

  private var steps: [(title: String, detail: String, state: StepState)] {
    let prepareState: StepState = .done

    let runState: StepState
    let runDetail: String
    if anyFailedTask {
      runState = .failed
      runDetail = "\(completedTaskCount)/\(tasks.count)"
    } else if anyWaitingGate {
      runState = .attention
      runDetail = "Gate"
    } else if anyRunningTask {
      runState = .active
      runDetail = "\(completedTaskCount)/\(tasks.count)"
    } else if allTasksDone || orderStatus == .shipped || orderStatus == .readyToShip {
      runState = .done
      runDetail = tasks.isEmpty ? "Done" : "\(completedTaskCount)/\(tasks.count)"
    } else {
      runState = .active
      runDetail = tasks.isEmpty ? "Ready" : "0/\(tasks.count)"
    }

    let verifyState: StepState
    let verifyDetail: String
    if isBusy && activeAction == "verify" {
      verifyState = .active
      verifyDetail = "Checking"
    } else if gaugeVerdict == .ship {
      verifyState = .done
      verifyDetail = "SHIP"
    } else if gaugeVerdict == .reject {
      verifyState = .failed
      verifyDetail = "REJECT"
    } else if gaugeVerdict == .hold {
      verifyState = .attention
      verifyDetail = "HOLD"
    } else if allTasksDone {
      verifyState = .active
      verifyDetail = "Next"
    } else {
      verifyState = .pending
      verifyDetail = "Waiting"
    }

    let shipState: StepState
    let shipDetail: String
    if orderStatus == .shipped {
      shipState = .done
      shipDetail = "Applied"
    } else if isBusy && (activeAction == "approve" || activeAction == "apply") {
      shipState = .active
      shipDetail = activeAction == "approve" ? "Touch ID" : "Applying"
    } else if gaugeVerdict == .ship && hasCandidate {
      shipState = .active
      shipDetail = "Ready"
    } else {
      shipState = .pending
      shipDetail = "Locked"
    }

    return [
      ("Prepare", "Pinned", prepareState),
      ("Run Stages", runDetail, runState),
      ("Verify", verifyDetail, verifyState),
      ("Ship", shipDetail, shipState),
    ]
  }

  private func color(for state: StepState) -> Color {
    switch state {
    case .pending: return Color.secondary.opacity(0.6)
    case .active: return Brand.purple
    case .attention: return Brand.orange
    case .done: return Color(red: 0.14, green: 0.64, blue: 0.42)
    case .failed: return Color(red: 0.86, green: 0.24, blue: 0.28)
    }
  }

  private func symbol(for state: StepState) -> String {
    switch state {
    case .pending: return "circle"
    case .active: return "dot.circle.fill"
    case .attention: return "hand.raised.fill"
    case .done: return "checkmark.circle.fill"
    case .failed: return "xmark.circle.fill"
    }
  }

  var body: some View {
    HStack(spacing: 6) {
      ForEach(Array(steps.enumerated()), id: \.offset) { index, step in
        let tone = color(for: step.state)
        HStack(spacing: 6) {
          if step.state == .active && isBusy {
            FactoryStatusDot(status: .running, size: 7)
          } else if step.state == .attention {
            FactoryStatusDot(status: .waitingHuman, size: 7)
          } else {
            Image(systemName: symbol(for: step.state))
              .font(.system(size: 12, weight: .semibold))
              .foregroundStyle(tone)
          }
          VStack(alignment: .leading, spacing: 1) {
            Text(step.title)
              .font(.system(size: 11, weight: step.state == .pending ? .medium : .semibold))
              .foregroundStyle(step.state == .pending ? .secondary : .primary)
            Text(step.detail)
              .font(.system(size: 10, weight: .medium))
              .foregroundStyle(tone)
          }
        }
        .padding(.horizontal, 8)
        .padding(.vertical, 6)
        .background(
          step.state == .active || step.state == .attention
            ? tone.opacity(0.10)
            : Color.primary.opacity(0.03),
          in: RoundedRectangle(cornerRadius: 8, style: .continuous)
        )
        .overlay(
          RoundedRectangle(cornerRadius: 8, style: .continuous)
            .strokeBorder(
              step.state == .active || step.state == .attention
                ? tone.opacity(0.32)
                : Color.primary.opacity(0.06),
              lineWidth: 0.75
            )
            .allowsHitTesting(false)
        )
        if index < steps.count - 1 {
          Rectangle()
            .fill(step.state == .done ? Color(red: 0.14, green: 0.64, blue: 0.42).opacity(0.45) : Color.primary.opacity(0.12))
            .frame(height: 1.5)
            .frame(minWidth: 8, maxWidth: 24)
        }
      }
      Spacer(minLength: 0)
    }
  }
}

/// Clean, uncluttered left-pane card for a Factory trial run.
struct FactoryRunListCard: View {
  let row: [String: Any]
  let selected: Bool
  let activeRunBusy: Bool

  private var status: FactoryStatus {
    let raw = string(row, "status")
    if activeRunBusy && !FactoryStatus(raw: raw).isComplete && FactoryStatus(raw: raw) != .failed {
      return .running
    }
    return FactoryStatus(raw: raw)
  }

  private var goalText: String {
    let text = string(row, "goal").trimmingCharacters(in: .whitespacesAndNewlines)
    return text.isEmpty ? "Untitled trial" : text
  }

  private var shortID: String {
    String(string(row, "id").prefix(12))
  }

  var body: some View {
    HStack(spacing: 0) {
      RoundedRectangle(cornerRadius: 2, style: .continuous)
        .fill(status.color.opacity(selected ? 0.95 : 0.65))
        .frame(width: 3)
        .padding(.vertical, 6)
      VStack(alignment: .leading, spacing: 6) {
        Text(goalText)
          .font(.system(size: 12.5, weight: selected ? .semibold : .medium))
          .foregroundStyle(.primary)
          .lineLimit(2)
          .fixedSize(horizontal: false, vertical: true)
        HStack(spacing: 6) {
          FactoryStatusBadge(status: status)
          Spacer(minLength: 4)
          Text(shortID)
            .font(.system(size: 10, design: .monospaced))
            .foregroundStyle(.tertiary)
        }
      }
      .padding(.horizontal, 10)
      .padding(.vertical, 9)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(
      selected ? status.color.opacity(0.10) : Color.primary.opacity(0.025),
      in: RoundedRectangle(cornerRadius: 10, style: .continuous)
    )
    .overlay(
      RoundedRectangle(cornerRadius: 10, style: .continuous)
        .strokeBorder(
          selected ? status.color.opacity(0.42) : Color.primary.opacity(0.08),
          lineWidth: selected ? 1.2 : 0.75
        )
        .allowsHitTesting(false)
    )
  }
}

/// Connected, semantic stage card for the live Factory pipeline.
struct FactoryStageRowCard: View {
  let index: Int
  let task: [String: Any]
  let idle: Bool
  @Binding var gateReason: String
  let onApprove: () -> Void
  let onHold: () -> Void

  private var rawStatus: String { string(task, "status") }
  private var status: FactoryStatus { FactoryStatus(raw: rawStatus) }
  private var taskID: String { string(task, "task_id") }
  private var title: String {
    let t = string(task, "title").trimmingCharacters(in: .whitespacesAndNewlines)
    return t.isEmpty ? taskID : t
  }
  private var role: String { string(task, "role") }
  private var worker: String { string(task, "worker_id") }
  private var errorText: String { string(task, "error").trimmingCharacters(in: .whitespacesAndNewlines) }

  var body: some View {
    HStack(spacing: 0) {
      RoundedRectangle(cornerRadius: 2, style: .continuous)
        .fill(status.color.opacity(status.isActive ? 0.95 : 0.72))
        .frame(width: 3.5)
        .padding(.vertical, 8)
      VStack(alignment: .leading, spacing: 8) {
        HStack(spacing: 8) {
          Text("\(index + 1)")
            .font(.caption2.weight(.bold).monospacedDigit())
            .foregroundStyle(.white)
            .frame(width: 20, height: 20)
            .background(status.color, in: Circle())
          VStack(alignment: .leading, spacing: 2) {
            Text(title)
              .font(.subheadline.weight(.semibold))
              .lineLimit(2)
            HStack(spacing: 6) {
              if title != taskID {
                Text(taskID)
                  .font(.caption2.monospaced())
                  .foregroundStyle(.secondary)
              }
              if !role.isEmpty {
                Text(role)
                  .font(.caption2.weight(.medium))
                  .foregroundStyle(.secondary)
                  .padding(.horizontal, 6)
                  .padding(.vertical, 1.5)
                  .background(Color.primary.opacity(0.05), in: Capsule())
              }
              if !worker.isEmpty {
                Label(worker, systemImage: "cpu")
                  .font(.caption2.monospaced())
                  .foregroundStyle(.secondary)
              }
            }
          }
          Spacer(minLength: 6)
          FactoryStatusBadge(status: status)
        }

        if status == .running {
          ThinkingBar().frame(maxWidth: 200)
        }

        if !errorText.isEmpty {
          Label(errorText, systemImage: "exclamationmark.triangle.fill")
            .font(.caption)
            .foregroundStyle(Color(red: 0.86, green: 0.24, blue: 0.28))
            .lineLimit(3)
            .textSelection(.enabled)
        }

        if status == .waitingHuman {
          VStack(alignment: .leading, spacing: 8) {
            Label("Paused at human gate — review and decide to continue", systemImage: "hand.raised.fill")
              .font(.caption.weight(.semibold))
              .foregroundStyle(Brand.orange)
            TextField("Decision reason (required)", text: $gateReason)
              .textFieldStyle(.roundedBorder)
            HStack(spacing: 8) {
              Button("Approve stage gate", action: onApprove)
                .buttonStyle(BrandButtonStyle())
                .disabled(!idle || gateReason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
              Button("Hold stage", action: onHold)
                .disabled(!idle || gateReason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
          }
          .padding(10)
          .background(Brand.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
        }
      }
      .padding(.horizontal, 12)
      .padding(.vertical, 10)
    }
    .frame(maxWidth: .infinity, alignment: .leading)
    .brandSurface(radius: 12)
    .overlay(
      RoundedRectangle(cornerRadius: 12, style: .continuous)
        .strokeBorder(
          status.isActive || status == .failed ? status.color.opacity(0.38) : Color.clear,
          lineWidth: 1.2
        )
        .allowsHitTesting(false)
    )
  }
}
