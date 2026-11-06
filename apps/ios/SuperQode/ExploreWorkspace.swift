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
  static let permissions: [String] = ["read", "tasks", "evaluate", "approve", "cancel", "steer"]
  static var catalog: JSONValue {
    .object(["protocol": .number(1), "device": .object(["name": .string("Sample iPhone")]),
      "permissions": .array(permissions.map(JSONValue.string)), "profiles": .array([.object(profileRecord.raw)]),
      "suites": .array([.object(["id": .string("decision-routing"), "name": .string("Labelled route decisions"), "description": .string("Sample evaluation suite"), "tasks": .number(6)])]),
      "features": .object(["threads": .array(["search", "pagination", "rename", "pin", "archive"].map(JSONValue.string)), "request_reconciliation": .bool(true)])])
  }
  static var result: JSONValue {
    .object(["live": .bool(true), "summary": .string("Both splits passed the labelled routing checks."),
      "variants": .array([.object(["name": .string("Core · Qwen3 Coder"), "harness": .string("core"), "passed": .number(6), "failed": .number(0), "skipped": .number(0)])])])
  }
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
      let events: [JSONValue] = params.number("after") > 0 ? [] : [.object(["sequence": .number(1), "type": .string("answer"), "data": .object(["text": .string(ExploreWorkspace.answer)])])]
      record["events"] = .array(events)
      if id == ExploreWorkspace.failedRun {
        record["result"] = .object(["error": .string(ExploreWorkspace.failure)])
        record["events"] = .array(params.number("after") > 0 ? [] : [.object(["sequence": .number(1), "type": .string("error"), "data": .object(["message": .string(ExploreWorkspace.failure)])])])
      }
      record["next_sequence"] = .number(1)
      record["has_more_events"] = .bool(false)
      if id == ExploreWorkspace.evaluation { record["result"] = ExploreWorkspace.result }
      if id == "sample-approval" {
        record["pending_approval"] = .object(["request_id": .string("sample-request"), "tool": .object(["name": .string("Run checks"), "arguments": .object(["command": .string("python -m pytest tests/test_request_queue.py -q")])])])
      }
      return .object(record)
    case "conversations.get": return .object(["turns": .array([]), "earlier": .string("")])
    case "files.list": return .array(["Sources/RequestQueue.swift", "tests/test_request_queue.py", "README.md"].map(JSONValue.string))
    case "files.read": return .object(["path": .string(params.text("path")), "text": .string("import Foundation\n\nstruct CodingRequest: Codable {\n  let id: UUID\n  let prompt: String\n}\n")])
    case "git.status": return .object(["branch": .string("feat/resilient-queue"), "status": .string(" M Sources/RequestQueue.swift"), "stat": .string("1 file changed, 3 insertions(+), 1 deletion(-)"), "diff": .string("diff --git a/RequestQueue.swift b/RequestQueue.swift\n@@ -1,3 +1,5 @@\n- await queue.start(prompt)\n+ let state = try await queue.status(request.id)\n+ guard state == .notStarted else { return }\n+ try await queue.submit(request)\n")])
    case "experiments.list": return .array([.object(ExploreWorkspace.jobs[1].raw)])
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
