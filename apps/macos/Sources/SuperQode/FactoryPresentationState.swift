import Foundation

/// Presentation playback has no engine, filesystem or release authority.
struct FactoryPresentationState: Equatable {
  enum Stage: Int, CaseIterable, Identifiable {
    case request, investigate, repair, review, verify, complete
    var id: Int { rawValue }
    var title: String {
      switch self {
      case .request: "Request"
      case .investigate: "Investigate"
      case .repair: "Repair"
      case .review: "Human review"
      case .verify: "Verify"
      case .complete: "Evidence"
      }
    }
    var symbol: String {
      switch self {
      case .request: "text.bubble"
      case .investigate: "magnifyingglass"
      case .repair: "hammer"
      case .review: "hand.raised"
      case .verify: "checkmark.shield"
      case .complete: "doc.text.magnifyingglass"
      }
    }
    var headline: String {
      switch self {
      case .request: "A small request. A clear finish line."
      case .investigate: "Find the defect before changing code."
      case .repair: "A focused repair, ready for review."
      case .review: "The factory waits for you."
      case .verify: "Test the repair against protected expectations."
      case .complete: "See the evidence behind the result."
      }
    }
    var detail: String {
      switch self {
      case .request: "The checkout total shows only the last item. Add every amount, including discounts and an empty basket."
      case .investigate: "Two amounts, 2 and 3, produce 3. The expected total is 5. A protected case captures that difference."
      case .repair: "The loop replaces the running total. Accumulating each value fixes the behavior with one changed line."
      case .review: "Inspect the proposed change. This demo pauses here until you approve the illustrated repair."
      case .verify: "Multiple items, discounts and an empty basket all meet their expectations in this scripted example."
      case .complete: "One changed line, three illustrated passing cases and a recorded review step. A real trial supplies actual usage and verification evidence."
      }
    }
  }
  private(set) var stage: Stage = .request
  private(set) var playing = false
  private(set) var reviewApproved = false
  private(set) var playbackID = 0
  var waitingForReview: Bool { stage == .review && !reviewApproved }
  var canAdvance: Bool { stage != .complete && !waitingForReview }

  mutating func play() {
    guard stage != .complete, !waitingForReview else { return }
    playing = true; playbackID += 1
  }
  mutating func pause() { playing = false; playbackID += 1 }
  @discardableResult mutating func advance() -> Bool {
    guard canAdvance, let next = Stage(rawValue: stage.rawValue + 1) else { return false }
    stage = next
    if stage == .review || stage == .complete { playing = false }
    return true
  }
  mutating func approveReview() {
    guard waitingForReview else { return }
    reviewApproved = true; stage = .verify; playing = false; playbackID += 1
  }
  mutating func back() {
    pause()
    guard let previous = Stage(rawValue: stage.rawValue - 1) else { return }
    stage = previous
    if stage.rawValue <= Stage.review.rawValue { reviewApproved = false }
  }
  mutating func reset() {
    let nextID = playbackID + 1
    self = FactoryPresentationState(); playbackID = nextID
  }
}

enum FactoryJourneyStep: Int, CaseIterable, Identifiable {
  case intent, models, review, trial, evidence
  var id: Int { rawValue }
  var title: String {
    switch self {
    case .intent: "Describe"
    case .models: "Connect"
    case .review: "Review"
    case .trial: "Run"
    case .evidence: "Verify"
    }
  }
  var symbol: String {
    switch self {
    case .intent: "text.bubble"
    case .models: "cpu"
    case .review: "slider.horizontal.3"
    case .trial: "play"
    case .evidence: "checkmark.shield"
    }
  }
  static func suggested(saved: Bool, trialPrepared: Bool, verified: Bool) -> Self {
    verified ? .evidence : trialPrepared ? .trial : saved ? .review : .intent
  }
}
