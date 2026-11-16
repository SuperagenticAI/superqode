import Foundation

@MainActor extension Workspace {
  func smokeHarnessStudio() async throws -> String {
    let before = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
    let studio = harnessStudio
    studio.enter(projectID)
    await studio.load(engine: engine, reference: "core")
    studio.name = "native-studio-fixture"
    studio.source = "provider"; studio.provider = "openai"; studio.model = "gpt-4o-mini"
    await studio.validate(engine: engine)
    guard !string(studio.review, "review").isEmpty, (studio.review["inspection"] as? [String: Any])?["ok"] as? Bool == true else {
      throw EngineError(message: "Harness Studio did not validate the native draft: " + studio.failure)
    }
    try await studio.save(engine: engine, reason: "Native snapshot and route validation fixture")
    await studio.validate(engine: engine)
    let plan = try await engine.call("studio.check.prepare", ["project": projectID, "review": string(studio.review, "review"), "digest": string(studio.review, "digest"), "check": "edit", "repeats": 2]) as? [String: Any] ?? [:]
    var rejected = false
    do { _ = try await engine.call("studio.check.start", ["project": projectID, "plan": string(plan, "plan"), "digest": "stale", "command_id": "must-not-run-studio"]) }
    catch { rejected = true }
    let after = try await engine.call("jobs.list", ["project": projectID]) as? [[String: Any]] ?? []
    let versions = studio.catalog.first?["revisions"] as? [[String: Any]] ?? []
    guard rejected, before.count == after.count, versions.count == 1,
      versions[0]["intact"] as? Bool == true, string(plan, "source_digest") == string(studio.review, "digest")
    else { throw EngineError(message: "Studio revision, source identity or no-call review boundary failed.") }
    let silicon = try await engine.call("studio.open", ["project": projectID, "reference": "silicon"]) as? [String: Any] ?? [:]
    let siliconText = string(silicon, "yaml")
    let options = try await engine.call("studio.silicon.options", ["project": projectID, "yaml": siliconText]) as? [String: Any] ?? [:]
    let added: [String: Any] = ["name": "Verify", "command": "python3 verify.py", "timeout": 60]
    let edited = try await engine.call("studio.silicon.apply", ["project": projectID, "name": "native-silicon-fixture", "yaml": siliconText,
      "options": ["checks": ["add": [added]]] as [String: Any]]) as? [String: Any] ?? [:]
    guard isSiliconDraft(siliconText), options["tool_count"] as? Int == 4, (options["mcp"] as? [String: Any])?["enabled"] as? Bool == false,
      edited["changed"] as? Bool == true, string(edited, "diff").contains("python3 verify.py")
    else { throw EngineError(message: "Silicon options did not read or edit the draft as expected.") }
    return "passed; native draft validation, immutable snapshot, revision history, Silicon option draft edits and digest-bound repeated-check review without model calls"
  }
}
