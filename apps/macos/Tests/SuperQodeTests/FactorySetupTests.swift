import XCTest
@testable import SuperQode

final class FactorySetupTests: XCTestCase {
  private let review: [String: Any] = ["review": "native-review", "yaml": "draft", "digest": "saved", "snapshot_digest": "snapshot", "acceptance_checks": ["regression"], "application_checks": ["regression": ["evaluator": "probes"]]]
  func testAnEditedOrUnvalidatedDraftCannotAppearReady() {
    let empty = FactorySetupState(text: "", review: [:], savedDigest: "", sources: [:], runs: [])
    XCTAssertEqual(empty.action, "Load a starter")
    let changed = FactorySetupState(text: "new draft", review: review, savedDigest: "saved", sources: [:], runs: [])
    XCTAssertFalse(changed.validated); XCTAssertFalse(changed.saved); XCTAssertEqual(changed.action, "Validate draft")
  }
  func testValidationDoesNotImplySavingOrCommitting() {
    let unsaved = FactorySetupState(text: "draft", review: review, savedDigest: "old", sources: [:], runs: [])
    XCTAssertTrue(unsaved.validated); XCTAssertFalse(unsaved.saved); XCTAssertFalse(unsaved.committed)
    XCTAssertEqual(unsaved.action, "Review & save")
    let saved = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: [:], runs: [])
    XCTAssertTrue(saved.saved); XCTAssertFalse(saved.committed); XCTAssertEqual(saved.action, "Review source changes")
  }
  func testSourceEvidenceMustMatchAndEveryDeclaredSourceMustBeUnchanged() {
    for sources: [String: Any] in [
      ["snapshot_digest": "other", "files": [["changed": false]]],
      ["snapshot_digest": "snapshot", "files": [["changed": true]]],
      ["snapshot_digest": "snapshot", "files": [[:]]],
      ["snapshot_digest": "snapshot", "files": []]] {
      let state = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: sources, runs: [])
      XCTAssertFalse(state.committed)
    }
  }
  func testReadyJourneyPointsToAnExplicitTrialWithoutPretendingItRan() {
    let sources: [String: Any] = ["snapshot_digest": "snapshot", "files": [["changed": false]]]
    let ready = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: sources, runs: [["factory_digest": "other"]])
    XCTAssertTrue(ready.committed); XCTAssertFalse(ready.trialPrepared); XCTAssertEqual(ready.action, "Prepare a trial")
    let queued = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: sources, runs: [["factory_digest": "snapshot", "status": "queued"]])
    XCTAssertTrue(queued.trialPrepared); XCTAssertEqual(queued.action, "Open trials")
  }

  func testGuidedMilestonesAdvanceFromDraftToSelfImprovement() {
    let sources: [String: Any] = ["snapshot_digest": "snapshot", "files": [["changed": false]]]
    let start = FactorySetupState(text: "", review: [:], savedDigest: "", sources: [:], runs: [])
    XCTAssertEqual(start.guidedStepIndex, 0)
    XCTAssertEqual(start.nextActionTitle, "Load Fix and verify")

    let saved = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: sources, runs: [])
    XCTAssertEqual(saved.guidedStepIndex, 3)
    XCTAssertEqual(saved.nextDestination, "Runs")

    let completed = FactorySetupState(
      text: "draft",
      review: ["review": "native-review", "yaml": "draft", "digest": "saved", "snapshot_digest": "snapshot", "acceptance_checks": ["regression"], "application_checks": ["regression": ["evaluator": "probes"]]],
      savedDigest: "saved",
      sources: sources,
      runs: [["factory_digest": "snapshot", "status": "ready_to_merge", "verification_valid": true]],
      hasSuite: true,
      hasImprovement: true
    )
    XCTAssertTrue(completed.hasCompletedRun)
    XCTAssertEqual(completed.guidedStepIndex, 4)
    XCTAssertEqual(completed.completedBadgeText, "Improvement plan prepared ✓")
  }

  func testOrdinaryCompletionAndForeignReceiptsDoNotCountAsVerified() {
    for run: [String: Any] in [
      ["factory_digest": "snapshot", "status": "completed"],
      ["factory_digest": "other", "verification_valid": true],
      ["factory_digest": "snapshot", "verification_valid": false]] {
      let state = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: [:], runs: [run])
      XCTAssertFalse(state.hasCompletedRun)
    }
  }

  func testSuiteAndHumanGateDoNotSubstituteForProtectedAcceptance() {
    var ordinary = review
    ordinary["application_checks"] = ["regression": ["command": "pytest"]]
    ordinary["stages"] = [["human_gate": true]]
    let state = FactorySetupState(text: "draft", review: ordinary, savedDigest: "saved", sources: [:], runs: [], hasSuite: true)
    XCTAssertFalse(state.hasProtectedChecks)
    XCTAssertEqual(state.guidedStepIndex, 2)
    XCTAssertEqual(state.nextDestination, "Acceptance")
  }

  func testSharedChecklistCanRejectEvidenceFromAnOlderApplicationBaseline() {
    let state = FactorySetupState(text: "draft", review: review, savedDigest: "saved", sources: [:],
      runs: [["factory_digest": "snapshot", "verification_valid": true]], verifiedTrial: false)
    XCTAssertFalse(state.hasCompletedRun)
  }

  func testMergeRiskSnapshotParsesFiveDimensions() {
    let detail: [String: Any] = [
      "merge_risk": [
        "overall": "medium",
        "file_count": 3,
        "churn_lines": 42,
        "categories": [
          ["id": "alignment", "title": "Alignment", "risk": "low", "summary": "Focused scope."],
          ["id": "impact", "title": "Impact", "risk": "medium", "summary": "Touches auth."],
        ],
        "gaps": ["Verify auth path."],
        "markdown": "## Merge Risk Assessment",
      ]
    ]
    let snapshot = FactoryMergeRiskSnapshot.parse(detail: detail)
    XCTAssertNotNil(snapshot)
    XCTAssertEqual(snapshot?.overall, .medium)
    XCTAssertEqual(snapshot?.categories.count, 2)
    XCTAssertEqual(snapshot?.gaps, ["Verify auth path."])
  }

  func testRLMLineageSnapshotParsesProposal() {
    let proposal: [String: Any] = [
      "yaml": "apiVersion: superqode.dev/v1alpha1",
      "recommended_skills": [
        ["name": "merge-risk", "preset": "", "reason": "Guards auth paths"],
        ["name": "ui-verification", "preset": "macos", "reason": "Matches SwiftUI app"],
      ],
      "rlm_lineage": [
        "engine": "monty-repl",
        "mode": "rlm-live",
        "repo_files": 48,
        "repo_bytes": 128000,
        "files_inspected": ["Package.swift", "pyproject.toml"],
        "detected_stacks": ["python", "swift"],
        "detected_test_command": "pytest -q",
        "detected_build_command": "swift build",
        "sensitive_areas": ["src/auth"],
        "recommended_workflow": "triage-spec-build",
        "subcalls": [
          ["id": "subcall-1", "topic": "architecture-and-stages", "ok": true, "input_tokens": 120, "output_tokens": 45, "duration_ms": 620, "error": ""],
        ],
        "subcall_budget": ["used_calls": 1, "max_calls": 4, "total_tokens": 165],
        "duration_ms": 840,
      ],
    ]
    let snapshot = FactoryRLMLineageSnapshot.parse(proposal: proposal)
    XCTAssertNotNil(snapshot)
    XCTAssertEqual(snapshot?.engineLabel, "RLM · Monty REPL")
    XCTAssertEqual(snapshot?.modeLabel, "Live · 1/4 sub-queries")
    XCTAssertEqual(snapshot?.repoFiles, 48)
    XCTAssertEqual(snapshot?.detectedStacks, ["python", "swift"])
    XCTAssertEqual(snapshot?.recommendedSkills.count, 2)
    XCTAssertEqual(snapshot?.subcalls.count, 1)
  }
}
