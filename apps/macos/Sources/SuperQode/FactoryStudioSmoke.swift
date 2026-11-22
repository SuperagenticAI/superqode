import Foundation

@MainActor extension Workspace {
  /// Inspect existing recovery evidence through the native app without new jobs.
  func inspectFactoryOperations() async {
    var report: [String: Any] = [:]
    do {
      guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"] ?? ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_VALIDATION_ROOT"], !projectID.isEmpty,
        URL(fileURLWithPath: string(project, "path")).standardizedFileURL.path.hasPrefix(source + "/.superqode/validation/") else {
        throw EngineError(message: "Operations inspection requires a repository-local validation project")
      }
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio; studio.enter(projectID); await studio.load(engine: engine)
      await studio.operations.refresh(engine)
      guard studio.operations.failure.isEmpty,
        let package = studio.operations.packages.first, package["verified"] as? Bool == true else {
        throw EngineError(message: "Expected verified native handover package: " + studio.operations.failure)
      }
      await studio.operations.perform(engine, "verify", ["id": string(package, "id"), "sha256": string(package, "sha256")])
      guard studio.operations.result["verified"] as? Bool == true else { throw EngineError(message: "Native package verification failed") }
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count == after.count else { throw EngineError(message: "Operations inspection started a job") }
      section = "Factory Studio"; showWelcome = false
      report = ["passed": true, "package": string(package, "id"), "verified": true,
        "new_jobs": 0, "queue_restored": false, "release_authorization": false]
    } catch { report = ["passed": false, "error": error.localizedDescription] }
    if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: destination))
    }
  }
  /// Inspect a completed metered optimiser plan without new model work.
  func inspectFactoryOptimization() async {
    var report: [String: Any] = [:]
    do {
      guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"] ?? ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_VALIDATION_ROOT"], !projectID.isEmpty,
        URL(fileURLWithPath: string(project, "path")).standardizedFileURL.path.hasPrefix(source + "/.superqode/validation/") else {
        throw EngineError(message: "Optimizer inspection requires a repository-local validation project")
      }
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio; studio.enter(projectID); await studio.load(engine: engine)
      await studio.refreshImprovements(engine: engine)
      guard let plan = studio.improvementPlans.first else { throw EngineError(message: "No prepared optimizer plan") }
      await studio.openImprovement(engine: engine, id: string(plan, "id"))
      await studio.refreshImprovementBudget(engine)
      let budget = studio.improvementPlan["budget"] as? [String: Any] ?? [:]
      let operations = budget["operations"] as? [[String: Any]] ?? []
      let phases = Set(operations.map { string($0, "phase") })
      guard studio.failure.isEmpty, budget["evidence_complete"] as? Bool == true,
        phases.isSuperset(of: ["reflection", "held-in", "held-out"]), !studio.improvementResult.isEmpty else {
        throw EngineError(message: "Incomplete native optimizer evidence: " + studio.failure)
      }
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count == after.count else { throw EngineError(message: "Inspection started an optimizer job") }
      section = "Factory Studio"; showWelcome = false
      report = ["passed": true, "plan": string(plan, "id"), "optimizer": string(plan, "optimizer_engine"),
        "request_count": budget["request_count"] ?? 0, "phases": phases.sorted(),
        "budget_complete": true, "comparison_eligible": studio.improvementResult["eligible"] as? Bool ?? false,
        "new_jobs": 0, "promotion_authority": false]
    } catch { report = ["passed": false, "error": error.localizedDescription] }
    if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: destination))
    }
  }
  /// Inspect recorded feedback through native RPCs. No review, inference or execution.
  func inspectFactoryFeedback() async {
    var report: [String: Any] = [:]
    do {
      guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"], !projectID.isEmpty,
        URL(fileURLWithPath: string(project, "path")).standardizedFileURL.path.hasPrefix(source + "/.superqode/validation/") else {
        throw EngineError(message: "Feedback inspection requires a repository-local validation project")
      }
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio; studio.enter(projectID); await studio.load(engine: engine)
      let suites = studio.trialSuites; await suites.refresh(engine)
      let feedback = suites.feedback; await feedback.refresh(engine)
      guard let issue = feedback.issues.first else { throw EngineError(message: "No recorded feedback: " + feedback.failure) }
      await feedback.select(engine, id: string(issue, "id"))
      let observations = feedback.detail["observations"] as? [[String: Any]] ?? []
      guard feedback.failure.isEmpty, !observations.isEmpty, observations.allSatisfy({ $0["source_valid"] as? Bool == true }), !feedback.proposal.isEmpty else {
        throw EngineError(message: "Expected source-verified feedback and a proposal: " + feedback.failure)
      }
      let evaluations = feedback.proposal["evaluations"] as? [[String: Any]] ?? []
      let measurement = evaluations.last ?? [:]
      suites.selected = string(measurement, "suite", observations.first.map { string($0, "suite") } ?? "")
      await suites.inspect(engine)
      guard suites.failure.isEmpty else { throw EngineError(message: suites.failure) }
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count == after.count else { throw EngineError(message: "Feedback inspection started a job") }
      section = "Factory Studio"; showWelcome = false
      report = ["passed": true, "issue": feedback.selected, "observations": observations.count,
        "reused_outcomes": observations.filter { $0["reused_outcome"] as? Bool == true }.count,
        "suggested_category": string(feedback.detail, "suggested_category"), "proposal_status": string(feedback.proposal, "status"),
        "linked_evaluations": evaluations.count, "linked_verdict": string(measurement, "verdict"), "selected_suite": suites.selected,
        "new_jobs": 0, "promotion_authority": feedback.proposal["promotion_authority"] as? Bool ?? true]
    } catch { report = ["passed": false, "error": error.localizedDescription] }
    if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: destination))
    }
  }
  /// Read an existing suite scorecard using the actual native client, without execution.
  func inspectFactorySuite() async {
    var report: [String: Any] = [:]
    do {
      guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"], !projectID.isEmpty,
        URL(fileURLWithPath: string(project, "path")).standardizedFileURL.path.hasPrefix(source + "/.superqode/validation/") else {
        throw EngineError(message: "Suite inspection requires a repository-local validation project")
      }
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio; studio.enter(projectID); await studio.load(engine: engine)
      let suites = studio.trialSuites; await suites.refresh(engine)
      guard let plan = suites.plans.first else { throw EngineError(message: "No prepared suite: " + suites.failure) }
      suites.selected = string(plan, "id"); await suites.inspect(engine)
      guard suites.failure.isEmpty, let row = (suites.board["entries"] as? [[String: Any]])?.last else { throw EngineError(message: suites.failure) }
      suites.entry = string(row, "id"); await suites.inspectEntry(engine)
      guard suites.failure.isEmpty, !suites.detail.isEmpty else { throw EngineError(message: suites.failure) }
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count == after.count else { throw EngineError(message: "Inspection started a job") }
      section = "Factory Studio"; showWelcome = false
      report = ["passed": true, "suite": suites.selected, "verdict": string(suites.board, "verdict"), "entries": (suites.board["entries"] as? [[String: Any]] ?? []).count, "new_jobs": 0, "promotion_authority": suites.board["promotion_authority"] as? Bool ?? true]
      report["inspected_handoffs"] = (suites.detail["handoffs"] as? [[String: Any]] ?? []).count
      report["inspected_skipped_stages"] = (suites.detail["skipped"] as? [[String: Any]] ?? []).count
    } catch { report = ["passed": false, "error": error.localizedDescription] }
    if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: destination))
    }
  }
  /// Open completed real-model demo evidence without modifying its Factory or running jobs.
  func inspectFactoryDemo() async {
    var report: [String: Any] = [:]
    do {
      guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"],
        !projectID.isEmpty,
        URL(fileURLWithPath: string(project, "path")).standardizedFileURL.path.hasPrefix(source + "/.superqode/validation/") else {
        throw EngineError(message: "Demo inspection requires a repository-local validation project")
      }
      let path = URL(fileURLWithPath: string(project, "path")).appendingPathComponent(".superqode/factory.yaml")
      let definition = try Data(contentsOf: path)
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio; studio.enter(projectID)
      await studio.load(engine: engine); await studio.refresh(engine: engine)
      guard studio.failure.isEmpty, let run = studio.runs.first else { throw EngineError(message: "No completed Factory evidence: " + studio.failure) }
      studio.run = string(run, "id"); await studio.inspect(engine: engine)
      let order = studio.detail["work_order"] as? [String: Any] ?? [:]
      guard studio.failure.isEmpty, string(order, "status") == "merged" else { throw EngineError(message: "Expected a completed demo run: " + studio.failure) }
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count == after.count, try Data(contentsOf: path) == definition else { throw EngineError(message: "Evidence inspection changed the demo or started a job") }
      section = "Factory Studio"; showWelcome = false
      report = ["passed": true, "run": studio.run, "project": string(project, "path"), "status": "merged", "factory_unchanged": true, "new_jobs": 0]
    } catch { report = ["passed": false, "error": error.localizedDescription] }
    if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_INSPECT_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys]).write(to: URL(fileURLWithPath: destination))
    }
  }
  /// Source-development fixture only: no model calls, signing enrollment or delivery.
  func smokeFactoryStudio() async {
    var report: [String: Any] = [:]
    do {
      guard !projectID.isEmpty else { throw EngineError(message: "Factory smoke requires a fixture --project") }
      let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      let studio = factoryStudio; studio.enter(projectID)
      await studio.load(engine: engine, template: "fix-and-verify")
      await studio.validate(engine: engine)
      guard !studio.review.isEmpty else { throw EngineError(message: studio.failure) }
      report["seven_layers"] = studio.review["layers"]
      await studio.save(engine: engine, reason: "Native Factory Studio fixture")
      guard studio.failure.isEmpty, !studio.revisions.isEmpty else { throw EngineError(message: studio.failure) }
      var expectedNewJobs = 0
      if ProcessInfo.processInfo.arguments.contains("--factory-source-commit-fixture") {
        // This opt-in smoke can only commit to a marked, repository-local fixture.
        guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"] else {
          throw EngineError(message: "Source commit smoke requires a development checkout")
        }
        let fixture = string(project, "path")
        let base = URL(fileURLWithPath: source).appendingPathComponent(".superqode/validation").standardizedFileURL.path + "/"
        guard URL(fileURLWithPath: fixture).standardizedFileURL.path.hasPrefix(base),
          FileManager.default.fileExists(atPath: fixture + "/.superqode/source-smoke-fixture") else {
          throw EngineError(message: "Source commit smoke is restricted to a marked validation fixture")
        }
        await studio.refreshSources(engine: engine)
        guard studio.failure.isEmpty, !studio.sourceReview.isEmpty else { throw EngineError(message: studio.failure) }
        let rows = studio.sourceReview["files"] as? [[String: Any]] ?? []
        let paths = rows.filter { $0["changed"] as? Bool == true }.map { string($0, "path") }
        guard paths == [".superqode/factory.yaml"] else { throw EngineError(message: "Unexpected source smoke commit selection") }
        await studio.commitSources(engine: engine, paths: paths, message: "Version native Factory fixture")
        let result = studio.job["result"] as? [String: Any] ?? [:]
        guard studio.failure.isEmpty, string(studio.job, "status") == "completed", !string(result, "sha").isEmpty,
          (studio.sourceReview["files"] as? [[String: Any]] ?? []).allSatisfy({ $0["changed"] as? Bool == false }) else {
          throw EngineError(message: "Native source commit failed: " + studio.failure)
        }
        expectedNewJobs = 1
        report["source_commit"] = ["sha": string(result, "sha"), "paths": paths, "pushed": result["pushed"] as? Bool ?? true]
      }
      if ProcessInfo.processInfo.arguments.contains("--factory-improvement-fixture") {
        guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"],
          string(project, "path").hasPrefix(source + "/.superqode/validation/") else {
          throw EngineError(message: "Improvement smoke requires a repository-local validation fixture")
        }
        let suitePath = ".superqode/evals/native-improvement.yaml"
        let suite = try await engine.call("factory.improvement.suite.open", ["project": projectID, "path": suitePath]) as? [String: Any] ?? [:]
        _ = try await engine.call("factory.improvement.suite.save", ["project": projectID, "path": suitePath,
          "yaml": string(suite, "yaml"), "expected_file_digest": string(suite, "expected_file_digest")])
        await studio.prepareImprovement(engine: engine, params: ["binding": "coder", "tasks": suitePath,
          "fixture": "@empty", "max_evals": 1, "max_seconds": 30, "reflection_model": ""])
        guard studio.failure.isEmpty, !studio.improvementPlan.isEmpty else { throw EngineError(message: studio.failure) }
        let candidate = string(studio.improvementPlan, "baseline_yaml").replacingOccurrences(of: "role: implementation", with: "role: careful implementation")
        await studio.proposeImprovement(engine: engine, yaml: candidate)
        guard studio.failure.isEmpty, !studio.improvementCandidate.isEmpty,
          !string(studio.improvementPreview, "diff").isEmpty else { throw EngineError(message: studio.failure) }
        var rejected = false
        do { _ = try await engine.call("factory.improvement.adopt", ["project": projectID,
          "plan": string(studio.improvementPlan, "id"), "candidate": studio.improvementCandidate,
          "comparison_job": "invented", "confirmed": true]) }
        catch { rejected = true }
        guard rejected else { throw EngineError(message: "Imported proposal acquired unearned adoption authority") }
        report["improvement"] = ["suite_edit": true, "pinned_plan": true, "candidate_audit": true,
          "diff_review": true, "unearned_adoption_rejected": true, "model_calls": 0]
      }
      if ProcessInfo.processInfo.arguments.contains("--factory-skill-fixture") {
        guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"],
          string(project, "path").hasPrefix(source + "/.superqode/validation/") else {
          throw EngineError(message: "Skill smoke requires a repository-local validation fixture")
        }
        let markdown = "---\nname: review\ndescription: Native skill fixture\n---\nCheck the requested output format.\n"
        guard await studio.createBoundSkill(engine: engine, binding: "coder", id: "review", markdown: markdown) else {
          throw EngineError(message: studio.failure)
        }
        await studio.save(engine: engine, reason: "Bind native skill fixture")
        guard studio.failure.isEmpty else { throw EngineError(message: studio.failure) }
        let cap = try await studio.rpc(engine, "improvement.capabilities")
        guard (cap["bound_skills"] as? [String: [String]])?["coder"] == ["review"] else {
          throw EngineError(message: "Saved skill binding was not exposed")
        }
        let suitePath = ".superqode/evals/native-skill.yaml"
        let suite = try await studio.rpc(engine, "improvement.suite.open", ["path": suitePath])
        _ = try await studio.rpc(engine, "improvement.suite.save", ["path": suitePath,
          "yaml": string(suite, "yaml"), "expected_file_digest": string(suite, "expected_file_digest")])
        await studio.prepareImprovement(engine: engine, params: ["binding": "coder", "target_kind": "skill",
          "skill": "review", "tasks": suitePath, "fixture": "@empty", "max_evals": 1, "max_seconds": 30, "reflection_model": ""])
        guard studio.failure.isEmpty, string(studio.improvementPlan, "baseline_yaml") == markdown else {
          throw EngineError(message: "Native skill preparation failed: " + studio.failure)
        }
        await studio.proposeImprovement(engine: engine, yaml: markdown.replacingOccurrences(of: "Check the requested output format.", with: "Check the requested output format and verify the response."))
        guard studio.failure.isEmpty, !studio.improvementCandidate.isEmpty,
          string(studio.improvementPreview, "diff").contains("verify the response") else {
          throw EngineError(message: "Native skill proposal failed: " + studio.failure)
        }
        var rejected = false
        do { _ = try await studio.rpc(engine, "improvement.adopt", ["plan": string(studio.improvementPlan, "id"),
          "candidate": studio.improvementCandidate, "comparison_job": "invented", "confirmed": true]) }
        catch { rejected = true }
        guard rejected else { throw EngineError(message: "Skill proposal acquired unearned authority") }
        report["skill_improvement"] = ["created_and_bound": true, "saved_binding": true, "pinned_markdown": true,
          "body_diff": true, "unearned_adoption_rejected": true, "model_calls": 0]
      }
      if ProcessInfo.processInfo.arguments.contains("--factory-route-workflow-fixture") {
        guard let source = ProcessInfo.processInfo.environment["SUPERQODE_SOURCE_ROOT"],
          string(project, "path").hasPrefix(source + "/.superqode/validation/") else {
          throw EngineError(message: "Route/workflow smoke requires a repository-local validation fixture")
        }
        let suitePath = ".superqode/evals/native-route-workflow.yaml"
        let suite = try await studio.rpc(engine, "improvement.suite.open", ["path": suitePath])
        _ = try await studio.rpc(engine, "improvement.suite.save", ["path": suitePath,
          "yaml": string(suite, "yaml"), "expected_file_digest": string(suite, "expected_file_digest")])
        for kind in ["route", "workflow"] {
          await studio.prepareImprovement(engine: engine, params: ["binding": "coder", "target_kind": kind,
            "stage": "investigate", "route_models": ["ollama/qwen3-coder", "lmstudio/native-candidate"],
            "tasks": suitePath, "fixture": "@empty", "max_evals": 1, "max_seconds": 30, "reflection_model": ""])
          guard studio.failure.isEmpty, string(studio.improvementPlan, "target_kind") == kind else {
            throw EngineError(message: "Native adapter preparation failed: " + studio.failure)
          }
          let candidate = kind == "route" ? "model: lmstudio/native-candidate\n"
            : "stage: investigate\ngoal: Inspect the requested output and report concrete evidence.\n"
          await studio.proposeImprovement(engine: engine, yaml: candidate)
          guard studio.failure.isEmpty, !studio.improvementCandidate.isEmpty,
            !string(studio.improvementPreview, "diff").isEmpty else {
            throw EngineError(message: "Native adapter proposal failed: " + studio.failure)
          }
          let reopened = try await studio.rpc(engine, "improvement.open", ["plan": string(studio.improvementPlan, "id")])
          guard (reopened["candidates"] as? [String] ?? []).contains(studio.improvementCandidate) else {
            throw EngineError(message: "Adapter history lost the staged proposal")
          }
          var rejected = false
          do { _ = try await studio.rpc(engine, "improvement.adopt", ["plan": string(studio.improvementPlan, "id"),
            "candidate": studio.improvementCandidate, "comparison_job": "invented", "confirmed": true]) }
          catch { rejected = true }
          guard rejected else { throw EngineError(message: "Adapter proposal acquired unearned authority") }
          report[kind + "_improvement"] = ["pinned_plan": true, "candidate_diff": true,
            "history_reopened": true, "unearned_adoption_rejected": true, "model_calls": 0]
        }
        var gatedRejected = false
        do { _ = try await studio.rpc(engine, "improvement.prepare", ["binding": "coder", "target_kind": "workflow",
          "stage": "verify", "tasks": suitePath, "fixture": "@empty", "max_evals": 1, "max_seconds": 30, "reflection_model": ""]) }
        catch { gatedRejected = true }
        guard gatedRejected else { throw EngineError(message: "Adapter bypassed the workflow human gate") }
        report["workflow_human_gate_preserved"] = true
      }
      await studio.trial(engine: engine, goal: "Inspect a synthetic factory fixture without model execution")
      guard studio.failure.isEmpty, !studio.run.isEmpty, !studio.detail.isEmpty else { throw EngineError(message: studio.failure) }
      let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
      guard before.count + expectedNewJobs == after.count else { throw EngineError(message: "Preparation unexpectedly started a job") }
      section = "Factory Studio"; showWelcome = false
      report["passed"] = true
      report["checks"] = ["native client validation", "revision save and history", "pinned trial", "run inspection", "no model execution jobs"]
      report["work_order"] = studio.run
    } catch { report["passed"] = false; report["error"] = error.localizedDescription }
    if let destination = ProcessInfo.processInfo.environment["SUPERQODE_FACTORY_SMOKE_REPORT"] {
      try? JSONSerialization.data(withJSONObject: report, options: [.prettyPrinted, .sortedKeys])
        .write(to: URL(fileURLWithPath: destination))
    }
  }
}
