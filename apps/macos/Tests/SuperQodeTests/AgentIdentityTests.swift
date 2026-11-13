import XCTest
@testable import SuperQode

final class AgentIdentityTests: XCTestCase {
  func testHarnessIdentityFollowsRouteAndDisconnectedThreadsHaveNoLogo() {
    let openCode = HarnessIdentity(["id": "acp:opencode", "name": "OpenCode", "model": "claude"])
    let sameAgent = HarnessIdentity(["id": "acp:opencode", "name": "Local coding", "model": "qwen"])
    XCTAssertEqual(openCode.assetName, sameAgent.assetName)
    XCTAssertEqual(openCode.assetName, "Agent-opencode")
    XCTAssertEqual(HarnessIdentity(["id": "opencode-v2"]).assetName, "Agent-opencode-v2")
    XCTAssertNotEqual(openCode.assetName, HarnessIdentity(["id": "opencode-v2"]).assetName)
    XCTAssertNotEqual(openCode.assetName, HarnessIdentity(["id": "connection:codex", "runtime": "codex-cli"]).assetName)
    XCTAssertNotEqual(openCode.assetName, HarnessIdentity(["id": "core", "model": "opencode"]).assetName)
    XCTAssertTrue(HarnessIdentity.used(in: ["harness": "disconnected"]).isEmpty)
  }

  func testOnlyOfficiallyColouredMarksKeepBrandColours() {
    for id in ["acp:claude", "acp:gemini", "acp:qwen-code", "acp:mistral-vibe", "acp:junie", "acp:cortex-code", "acp:antigravity", "connection:antigravity", "core"] {
      XCTAssertTrue(HarnessIdentity(["id": id]).keepsBrandColours, id)
    }
    let antigravity = HarnessIdentity(["id": "connection:antigravity", "runtime": "antigravity-cli", "subscription_vendor": "antigravity"])
    XCTAssertEqual(antigravity.assetName, "Agent-antigravity-acp")
    XCTAssertTrue(antigravity.keepsBrandColours)
    for id in ["acp:codex", "acp:grok-build", "acp:cursor", "acp:github-copilot-cli", "acp:opencode", "acp:kimi", "acp:custom-research"] {
      XCTAssertFalse(HarnessIdentity(["id": id]).keepsBrandColours, id)
    }
    XCTAssertTrue(BundledAgentIcons.brandColoured.isSubset(of: Set(BundledAgentIcons.assets.values)))
  }

  func testClientDirectoryHasUniquePublicWebsiteDestinations() {
    XCTAssertFalse(ACPClientDirectory.projects.isEmpty)
    XCTAssertEqual(Set(ACPClientDirectory.projects.map(\.id)).count, ACPClientDirectory.projects.count)
    for project in ACPClientDirectory.projects {
      let url = URL(string: project.url)
      XCTAssertEqual(url?.scheme, "https", project.name)
      XCTAssertNotNil(url?.host, project.name)
      XCTAssertNil(url?.user, project.name)
      XCTAssertNil(url?.password, project.name)
    }
  }

  func testAgentIdentityUsesExecutionRouteAndNeverTheModel() {
    XCTAssertEqual(HarnessIdentity(["id": "acp:codex"]).assetName, "Agent-codex-acp")
    XCTAssertEqual(HarnessIdentity(["id": "connection:claude", "subscription_vendor": "claude"]).assetName, "Agent-claude-acp")
    XCTAssertEqual(HarnessIdentity(["id": "my-harness", "runtime": "codex-cli"]).assetName, "Agent-codex-acp")
    XCTAssertEqual(HarnessIdentity(["id": "core", "model": "codex"]).assetName, "BrandMark")
    XCTAssertNil(HarnessIdentity(["id": "acp:custom-research", "name": "Codex experiment"]).assetName)
  }

