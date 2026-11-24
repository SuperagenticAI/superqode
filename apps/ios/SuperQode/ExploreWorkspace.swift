import Foundation

/// Offline sample workspace, always labelled and incapable of executing actions.
enum ExploreWorkspace {
  static let project = "sample-workspace"
  static let profile = "sample-local-qwen"
  static let conversation = "sample-conversation"
  static let evaluation = "sample-evaluation"
  static let failedRun = "sample-failed"
  static let failure = "The local model server is unavailable. Start Ollama on your Mac, then check this connection."
  static let address = "https://studio-mac.sample-tailnet.ts.net:47832"
  static let prompt = "Make the request queue resilient to reconnects and show me the tests."
  static let answer = """
    ## The queue now resumes safely

    Each request keeps its original identity across a reconnect. The Mac returns the existing run instead of starting it twice.

    ```swift
    struct CodingRequest: Codable {
      let id: UUID
      let prompt: String
    }

    func resume(_ request: CodingRequest) async throws {
      let state = try await engine.status(request.id)
      guard state == .notStarted else { return }
      try await engine.submit(request)
    }
    ```

    - Preserved pending requests across reconnects.
    - Added a regression check for repeated delivery.
    - Kept execution on the Mac.

    **3 tests passed.** The changes are ready for your review.
    """
  static let profileRecord = RemoteRecord(raw: [
    "id": .string(profile), "name": .string("Qwen · Local"), "project": .string(project),
    "harness": .string("core"), "provider": .string("ollama"), "model": .string("qwen3-coder:30b"),
    "local_only": .bool(true), "evaluation": .bool(true), "optimization": .bool(false), "chat": .bool(true),
    "enforces_controls": .bool(true), "permission_note": .string("Ask before edits and commands"),
  ])
  static let jobs: [RemoteRecord] = [
    RemoteRecord(raw: ["id": .string(conversation), "project": .string(project), "kind": .string("task"),
      "conversation_id": .string(conversation), "conversation_title": .string("A queue that picks up where you left off"),
      "title": .string(prompt), "status": .string("completed"), "harness": .string("core"), "pinned": .bool(true), "updated": .number(1_799_000_000)]),
    RemoteRecord(raw: ["id": .string(evaluation), "project": .string(project), "kind": .string("evaluation"),
      "title": .string("Routing decisions · held-out evaluation"), "status": .string("completed"), "harness": .string("core"), "updated": .number(1_798_999_000)]),
    RemoteRecord(raw: ["id": .string("sample-approval"), "project": .string(project), "kind": .string("task"),
      "title": .string("Run the final regression checks"), "conversation_title": .string("One last check before the review"), "status": .string("needs_approval"), "harness": .string("core"), "updated": .number(1_799_001_000)]),
    RemoteRecord(raw: ["id": .string(failedRun), "project": .string(project), "kind": .string("task"),
      "title": .string("Check the local connection"), "status": .string("failed"), "harness": .string("core"), "updated": .number(1_798_998_000)]),
  ]
  static let permissions: [String] = ["read", "tasks", "evaluate", "approve", "cancel", "steer", "edit", "queue", "restore"]
  static var catalog: JSONValue {
    .object(["protocol": .number(1), "device": .object(["name": .string("Sample iPhone")]),
      "permissions": .array(permissions.map(JSONValue.string)), "profiles": .array([.object(profileRecord.raw)]),
      "suites": .array([.object(["id": .string("decision-routing"), "name": .string("Labelled route decisions"), "description": .string("Sample evaluation suite"), "tasks": .number(6)])]),
      "features": .object([
        "threads": .array(["search", "pagination", "rename", "pin", "archive"].map(JSONValue.string)),
        "request_reconciliation": .bool(true),
        "context_files": .bool(true),
        "editing": .bool(true),
        "image_upload": .bool(true),
        "queue_management": .bool(true),
        "checkpoint_restore": .bool(true),
        "review_stage": .bool(true),
        "turn_changes": .bool(true),
        "factory_gates": .bool(true),
        "project_inspection": .array(["review", "checkpoints", "queue", "workorders", "factory"].map(JSONValue.string)),
      ]),
    ])
  }
  static let sampleQualityRecord: String = """
    {"profile":{"id":"sg/coding-agent","tier":"standard"},"decision":{"verdict":"ship","reasons":["All 4 held-out checks passed in an isolated container"]},"task_set":{"held_out":4},"measures":[{"name":"task.completion","value":1.0},{"name":"assurance.evidence_complete","value":true}],"gates":[{"name":"safety.isolation","status":"pass"},{"name":"assurance.evaluator_hidden","status":"pass"},{"name":"assurance.contamination","status":"pass"}],"subject":{"authority":{"sandbox":"container"}}}
    """
  static let result: JSONValue = {
    guard let url = Bundle.main.url(forResource: "SampleEvaluation", withExtension: "json"),
      let bytes = try? Data(contentsOf: url), let value = try? JSONDecoder().decode(JSONValue.self, from: bytes) else { return .object(["summary": .string("Sample evidence is unavailable.")]) }
    return value
  }()
  static let reviewFile: [String: JSONValue] = ["id": .string("sample-file"), "path": .string("Sources/RequestQueue.swift"), "layer": .string("unstaged"), "change": .string("M")]
  static let reviewHunk: JSONValue = .object(["id": .number(0), "header": .string("@@ -1,2 +1,3 @@"), "lines": .array([
    .object(["kind": .string("context"), "text": .string("import Foundation"), "old_line": .number(1), "new_line": .number(1)]),
    .object(["kind": .string("delete"), "text": .string("await queue.start(prompt)"), "old_line": .number(2), "new_line": .null]),
    .object(["kind": .string("add"), "text": .string("let state = try await queue.status(request.id)"), "old_line": .null, "new_line": .number(2)]),
    .object(["kind": .string("add"), "text": .string("guard state == .notStarted else { return }"), "old_line": .null, "new_line": .number(3)]),
  ])])
}

