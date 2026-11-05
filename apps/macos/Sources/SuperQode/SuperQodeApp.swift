import AppKit
import SwiftUI
import UniformTypeIdentifiers
import UserNotifications

@MainActor final class ApplicationDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
  weak var workspace: Workspace?
  var bootReady = false
  var openWorkspace: (() -> Void)?
  private var notificationDestination: (String, String)?
  func applicationDidFinishLaunching(_ notification: Notification) {
    NSApp.setActivationPolicy(.regular)
    if Bundle.main.bundleIdentifier != nil && UserDefaults.standard.bool(forKey: "threadAlertsEnabled") {
      UNUserNotificationCenter.current().delegate = self
    }
    if let url = Bundle.main.url(forResource: "icon", withExtension: "icns"),
      let icon = NSImage(contentsOf: url)
    {
      NSApp.applicationIconImage = icon
    }
    NSApp.appearance = NSAppearance(named: .darkAqua)
    NSApp.activate(ignoringOtherApps: true)
    Task { @MainActor in
      // A launch targeting a project can arrive without a restored window.
      // Open this app's single workspace scene; never start work here.
      for _ in 0..<20 {
        if NSApp.windows.contains(where: { $0.isVisible && $0.title == "SuperQode" }) { return }
        if let openWorkspace = self.openWorkspace { openWorkspace(); return }
        try? await Task.sleep(for: .milliseconds(50))
      }
    }

  }
  func applicationShouldHandleReopen(_ sender: NSApplication, hasVisibleWindows flag: Bool) -> Bool {
    if !flag { openWorkspace?() }
    return true
  }
  func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
    if let workspace,
      workspace.anyActive || workspace.busy || !workspace.fileDrafts.isEmpty
        || !workspace.terminals.running.isEmpty
    {
      guard
        workspace.confirm(
          "Quit SuperQode?",
          (workspace.backgroundEngineMode ? "Agent runs continue in the background engine. Quitting closes app terminals. " : "Quitting stops active runs and terminals. ") + "File-edit drafts (\(workspace.fileDrafts.count)) are kept in local recovery storage when recovery is available. Recorded run history remains on this Mac.",
          button: "Quit")
      else { return .terminateCancel }
    }
    workspace?.saveDraft()
    if let workspace, !workspace.flushRecovery() {
      guard workspace.confirm("Quit without saved recovery?", workspace.recoveryIssue,
        button: "Quit anyway") else { return .terminateCancel }
    }
    workspace?.shutdown()
    return .terminateNow
  }
  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
  nonisolated func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse, withCompletionHandler completionHandler: @escaping () -> Void) {
    let info = response.notification.request.content.userInfo
    let project = info["project"] as? String ?? ""
    let job = info["job"] as? String ?? ""
    Task { @MainActor in
      self.notificationDestination = (project, job)
      if self.bootReady { self.openPendingNotification() }
    }
    completionHandler()
  }
  func openPendingNotification() {
    guard bootReady, let destination = notificationDestination, let workspace else { return }
    notificationDestination = nil
    workspace.threadNotifications.openThread?(destination.0, destination.1)
  }
}

@main struct SuperQodeApp: App {
  @NSApplicationDelegateAdaptor(ApplicationDelegate.self) var delegate
  @StateObject private var workspace = Workspace()
  @State private var showBetaGuide = false
  var body: some Scene {
    Window(Bundle.main.object(forInfoDictionaryKey: "CFBundleDisplayName") as? String ?? "SuperQode", id: "main") {
      RootView().environmentObject(workspace)
        .preferredColorScheme(
          workspace.theme == "system" ? nil : workspace.theme == "light" ? .light : .dark
        )
        .task {
          delegate.workspace = workspace
          await workspace.boot()
          delegate.bootReady = true
          delegate.openPendingNotification()
          applyAppearance()
        }
        .onChange(of: workspace.theme) { _, _ in applyAppearance() }
        .centeredDialog(isPresented: $showBetaGuide, title: "Public Beta") {
          BetaGuideView()
        }
    }
    .defaultSize(width: 1440, height: 900)
    .windowStyle(.hiddenTitleBar)
    .commands {
      WorkspaceWindowCommands(delegate: delegate)
      CommandGroup(replacing: .newItem) {
        WorkspaceCommandMenuItem(app: workspace, action: .openProject)
        WorkspaceCommandMenuItem(app: workspace, action: .newTask)
      }
      CommandGroup(replacing: .help) {
        Button("Public Beta Guide…") { showBetaGuide = true }
        Link("Downloads & Release Notes", destination: BetaRelease.downloads)
        Link("Report an Issue…", destination: BetaRelease.feedback)
        Divider()
        WorkspaceCommandMenuItem(app: workspace, action: .welcome)
        Divider()
        WorkspaceCommandMenuItem(app: workspace, action: .learning)
      }
      CommandMenu("Agent Space") {
        Button("Command Palette…", action: workspace.presentCommandPalette)
          .keyboardShortcut("k").disabled(workspace.showCommandPalette)
        Button("All Features…") { workspace.showWelcome = false; workspace.showFeatureBrowser = true }
          .disabled(workspace.openingProject || workspace.restoringNavigation)
        Divider()
        Button("Next Conversation Tab") { workspace.cycleThreadTab(by: 1) }
          .keyboardShortcut(.tab, modifiers: .control)
          .disabled(workspace.openThreadTabs.isEmpty || workspace.openingProject || workspace.restoringNavigation)
        Button("Previous Conversation Tab") { workspace.cycleThreadTab(by: -1) }
          .keyboardShortcut(.tab, modifiers: [.control, .shift])
          .disabled(workspace.openThreadTabs.isEmpty || workspace.openingProject || workspace.restoringNavigation)
        Divider()
        ForEach(Sections.names, id: \.self) { name in
          WorkspaceCommandMenuItem(app: workspace, action: .section(name))
        }
        Divider()
        WorkspaceCommandMenuItem(app: workspace, action: .back)
        WorkspaceCommandMenuItem(app: workspace, action: .forward)
        WorkspaceCommandMenuItem(app: workspace, action: .refreshChanges)
        WorkspaceCommandMenuItem(app: workspace, action: .exportEvidence)
      }
    }
    Settings { SettingsView().environmentObject(workspace).frame(width: 560, height: 460) }
  }
  private func applyAppearance() {
    NSApp.appearance =
      workspace.theme == "system"
      ? nil : NSAppearance(named: workspace.theme == "light" ? .aqua : .darkAqua)
  }
}