  func testMixedHarnessHistoryKeepsDistinctRoutesAndNames() {
    let row: [String: Any] = ["harnesses_used": [
      ["id": "acp:codex", "name": "Codex", "icon_key": "codex"],
      ["id": "acp:claude", "name": "Claude", "icon_key": "claude"],
      ["id": "acp:codex", "name": "Codex", "icon_key": "codex"],
      ["id": "retired", "name": "Old research harness", "icon_key": ""],
    ]]
    XCTAssertEqual(HarnessIdentity.used(in: row).map(\.name), ["Codex", "Claude", "Old research harness"])
    XCTAssertEqual(HarnessIdentity.used(in: ["harness": "acp:codex"]).first?.assetName, "Agent-codex-acp")
    XCTAssertTrue(HarnessIdentity.used(in: [:]).isEmpty)
    let overflow: [String: Any] = ["harness": "five", "harnesses_used": ["one", "two", "three", "four", "five"].map { ["id": $0, "name": $0] }]
    XCTAssertEqual(HarnessIdentity.visible(in: overflow, limit: 3).map(\.id), ["one", "two", "five"])
    XCTAssertEqual(HarnessIdentity.visible(in: overflow, limit: 1).map(\.id), ["five"])
  }

  func testHubHarnessesResolveBundledVendorLogosFromTheirRoute() {
    for (id, runtime, asset) in [
      ("codex-sdk", "codex-sdk", "Agent-codex-acp"),
      ("claude-code", "claude-agent-sdk", "Agent-claude-acp"),
      ("droid", "factory", "Agent-factory-droid"),
      ("acp:opencode", "acp", "Agent-opencode"),
      ("antigravity", "antigravity-cli", "Agent-antigravity-acp"),
    ] {
      XCTAssertEqual(HarnessIdentity(["id": id, "runtime": runtime]).assetName, asset, id)
    }
    XCTAssertNil(HarnessIdentity(["id": "private-coder", "runtime": "custom"]).assetName)
  }

  func testAppleFoundationRoutesUseTheDeviceMarkOnEveryHarness() {
    let development = HarnessIdentity(["id": "apple-local", "name": "Apple on-device", "runtime": "builtin"])
    XCTAssertTrue(development.appleDevice)
    XCTAssertNil(development.assetName)
    XCTAssertFalse(development.keepsBrandColours)
    let chat = HarnessIdentity(["id": "no-tool", "name": "No Tool", "provider": "apple-foundation", "icon_key": "apple-device"])
    XCTAssertTrue(chat.appleDevice)
    XCTAssertEqual(chat.id, "no-tool")
    XCTAssertFalse(HarnessIdentity(["id": "no-tool", "provider": "openai"]).appleDevice)
    XCTAssertFalse(HarnessIdentity(["id": "core"]).appleDevice)
  }

  func testCatalogFiltersKeepMissingAgentsDiscoverableAndRejectStaleVerification() {
    let routes: [[String: Any]] = [
      ["id": "acp:missing", "name": "Missing", "available": false],
      ["id": "acp:codex", "name": "Codex", "available": true, "digest": "new"],
      ["id": "acp:custom", "name": "Custom", "available": true, "custom": true, "digest": "current"],
    ]
    let metadata: [String: [String: Any]] = [
      "acp:codex": ["connected": true, "route_digest": "old"],
      "acp:custom": ["connected": true, "route_digest": "current"],
    ]
    func ids(_ filter: ACPAgentFilter, _ search: String = "") -> [String] {
      filteredACPAgents(routes, search: search, filter: filter, metadata: metadata, selected: "acp:codex").map { string($0, "id") }
    }
    XCTAssertEqual(ids(.all), ["acp:codex", "acp:custom", "acp:missing"])
    XCTAssertEqual(ids(.installed), ["acp:codex", "acp:custom"])
    XCTAssertEqual(ids(.verified), ["acp:custom"])
    XCTAssertEqual(ids(.custom), ["acp:custom"])
    XCTAssertEqual(ids(.all, "  MISSING  "), ["acp:missing"])
    XCTAssertTrue(ids(.all, "not here").isEmpty)
  }
}
