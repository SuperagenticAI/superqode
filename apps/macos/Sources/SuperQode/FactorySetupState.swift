import Foundation

/// Progress is derived from matching evidence, never from the page a user visited.
struct FactorySetupState {
  struct GuidedMilestone: Equatable, Identifiable {
    let id: String
    let number: Int
    let title: String
    let completed: Bool
    let destination: String
  }

  let hasDraft: Bool
  let validated: Bool
  let saved: Bool
  let committed: Bool
  let trialPrepared: Bool
  let hasCompletedRun: Bool
  let hasHumanGate: Bool
  let hasChecksOrSuite: Bool
  let hasProtectedChecks: Bool
  let hasImprovement: Bool

  init(
    text: String,
    review: [String: Any],
    savedDigest: String,
    sources: [String: Any],
    runs: [[String: Any]],
    hasSuite: Bool = false,
    hasImprovement: Bool = false,
    verifiedTrial: Bool? = nil
  ) {
    hasDraft = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    validated = hasDraft && string(review, "yaml") == text && !string(review, "review").isEmpty
    saved = validated && !savedDigest.isEmpty && string(review, "digest") == savedDigest
    let snapshot = string(review, "snapshot_digest")
    let files = sources["files"] as? [[String: Any]] ?? []
    committed = saved && !snapshot.isEmpty && string(sources, "snapshot_digest") == snapshot
      && !files.isEmpty && files.allSatisfy { $0["changed"] as? Bool == false }
    trialPrepared = saved && !snapshot.isEmpty && runs.contains { string($0, "factory_digest") == snapshot }
    hasCompletedRun = (verifiedTrial ?? true) && runs.contains {
      string($0, "factory_digest") == snapshot && !snapshot.isEmpty
        && ($0["verification_valid"] as? Bool) == true
    }
    let stages = review["stages"] as? [[String: Any]] ?? []
    hasHumanGate = stages.contains { $0["human_gate"] as? Bool == true }
    let acceptanceChecks = review["acceptance_checks"] as? [String] ?? []
    let configured = review["application_checks"] as? [String: [String: Any]] ?? [:]
    hasProtectedChecks = !acceptanceChecks.isEmpty && acceptanceChecks.allSatisfy {
      !string(configured[$0] ?? [:], "evaluator").isEmpty
    }
    hasChecksOrSuite = hasProtectedChecks
    self.hasImprovement = hasImprovement
  }

  var step: Int { !hasDraft ? 0 : !validated || !saved ? 1 : !committed ? 2 : 3 }

  var action: String {
    !hasDraft ? "Load a starter" : !validated ? "Validate draft" : !saved ? "Review & save"
      : !hasProtectedChecks ? "Configure acceptance" : !committed ? "Review source changes" : trialPrepared ? "Open trials" : "Prepare a trial"
  }

  var milestones: [GuidedMilestone] {
    [
      GuidedMilestone(id: "starter", number: 1, title: "Pick workflow", completed: hasDraft, destination: "Stack"),
      GuidedMilestone(id: "save", number: 2, title: "Check & save", completed: saved, destination: "Definition"),
      GuidedMilestone(id: "protect", number: 3, title: "Acceptance", completed: hasProtectedChecks, destination: "Acceptance"),
      GuidedMilestone(id: "trial", number: 4, title: "Verified trial", completed: hasCompletedRun, destination: "Runs"),
      GuidedMilestone(id: "improve", number: 5, title: "Measure & improve", completed: hasImprovement, destination: "Improve"),
    ]
  }

  var guidedStepIndex: Int {
    if !hasDraft { return 0 }
    if !saved { return 1 }
    if !hasProtectedChecks { return 2 }
    if !hasCompletedRun { return 3 }
    return 4
  }

  var completedBadgeText: String {
    if !hasDraft { return "Step 1 of 5" }
    if !validated { return "Starter loaded ✓" }
    if !saved { return "Definition checked ✓" }
    if !hasProtectedChecks { return "Revision saved ✓" }
    if !committed { return "Revision saved ✓" }
    if !trialPrepared && !hasCompletedRun { return "Sources ready ✓" }
    if !hasCompletedRun { return "Trial prepared ✓" }
    if !hasImprovement { return "First trial complete ✓" }
    return "Improvement plan prepared ✓"
  }

  var nextTitle: String {
    if !hasDraft { return "Pick a starter workflow" }
    if !validated { return "Check your factory definition" }
    if !saved { return "Save this checked revision" }
    if !hasProtectedChecks { return "Add protected acceptance checks" }
    if !committed { return "Review factory files in Source control" }
    if !trialPrepared && !hasCompletedRun { return "Prepare and run your first trial" }
    if !hasCompletedRun { return "Run ready stages and verify with SuperGauge" }
    return "Measure with Trial Suites or run Improve"
  }

  var nextDetail: String {
    if !hasDraft {
      return "Choose Fix and verify for a quick first run, or Triage, spec & build to gate ambiguous work before coding. No model call yet."
    }
    if !validated {
      return "Validate your draft locally to verify stages, contracts, and permissions before saving."
    }
    if !saved {
      return "Your draft passed checks. Save the revision so trials can pin an immutable snapshot."
    }
    if !hasProtectedChecks {
      return "Configure and independently review protected probe expectations. Ordinary tests, skills and human gates do not establish protected acceptance."
    }
    if !committed {
      return "Your factory is defined as code. Review or commit factory files before pinning a trial."
    }
    if !trialPrepared && !hasCompletedRun {
      return "Open Single trial, enter a concrete goal (or pick a sample chip), and prepare your first run."
    }
    if !hasCompletedRun {
      return "Run the ready stages in isolated worktrees, approve any human gates, then verify with SuperGauge."
    }
    return "Build a Trial Suite from real tasks and let Native, GEPA, MetaHarness, or Omni propose measured changes for review."
  }

  var nextActionTitle: String {
    if !hasDraft { return "Load Fix and verify" }
    if !validated { return "Check definition" }
    if !saved { return "Save revision…" }
    if !hasProtectedChecks { return "Open Acceptance →" }
    if !committed { return "Review sources →" }
    if !trialPrepared && !hasCompletedRun { return "Go to Single trial →" }
    if !hasCompletedRun { return "Open active trial →" }
    return "Open Improve →"
  }

  var nextDestination: String {
    if !hasDraft { return "Stack" }
    if !validated || !saved { return "Definition" }
    if !hasProtectedChecks { return "Acceptance" }
    if !committed { return "Sources" }
    if !hasCompletedRun { return "Runs" }
    return "Improve"
  }
}
