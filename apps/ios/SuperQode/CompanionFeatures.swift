import SwiftUI

enum DeveloperWorkflow: String, CaseIterable, Identifiable, Codable {
  case code = "Code", review = "Review", evaluate = "Evaluate", optimize = "Optimize"
  case conversations = "Conversations", files = "Project files", workorders = "WorkOrders", queue = "Task queue", checkpoints = "Checkpoints"
  case connections = "Shared connections", activity = "Activity"
  var id: String { rawValue }
  var symbol: String {
    switch self {
    case .code: return "square.and.pencil"
    case .review: return "text.magnifyingglass"
    case .evaluate: return "checkmark.seal"
    case .optimize: return "slider.horizontal.3"
    case .conversations: return "bubble.left.and.bubble.right"
    case .files: return "folder"
    case .workorders: return "person.3"
    case .queue: return "list.number"
    case .checkpoints: return "clock.arrow.circlepath"
    case .connections: return "cpu"
    case .activity: return "waveform.path"
    }
  }
  var subtitle: String {
    switch self {
    case .code: return "Start a fresh conversation"
    case .review: return "Inspect revisions and give feedback"
    case .evaluate: return "Measure harness outcomes"
    case .optimize: return "Stage an evidence-backed improvement"
    default: return "Open " + rawValue.lowercased()
    }
  }
}

struct DeveloperShortcuts: View {
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      Text("Build. Verify. Improve.").font(.title3.bold())
      LazyVGrid(columns: [GridItem(.adaptive(minimum: 155), spacing: 12)], spacing: 12) {
        ForEach([DeveloperWorkflow.code, .review, .evaluate, .optimize]) { workflow in
          NavigationLink { WorkflowProjectPicker(workflow: workflow) } label: {
            VStack(alignment: .leading, spacing: 10) {
              Image(systemName: workflow.symbol).font(.title2).foregroundStyle(CompanionTheme.accent)
              Text(workflow.rawValue).font(.headline).foregroundStyle(.primary)
              Text(workflow.subtitle).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
            }.frame(maxWidth: .infinity, minHeight: 104, alignment: .topLeading).padding(16)
              .background(CompanionTheme.panel, in: RoundedRectangle(cornerRadius: 18))
              .overlay(RoundedRectangle(cornerRadius: 18).strokeBorder(CompanionTheme.accent.opacity(0.25)))
          }.buttonStyle(.plain).accessibilityIdentifier("workflow." + workflow.id.lowercased())
        }
      }
    }
  }
}

struct WorkflowProjectPicker: View {
  let workflow: DeveloperWorkflow
  var fixedProject: RemoteRecord? = nil
  @EnvironmentObject private var store: CompanionStore
  var body: some View {
    Group {
      if workflow == .activity { ActivityScreen() }
      else if workflow == .connections { HarnessLabScreen(initialSection: "Connections") }
      else if workflow == .code && !store.permissions.contains("tasks") {
        ContentUnavailableView("Task permission required", systemImage: "lock", description: Text("Allow coding tasks when pairing this phone on your Mac."))
      } else if let fixedProject { destination(fixedProject) }
      else if store.projects.count == 1 {
        destination(store.projects[0])
      } else {
        List {
          Section { ConnectionStatus(); Text("Choose the workspace for " + workflow.rawValue.lowercased() + ".").font(.footnote).foregroundStyle(.secondary) }
          ForEach(store.projects) { project in NavigationLink(project.text("name")) { destination(project) } }
          if store.projects.isEmpty { ContentUnavailableView("Share a workspace first", systemImage: "folder.badge.plus", description: Text("Select and share a connection from Private remote access on your Mac.")) }
        }.navigationTitle(workflow.rawValue)
      }
    }
  }
  @ViewBuilder private func destination(_ project: RemoteRecord) -> some View {
    switch workflow {
    case .code: ComposeTaskScreen(project: project.id)
    case .review: ProjectReviewScreen(project: project.id)
    case .evaluate: EvaluationScreen(project: project.id)
    case .optimize: EvaluationScreen(project: project.id, intent: .optimize)
    case .conversations: ProjectScreen(project: project)
    case .files: FilesScreen(project: project.id)
    case .workorders: ProjectInspectionScreen(project: project.id, kind: .workorders)
    case .queue: ProjectInspectionScreen(project: project.id, kind: .queue)
    case .checkpoints: ProjectInspectionScreen(project: project.id, kind: .checkpoints)
    case .connections: HarnessLabScreen(initialSection: "Connections")
    case .activity: ActivityScreen()
    }
  }
}

