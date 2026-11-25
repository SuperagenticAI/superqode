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
  let hasImprovement: Bool

  init(
    text: String,
    review: [String: Any],
    savedDigest: String,
    sources: [String: Any],
    runs: [[String: Any]],
    hasSuite: Bool = false,
    hasImprovement: Bool = false
  ) {
    hasDraft = !text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
    validated = hasDraft && string(review, "yaml") == text && !string(review, "review").isEmpty
    saved = validated && !savedDigest.isEmpty && string(review, "digest") == savedDigest
    let snapshot = string(review, "snapshot_digest")
    let files = sources["files"] as? [[String: Any]] ?? []
    committed = saved && !snapshot.isEmpty && string(sources, "snapshot_digest") == snapshot
      && !files.isEmpty && files.allSatisfy { $0["changed"] as? Bool == false }
    trialPrepared = saved && !snapshot.isEmpty && runs.contains { string($0, "factory_digest") == snapshot }
    hasCompletedRun = runs.contains {
      let status = string($0, "status").lowercased()
      return status == "completed" || status == "succeeded" || status == "shipped" || status == "ready_to_merge"
    }
    let stages = review["stages"] as? [[String: Any]] ?? []
    hasHumanGate = stages.contains { $0["human_gate"] as? Bool == true }
    let acceptanceChecks = review["acceptance_checks"] as? [Any] ?? []
    hasChecksOrSuite = hasSuite || !acceptanceChecks.isEmpty || hasHumanGate
    self.hasImprovement = hasImprovement
  }

  var step: Int { !hasDraft ? 0 : !validated || !saved ? 1 : !committed ? 2 : 3 }

  var action: String {
    !hasDraft ? "Load a starter" : !validated ? "Validate draft" : !saved ? "Review & save"
      : !committed ? "Review source changes" : trialPrepared ? "Open trials" : "Prepare a trial"
  }

  var milestones: [GuidedMilestone] {
    [
      GuidedMilestone(id: "starter", number: 1, title: "Pick workflow", completed: hasDraft, destination: "Stack"),
      GuidedMilestone(id: "save", number: 2, title: "Check & save", completed: saved, destination: "Definition"),
      GuidedMilestone(id: "trial", number: 3, title: "First trial", completed: hasCompletedRun, destination: "Runs"),
      GuidedMilestone(id: "protect", number: 4, title: "Checks & gates", completed: hasCompletedRun && hasChecksOrSuite, destination: "Acceptance"),
      GuidedMilestone(id: "improve", number: 5, title: "Measure & improve", completed: hasImprovement, destination: "Improve"),
    ]
  }

  var guidedStepIndex: Int {
    if !hasDraft { return 0 }
    if !saved { return 1 }
    if !hasCompletedRun { return 2 }
    if !hasChecksOrSuite { return 3 }
    return 4
  }

  var completedBadgeText: String {
    if !hasDraft { return "Step 1 of 5" }
    if !validated { return "Starter loaded ✓" }
    if !saved { return "Definition checked ✓" }
    if !committed { return "Revision saved ✓" }
    if !trialPrepared && !hasCompletedRun { return "Sources ready ✓" }
    if !hasCompletedRun { return "Trial prepared ✓" }
    if !hasImprovement { return "First trial complete ✓" }
    return "Self-improving loop active ✓"
  }

  var nextTitle: String {
    if !hasDraft { return "Pick a starter workflow" }
    if !validated { return "Check your factory definition" }
    if !saved { return "Save this checked revision" }
    if !committed { return "Review factory files in Source control" }
    if !trialPrepared && !hasCompletedRun { return "Prepare and run your first trial" }
    if !hasCompletedRun { return "Run ready stages and verify with SuperGauge" }
    if !hasChecksOrSuite { return "Add protected checks or a Trial Suite" }
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
    if !committed {
      return "Your factory is defined as code. Review or commit factory files before pinning a trial."
    }
    if !trialPrepared && !hasCompletedRun {
      return "Open Single trial, enter a concrete goal (or pick a sample chip), and prepare your first run."
    }
    if !hasCompletedRun {
      return "Run the ready stages in isolated worktrees, approve any human gates, then verify with SuperGauge."
    }
    if !hasChecksOrSuite {
      return "Add a protected acceptance check or attach the merge-risk and ui-verification skills to build review trust."
    }
    return "Build a Trial Suite from real tasks and let Native, GEPA, MetaHarness, or Omni propose verified upgrades."
  }

  var nextActionTitle: String {
    if !hasDraft { return "Load Fix and verify" }
    if !validated { return "Check definition" }
    if !saved { return "Save revision…" }
    if !committed { return "Review sources →" }
    if !trialPrepared && !hasCompletedRun { return "Go to Single trial →" }
    if !hasCompletedRun { return "Open active trial →" }
    if !hasChecksOrSuite { return "Open Acceptance →" }
    return "Open Improve →"
  }

  var nextDestination: String {
    if !hasDraft { return "Stack" }
    if !validated || !saved { return "Definition" }
    if !committed { return "Sources" }
    if !hasCompletedRun { return "Runs" }
    if !hasChecksOrSuite { return "Acceptance" }
    return "Improve"
  }
}