enum Sections {
  static func title(for section: String) -> String {
    section == "Workspace" ? "Agent Space" : section == "Agent activity" ? "All work" : section == "Models" ? "Local AI" : section
  }
  static let names = [
    "Workspace", "Harness Hub", "Models", "Evaluations", "Optimization", "Files", "Tools",
    "Terminal", "Checkpoints", "Review", "Threads", "Agent activity", "Harness Studio", "Super Agent",
  ]
  static let icons = [
    "chevron.left.forwardslash.chevron.right", "square.stack.3d.up", "cpu", "checkmark.seal",
    "slider.horizontal.3", "folder", "wrench.and.screwdriver", "terminal", "clock.arrow.circlepath", "text.magnifyingglass", "bubble.left.and.bubble.right", "square.stack.3d.up", "hammer",
    "arrow.triangle.2.circlepath",
  ]
}
extension Color {
  static var qAccent: Color { NativeAccent.accent() }
  static let qPanel = Color(nsColor: NSColor(name: nil) { appearance in
    appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua ? .black : .white
  })
}
struct BrandMark: View {
  var body: some View {
    Image("BrandMark").resizable().scaledToFit().accessibilityLabel("SuperQode")
  }
}
struct Pill: View {
  var title: String
  var color: Color = .secondary
  var body: some View {
    Text(title).font(.system(size: 11, weight: .semibold, design: .monospaced)).foregroundStyle(
      .primary
    ).padding(.horizontal, 8).padding(.vertical, 5).background(color.opacity(0.11), in: Capsule())
  }
}
struct PageTitle: View {
  var eyebrow: String
  var title: String
  var subtitle: String
  var body: some View {
    VStack(alignment: .leading, spacing: 9) {
      Text(eyebrow.uppercased()).font(.system(size: 11, weight: .bold, design: .monospaced))
        .tracking(2).modifier(BrandText())
      Text(title).font(.system(size: 30, weight: .semibold))
      Text(subtitle).font(.system(size: 13)).foregroundStyle(.secondary).fixedSize(
        horizontal: false, vertical: true)
    }.frame(maxWidth: .infinity, alignment: .leading)
  }
}
struct CodeBlock: View {
  var text: String
  var body: some View {
    ScrollView([.horizontal, .vertical]) {
      Text(text.isEmpty ? "No output recorded." : text).font(.system(size: 11, design: .monospaced))
        .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .topLeading).padding(14)
    }.outlinedSurface(radius: 9)
  }
}
struct EmptyState: View {
  var icon: String
  var title: String
  var detail: String
  var body: some View {
    VStack(spacing: 14) {
      Image(systemName: icon).font(.system(size: 32, weight: .light)).foregroundStyle(Color.qAccent)
      Text(title).font(.title2.weight(.medium))
      Text(detail).font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center).frame(
        maxWidth: 480)
    }.frame(maxWidth: .infinity, maxHeight: .infinity).padding(30)
  }
}
struct RootView: View {
  @EnvironmentObject var app: Workspace
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @AppStorage("animatedInterface") private var animatedInterface = true
  var body: some View {
    GeometryReader { viewport in
      Group {
        if app.showWelcome { WelcomeView() } else { workspaceShell }
      }.frame(width: viewport.size.width, height: viewport.size.height, alignment: .topLeading)
        .clipped()
    }
    .animation(
      reduceMotion || !animatedInterface ? nil : .easeInOut(duration: 0.18), value: app.showWelcome
    )
    .background { BrandBackdrop() }.tint(.qAccent).frame(minWidth: 1120, minHeight: 740)
    .background { CommandPaletteWindowReader(app: app).frame(width: 0, height: 0) }
    .alert(
      "SuperQode",
      isPresented: Binding(get: { app.error != nil }, set: { if !$0 { app.error = nil } })
    ) {
      Button("OK") { app.error = nil }
    } message: {
      Text(app.error ?? "")
    }
    .centeredDialog(isPresented: $app.showConnection, title: "Connect") {
      ConnectionView(initialPage: app.connectionStartPage).environmentObject(app)
    }
    .centeredDialog(isPresented: $app.showConnectionInspector, title: "Connection details") {
      ConnectionInspectorView().environmentObject(app)
    }
    .centeredDialog(isPresented: $app.showLearningGuide, title: "Getting started") {
      LearningGuideView().environmentObject(app)
    }
    .sheet(isPresented: $app.showCommandPalette, onDismiss: app.finishCommandPalette) {
      CommandPaletteView().environmentObject(app)
    }
  }
  private var workspaceShell: some View {
    HStack(spacing: 0) {
      WorkspaceNavigationRail()
      Divider()
      SidebarView().frame(width: 260).background(Color.qPanel)
        .disabled(app.openingProject || app.restoringNavigation)
      Divider()
      VStack(spacing: 0) {
        HStack(spacing: 12) {
          Button {
            app.showWelcome = true
          } label: {
            Image(systemName: "house")
          }
          .help("Welcome to SuperQode").accessibilityLabel("Welcome to SuperQode")
          Button(action: app.goBack) { Image(systemName: "chevron.left") }
            .disabled(app.navigationHistory.isEmpty || app.openingProject || app.restoringNavigation)
            .help("Back (⌘[)").accessibilityLabel("Back")
          Button(action: app.goForward) { Image(systemName: "chevron.right") }
            .disabled(app.forwardHistory.isEmpty || app.openingProject || app.restoringNavigation)
            .help("Forward (⌘])").accessibilityLabel("Forward")
          Text(Sections.title(for: app.section)).font(.system(size: 12, weight: .medium)).lineLimit(1)
          Text("/").foregroundStyle(.tertiary)
          Text(string(app.project, "name", "No project")).font(.system(size: 12)).lineLimit(1).truncationMode(.middle).foregroundStyle(
            .secondary)
          Spacer()
          Button(action: app.presentCommandPalette) {
            Image(systemName: "command")
          }.help("Command Palette (⌘K)").accessibilityLabel("Open command palette")
          Button {
            app.showLearningGuide = true
          } label: {
            Image(systemName: "questionmark.circle")
          }.help("Getting started & learning (⌘?)")
          Pill(title: "ON YOUR MAC", color: .green)
          Button {
            if !app.project.isEmpty {
              NSWorkspace.shared.open(URL(fileURLWithPath: string(app.project, "path")))
            }
          } label: {
            Image(systemName: "folder")
          }.help("Reveal project in Finder").disabled(app.project.isEmpty)
        }.padding(.horizontal, 20).padding(.vertical, 12).modifier(NavigationGlass()).padding(
          .horizontal, 12
        ).padding(.vertical, 6)
        ThreadTabBar()
        ForkWorkspaceBar()
        if app.project.isEmpty && !["Agent activity", "Models"].contains(app.section) {
          GettingStartedView(draftStore: app.draftStore)
        } else {
          GeometryReader { geometry in
            Group {
              switch app.section {
              case "Threads": ThreadsView(library: app.threadLibrary(for: app.projectID)).id(app.projectID)
              case "Agent activity": AgentFleetView()
              case "Harness Hub": HubView()
              case "Harness Studio": HarnessStudioView(library: app.harnessStudio)
              case "Super Agent": CreatorModeView().id(app.projectID)
              case "Models": ModelsView()
              case "Evaluations": EvaluationView()
              case "Optimization": OptimizationView()
              case "Tools": ToolsView()
              default: CodingView()
              }
            }.id(WorkspaceNavigationGroup.isWorkbench(app.section) ? "workbench" : app.section).transition(.opacity).disabled(app.openingProject || app.restoringNavigation).frame(
              width: geometry.size.width, height: geometry.size.height, alignment: .topLeading
            )
            .background(Color.qPanel)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.primary.opacity(0.07)))
          }.padding(.horizontal, 20).padding(.bottom, 20)
        }
        ExecutionRecoveryView()
        if !app.recoveryIssue.isEmpty {
          HStack {
            Label(app.recoveryIssue, systemImage: "exclamationmark.triangle").font(.caption)
              .textSelection(.enabled)
            Spacer()
            Button("Retry recovery save") { app.saveDraft(); app.flushRecovery() }
            if !app.recoveryStore.loadIssue.isEmpty {
              Button("Reset recovery…", action: app.resetRecovery)
            }
          }.padding(12).background(Color.orange.opacity(0.12))
        }
        if !app.notice.isEmpty {
          HStack {
            Text(app.notice).font(.caption)
            Spacer()
            nativeButton("notice.close", action: { app.notice = "" }, title: "Dismiss notification") {
              Image(systemName: "xmark")
            }
          }.padding(12).background(Color.qAccent.opacity(0.1))
        }
      }.frame(maxWidth: .infinity, maxHeight: .infinity, alignment: .topLeading)
    }
    // Section changes replace substantial editors and inspectors. A shell-wide
    // animation retains both pages and animates all their layout work per click.

  }
}
extension Dictionary where Key == String, Value == Any {
  var projectRowID: String {
    self["id"] as? String ?? self["model_id"] as? String ?? self["name"] as? String ?? ""
  }
}

