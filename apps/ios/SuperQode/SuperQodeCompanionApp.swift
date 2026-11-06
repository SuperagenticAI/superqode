import SwiftUI

@main struct SuperQodeCompanionApp: App {
  @StateObject private var store = CompanionStore()
  var body: some Scene {
    WindowGroup {
      CompanionRootView().environmentObject(store)
        .preferredColorScheme(.dark)
        .task { await store.restore() }
        .onOpenURL { store.acceptInvitation($0) }
    }
  }
}

enum CompanionTheme {
  static let background = Color(red: 0.035, green: 0.055, blue: 0.085)
  static let panel = Color(red: 0.065, green: 0.09, blue: 0.13)
  static let accent = Color(red: 0.3, green: 0.86, blue: 0.82)
  static func harnessColor(_ name: String) -> Color {
    let lower = name.lowercased()
    if lower.contains("claude") { return .orange }
    if lower.contains("qwen") || lower.contains("gemma") { return .purple }
    if lower.contains("codex") || lower.contains("openai") { return .cyan }
    if lower.contains("deepseek") { return .blue }
    if lower.contains("glm") || lower.contains("kimi") { return .pink }
    return accent
  }
}

struct CompanionCard<Content: View>: View {
  let content: Content
  init(@ViewBuilder content: () -> Content) { self.content = content() }
  var body: some View {
    VStack(alignment: .leading, spacing: 12) { content }
      .frame(maxWidth: .infinity, alignment: .leading).padding(18)
      .background(CompanionTheme.panel, in: RoundedRectangle(cornerRadius: 22))
      .overlay(RoundedRectangle(cornerRadius: 22).stroke(.white.opacity(0.06)))
  }
}

struct HarnessBadge: View {
  let name: String
  var body: some View {
    let color = CompanionTheme.harnessColor(name)
    HStack(spacing: 6) {
      Image(systemName: "sparkles").symbolRenderingMode(.hierarchical)
      Text(name).lineLimit(1)
    }.font(.caption.weight(.semibold)).foregroundStyle(color)
      .padding(.horizontal, 10).padding(.vertical, 6)
      .background(color.opacity(0.12), in: Capsule())
  }
}

struct CompanionRootView: View {
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.scenePhase) private var scenePhase
  @State private var tab = 0
  var body: some View {
    Group {
      if store.paired {
        TabView(selection: $tab) {
          NavigationStack { ProjectsScreen() }
            .tabItem { Label("Projects", systemImage: "square.grid.2x2") }.tag(0)
          NavigationStack { ActivityScreen() }
            .tabItem { Label("Activity", systemImage: "waveform.path") }.tag(1)
          NavigationStack { ConnectionsScreen() }
            .tabItem { Label("Harnesses", systemImage: "sparkles") }.tag(2)
          NavigationStack { CompanionSettingsScreen() }
            .tabItem { Label("Settings", systemImage: "slider.horizontal.3") }.tag(3)
        }
      } else { NavigationStack { PairMacScreen() } }
    }
    .tint(CompanionTheme.accent)
    .task(id: "\(scenePhase)-\(store.paired)-\(tab)") {
      guard scenePhase == .active, store.paired else { return }
      await store.refresh()
      guard tab == 0 || tab == 1 else { return }
      while !Task.isCancelled {
        do { try await Task.sleep(for: .seconds(5)) } catch { break }
        await store.refreshActivity()
      }
    }
  }
}

struct ConnectionStatus: View {
  @EnvironmentObject private var store: CompanionStore
  var body: some View {
    VStack(alignment: .leading, spacing: 6) {
      Label(store.reachable ? "Connected privately to your Mac" : "Mac connection needs attention",
        systemImage: store.reachable ? "checkmark.shield.fill" : "wifi.exclamationmark")
        .font(.caption.weight(.medium)).foregroundStyle(store.reachable ? CompanionTheme.accent : .orange)
      if !store.message.isEmpty { Text(store.message).font(.caption).foregroundStyle(.secondary) }
    }.accessibilityElement(children: .combine)
  }
}

