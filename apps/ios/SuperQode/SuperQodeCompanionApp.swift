import SwiftUI

@main struct SuperQodeCompanionApp: App {
  @StateObject private var store: CompanionStore
  @AppStorage("companionAppearance") private var appearance = CompanionAppearance.system.rawValue
  init() {
    #if DEBUG
    if ProcessInfo.processInfo.arguments.contains("--design-preview") {
      _store = StateObject(wrappedValue: CompanionPreview.makeStore())
    } else { _store = StateObject(wrappedValue: CompanionStore()) }
    #else
    _store = StateObject(wrappedValue: CompanionStore())
    #endif
  }
  var body: some Scene {
    WindowGroup {
      CompanionRootView().environmentObject(store)
        .preferredColorScheme((CompanionAppearance(rawValue: appearance) ?? .system).scheme)
        .task { await store.restore() }
        .onOpenURL { store.acceptInvitation($0) }
    }
  }
}

struct CompanionRootView: View {
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.scenePhase) private var scenePhase
  var body: some View {
    Group {
      if store.paired {
        TabView(selection: $store.selectedTab) {
          NavigationStack { ProjectsScreen() }.tabItem { Label("Workspaces", systemImage: "square.grid.2x2") }.tag(0)
          NavigationStack { ActivityScreen() }.tabItem { Label("Activity", systemImage: "waveform.path") }.tag(1)
          NavigationStack { HarnessLabScreen() }.tabItem { Label("Harness lab", systemImage: "sparkles") }.tag(2)
          NavigationStack { CompanionSettingsScreen() }.tabItem { Label("Settings", systemImage: "slider.horizontal.3") }.tag(3)
        }
      } else if store.restoring {
        VStack(spacing: 20) { SuperQodeMark(size: 64); ProgressView("Opening your workspace…") }
          .frame(maxWidth: .infinity, maxHeight: .infinity).background(CompanionTheme.background)
      } else { NavigationStack { PairMacScreen() } }
    }.tint(CompanionTheme.accent)
      .task(id: "\(scenePhase)-\(store.paired)-\(store.selectedTab)") {
        guard scenePhase == .active, store.paired else { return }
        await store.refresh()
        guard store.selectedTab == 0 || store.selectedTab == 1 else { return }
        while !Task.isCancelled {
          do { try await Task.sleep(for: .seconds(5)) } catch { break }
          await store.refreshActivity()
        }
      }
  }
}

struct ConnectionStatus: View {
  @EnvironmentObject private var store: CompanionStore
  private var title: String {
    if store.isPreview { return "Explore mode · sample data" }
    switch store.phase {
    case .connected: return "Private connection to \(store.macName)"
    case .connecting: return "Connecting to your Mac…"
    case .authorizationExpired: return "Pair this iPhone again"
    default: return "Your Mac is currently unavailable"
    }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack(spacing: 8) {
        if store.phase == .connecting { ProgressView().controlSize(.small) }
        else { Image(systemName: store.isPreview ? "eye" : store.reachable ? "checkmark.shield.fill" : "wifi.exclamationmark") }
        Text(title).font(.caption.weight(.semibold))
      }.foregroundStyle(store.reachable ? CompanionTheme.accent : Color.orange)
      if !store.message.isEmpty { Text(store.message).font(.caption).foregroundStyle(.secondary) }
      if store.phase == .authorizationExpired {
        Button("Pair again") { Task { await store.disconnect() } }.font(.caption.weight(.semibold))
      }
    }.accessibilityElement(children: .contain)
  }
}