struct RouteControls: View {
  @EnvironmentObject var app: Workspace
  var allowACP = true
  var body: some View {
    HStack(alignment: .bottom, spacing: 12) {
      VStack(alignment: .leading, spacing: 6) {
        Text("HARNESS").font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
        Picker("Harness", selection: Binding(get: { app.harness }, set: { app.chooseHarness($0) }))
        {
          if !allowACP && app.isManaged { Text("Choose a HarnessSpec").tag(app.harness) }
          ForEach(
            app.harnesses.filter { allowACP || string($0, "desktop_kind").isEmpty },
            id: \.projectRowID
          ) { row in
            Text(string(row, "name")).tag(string(row, "id"))
          }
        }.labelsHidden().frame(minWidth: 170)
      }
      VStack(alignment: .leading, spacing: 6) {
        Text("PROVIDER").font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
        if app.isACP {
          Text("Agent-managed auth").font(.caption).frame(width: 150, height: 22)
        } else {
          TextField("openai / anthropic / ollama", text: $app.provider).textFieldStyle(
            .roundedBorder
          ).frame(width: 150)
        }
      }
      VStack(alignment: .leading, spacing: 6) {
        Text("MODEL").font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
        TextField(app.isACP ? "Agent default (optional)" : "Enter model ID", text: $app.model)
          .textFieldStyle(.roundedBorder).frame(
            minWidth: 150)
      }
    }
  }
}
struct CodingView: View {
  @EnvironmentObject var app: Workspace
  @State private var shareSource = ""
  @State private var shareProject = ""
  @State private var showShare = false
  @State private var forkSource: [String: Any]?
  @StateObject private var review = WorkbenchReview()
  @State private var scope: ReviewScope = .turn
  @State private var showFullReview = false
  @State private var inspectorTab = "Changes"
  private var reviewKey: String { app.projectID + "\n" + app.selectedJob + "\n" + scope.rawValue + "\n" + string(app.detail, "status") + "\n" + String(app.connected) + "\n" + String(app.inspectorVisible) + "\n" + String(app.drawerExpanded) + "\n" + inspectorTab }
  var body: some View {
    GeometryReader { geometry in
      VStack(spacing: 0) {
        workbenchToolbar
        Divider()
        if app.detail["archived"] as? Bool == true {
          HStack { Label("Archived thread", systemImage: "archivebox"); Spacer(); Button("Restore thread") { app.restoreSelectedThread() } }
            .font(.caption).padding(10)
        }
        if app.connected && string(app.detail, "status") == "needs_approval",
          let approval = app.events.last(where: { string($0, "type") == "approval" }) {
          EventRow(event: approval, embeddedResponse: true).padding(10)
        }
        ZStack(alignment: .bottom) {
          VStack(spacing: 0) {
            let wide = geometry.size.width >= 900
            let layout = wide ? AnyLayout(HStackLayout(spacing: 0)) : AnyLayout(ZStackLayout())
            layout {
              conversation.frame(minWidth: wide ? 400 : nil, maxWidth: .infinity, maxHeight: .infinity)
                .opacity(!wide && app.inspectorVisible ? 0 : 1)
                .allowsHitTesting(wide || !app.inspectorVisible)
                .accessibilityHidden(!wide && app.inspectorVisible)
              if app.inspectorVisible {
                if wide { Divider() }
                inspector.frame(width: wide ? 350 : nil).background(Color.qPanel)
              }
            }.frame(maxHeight: .infinity)
            CodingComposer(draftStore: app.draftStore)
          }
          .padding(.bottom, !app.workbenchDrawer.isEmpty && !app.drawerExpanded ? max(150, min(220, geometry.size.height * 0.30)) : 0)
          .opacity(app.drawerExpanded ? 0 : 1)
          .disabled(app.drawerExpanded).allowsHitTesting(!app.drawerExpanded)
          .accessibilityHidden(app.drawerExpanded)
          if !app.workbenchDrawer.isEmpty { drawer(height: geometry.size.height).background(Color.qPanel) }
        }
      }
      .task(id: reviewKey) {
        guard app.connected else { review.reset(); return }
        guard app.inspectorVisible, !app.drawerExpanded, inspectorTab == "Changes" else { return }
        await review.load(engine: app.engine, project: app.projectID, job: app.selectedJob, scope: scope)
      }
    }
    .centeredDialog(isPresented: $showShare, title: "Share thread context") {
      ThreadShareView(project: shareProject, source: shareSource).environmentObject(app)
    }
    .centeredDialog(isPresented: Binding(get: { forkSource != nil }, set: { if !$0 { forkSource = nil } }), title: "Fork thread") {
      if let source = forkSource { ThreadForkView(project: string(source, "project"), source: string(source, "id")) }
    }
    .sheet(isPresented: $showFullReview) {
      VStack(spacing: 0) {
        HStack { Text("Full review").font(.headline); Spacer(); Button("Done") { showFullReview = false } }.padding(14)
        ReviewWorkspaceView(commentStore: app.reviewCommentStore).id(app.projectID + "\n" + app.selectedJob)
      }.frame(width: 1000, height: 640).environmentObject(app)
    }
    .onAppear { focusSection() }
    .onChange(of: app.section) { _, section in
      focusSection()
      if section == "Workspace" {
        showFullReview = false
      }
    }
    .onChange(of: app.selectedJob) { _, _ in
      scope = app.selectedJob.isEmpty ? .uncommitted : .turn
    }
    .onChange(of: string(app.detail, "kind")) { _, kind in
      if !kind.isEmpty && kind != "task" { scope = .uncommitted }
    }
  }
  private var inspector: some View {
    VStack(spacing: 0) {
      Picker("Thread inspector", selection: $inspectorTab) {
        Text("Changes").tag("Changes")
        Text("Checks").tag("Checks")
        Text("Evidence").tag("Evidence")
      }.pickerStyle(.segmented).labelsHidden().padding(10)
      Divider()
      if inspectorTab == "Changes" {
        WorkbenchChangesView(review: review, scope: $scope, fullReview: openFullReview, refresh: refreshReview)
      } else { InspectorView(fixedTab: inspectorTab) }
    }
  }
  private var conversation: some View {
    Group {
      if app.selectedJob.isEmpty { GettingStartedView(draftStore: app.draftStore) }
      else { EventStream().id(app.projectID + "\n" + app.selectedJob) }
    }
  }
  private var workbenchToolbar: some View {
    HStack(spacing: 12) {
      if !app.selectedJob.isEmpty {
        if app.active { BrandActivityIndicator(status: string(app.detail, "status")) }
        else {
          ThreadStatusIndicator(status: string(app.detail, "status"))
          Text(ThreadStatusIndicator.title(string(app.detail, "status"))).font(.caption).foregroundStyle(.secondary)
        }
      }
      Spacer(minLength: 0)
      Button(app.inspectorVisible ? "Hide changes" : "Changes", systemImage: app.inspectorVisible ? "bubble.left" : "sidebar.right") {
        app.toggleWorkbenchInspector()
      }.help("Show the conversation and changes side by side when space allows")
      ForEach(["Files", "Terminal", "Tasks", "Checkpoints"], id: \.self) { tool in
        Button(tool) { app.toggleWorkbenchDrawer(tool) }
          .fontWeight(app.workbenchDrawer == tool ? .semibold : .regular)
      }
      Menu {
        if !app.repositoryPanels.isEmpty {
          ForEach(app.repositoryPanels, id: \.self) { section in Button(Sections.title(for: section)) { app.section = section } }
          Divider()
        }
        Button("Fork thread…") { forkSource = ["project": app.projectID, "id": app.selectedJob] }
          .disabled(app.active || app.busy || string(app.detail, "kind") != "task")
        Button("Share to thread…") { shareSource = app.selectedJob; shareProject = app.projectID; showShare = true }
          .disabled(app.selectedJob.isEmpty || app.active || app.busy || app.loadingConversationDraft)
        Button("Export evidence…", action: app.exportEvidence).disabled(app.selectedJob.isEmpty)
        Button("Full review…", action: openFullReview)
      } label: { Image(systemName: "ellipsis") }.menuStyle(.borderlessButton).fixedSize()
    }.font(.system(size: 11)).buttonStyle(.plain).padding(.horizontal, 16).padding(.vertical, 10)
  }
  private func focusSection() {
    // Local focus only. Workspace pane state is applied atomically by the
    // navigation action, never from this view-graph callback.
    if app.selectedJob.isEmpty && scope != .uncommitted { scope = .uncommitted }
    if app.section == "Review" && inspectorTab != "Changes" { inspectorTab = "Changes" }
  }
  private func openFullReview() {
    app.reviewSelection.scope = scope; app.section = "Review"; showFullReview = true
  }
  private func refreshReview() {
    guard app.connected else { return }
    Task { await review.load(engine: app.engine, project: app.projectID, job: app.selectedJob, scope: scope) }
  }
  private func drawer(height: CGFloat) -> some View {
    VStack(spacing: 0) {
      Divider()
      HStack {
        Text("PROJECT · " + app.workbenchDrawer.uppercased()).font(.system(size: 10, weight: .semibold)).foregroundStyle(.secondary)
        Spacer()
        Button { app.drawerExpanded.toggle() } label: { Image(systemName: app.drawerExpanded ? "arrow.down.right.and.arrow.up.left" : "arrow.up.left.and.arrow.down.right") }
          .buttonStyle(.plain).accessibilityLabel(app.drawerExpanded ? "Restore conversation" : "Expand project panel")
        Button { app.workbenchDrawer = "" } label: { Image(systemName: "xmark") }.buttonStyle(.plain).accessibilityLabel("Close project panel")
      }.padding(.horizontal, 14).padding(.vertical, 8)
      Group {
        switch app.workbenchDrawer {
        case "Files": FilesView(compact: true).id(app.projectID)
        case "Terminal": ProjectTerminalView(terminals: app.terminals, compact: true)
        case "Tasks": TaskQueueView(compact: true)
        default: CheckpointsView(compact: true).id(app.projectID)
        }
      }.frame(height: app.drawerExpanded ? max(200, height - 70) : max(150, min(220, height * 0.30)))
    }
  }
}

