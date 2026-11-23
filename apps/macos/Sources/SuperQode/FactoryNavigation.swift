import Foundation
import Observation
import SwiftUI

/// A completion may offer its next page only while its originating intent is current.
@Observable @MainActor final class FactoryNavigation {
  struct Ticket: Equatable { let project: String; let generation: UUID }
  struct Group: Identifiable {
    let id: String; let title: String; let detail: String; let destinations: [String]
    var mark: String {
      switch id {
      case "build": "🏗️"
      case "run": "🧪"
      case "improve": "✨"
      case "export": "📦"
      case "manage": "⚙️"
      default: "🏭"
      }
    }
  }
  static let groups: [Group] = [
    Group(id: "build", title: "Build", detail: "Describe, configure and review your Factory.", destinations: ["Stack", "Configuration", "Workflow", "Acceptance", "Definition"]),
    Group(id: "run", title: "Test", detail: "Run a trial and inspect its evidence.", destinations: ["Runs", "Suites"]),
    Group(id: "improve", title: "Improve", detail: "Compare proposals before adopting changes.", destinations: ["Improve", "ImproveCandidate", "ImproveEvidence", "Experiments"]),
    Group(id: "export", title: "Export", detail: "Take editable sources to your own environment.", destinations: ["Export"]),
    Group(id: "manage", title: "Manage", detail: "Review versions and source changes, check this host, and prepare recovery or deployment packages.", destinations: ["Sources", "Revisions", "Operations"])]
  static let tabs: [(id: String, title: String)] = [
    ("Stack", "Describe"), ("Configuration", "Configuration"), ("Workflow", "Workflow"), ("Acceptance", "Acceptance checks"), ("Definition", "Definition & diff"),
    ("Runs", "Single trial"), ("Revisions", "History"), ("Sources", "Source control"),
    ("Improve", "Set up experiment"), ("ImproveCandidate", "Candidate & diff"), ("ImproveEvidence", "Comparison evidence"), ("Experiments", "Workflow experiment"),
    ("Export", "Portable package"), ("Suites", "Trial suites"), ("Operations", "Operations")]
  static let buildPages: Set<String> = ["Stack", "Configuration", "Workflow", "Acceptance", "Definition"]
  static let improvementPages: Set<String> = ["Improve", "ImproveCandidate", "ImproveEvidence"]
  var pageTitle: String { Self.tabs.first { $0.id == selection }?.title ?? "Factory" }
  private(set) var selection: String
  private(set) var mounted: Set<String>
  private(set) var project = ""
  private(set) var active = false
  private var generation = UUID()
  private var selections: [String: String] = [:]
  private var groupSelections: [String: String] = [:]
  private let initial: String

  init(initial: String = "Stack") {
    self.initial = initial; selection = initial; mounted = [initial]
  }
  func enter(_ identity: String) {
    guard project != identity else { return }
    if !project.isEmpty { selections[project] = selection }
    project = identity; generation = UUID(); active = false
    selection = selections[identity] ?? initial; mounted = [selection]
  }
  func select(_ destination: String) {
    guard Self.tabs.contains(where: { $0.id == destination }), destination != selection else { return }
    selection = destination; mounted.insert(destination); generation = UUID()
    groupSelections[project + ":" + group.id] = destination
  }
  var group: Group { Self.groups.first { $0.destinations.contains(selection) } ?? Self.groups[0] }
  var destinations: [(id: String, title: String)] {
    group.destinations.compactMap { id in Self.tabs.first { $0.id == id } }
  }
  func selectGroup(_ identity: String) {
    guard let target = Self.groups.first(where: { $0.id == identity }), identity != group.id else { return }
    select(groupSelections[project + ":" + identity] ?? target.destinations[0])
  }
  func setActive(_ value: Bool) {
    guard active != value else { return }; active = value; generation = UUID()
  }
  func ticket() -> Ticket { Ticket(project: project, generation: generation) }
  func isCurrent(_ ticket: Ticket) -> Bool {
    active && !project.isEmpty && ticket.project == project && ticket.generation == generation
  }
  @discardableResult func follow(_ ticket: Ticket, to destination: String) -> Bool {
    guard isCurrent(ticket) else { return false }; select(destination); return true
  }
  static var initialTab: String {
    let args = ProcessInfo.processInfo.arguments
    if args.contains("--factory-operations-inspect") || args.contains("--factory-navigation-inspect") { return "Operations" }
    if args.contains("--factory-optimization-inspect") { return "ImproveEvidence" }
    if args.contains("--factory-suite-inspect") || args.contains("--factory-feedback-inspect") { return "Suites" }
    return args.contains("--factory-demo-inspect") ? "Runs" : "Stack"
  }
}

struct FactoryPaneVisibility: ViewModifier {
  let active: Bool
  func body(content: Content) -> some View {
    content.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
      .opacity(active ? 1 : 0).disabled(!active).allowsHitTesting(active)
      .accessibilityHidden(!active).zIndex(active ? 1 : 0)
  }
}