struct ProjectsScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @State private var showingDrafts = false
  @State private var draftCount = 0
  private var working: Int { store.jobs.filter(\.active).count }
  private var attention: Int { store.jobs.filter { $0.text("status") == "needs_approval" }.count }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 24) {
        VStack(alignment: .leading, spacing: 8) {
          Text("YOUR WORKSPACE").font(.caption.weight(.semibold)).tracking(1.8).foregroundStyle(.secondary)
          Text("Make room\nfor your next idea.").font(.system(.largeTitle, design: .rounded, weight: .bold))
          Text("Your Mac does the work. You stay in the flow.").font(.subheadline).foregroundStyle(.secondary)
        }.padding(.top, 12)
        macCard
        if attention > 0 {
          Button { store.activityFilter = "Approvals"; store.selectedTab = 1 } label: {
            HStack {
              Image(systemName: "hand.raised.fill").foregroundStyle(CompanionTheme.warning)
              VStack(alignment: .leading, spacing: 3) {
                Text("\(attention) action\(attention == 1 ? "" : "s") waiting for you").font(.subheadline.bold())
                Text("Review the exact action before it runs.").font(.caption).foregroundStyle(.secondary)
              }
              Spacer(); Image(systemName: "chevron.right").font(.caption)
            }.padding(16).background(Color.orange.opacity(0.09), in: RoundedRectangle(cornerRadius: 16))
          }.buttonStyle(.plain)
        }
        DeveloperShortcuts()
        HStack {
          Text("Workspaces").font(.title3.bold())
          Spacer()
          Button { showingDrafts = true } label: { Label(draftCount > 0 ? "Drafts · \(draftCount)" : "Drafts", systemImage: "square.and.pencil") }.font(.subheadline)
        }
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 280), spacing: 16)], spacing: 16) {
          ForEach(store.projects) { project in
            NavigationLink { ProjectScreen(project: project) } label: { projectCard(project) }.buttonStyle(.plain)
          }
        }
        if store.projects.isEmpty {
          ContentUnavailableView("A workspace of your own", systemImage: "folder.badge.plus",
            description: Text("Share a project connection in your Mac's Private remote access settings. It will appear here."))
        }
        Text("Models, credentials and execution stay on your Mac. Your phone receives the conversations and results you request.")
          .font(.caption).foregroundStyle(.secondary)
      }.padding(20).frame(maxWidth: 1000).frame(maxWidth: .infinity)
    }.background(CompanionTheme.background).navigationTitle("Workspaces").companionNavigationBrand()
      .toolbar { ToolbarItem(placement: .topBarTrailing) { NavigationLink { AllFeaturesScreen() } label: { Image(systemName: "square.grid.2x2") }.accessibilityLabel("All features") } }
      .sheet(isPresented: $showingDrafts, onDismiss: { Task { await refreshDraftCount() } }) { NavigationStack { DraftsScreen() } }
      .task { await refreshDraftCount() }
      .refreshable { await store.refresh(); await refreshDraftCount() }
  }
  private var macCard: some View {
    CompanionCard {
      HStack(spacing: 14) {
        Image(systemName: "desktopcomputer").font(.title2).foregroundStyle(CompanionTheme.accent)
          .frame(width: 48, height: 48).background(CompanionTheme.accent.opacity(0.1), in: RoundedRectangle(cornerRadius: 14))
        VStack(alignment: .leading, spacing: 4) {
          Text(store.macName).font(.headline)
          Text(working > 0 ? "\(working) active run\(working == 1 ? "" : "s")" : "Ready when you are").font(.subheadline).foregroundStyle(.secondary)
        }
        Spacer()
        if store.reachable { Circle().fill(store.isPreview ? CompanionTheme.accent : Color.green).frame(width: 8, height: 8).accessibilityLabel(store.isPreview ? "Sample workspace" : "Connected") }
        else { Button { Task { await store.refresh() } } label: { Image(systemName: "arrow.clockwise") }.accessibilityLabel("Reconnect to Mac") }
      }
      ConnectionStatus()
    }
  }
  private func projectCard(_ project: RemoteRecord) -> some View {
    CompanionCard {
      HStack {
        Image(systemName: "folder.fill").font(.title2).foregroundStyle(CompanionTheme.accent)
        Spacer(); Image(systemName: "arrow.up.right").foregroundStyle(.secondary)
      }
      Text(project.text("name")).font(.title3.bold()).foregroundStyle(.primary)
      let profiles = store.profiles.filter { $0.text("project") == project.id }
      Text("\(profiles.count) shared connection\(profiles.count == 1 ? "" : "s")").font(.subheadline).foregroundStyle(.secondary)
      if let profile = profiles.first { HarnessBadge(name: profile.text("name")) }
    }
  }
  private func refreshDraftCount() async {
    guard !store.isPreview else { draftCount = 0; return }
    draftCount = (try? await store.drafts.list().filter { $0.origin == store.address }.count) ?? 0
  }
}

struct ActivityScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @State private var query = ""
  @State private var initialRun: OpenedRun?
  private var jobs: [RemoteRecord] {
    store.jobs.filter {
      (store.activityFilter == "All" || (store.activityFilter == "Running" ? $0.active : $0.text("status") == "needs_approval"))
        && (query.isEmpty || $0.text("conversation_title", $0.text("title")).localizedCaseInsensitiveContains(query))
    }
  }
  var body: some View {
    List {
      Section { ConnectionStatus() }.listRowBackground(Color.clear)
      Picker("Filter", selection: $store.activityFilter) {
        Text("All").tag("All"); Text("Running").tag("Running"); Text("Approvals").tag("Approvals")
      }.pickerStyle(.segmented).listRowBackground(Color.clear)
      ForEach(jobs) { job in
        NavigationLink { JobScreen(identity: job.id) } label: { JobRow(job: job) }.listRowBackground(CompanionTheme.panel)
      }
      if jobs.isEmpty { ContentUnavailableView("All caught up", systemImage: "checkmark.circle", description: Text("Matching activity from your shared workspaces will appear here.")) }
      Section { Text("Recent runs across shared workspaces. Open a workspace to search its complete conversation history.").font(.caption).foregroundStyle(.secondary) }.listRowBackground(Color.clear)
    }.scrollContentBackground(.hidden).background(CompanionTheme.background)
      .navigationTitle("Activity").searchable(text: $query, prompt: "Search recent activity")
      .navigationDestination(item: $initialRun) { JobScreen(identity: $0.id) }
      .task { if store.isPreview { initialRun = CompanionPreview.initialRun } }
      .refreshable { await store.refreshActivity() }
      .companionNavigationBrand()
  }
}