struct ExploreTransport: CompanionTransport {
  func post(_ path: String, _ payload: [String: JSONValue], key: String?) async throws -> JSONValue {
    throw CompanionError("Explore mode cannot pair a device or execute a request. Connect your own Mac to continue.")
  }
  func rpc(_ method: String, _ params: [String: JSONValue], key: String?) async throws -> JSONValue {
    switch method {
    case "companion.catalog": return ExploreWorkspace.catalog
    case "projects.list": return .array([.object(["id": .string(ExploreWorkspace.project), "name": .string("SuperQode Studio")])])
    case "jobs.list": return .array(ExploreWorkspace.jobs.map { .object($0.raw) })
    case "threads.list":
      let query = params.text("query").lowercased()
      let items = ExploreWorkspace.jobs.filter { $0.text("kind") == "task" && (params.text("view") != "pinned" || $0.flag("pinned")) && (query.isEmpty || $0.text("conversation_title").lowercased().contains(query)) }
      return .object(["items": .array(params.text("view") == "archived" ? [] : items.map { .object($0.raw) }), "next_cursor": .string("")])
    case "jobs.get":
      let id = params.text("id")
      var record = (ExploreWorkspace.jobs.first { $0.id == id } ?? ExploreWorkspace.jobs[0]).raw
      record["request"] = .object(["prompt": .string(ExploreWorkspace.prompt), "model": .string("qwen3-coder:30b"), "harness": .string("core")])
      record["started_at"] = .number(1_798_999_958)
      record["finished_at"] = .number(1_799_000_000)
      let samplePlan: JSONValue = .object([
        "sequence": .number(1),
        "type": .string("harness_event"),
        "data": .object([
          "event": .string("plan"),
          "payload": .object([
            "entries": .array([
              .object(["id": .string("1"), "content": .string("Inspect request idempotency across reconnects"), "status": .string("completed")]),
              .object(["id": .string("2"), "content": .string("Add regression tests for repeated delivery"), "status": .string("completed")]),
              .object(["id": .string("3"), "content": .string("Verify clean git diff and checkpoint"), "status": .string("completed")]),
            ])
          ]),
        ]),
      ])
      let events: [JSONValue] = params.number("after") > 0 || id == ExploreWorkspace.evaluation
        ? []
        : [
          samplePlan,
          .object(["sequence": .number(2), "type": .string("answer"), "data": .object(["text": .string(ExploreWorkspace.answer)])]),
        ]
      record["events"] = .array(events)
      if id == ExploreWorkspace.conversation {
        record["result"] = .object([
          "usage_summary": .object(["tokens_in": .number(1840), "tokens_out": .number(420), "total_tokens": .number(2260), "cost": .number(0.0)])
        ])
      }
      if id == ExploreWorkspace.failedRun {
        record["result"] = .object(["error": .string(ExploreWorkspace.failure)])
        record["events"] = .array(params.number("after") > 0 ? [] : [.object(["sequence": .number(1), "type": .string("error"), "data": .object(["message": .string(ExploreWorkspace.failure)])])])
      }
      record["next_sequence"] = .number(2)
      record["has_more_events"] = .bool(false)
      if id == ExploreWorkspace.evaluation {
        record["result"] = ExploreWorkspace.result
        record["request"] = .object(["model": .string("qwen3-coder:30b"), "harness": .string("core")])
      }
      if id == "sample-approval" {
        record["finished_at"] = .null
        record["pending_approval"] = .object(["request_id": .string("sample-request"), "tool": .object(["name": .string("Run checks"), "arguments": .object(["command": .string("python -m pytest tests/test_request_queue.py -q")])])])
      }
      return .object(record)
    case "turns.changes":
      return .object([
        "available": .bool(true),
        "checkpoint": .string("sample-checkpoint"),
        "live": .bool(false),
        "running": .bool(false),
        "file_count": .number(2),
        "added": .number(14),
        "removed": .number(3),
        "can_restore": .bool(true),
        "later_turns": .number(0),
        "conflicts": .array([]),
        "files": .array([
          .object(["path": .string("Sources/RequestQueue.swift"), "change": .string("modified"), "added": .number(8), "removed": .number(3), "binary": .bool(false)]),
          .object(["path": .string("tests/test_request_queue.py"), "change": .string("added"), "added": .number(6), "removed": .number(0), "binary": .bool(false)]),
        ]),
      ])
    case "factory.list":
      return .object([
        "revision_count": .number(3),
        "runs_truncated": .bool(false),
        "runs": .array([
          .object([
            "id": .string("sample-factory-run"),
            "goal": .string("Harden request queue reconnects and verify held-out checks"),
            "status": .string("needs_review"),
            "factory_digest": .string("a94f2c1b8e7d"),
          ])
        ]),
      ])
    case "factory.run.inspect":
      return .object([
        "work_order": .object([
          "work_order_id": .string("sample-factory-run"),
          "goal": .string("Harden request queue reconnects and verify held-out checks"),
          "status": .string("needs_review"),
          "metadata": .object([
            "factory": .object(["snapshot_digest": .string("a94f2c1b8e7d")]),
            "factory_verification": .object(["state": .string("passed"), "sandbox": .string("container"), "isolation_applied": .bool(true)]),
          ]),
          "tasks": .array([
            .object(["task_id": .string("implement"), "title": .string("Implement reconnect guard"), "role": .string("builder"), "status": .string("succeeded"), "metadata": .object([:])]),
            .object(["task_id": .string("verify"), "title": .string("Run hidden SuperGauge suite"), "role": .string("verifier"), "status": .string("succeeded"), "metadata": .object([:])]),
            .object(["task_id": .string("human-review"), "title": .string("Review candidate before release"), "role": .string("reviewer"), "status": .string("blocked"), "metadata": .object(["human_gate": .bool(true), "gate_digest": .string("sample-gate-digest")])]),
          ]),
        ]),
        "evidence": .array([
          .object(["id": .string("sample-sg"), "kind": .string("factory_quality_record"), "task_id": .string("verify"), "content": .string(ExploreWorkspace.sampleQualityRecord), "truncated": .bool(false)])
        ]),
        "candidate_diff": .string("diff --git a/Sources/RequestQueue.swift b/Sources/RequestQueue.swift\n@@ -1,2 +1,4 @@\n-await queue.start(prompt)\n+let state = try await queue.status(request.id)\n+guard state == .notStarted else { return }\n+try await queue.submit(request)\n"),
        "diff_truncated": .bool(false),
        "cockpit": .object(["status": .string("needs_review"), "elapsed_seconds": .number(48)]),
      ])
    case "factory.evidence.trace":
      return .object([
        "format": .string("superqode.factory-trace/2"),
        "run": .string("sample-factory-run"),
        "verification_bound_to_current": .bool(true),
        "summary": .object([
          "checks": .object(["passed": .number(4), "failed": .number(0), "blocked": .number(0), "never_ran": .number(0)]),
          "requirements": .object(["covered": .number(2), "failed": .number(0), "blocked": .number(0), "uncovered": .number(0)]),
        ]),
        "application_checks": .array([
          .object(["check": .string("unit-tests"), "category": .string("test"), "status": .string("passed"), "reason": .string("All protected cases passed.")]),
          .object(["check": .string("reconnect-idempotency"), "category": .string("integration"), "status": .string("passed"), "reason": .string("All protected cases passed.")]),
        ]),
      ])
    case "conversations.get": return .object(["turns": .array([]), "earlier": .string("")])
    case "files.list": return .array(["Sources/RequestQueue.swift", "tests/test_request_queue.py", "README.md"].map(JSONValue.string))
    case "files.read": return .object(["path": .string(params.text("path")), "text": .string("import Foundation\n\nstruct CodingRequest: Codable {\n  let id: UUID\n  let prompt: String\n}\n")])
    case "git.status": return .object(["branch": .string("feat/resilient-queue"), "status": .string(" M Sources/RequestQueue.swift"), "stat": .string("1 file changed, 3 insertions(+), 1 deletion(-)"), "diff": .string("diff --git a/RequestQueue.swift b/RequestQueue.swift\n@@ -1,3 +1,5 @@\n- await queue.start(prompt)\n+ let state = try await queue.status(request.id)\n+ guard state == .notStarted else { return }\n+ try await queue.submit(request)\n")])
    case "experiments.list": return .array([.object(ExploreWorkspace.jobs[1].raw)])
    case "conversations.share": return .object(["text": .string("Shared sample context: " + ExploreWorkspace.prompt + "\n" + ExploreWorkspace.answer), "omitted_messages": .number(0)])
    case "jobs.export": return .object(["name": .string("superqode-sample.md"), "content": .string("# Sample recorded evidence\n\n" + ExploreWorkspace.answer), "truncated": .bool(false)])
    case "context.preview": return .object(["prompt": .string(params.text("prompt") + "\n\nSample reference material."), "files": .array((params["context_files"]?.array ?? []).map { .object(["path": $0, "sha256": .string("sample-only-file-fingerprint"), "bytes": .number(85)]) }), "image_count": .number(0)])
    case "review.list": return .object(["label": .string("Sample working-tree changes"), "files": .array([.object(ExploreWorkspace.reviewFile)]), "excluded_count": .number(0), "truncated": .bool(false)])
    case "review.diff": return .object(ExploreWorkspace.reviewFile.merging(["snapshot_id": .string("sample-review-snapshot"), "hunks": .array([ExploreWorkspace.reviewHunk]), "truncated": .bool(false), "issue": .string(""), "can_stage": .bool(true)]) { _, new in new })
    case "review.feedback": return .object(["text": .string("Review feedback for the sample RequestQueue.swift revision:\n" + params.text("comment"))])
    case "queue.list": return .object(["running": .bool(false), "items": .array([.object(["id": .string("sample-queue"), "state": .string("pending"), "job": .string(""), "request": .object(["prompt": .string("Run the reviewed regression checks"), "harness": .string("core")])])])])
    case "checkpoints.list": return .object(["items": .array([.object(["id": .string("sample-checkpoint"), "name": .string("Before the queue update"), "timestamp": .string("Sample checkpoint"), "sealed": .bool(true), "changes": .array([.object(["path": .string("Sources/RequestQueue.swift"), "change_type": .string("modified")])])])])])
    case "checkpoints.diff": return .object(["diff": .string("-await queue.start(prompt)\n+try await queue.submit(request)\n")])
    case "workorders.snapshot": return .object(["items": .array([.object(["work_order_id": .string("sample-order"), "goal": .string("Make request delivery reliable"), "status": .string("needs_review"), "harness": .string("core"), "elapsed_seconds": .number(42), "tasks": .array([.object(["task_id": .string("sample-task"), "title": .string("Verify reconnect behavior"), "role": .string("verifier"), "status": .string("completed"), "worker_id": .string("sample-worker")])]), "workers": .array([.object(["worker_id": .string("sample-worker"), "responsive": .bool(true)])]), "gates": .object(["check_results": .number(1), "last_check_passed": .bool(true), "approved_reviews": .number(0)]), "budget": .object(["max_cost_usd": .number(1)]), "usage": .object(["cost_usd": .number(0)])])])])
    case "evals.inspect": return .object(["tasks_hash": .string("sample-hash"), "task_count": .number(6), "warnings": .array([]), "repository_checks": .array([])])
    default: throw CompanionError("Explore mode is read-only. Pair your own Mac to use this action.")
    }
  }
}

enum CompanionPreview {
  @MainActor static func makeStore() -> CompanionStore {
    let store = CompanionStore()
    store.enterExploreMode()
    let args = ProcessInfo.processInfo.arguments
    if let index = args.firstIndex(of: "--design-preview"), args.count > index + 1 {
      switch args[index + 1] {
      case "activity", "conversation", "approval", "evaluation", "failed": store.selectedTab = 1
      case "lab": store.selectedTab = 2
      case "settings": store.selectedTab = 3
      default: break
      }
    }
    return store
  }
  static var initialRun: OpenedRun? {
    #if DEBUG
    let args = ProcessInfo.processInfo.arguments
    guard let index = args.firstIndex(of: "--design-preview"), args.count > index + 1 else { return nil }
    switch args[index + 1] {
    case "conversation": return OpenedRun(id: ExploreWorkspace.conversation)
    case "approval": return OpenedRun(id: "sample-approval")
    case "evaluation": return OpenedRun(id: ExploreWorkspace.evaluation)
    case "failed": return OpenedRun(id: ExploreWorkspace.failedRun)
    default: return nil
    }
    #else
    return nil
    #endif
  }
}