struct ProjectToolsScreen: View {
  let project: RemoteRecord
  var body: some View {
    List {
      Section { ConnectionStatus(); Text(project.text("name")).font(.headline) }
      Section("Build and review") {
        tool(.code); tool(.review); tool(.files)
        NavigationLink("Working-tree overview") { ChangesScreen(project: project.id) }
      }
      Section("Harness quality") { tool(.evaluate); tool(.optimize) }
      Section("Execution and history") { tool(.workorders); tool(.queue); tool(.checkpoints) }
      Section { NavigationLink("All features and availability") { AllFeaturesScreen() } }
    }.navigationTitle("Project tools").scrollContentBackground(.hidden).background(CompanionTheme.background)
  }
  private func tool(_ workflow: DeveloperWorkflow) -> some View {
    NavigationLink { WorkflowProjectPicker(workflow: workflow, fixedProject: project) } label: { Label(workflow.rawValue, systemImage: workflow.symbol) }
  }
}

struct CompanionFeature: Identifiable, Decodable {
  let id: String
  let title: String
  let group: String
  let status: String
  let detail: String
  var workflow: DeveloperWorkflow? = nil
  let parity: String
  let macRoute: String
  static let all: [Self] = {
    guard let url = Bundle.main.url(forResource: "FeatureParity", withExtension: "json"),
      let data = try? Data(contentsOf: url), let items = try? JSONDecoder().decode([Self].self, from: data) else { return [] }
    return items
  }()
}

struct AllFeaturesScreen: View {
  @State private var query = ""
  private let groups = ["Daily development", "Harness quality", "Execution and recovery", "Connections and setup"]
  private var visible: [CompanionFeature] { CompanionFeature.all.filter { query.isEmpty || ($0.title + " " + $0.detail).localizedCaseInsensitiveContains(query) } }
  var body: some View {
    List {
      Section { Text("Every major Mac workflow, with its actual phone availability. Inspect means read-only; On Mac means the phone does not implement that action yet.").font(.footnote).foregroundStyle(.secondary) }
      ForEach(groups, id: \.self) { group in
        let items = visible.filter { $0.group == group }
        if !items.isEmpty {
          Section(group) {
            ForEach(items) { feature in
              NavigationLink { FeatureDetailScreen(feature: feature) } label: {
                VStack(alignment: .leading, spacing: 6) {
                  Text(feature.title).font(.headline)
                  Text(feature.status).font(.caption.weight(.semibold)).foregroundStyle(feature.workflow == nil ? Color.secondary : CompanionTheme.accent)
                }.padding(.vertical, 4)
              }.listRowBackground(CompanionTheme.panel)
            }
          }
        }
      }
    }.navigationTitle("All features").searchable(text: $query, prompt: "Find a developer workflow")
      .scrollContentBackground(.hidden).background(CompanionTheme.background)
  }
}

struct FeatureDetailScreen: View {
  let feature: CompanionFeature
  var body: some View {
    List {
      Section { ConnectionStatus(); Text(feature.status).font(.headline).foregroundStyle(CompanionTheme.accent); Text(feature.detail).textSelection(.enabled); if feature.parity == "partial" { Text("Some actions still require your Mac.").font(.footnote).foregroundStyle(CompanionTheme.warning) } }
      if let workflow = feature.workflow { Section { NavigationLink("Open " + workflow.rawValue.lowercased()) { WorkflowProjectPicker(workflow: workflow) } } }
      if feature.workflow == nil || feature.parity == "partial" { Section("On your Mac") { Text("Open " + feature.macRoute + " in SuperQode on your Mac. No remote action is started from this page.").font(.footnote).foregroundStyle(.secondary) } }
    }.navigationTitle(feature.title).scrollContentBackground(.hidden).background(CompanionTheme.background)
  }
}