struct ProjectsScreen: View {
  @EnvironmentObject private var store: CompanionStore
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        VStack(alignment: .leading, spacing: 8) {
          Text("Your Mac,\nwithin reach.").font(.system(.largeTitle, design: .rounded, weight: .bold))
          Text("Local execution. Private connection.").foregroundStyle(.secondary)
        }.padding(.vertical, 8)
        ConnectionStatus()
        ForEach(store.projects) { project in
          NavigationLink { ProjectScreen(project: project) } label: {
            CompanionCard {
              HStack {
                Image(systemName: "folder.fill").font(.title2).foregroundStyle(CompanionTheme.accent)
                Text(project.text("name")).font(.title3.bold()).foregroundStyle(.primary)
                Spacer()
                Image(systemName: "arrow.up.right").foregroundStyle(.secondary)
              }
              let profiles = store.profiles.filter { $0.text("project") == project.id }
              Text("\(profiles.count) shared connection\(profiles.count == 1 ? "" : "s")")
                .font(.subheadline).foregroundStyle(.secondary)
              if let profile = profiles.first { HarnessBadge(name: profile.text("name")) }
            }
          }.buttonStyle(.plain)
        }
        if store.projects.isEmpty {
          ContentUnavailableView("No projects shared", systemImage: "folder.badge.plus",
            description: Text("Share a project connection and pair this device in the Mac app's Private remote access settings."))
        }
      }.padding(20)
    }.background(CompanionTheme.background).navigationTitle("SuperQode")
      .navigationBarTitleDisplayMode(.inline)
      .refreshable { await store.refresh() }
  }
}

struct ActivityScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @State private var filter = "All"
  private var jobs: [RemoteRecord] {
    store.jobs.filter { filter == "All" || (filter == "Running" ? $0.active : $0.text("status") == "needs_approval") }
  }
  var body: some View {
    List {
      Section { ConnectionStatus() }
      Picker("Filter", selection: $filter) {
        Text("All").tag("All"); Text("Running").tag("Running"); Text("Approvals").tag("Approvals")
      }.pickerStyle(.segmented).listRowBackground(Color.clear)
      ForEach(jobs) { job in
        NavigationLink { JobScreen(identity: job.id) } label: { JobRow(job: job) }
          .listRowBackground(CompanionTheme.panel)
      }
      if jobs.isEmpty { Text("No matching runs. Tasks started on your Mac will appear here too.").foregroundStyle(.secondary) }
    }.scrollContentBackground(.hidden).background(CompanionTheme.background)
      .navigationTitle("Activity").refreshable { await store.refreshActivity() }
  }
}

struct JobRow: View {
  let job: RemoteRecord
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack {
        Image(systemName: job.text("kind") == "task" ? "bubble.left.and.bubble.right" : "chart.bar.xaxis")
          .foregroundStyle(CompanionTheme.harnessColor(job.text("harness")))
        Text(job.text("conversation_title", job.text("title", "Run"))).font(.headline).lineLimit(2)
      }
      HStack {
        Text(job.text("status").replacingOccurrences(of: "_", with: " ").capitalized)
          .foregroundStyle(job.text("status") == "needs_approval" ? Color.orange : Color.secondary)
        Spacer()
        if !job.text("harness").isEmpty { HarnessBadge(name: job.text("harness")) }
      }.font(.caption)
    }.padding(.vertical, 6)
  }
}