struct ChangeStrip: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    if let line = ChangeSummary.line(
      stat: string(app.git, "stat"), status: string(app.git, "status"),
      diff: string(app.git, "diff"), error: string(app.git, "error")) {
      HStack(spacing: 12) {
        Image(systemName: "arrow.triangle.branch")
        Text(string(app.git, "branch", "Git")).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
        Text(line).font(.system(size: 11, design: .monospaced)).lineLimit(1)
        Spacer()
        Button("Review") { app.section = "Review" }.font(.caption)
        Button(app.inspectorVisible ? "Hide diff" : "Show diff") { app.inspectorVisible.toggle() }
          .font(.caption)
      }.padding(.horizontal, 24).padding(.vertical, 8)
      Divider()
    }
  }
}
struct CodingComposer: View {
  @ObservedObject var draftStore: DraftStore
  @EnvironmentObject var app: Workspace
  @State private var showQueue = false
  @State private var showContext = false
  @State private var showOptions = false
  @State private var isolatePlan: [String: Any]?
  @State private var requestedFiles = false
  @FocusState private var composerFocused: Bool
  private var composerHeight: CGFloat {
    // Height stops growing after eight lines. Avoid allocating every line of
    // a large pasted prompt on each subsequent keystroke.
    let lines = 1 + draftStore.text.utf8.lazy.filter { $0 == 10 }.prefix(7).count
    return min(180, max(54, CGFloat(lines) * 22 + 16))
  }
  private var route: [String: Any] {
    app.harnesses.first { string($0, "id") == app.harness } ?? [:]
  }
  private var routeDisplayName: String {
    if app.connectionDisconnected { return "Connect an agent" }
    let name = string(route, "name", app.harness)
    return app.isManaged ? name : name + " · " + (app.model.isEmpty ? "Choose model" : app.model)
  }
  private var continuesConversation: Bool {
    app.canContinueConversation
  }
  var body: some View {
    composer
    .disabled(app.loadingConversationDraft)
    .centeredDialog(isPresented: $showQueue, title: "Task queue") {
      TaskQueueView().environmentObject(app)
    }
    .centeredDialog(isPresented: $showContext, title: "Project context") {
      ContextPreviewView().environmentObject(app)
    }
    .centeredDialog(
      isPresented: Binding(get: { isolatePlan != nil }, set: { if !$0 { isolatePlan = nil } }),
      title: "Isolate draft in a worktree"
    ) {
      isolateConfirmation
    }
    .onChange(of: draftStore.text) { _, _ in app.scheduleDraftSave() }
    .onChange(of: app.selectedJob) { _, _ in composerFocused = true }
    .onChange(of: app.projectID) { _, _ in requestedFiles = false }
    .onChange(of: app.mentionPrefix) { _, _ in
      if !requestedFiles, app.mentionQuery != nil, app.files.isEmpty {
        requestedFiles = true
        app.loadFiles()
      }
    }
  }
  private var composer: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(spacing: 8) {
        Menu {
          Button(app.connectionDisconnected ? "Connect an agent…" : "Change agent or model…") { app.openConnections() }
            .disabled(!app.connected || app.active || app.busy)
          Button("Connection and model options…") { showOptions = true }.disabled(app.connectionDisconnected)
          if app.isManaged { Button("Connection diagnostics…") { app.showConnectionInspector = true } }
          if !app.connectionDisconnected {
            Divider()
            Button("Disconnect", action: app.disconnectConnection).disabled(app.anyActive || app.busy)
          }
        } label: {
          HStack(spacing: 7) {
            if let identity = app.composerHarnessIdentity {
              HarnessIcon(identity: identity, size: 23)
            } else {
              Image(systemName: "cable.connector").foregroundStyle(.secondary)
                .frame(width: 23, height: 23)
            }
            Text(routeDisplayName).font(.system(size: 11)).lineLimit(1)
          }
        }.menuStyle(.borderlessButton).fixedSize(horizontal: false, vertical: true)
          .help(app.connectionDisconnected ? "No agent connected. Choose a connection for this new thread." : "Connection for your next message. Compatible sessions resume; other routes receive bounded thread context.")
          .popover(isPresented: $showOptions, arrowEdge: .top) { connectionOptions }
        Spacer(minLength: 0)
        if !app.connected { Label("Engine offline · draft kept", systemImage: "exclamationmark.circle").font(.caption).foregroundStyle(.secondary) }
      }
      if app.isManaged || app.routeStatus["ready"] as? Bool == false {
        HStack {
          if app.checkingConnection { ProgressView().controlSize(.small) }
          Text(string(app.routeStatus, "message", "The agent owns sign-in and model access."))
            .font(.caption).foregroundStyle(app.routeStatus["ready"] as? Bool == false ? Color.orange : Color.secondary)
            .lineLimit(2).textSelection(.enabled)
          if string(app.routeStatus, "state") == "connection-failed" {
            Button("Retry") { app.perform { await app.checkManagedConnection() } }.font(.caption)
          }
        }
      }
      if app.isACP {
        if !app.agentModels.isEmpty {
          Picker("Model", selection: $app.agentModel) {
            Text("Agent default").tag("")
            ForEach(app.agentModels, id: \.agentModelID) { row in
              Text(string(row, "name", row.agentModelID) + (row["free"] as? Bool == true ? " · Free" : ""))
                .tag(row.agentModelID)
            }
          }.disabled(app.active || app.checkingConnection)
        } else if !app.checkingConnection {
          Button("Load agent models") { app.perform { await app.checkManagedConnection() } }
        }
      }
      attachments
      PromptEditor(
        text: $draftStore.text,
        onCursorPrefix: app.noteComposerCursor,
        onImagePaste: app.pasteImage,
        onInterceptReturn: app.acceptTopMentionIfNeeded
      ) { app.send(continueSession: continuesConversation) }
        .focused($composerFocused)
        .frame(height: composerHeight).padding(8)
        .outlinedSurface(radius: 8)
        .onDrop(of: [.fileURL], isTargeted: nil) { app.consumeFileDrop($0) }
        .overlay(alignment: .topLeading) {
          if app.draft.isEmpty {
            Text(app.active ? "Draft your next message…" : continuesConversation ? "Ask a follow-up or describe the next change…" : "Describe the change you want to make…")
              .font(.system(size: 14)).foregroundStyle(.secondary).padding(13).allowsHitTesting(false)
          }
        }
        .accessibilityLabel("Message your coding agent")
      mentionChoices
      if app.enforcesSessionControls && app.interactionMode == "plan" {
        Text("Plan mode inspects the repository. It does not edit files, run shell commands, or use the network.")
          .font(.caption).foregroundStyle(.secondary)
      }
      if app.enforcesSessionControls && app.interactionMode != "plan" && app.interactionMode != "chat" && app.permissionMode == "full" {
        Text("Full runs writes and shell without a prompt. Network still asks. This app is not an OS sandbox.")
          .font(.caption).foregroundStyle(.orange)
      }
      if app.connected && !app.connectionDisconnected && !route.isEmpty && !app.isManaged && !app.enforcesSessionControls && app.interactionMode != "chat" {
        Text("This harness runs its own tools and permissions. SuperQode Ask and Plan do not apply.")
          .font(.caption).foregroundStyle(.secondary)
      }
      HStack(spacing: 12) {
        if !app.isManaged {
          Picker("Mode", selection: $app.interactionMode) {
            Text("Code").tag("code")
            if app.enforcesSessionControls { Text("Plan").tag("plan") }
            Text("Chat").tag("chat")
          }.pickerStyle(.menu).labelsHidden().fixedSize().disabled(app.active)
            .accessibilityLabel("Interaction mode")
          if app.interactionMode == "chat" {
            Text("Chat").font(.caption).foregroundStyle(.secondary)
              .help("Chat answers without tools.")
          } else if app.enforcesSessionControls && app.interactionMode == "plan" {
            Text("Ask").font(.caption).foregroundStyle(.secondary)
              .help("Plan keeps Ask. Writes, shell, and network stay closed.")
          } else if app.enforcesSessionControls {
            Picker("Permission", selection: $app.permissionMode) {
              Text("Ask").tag("ask")
              Text("Auto-edit").tag("auto-edit")
              Text("Full").tag("full")
            }.pickerStyle(.menu).labelsHidden().fixedSize()
              .accessibilityLabel("Permission mode")
          }
        }
        Menu {
          Button("Project text files…", action: app.attachFiles)
          Button("Images…", action: app.attachImages)
          Button("Paste image", action: app.pasteImage)
        } label: { Image(systemName: "paperclip") }
          .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().frame(width: 24)
          .accessibilityLabel("Attach context").disabled(app.projectID.isEmpty)
        Button("Context…") { showContext = true }.font(.caption)
        Menu("Tasks") {
          Button("Open queue…") { showQueue = true }
          Button("Add draft to queue", action: app.enqueueDraft).disabled(app.draft.isEmpty || app.connectionDisconnected)
          Button("Isolate draft in a worktree") { previewIsolation() }
            .disabled(app.busy)
        }.menuStyle(.borderlessButton).fixedSize().font(.caption).disabled(app.projectID.isEmpty)
        if app.isACP && !app.agentCommands.isEmpty {
          Menu("Agent commands") {
            ForEach(app.agentCommands, id: \.projectRowID) { command in
              Button("/" + string(command, "name")) { app.draft = "/" + string(command, "name") + " " }
            }
          }.font(.caption).disabled(app.active)
        }
        Spacer()
        if app.canSteer {
          Button("Steer run", action: app.steerDraft).disabled(app.draft.isEmpty)
        }
        if app.active {
          Button("Stop", systemImage: "stop.fill", action: app.cancel)
            .help("Stop the current run; wait for the agent to acknowledge cancellation")
        }
        Button {
          app.send(continueSession: continuesConversation)
        } label: {
          Label(app.busy ? "Starting…" : "Send", systemImage: "arrow.up")
        }.buttonStyle(BrandButtonStyle())
          .disabled(!app.canSubmitDraft)
          .keyboardShortcut(.return, modifiers: .command)
      }
    }
    .onAppear {
      if !app.enforcesSessionControls && app.interactionMode == "plan" { app.interactionMode = "code" }
    }
    .onChange(of: app.enforcesSessionControls) { _, enforced in
      if !enforced && app.interactionMode == "plan" { app.interactionMode = "code" }
    }
    .padding(16).brandSurface().padding(.horizontal, 20).padding(.bottom, 16).padding(.top, 8)
  }
  private var connectionOptions: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Text("Connection options").font(.headline)
        Spacer()
        nativeButton("options.close", action: { showOptions = false }, title: "Close connection options") { Text("Done") }
      }
      RouteReadiness()
      let identity = string(app.connectionMetadata[app.harness] ?? [:], "identity")
      if !identity.isEmpty { PrivateAccountDetails(identity: identity).id(app.harness) }
      if app.isACP {
        if !app.agentSession.isEmpty { AgentControlsView() }
        Text("The selected agent owns sign-in, models and tools. Its supported settings appear after the first connection.")
          .font(.caption).foregroundStyle(.secondary)
      } else if !app.isManaged {
        RouteControls()
        Picker("Interaction", selection: $app.interactionMode) {
          Text("Code").tag("code")
          if app.enforcesSessionControls { Text("Plan").tag("plan") }
          Text("Chat").tag("chat")
        }.pickerStyle(.segmented).disabled(app.active)
      } else {
        let models = app.connectionMetadata[app.harness]?["models"] as? [[String: Any]] ?? []
        if !models.isEmpty {
          Picker("Agent model", selection: $app.model) {
            Text("Agent default").tag("")
            ForEach(models, id: \.projectRowID) { model in
              Text(string(model, "name", string(model, "id"))).tag(string(model, "id"))
            }
          }.disabled(app.active)
        }
      }
      if app.isManaged {
        Button(app.checkingConnection ? "Checking…" : "Check connection") {
          app.perform { await app.checkManagedConnection() }
        }.disabled(app.checkingConnection || app.active)
      }
    }.padding(20).frame(minWidth: 540)
  }
  @ViewBuilder private var mentionChoices: some View {
    if app.mentionQuery != nil && app.mentionMatches.isEmpty {
      Text(app.files.isEmpty ? "Looking up project files…" : "No file matches @" + (app.mentionQuery ?? ""))
        .font(.caption).foregroundStyle(.secondary)
    } else if app.mentionQuery != nil {
      VStack(alignment: .leading, spacing: 2) {
        ForEach(app.mentionMatches, id: \.self) { path in
          Button(path) { app.acceptMention(path) }
            .buttonStyle(.borderless)
            .font(.system(size: 12, design: .monospaced))
        }
      }
    }
  }
  private var isolateConfirmation: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("Branch " + string(isolatePlan ?? [:], "branch"))
        .font(.system(size: 13, design: .monospaced))
      Text("The worktree is created from the latest commit, outside this checkout. Uncommitted files stay here. Nothing runs until you send a task in the new workspace.")
        .font(.callout).foregroundStyle(.secondary)
      Text(string(isolatePlan ?? [:], "path"))
        .font(.caption.monospaced()).foregroundStyle(.secondary).textSelection(.enabled).lineLimit(3)
      HStack {
        Button("Cancel") { isolatePlan = nil }
        Button("Create worktree") { createIsolation() }.buttonStyle(BrandButtonStyle())
          .disabled(app.busy)
      }
    }.padding(20).frame(width: 460)
  }
  private func previewIsolation() {
    let project = app.projectID
    let title = TaskIsolation.title(from: app.draft)
    app.perform {
      let plan = try await app.engine.call(
        "tasks.isolate.preview", ["project": project, "title": title]) as? [String: Any] ?? [:]
      guard app.projectID == project else { return }
      self.isolatePlan = plan
    }
  }
  private func createIsolation() {
    guard let plan = isolatePlan else { return }
    let project = app.projectID
    let sourceComposerKey = app.composerKey
    let carriedText = app.draft
    let carriedFiles = app.contextFiles
    let carriedImages = app.imageAttachments
    app.perform {
      let created = try await app.engine.call(
        "tasks.isolate.create",
        [
          "project": project,
          "fork_id": string(plan, "fork_id"),
          "title": string(plan, "title"),
          "expected_digest": string(plan, "digest"),
        ]) as? [String: Any] ?? [:]
      guard app.projectID == project else { return }
      self.isolatePlan = nil
      try await app.open(string(created, "path"))
      guard app.projectID != project, !app.projectID.isEmpty else { return }
      app.moveDraftToOpenedWorkspace(
        text: carriedText, files: carriedFiles, images: carriedImages, fromProject: project,
        fromComposerKey: sourceComposerKey)
    }
  }
  @ViewBuilder private var attachments: some View {
    if !app.imageAttachments.isEmpty || !app.contextFiles.isEmpty {
      ScrollView(.horizontal) {
        HStack {
          ForEach(app.contextFiles, id: \.self) { path in
            nativeButton("attachment.file." + path, action: { app.contextFiles.removeAll { $0 == path } }, padded: false, title: "Remove " + path) {
              Label(path, systemImage: "xmark.circle").font(.caption)
            }.buttonStyle(.borderless)
          }
          ForEach(app.imageAttachments, id: \.projectRowID) { image in
            nativeButton("attachment.image." + string(image, "id"), action: { app.imageAttachments.removeAll { string($0, "id") == string(image, "id") } }, padded: false, title: "Remove " + string(image, "name")) {
              Label(string(image, "name"), systemImage: "xmark.circle").font(.caption)
            }.buttonStyle(.borderless)
          }
        }
      }.frame(maxHeight: 28)
    }
  }
}

