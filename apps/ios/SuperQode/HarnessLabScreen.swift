import SwiftUI

struct HarnessLabScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @State private var section = "Connections"
  @State private var project = ""
  @State private var experiments: [RemoteRecord] = []
  @State private var launching: String?
  @State private var issue = ""
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
          Text("Connections").tag("Connections"); Text("Experiments").tag("Experiments")
        }.pickerStyle(.segmented)
        if section == "Connections" {
          ForEach(store.profiles) { profile in connection(profile) }
          if store.profiles.isEmpty { ContentUnavailableView("Bring your harnesses", systemImage: "sparkles", description: Text("Configure and share a connection from your Mac. Credentials stay there.")) }
        } else {
          Picker("Workspace", selection: $project) {
            Text("Choose a workspace").tag("")
            ForEach(store.projects) { Text($0.text("name")).tag($0.id) }
          }
          if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
          ForEach(experiments) { experiment in
            NavigationLink { JobScreen(identity: experiment.id) } label: { CompanionCard { JobRow(job: experiment) } }.buttonStyle(.plain)
          }
          if !project.isEmpty && experiments.isEmpty && issue.isEmpty {
            ContentUnavailableView("Your next improvement starts here", systemImage: "chart.bar.xaxis",
              description: Text("Run a setup check or a reviewed live evaluation. Results stay recorded on your Mac."))
          }
          Button { launching = project } label: { Label("New evaluation", systemImage: "plus") }
            .buttonStyle(CompanionPrimaryButton())
            .disabled(project.isEmpty || !store.canMutate || (!store.permissions.contains("evaluate") && !store.permissions.contains("optimize")))
        }
        Text("Execution uses the Mac's configured harness and policy. Local-only connections never fall back to an unverified cloud optimizer.")
          .font(.caption).foregroundStyle(.secondary)
      }.padding(20).frame(maxWidth: 900).frame(maxWidth: .infinity)
    }.background(CompanionTheme.background).navigationTitle("Harness lab").companionNavigationBrand()
      .task(id: project) { await load() }
      .refreshable { await store.refresh(); await load() }
      .sheet(isPresented: Binding(get: { launching != nil }, set: { if !$0 { launching = nil } }), onDismiss: { Task { await load() } }) {
        if let launching { NavigationStack { EvaluationScreen(project: launching) } }
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
        Button("Evaluate this workspace") { launching = profile.text("project") }
          .disabled(!store.canMutate || !store.permissions.contains("evaluate"))
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
