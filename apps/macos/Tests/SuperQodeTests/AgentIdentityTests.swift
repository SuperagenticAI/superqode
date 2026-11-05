import XCTest
import AppKit
@testable import SuperQode

final class AgentIdentityTests: XCTestCase {
  func testHarnessAccentsFollowAgentIdentityRatherThanModelOrDisplayName() {
    let openCode = HarnessIdentity(["id": "acp:opencode", "name": "OpenCode", "model": "claude"])
    let sameAgent = HarnessIdentity(["id": "acp:opencode", "name": "Local coding", "model": "qwen"])
    XCTAssertEqual(openCode.colorFamily, sameAgent.colorFamily)
    XCTAssertEqual(openCode.colorFamily, HarnessIdentity(["id": "opencode-v2"]).colorFamily)
    XCTAssertNotEqual(openCode.colorFamily, HarnessIdentity(["id": "connection:codex", "runtime": "codex-cli"]).colorFamily)
    XCTAssertNotEqual(openCode.colorFamily, HarnessIdentity(["id": "core", "model": "opencode"]).colorFamily)
    XCTAssertTrue(HarnessIdentity.used(in: ["harness": "disconnected"]).isEmpty)
  }

  func testHarnessLabelColoursHaveReadableContrastOnSelectedLightAndDarkRows() {
    func luminance(_ channels: [CGFloat]) -> Double {
      let values = channels.map { channel -> Double in
        let value = Double(channel)
        return value <= 0.04045 ? value / 12.92 : pow((value + 0.055) / 1.055, 2.4)
      }
      return zip(values, [0.2126, 0.7152, 0.0722]).reduce(0) { $0 + $1.0 * $1.1 }
    }
    for family in HarnessColorFamily.allCases {
      for dark in [false, true] {
        let color = family.nsColor(dark: dark)
        let channels = [color.redComponent, color.greenComponent, color.blueComponent]
        let panel: CGFloat = dark ? 0.1 : 0.96
        let background = channels.map { panel * 0.9 + $0 * 0.1 }
        let foregroundLuminance = luminance(channels)
        let backgroundLuminance = luminance(background)
        let contrast = (max(foregroundLuminance, backgroundLuminance) + 0.05) / (min(foregroundLuminance, backgroundLuminance) + 0.05)
        XCTAssertGreaterThanOrEqual(contrast, 4.5, "\(family) · \(dark ? "dark" : "light")")
      }
    }
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
    ] {
      XCTAssertEqual(HarnessIdentity(["id": id, "runtime": runtime]).assetName, asset, id)
    }
    XCTAssertNil(HarnessIdentity(["id": "private-coder", "runtime": "custom"]).assetName)
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