/// Coalesce consecutive model deltas for readable paragraphs while retaining raw evidence.
func displayEvents(_ events: [[String: Any]]) -> [[String: Any]] {
  var rows: [[String: Any]] = []
  var parts: [String] = []
  func flush() {
    guard !parts.isEmpty else { return }
    rows.append(["type": "output", "data": ["text": parts.joined()], "coalesced": true])
    parts.removeAll(keepingCapacity: true)
  }
  for event in events {
    let data = event["data"] as? [String: Any] ?? [:]
    let payload = data["payload"] as? [String: Any] ?? [:]
    let delta = string(event, "type") == "harness_event"
      && ["delta", "model_delta", "message.delta"].contains(string(data, "event"))
    let answer = string(event, "type") == "answer"
    if delta || answer {
      parts.append(answer ? string(data, "text") : string(payload, "text", string(payload, "content")))
    } else {
      flush()
      rows.append(event)
    }
  }
  flush()
  return rows
}
/// Keep approvals, tool work, errors and unknown events visible. Routine engine
/// bookkeeping stays available through Activity details and full evidence export.
func conversationEvents(_ events: [[String: Any]], includeDetails: Bool) -> [[String: Any]] {
  let rows = displayEvents(events)
  guard !includeDetails else { return rows }
  var visible: [[String: Any]] = []
  var activity: [[String: Any]] = []
  for row in rows {
    let type = string(row, "type")
    let data = row["data"] as? [String: Any] ?? [:]
    let name = string(data, "event")
    if ["approval", "error"].contains(type)
      || (type == "output" && row["coalesced"] as? Bool == true)
      || (type == "harness_event" && ["error", "failure", "failed"].contains(name)) {
      visible.append(row)
    } else {
      activity.append(row)
    }
  }
  if !activity.isEmpty {
    visible.append(["type": "activity_group", "data": ["events": activity]])
  }
  return visible
}