struct ProjectScreen: View {
  let project: RemoteRecord
  @EnvironmentObject private var store: CompanionStore
  @State private var compose = false
  @State private var evaluate = false
  var body: some View {
    List {
      Section("Workspace") {
        NavigationLink { FilesScreen(project: project.id) } label: { Label("Browse files", systemImage: "doc.text") }
        NavigationLink { ChangesScreen(project: project.id) } label: { Label("Review changes", systemImage: "arrow.triangle.branch") }
        Button { evaluate = true } label: { Label("Evaluate and optimize", systemImage: "chart.bar.xaxis") }
          .disabled(!store.permissions.contains("evaluate") && !store.permissions.contains("optimize"))
      }.listRowBackground(CompanionTheme.panel)
      Section("Conversations and runs") {
        ForEach(store.jobs.filter { $0.text("project") == project.id }) { job in
          NavigationLink { JobScreen(identity: job.id) } label: { JobRow(job: job) }
        }
      }.listRowBackground(CompanionTheme.panel)
    }.scrollContentBackground(.hidden).background(CompanionTheme.background)
      .navigationTitle(project.text("name"))
      .toolbar { Button { compose = true } label: { Label("New thread", systemImage: "square.and.pencil") }.disabled(!store.permissions.contains("tasks")) }
      .sheet(isPresented: $compose) { NavigationStack { ComposeTaskScreen(project: project.id) } }
      .sheet(isPresented: $evaluate) { NavigationStack { EvaluationScreen(project: project.id) } }
      .refreshable { await store.refreshActivity() }
  }
}

struct ConnectionsScreen: View {
  @EnvironmentObject private var store: CompanionStore
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 16) {
        Text("The harnesses you trust,\nready on your Mac.").font(.title2.bold())
        Text("Connections are configured and explicitly shared from the Mac. Credentials stay there.").foregroundStyle(.secondary)
        ForEach(store.profiles) { profile in
          CompanionCard {
            HarnessBadge(name: profile.text("name"))
            Text(profile.text("model", "Agent-managed model")).font(.headline)
            Label(profile.flag("local_only") ? "Local inference only" : "Provider or agent-managed inference",
              systemImage: profile.flag("local_only") ? "desktopcomputer" : "network")
              .font(.caption).foregroundStyle(profile.flag("local_only") ? CompanionTheme.accent : .orange)
            Text(profile.text("permission_note")).font(.caption).foregroundStyle(.secondary)
            HStack { if profile.flag("evaluation") { Label("Evaluation", systemImage: "checkmark.seal") }; if profile.flag("optimization") { Label("Optimization", systemImage: "slider.horizontal.3") } }.font(.caption)
          }
        }
      }.padding(20)
    }.background(CompanionTheme.background).navigationTitle("Harnesses")
  }
}

struct CompanionSettingsScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @State private var disconnect = false
  var body: some View {
    List {
      Section("Private connection") {
        ConnectionStatus()
        LabeledContent("Mac", value: store.address.replacingOccurrences(of: "https://", with: ""))
        Button("Check connection") { Task { await store.refresh() } }
        Button("Disconnect this iPhone", role: .destructive) { disconnect = true }
      }.listRowBackground(CompanionTheme.panel)
      Section("Your data") {
        Label("Execution and job history stay on your Mac", systemImage: "desktopcomputer")
        Label("Device credentials use this iPhone's Keychain", systemImage: "key.fill")
        Text("Prompts and results travel through an encrypted private connection. Configured cloud agents can still contact their own providers. Keep your Mac awake and online.").font(.footnote).foregroundStyle(.secondary)
      }.listRowBackground(CompanionTheme.panel)
      Section("Companion preview") {
        Text("Provider installation, model downloads, raw terminals, harness editing and adopting optimization candidates are managed on the Mac. Background push notifications are not included in this preview.").font(.footnote).foregroundStyle(.secondary)
        Link("Private connection documentation", destination: URL(string: "https://tailscale.com/docs/features/tailscale-serve")!)
      }.listRowBackground(CompanionTheme.panel)
    }.scrollContentBackground(.hidden).background(CompanionTheme.background).navigationTitle("Settings")
      .confirmationDialog("Disconnect this iPhone?", isPresented: $disconnect, titleVisibility: .visible) {
        Button("Disconnect", role: .destructive) { Task { await store.disconnect() } }
      } message: { Text("Jobs keep running on the Mac. Revoke this device on the Mac to invalidate its credential everywhere.") }
  }
}