struct JobRow: View {
  let job: RemoteRecord
  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(alignment: .top, spacing: 10) {
        Image(systemName: job.text("kind") == "task" ? "bubble.left.and.bubble.right" : "chart.bar.xaxis")
          .foregroundStyle(CompanionTheme.harnessColor(job.text("harness"))).padding(.top, 2)
        Text(job.text("conversation_title", job.text("title", "Conversation"))).font(.headline).lineLimit(2)
        Spacer(minLength: 0)
        if job.flag("pinned") { Image(systemName: "pin.fill").font(.caption).foregroundStyle(CompanionTheme.accent) }
      }
      HStack {
        Text(job.text("status").replacingOccurrences(of: "_", with: " ").capitalized)
          .foregroundStyle(job.text("status") == "needs_approval" ? CompanionTheme.warning : job.text("status") == "failed" ? Color.red : Color.secondary)
        Spacer()
        if !job.text("harness").isEmpty { HarnessBadge(name: job.text("harness")) }
      }.font(.caption)
    }.padding(.vertical, 8)
  }
}

struct CompanionSettingsScreen: View {
  @EnvironmentObject private var store: CompanionStore
  @AppStorage("companionAppearance") private var appearance = CompanionAppearance.system.rawValue
  @State private var disconnect = false
  @State private var clearDrafts = false
  @State private var issue = ""
  var body: some View {
    List {
      Section {
        HStack { SuperQodeMark(size: 46); VStack(alignment: .leading, spacing: 4) { Text("SuperQode").font(.title3.bold()); Text("Your private coding companion").font(.caption).foregroundStyle(.secondary) } }.padding(.vertical, 6)
      }.listRowBackground(CompanionTheme.panel)
      Section("Connection") {
        ConnectionStatus()
        LabeledContent("Mac", value: store.macName)
        Text(store.address).font(.caption.monospaced()).textSelection(.enabled).foregroundStyle(.secondary)
        if let expires = store.deviceExpires { LabeledContent("Authorization expires", value: expires.formatted(date: .abbreviated, time: .omitted)) }
        Button("Check connection") { Task { await store.refresh() } }
        if store.isPreview { Button("Connect my own Mac") { store.exitExploreMode() } }
        else { Button("Disconnect this iPhone", role: .destructive) { disconnect = true } }
      }.listRowBackground(CompanionTheme.panel)
      Section("Appearance") {
        Picker("Theme", selection: $appearance) { ForEach(CompanionAppearance.allCases, id: \.rawValue) { Text($0.title).tag($0.rawValue) } }
        Text("Follow your device appearance, or choose a light or dark workspace.").font(.caption).foregroundStyle(.secondary)
      }.listRowBackground(CompanionTheme.panel)
      Section("Your data") {
        Label("Provider credentials stay on your Mac", systemImage: "desktopcomputer")
        Label("Device authorization stays in Keychain", systemImage: "key.fill")
        Text("Unsent drafts use protected storage on this iPhone and are excluded from backups. Completed job history stays on the Mac; requested output is displayed here.").font(.footnote).foregroundStyle(.secondary)
        Button("Delete saved drafts on this iPhone", role: .destructive) { clearDrafts = true }.disabled(store.isPreview)
        if !issue.isEmpty { Text(issue).foregroundStyle(CompanionTheme.warning) }
      }.listRowBackground(CompanionTheme.panel)
      Section("Help & about") {
        NavigationLink("All developer features") { AllFeaturesScreen() }
        NavigationLink("Setup guide and privacy") { CompanionSetupGuide() }
        Link("Private connection setup", destination: URL(string: "https://tailscale.com/docs/features/tailscale-serve")!)
        Link("Source repository", destination: URL(string: "https://github.com/SuperagenticAI/superqode")!)
        Text("Keep the Mac awake and online. Providers can use their own cloud services. All developer features lists which workflows are available here and which still require the Mac.").font(.footnote).foregroundStyle(.secondary)
        LabeledContent("Version", value: Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String ?? "Source build")
      }.listRowBackground(CompanionTheme.panel)
    }.scrollContentBackground(.hidden).background(CompanionTheme.background).navigationTitle("Settings").companionNavigationBrand()
      .confirmationDialog("Disconnect this iPhone?", isPresented: $disconnect, titleVisibility: .visible) {
        Button("Disconnect", role: .destructive) { Task { await store.disconnect() } }
      } message: { Text("Tasks keep running on the Mac. Revoke this device there to invalidate its authorization. Saved drafts remain on this iPhone.") }
      .confirmationDialog("Delete all saved drafts?", isPresented: $clearDrafts, titleVisibility: .visible) {
        Button("Delete drafts", role: .destructive) { Task { do { try await store.drafts.clear(); issue = "" } catch { issue = error.localizedDescription } } }
      } message: { Text("This removes unsent text and saved request IDs from this iPhone. It does not cancel any task on the Mac.") }
  }
}