/// Completed turns do not rerender their Markdown on every live agent delta.
struct HistoricalConversationTurn: View, Equatable {
  let prompt: String
  let response: String
  let harness: String
  let status: String
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("YOU").font(.system(size: 11, weight: .semibold, design: .monospaced))
        .foregroundStyle(Color.qAccent)
      Text(prompt).font(.system(size: 15)).textSelection(.enabled)
      if !response.isEmpty {
        VStack(alignment: .leading, spacing: 10) {
          Text(harness).font(.caption).foregroundStyle(.secondary)
          ResponseDocument(text: response).equatable()
        }.padding(20).frame(maxWidth: .infinity, alignment: .leading)
          .modifier(ConversationSurface())
      }
      if status != "completed" {
        Text("Previous response: " + status).font(.caption).foregroundStyle(.secondary)
      }
      Divider()
    }.padding(.bottom, 12)
  }
}

struct EventStream: View {
  @EnvironmentObject var app: Workspace
  @State private var follow = true
  @State private var visibleAnchor: String?
  @State private var pendingAnchor: String?
  @State private var savedJob = ""
  @State private var savedProject = ""
  @State private var initialized = false
  @State private var restoringPosition = false
  @State private var restorePages = 0
  @State private var positionNotice = ""
  private var availableAnchors: [String] {
    var anchors = ["bottom"] + app.conversationHistory.map { "turn:" + string($0, "id") }
    if !(app.detail["request"] as? [String: Any] ?? [:]).isEmpty { anchors.append("prompt:" + app.selectedJob) }
    if conversationEvents(app.events, includeDetails: false).contains(where: { string($0, "type") != "activity_group" }) {
      anchors.append("response:" + app.selectedJob)
    }
    return anchors
  }
  var body: some View {
    let rows = conversationEvents(app.events, includeDetails: false)
    let activity = (rows.last(where: { string($0, "type") == "activity_group" })?["data"] as? [String: Any])?["events"] as? [[String: Any]] ?? []
    VStack(spacing: 0) {
      HStack {
        Text("CONVERSATION").font(.system(size: 12, design: .monospaced)).foregroundStyle(
          .secondary)
        Spacer()
        Toggle("Follow", isOn: $follow).toggleStyle(.checkbox).font(.caption)
        if !follow {
          Button("Jump to latest") {
            pendingAnchor = nil
            positionNotice = ""
            follow = true
            visibleAnchor = "bottom"
          }.font(.caption)
        }
        Button("Export…", action: app.exportEvidence).font(.caption)
      }.padding(.horizontal, 20).padding(.top, 10)
      if !app.activityLoadError.isEmpty {
        HStack {
          Label("Couldn’t load run activity.", systemImage: "exclamationmark.triangle")
          Button("Retry") { app.perform { await app.refreshDetail() } }
        }.font(.caption).help(app.activityLoadError).padding(.top, 8)
      } else if app.hasMoreRunEvents || (app.eventStreamOpen && !app.active) {
        Label("Loading run activity…", systemImage: "arrow.down.circle")
          .font(.caption).foregroundStyle(.secondary).padding(.top, 8)
      }
      if app.omittedRunEvents > 0 {
        Text("Showing recent run activity. Export to include all events.")
          .font(.caption).foregroundStyle(.secondary).padding(.top, 8)
      }
      if !positionNotice.isEmpty {
        Text(positionNotice).font(.caption).foregroundStyle(.secondary).padding(.top, 8)
      }
      ScrollViewReader { proxy in
        ScrollView {
          LazyVStack(alignment: .leading, spacing: 10) {
            if !app.earlierHistory.isEmpty {
              Button("Load earlier messages") {
                app.perform { await app.loadConversationHistory(earlier: true) }
              }.disabled(app.loadingHistory)
            }
            ForEach(app.conversationHistory, id: \.projectRowID) { turn in
              HistoricalConversationTurn(prompt: string(turn, "prompt"), response: string(turn, "response"),
                harness: string(turn, "harness"), status: string(turn, "status")).equatable()
                .id("turn:" + string(turn, "id"))
            }
            if let request = app.detail["request"] as? [String: Any],
              !string(request, "prompt").isEmpty
            {
              VStack(alignment: .leading, spacing: 8) {
                Text("YOU").font(.system(size: 11, weight: .semibold, design: .monospaced))
                  .foregroundStyle(Color.qAccent)
                Text(string(request, "prompt")).font(.system(size: 15)).textSelection(.enabled)
                if let continuity = request["_continuity"] as? [String: Any] {
                  Label(string(continuity, "mode") == "handoff" ? "Conversation handed to this agent" : "Agent session resumed",
                    systemImage: "arrow.triangle.branch").font(.caption).foregroundStyle(.secondary)
                  if (continuity["omitted_messages"] as? Int ?? 0) > 0 {
                    Text("Some earlier messages exceed the agent context limit. Your full conversation remains available above.")
                      .font(.caption).foregroundStyle(.secondary)
                  }
                  if continuity["historical_attachments"] as? Bool == true {
                    Text("Reattach earlier images if this agent needs them.").font(.caption).foregroundStyle(.secondary)
                  }
                }
              }.padding(16).frame(maxWidth: .infinity, alignment: .leading).background(
                Color.qPanel, in: RoundedRectangle(cornerRadius: 10)
              ).overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.qAccent.opacity(0.35), lineWidth: 1)).padding(.bottom, 10)
                .id("prompt:" + app.selectedJob)
            }
            let messages = rows.filter { string($0, "type") != "activity_group" }
            if !messages.isEmpty {
              VStack(alignment: .leading, spacing: 16) {
                HStack(spacing: 7) {
                  BrandMark().frame(width: 18, height: 18)
                  Text("SuperQode").font(.system(size: 12, weight: .semibold)).modifier(BrandText())
                }
                ForEach(Array(messages.enumerated()), id: \.offset) { index, event in
                  if index > 0 { Divider() }
                  EventRow(event: event, embeddedResponse: true)
                }
              }.padding(20).frame(maxWidth: .infinity, alignment: .leading).modifier(ConversationSurface())
                .id("response:" + app.selectedJob)
            }
            if messages.isEmpty && !app.hasMoreRunEvents && !app.eventStreamOpen && !app.active {
              VStack(alignment: .leading, spacing: 8) {
                Text("No response text was recorded for this turn.").font(.callout)
                Text("Inspect agent activity or export the recorded evidence. This is not a verification result.").font(.caption).foregroundStyle(.secondary)
              }.padding(16)
            }
            Color.clear.frame(height: 1).id("bottom")
          }.scrollTargetLayout().padding(24).frame(maxWidth: .infinity, alignment: .leading)
        }.scrollPosition(id: $visibleAnchor, anchor: follow ? .bottom : .top)
        .background(TranscriptScrollObserver { readingEarlier in
          pendingAnchor = nil
          positionNotice = ""
          if readingEarlier && follow { follow = false }
        })
        .onAppear {
          savedJob = app.selectedJob
          savedProject = app.projectID
          let saved = app.transcriptPosition(for: savedJob)
          follow = saved.follow
          pendingAnchor = saved.anchor
          initialized = true
          restorePosition(proxy)
        }
        .onChange(of: availableAnchors) { _, _ in restorePosition(proxy) }
        .onChange(of: app.hasMoreRunEvents) { _, _ in restorePosition(proxy) }
        .onChange(of: app.loadingHistory) { _, _ in restorePosition(proxy) }
        .onChange(of: follow) { _, value in
          guard initialized else { return }
          if value { pendingAnchor = nil; positionNotice = ""; proxy.scrollTo("bottom", anchor: .bottom) }
          savePosition()
        }
        .onChange(of: visibleAnchor) { _, _ in
          if initialized && !restoringPosition && pendingAnchor == nil { savePosition() }
        }.onChange(of: app.events.last?["sequence"] as? Int) { _, _ in
          if follow && initialized { proxy.scrollTo("bottom", anchor: .bottom) }
        }
      }
      if app.active || !activity.isEmpty {
        Divider()
        VStack(spacing: 6) {
          if app.active { AgentWorkingCard(status: string(app.detail, "status"), activity: currentAgentActivity(app.events)) }
          if !activity.isEmpty {
            AgentActivityView(events: activity, active: app.active && string(app.detail, "status") != "needs_approval")
              .id(app.selectedJob)
          }
        }.padding(.horizontal, 24).padding(.vertical, 10)
      }
    }.onDisappear { savePosition(); app.scheduleRecoverySave() }
  }
  private func savePosition() {
    guard initialized else { return }
    app.setTranscriptPosition(TranscriptPosition(follow: follow, anchor: pendingAnchor ?? visibleAnchor),
      for: savedJob, project: savedProject)
  }
  private func restorePosition(_ proxy: ScrollViewProxy) {
    guard initialized, savedJob == app.selectedJob, savedProject == app.projectID else { return }
    if follow { proxy.scrollTo("bottom", anchor: .bottom); return }
    guard let anchor = pendingAnchor else { return }
    if availableAnchors.contains(anchor) {
      restoringPosition = true
      visibleAnchor = anchor
      proxy.scrollTo(anchor, anchor: .top)
      pendingAnchor = nil
      positionNotice = ""
      // Let the scroll binding settle before recording its new visible target.
      Task { @MainActor in
        await Task.yield()
        restoringPosition = false
        savePosition()
      }
    } else if !app.loadingHistory && !app.hasMoreRunEvents {
      if !app.earlierHistory.isEmpty && restorePages < 4 {
        restorePages += 1
        app.perform { await app.loadConversationHistory(earlier: true) }
      } else {
        positionNotice = "Your saved reading position isn’t loaded. Load earlier messages or Jump to latest."
      }
    }
  }
}
struct EventRow: View {
  @EnvironmentObject var app: Workspace
  let event: [String: Any]
  var embeddedResponse = false
  var type: String { string(event, "type") }
  var data: [String: Any] { event["data"] as? [String: Any] ?? [:] }
  var body: some View {
    Group {
      if type == "activity_group" {
        AgentActivityView(events: data["events"] as? [[String: Any]] ?? [], active: app.active)
      } else if type == "approval" {
        VStack(alignment: .leading, spacing: 10) {
          Label("Permission requested", systemImage: "hand.raised").font(.headline).foregroundStyle(
            .orange)
          let tool = data["tool"] as? [String: Any] ?? [:]
          let arguments = tool["arguments"] as? [String: Any]
            ?? tool["rawInput"] as? [String: Any] ?? [:]
          Text(string(tool, "title", string(tool, "tool_name", string(tool, "name", "Review the requested action before allowing it."))))
            .textSelection(.enabled)
          if let command = tool["command"] as? String ?? arguments["command"] as? String {
            Text(command).font(.system(.callout, design: .monospaced)).textSelection(.enabled)
          }
          if let path = tool["path"] as? String ?? arguments["path"] as? String {
            Text(path).font(.callout).textSelection(.enabled)
          }
          DisclosureGroup("Technical details") {
            Text(pretty(data["tool"])).font(.system(size: 11, design: .monospaced))
              .textSelection(.enabled).frame(maxWidth: .infinity, alignment: .leading)
          }.font(.caption)
          if data["preview_truncated"] as? Bool == true {
            Text(
              "This request preview is truncated. Deny it if you need complete details before allowing the action."
            ).font(.caption).foregroundStyle(.orange)
          }
          if string(app.detail, "status") == "needs_approval",
            let latest = app.events.last(where: { string($0, "type") == "approval" }),
            (latest["sequence"] as? Int) == (event["sequence"] as? Int)
          {
            HStack {
              Button("Deny") { app.approve(string(data, "request_id"), allow: false) }
              Button("Allow once") { app.approve(string(data, "request_id"), allow: true) }
                .buttonStyle(BrandButtonStyle())
              if (data["options"] as? [[String: Any]] ?? []).contains(where: {
                string($0, "kind") == "allow_always"
              }) {
                Button("Allow always (agent)") {
                  app.approve(string(data, "request_id"), allow: true, always: true)
                }
              }
              if (data["options"] as? [[String: Any]] ?? []).contains(where: {
                string($0, "kind") == "reject_always"
              }) {
                Button("Always deny (agent)") {
                  app.approve(string(data, "request_id"), allow: false, always: true)
                }
              }
            }
          }
        }.padding(14).frame(maxWidth: .infinity, alignment: .leading).background(
          Color.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 8))
      } else if type == "harness_event" {
        let name = string(data, "event")
        let payload = data["payload"] as? [String: Any] ?? [:]
        if ["error", "failure", "failed"].contains(name) {
          Label(string(payload, "message", string(payload, "text", pretty(payload))), systemImage: "exclamationmark.triangle")
            .foregroundStyle(.red).textSelection(.enabled).padding(12)
        } else if ["delta", "model_delta", "message.delta"].contains(name) {
          AgentResponseView(text: string(payload, "text", string(payload, "content")), embedded: embeddedResponse)
        } else {
          DisclosureGroup(name) {
            Text(pretty(payload)).font(.system(size: 11, design: .monospaced)).textSelection(
              .enabled
            ).frame(maxWidth: .infinity, alignment: .leading)
          }.font(.caption).padding(10).outlinedSurface(radius: 6)
        }
      } else if type == "output" {
        if event["coalesced"] as? Bool == true {
          AgentResponseView(text: string(data, "text"), embedded: embeddedResponse)
        } else {
          AgentResponseView(text: string(data, "text"), embedded: embeddedResponse)
        }
      } else if type == "error" {
        VStack(alignment: .leading, spacing: 8) {
          Label("The agent could not complete this request", systemImage: "exclamationmark.triangle").font(.headline)
          Text(string(data, "message", pretty(data))).font(.system(size: 14)).textSelection(.enabled)
          Button("Change connection…") { app.openConnections() }
        }.foregroundStyle(.red).padding(16).frame(maxWidth: .infinity, alignment: .leading)
      } else {
        DisclosureGroup(type.replacingOccurrences(of: "_", with: " ").capitalized) {
          Text(pretty(data)).font(.system(size: 11, design: .monospaced)).textSelection(.enabled)
            .frame(maxWidth: .infinity, alignment: .leading)
        }.font(.caption).foregroundStyle(type == "error" ? Color.red : Color.secondary)
      }
    }
  }
}
struct InspectorView: View {
  var fixedTab: String? = nil
  @EnvironmentObject var app: Workspace
  @State private var tab = "Changes"
  @State private var command = ""
  @State private var commit = ""
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      if fixedTab == nil {
      Picker("Inspector", selection: $tab) {
        Text("Changes").tag("Changes")
        Text("Checks").tag("Checks")
        Text("Evidence").tag("Evidence")
      }.pickerStyle(.segmented)
      }
      if (fixedTab ?? tab) == "Changes" {
        Button("Open review workspace") { app.section = "Review" }
        Text("Current project preview. Open Review to choose a turn, staged/unstaged layers or a branch comparison.")
          .font(.caption).foregroundStyle(.secondary)
        HStack {
          Image(systemName: "arrow.triangle.branch")
          Text(string(app.git, "branch", "No branch")).font(.caption.monospaced())
          Spacer()
          Button {
            app.perform { await app.refreshGit() }
          } label: {
            Image(systemName: "arrow.clockwise")
          }
        }
        Text(string(app.git, "error", string(app.git, "stat", "No tracked changes."))).font(
          .system(size: 11, design: .monospaced)
        ).foregroundStyle(.secondary).textSelection(.enabled)
        DiffView(text: string(app.git, "diff"))
        Text(string(app.git, "status")).font(.system(size: 11, design: .monospaced)).textSelection(
          .enabled
        ).lineLimit(6)
        Button("Stage tracked changes") { app.gitAction("git.stage") }.disabled(app.hasActiveWork(project: app.projectID))
        TextField("Commit message", text: $commit).textFieldStyle(.roundedBorder)
        Button("Commit staged changes") { app.gitAction("git.commit", message: commit) }.disabled(
          commit.isEmpty || app.hasActiveWork(project: app.projectID))
      } else if (fixedTab ?? tab) == "Checks" {
        Text("Run a command in this project").font(.headline)
        Text(
          "Commands run with your Mac account’s permissions. Review commands before running them."
        ).font(.caption).foregroundStyle(.secondary)
        TextField("e.g. uv run pytest -q", text: $command).textFieldStyle(.roundedBorder)
        Button("Run check") { app.start("checks.start", extra: ["command": command]) }.disabled(
          !app.connected || command.isEmpty || app.busy || app.anyActive)
        Spacer()
      } else {
        Text("Recorded locally").font(.headline)
        Text(
          "Harness provenance, tool events and results are saved on this Mac. Export a complete run for review."
        ).font(.caption).foregroundStyle(.secondary)
        CodeBlock(text: pretty(app.detail["result"]))
        Button("Export run evidence…", action: app.exportEvidence).disabled(app.selectedJob.isEmpty)
      }
    }.padding(18).frame(maxHeight: .infinity, alignment: .top).background(Color.qPanel)
  }
}
struct DiffView: View {
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast
  let text: String
  var body: some View {
    ScrollView([.horizontal, .vertical]) {
      LazyVStack(alignment: .leading, spacing: 1) {
        if text.isEmpty { Text("No diff to display").foregroundStyle(.tertiary) }
        ForEach(Array(text.components(separatedBy: "\n").enumerated()), id: \.offset) { _, line in
          Text(line).foregroundStyle(ink(for: line)).textSelection(.enabled).fixedSize(horizontal: true, vertical: false)
        }
      }.font(.system(size: 12, design: .monospaced)).padding(12).frame(
        maxWidth: .infinity, alignment: .leading)
    }.outlinedSurface(radius: 8)
  }
  private func ink(for line: String) -> Color {
    guard contrast != .increased else { return .primary }
    if line.hasPrefix("+") {
      return scheme == .dark
        ? Color(red: 0.52, green: 0.90, blue: 0.63)
        : Color(red: 0.08, green: 0.35, blue: 0.16)
    }
    if line.hasPrefix("-") {
      return scheme == .dark
        ? Color(red: 1, green: 0.69, blue: 0.72)
        : Color(red: 0.62, green: 0.15, blue: 0.15)
    }
    return line.hasPrefix("@@") ? .qAccent : .primary
  }
}
