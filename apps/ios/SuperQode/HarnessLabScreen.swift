import SwiftUI

struct HarnessLabScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @State private var section = "Experiments"
  @State private var project = ""
  @State private var experiments: [RemoteRecord] = []
  @State private var launching: ExperimentLaunch?
  @State private var issue = ""
  init(initialSection: String = "Experiments") { _section = State(initialValue: initialSection) }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 22) {
        ConnectionStatus()
        VStack(alignment: .leading, spacing: 8) {
          Text("Evaluate what works.").font(.system(.title, design: .rounded, weight: .bold))
          Text("Improve with evidence.").font(.system(.title, design: .rounded, weight: .bold)).foregroundStyle(CompanionTheme.accent)
          Text("Your harnesses, local models and evaluation results, together.").font(.subheadline).foregroundStyle(.secondary)
        }.padding(.top, 12)
        Picker("Harness lab", selection: $section) {
          Text("Evaluate & improve").tag("Experiments"); Text("Connections").tag("Connections")
        }.pickerStyle(.segmented)
        if section == "Connections" {
          ForEach(store.profiles) { profile in connection(profile) }
          if store.profiles.isEmpty { ContentUnavailableView("Bring your harnesses", systemImage: "sparkles", description: Text("Configure and share a connection from your Mac. Credentials stay there.")) }
        } else {
          Picker("Workspace", selection: $project) {
            Text("Choose a workspace").tag("")
            ForEach(store.projects) { Text($0.text("name")).tag($0.id) }
          }
          workflowCard("Evaluate a harness", detail: "Validate a suite or run reviewed live tasks. Compare outcomes, cost and regressions.", symbol: "checkmark.seal", intent: .evaluate)
          workflowCard("Optimize a harness", detail: "Stage a candidate within explicit budgets and inspect its held-out evidence.", symbol: "slider.horizontal.3", intent: .optimize)
          if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
          ForEach(experiments) { experiment in
            NavigationLink { JobScreen(identity: experiment.id) } label: { CompanionCard { JobRow(job: experiment) } }.buttonStyle(.plain)
          }
          if !project.isEmpty && experiments.isEmpty && issue.isEmpty {
            ContentUnavailableView("Your next improvement starts here", systemImage: "chart.bar.xaxis",
              description: Text("Run a setup check or a reviewed live evaluation. Results stay recorded on your Mac."))
          }
        }
        Text("Execution uses the Mac's configured harness and policy. Local-only connections never fall back to an unverified cloud optimizer.")
          .font(.caption).foregroundStyle(.secondary)
      }.padding(20).frame(maxWidth: 900).frame(maxWidth: .infinity)
    }.background(CompanionTheme.background).navigationTitle("Harness lab").companionNavigationBrand()
      .task(id: project) {
        if project.isEmpty && store.projects.count == 1 { project = store.projects[0].id }
        else { await load() }
      }
      .refreshable { await store.refresh(); await load() }
      .sheet(item: $launching, onDismiss: { Task { await load() } }) { launch in
        NavigationStack { EvaluationScreen(project: launch.project, intent: launch.intent, initialProfile: launch.profile) }
      }
  }
  private func workflowCard(_ title: String, detail: String, symbol: String, intent: EvaluationIntent) -> some View {
    CompanionCard {
      Label(title, systemImage: symbol).font(.headline).foregroundStyle(CompanionTheme.accent)
      Text(detail).font(.subheadline).foregroundStyle(.secondary)
      Button(intent == .evaluate ? "Set up evaluation" : "Set up optimization") { launching = ExperimentLaunch(project: project, intent: intent) }
        .buttonStyle(CompanionPrimaryButton()).disabled(project.isEmpty)
      if project.isEmpty { Text("Choose a shared workspace first.").font(.caption).foregroundStyle(.secondary) }
      if intent == .optimize { Text("Candidate adoption and promotion stay on your Mac.").font(.caption).foregroundStyle(.secondary) }
    }
  }
  private func connection(_ profile: RemoteRecord) -> some View {
    CompanionCard {
      HStack { HarnessBadge(name: profile.text("name")); Spacer(); Image(systemName: profile.flag("local_only") ? "desktopcomputer" : "network").foregroundStyle(.secondary) }
      Text(profile.text("model", "Agent-managed model")).font(.headline).textSelection(.enabled)
      Text(store.projects.first { $0.id == profile.text("project") }?.text("name") ?? "Shared workspace")
        .font(.subheadline).foregroundStyle(.secondary)
      Label(profile.flag("local_only") ? "Local inference" : "Provider-managed inference", systemImage: profile.flag("local_only") ? "checkmark.shield" : "cloud")
        .font(.caption).foregroundStyle(profile.flag("local_only") ? CompanionTheme.accent : Color.secondary)
      Text(profile.text("permission_note")).font(.caption).foregroundStyle(.secondary)
      HStack(spacing: 14) {
        if profile.flag("evaluation") { Label("Evaluation", systemImage: "checkmark.seal") }
        if profile.flag("optimization") { Label("Optimization", systemImage: "slider.horizontal.3") }
      }.font(.caption).foregroundStyle(.secondary)
      if profile.flag("evaluation") {
        Button("Evaluate this connection") { launching = ExperimentLaunch(project: profile.text("project"), profile: profile.id) }
      }
    }
  }
  private func load() async {
    guard let api = store.api, !project.isEmpty else { experiments = []; return }
    let current = project
    do {
      let next = try await api.rpc("experiments.list", ["project": .string(current)]).array.map { RemoteRecord(raw: $0.object) }
      try Task.checkCancellation()
      guard project == current else { return }
      experiments = next; issue = ""
    } catch is CancellationError { }
    catch { issue = error.localizedDescription }
  }
}
