import AppKit
import SwiftUI

@MainActor final class ApplicationDelegate: NSObject, NSApplicationDelegate {
  weak var workspace: Workspace?
  func applicationDidFinishLaunching(_ notification: Notification) {
    NSApp.setActivationPolicy(.regular)
    if let url = Bundle.main.url(forResource: "icon", withExtension: "icns"),
      let icon = NSImage(contentsOf: url)
    {
      NSApp.applicationIconImage = icon
    }
    NSApp.appearance = NSAppearance(named: .darkAqua)
    NSApp.activate(ignoringOtherApps: true)
  }
  func applicationShouldTerminate(_ sender: NSApplication) -> NSApplication.TerminateReply {
    if let workspace,
      workspace.anyActive || workspace.busy || !workspace.fileDrafts.isEmpty
        || !workspace.terminals.running.isEmpty
    {
      guard
        workspace.confirm(
          "Quit SuperQode?",
          "Quitting stops active runs and terminals. File-edit drafts (\(workspace.fileDrafts.count)) are kept in local recovery storage when recovery is available. Recorded run history remains on this Mac.",
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
  static func title(for section: String) -> String { section == "Workspace" ? "Agent Space" : section }
  static let names = [
    "Workspace", "Harness Hub", "Models", "Evaluations", "Optimization", "Files", "Tools",
    "Terminal", "Checkpoints", "Review",
  ]
  static let icons = [
    "chevron.left.forwardslash.chevron.right", "square.stack.3d.up", "cpu", "checkmark.seal",
    "slider.horizontal.3", "folder", "wrench.and.screwdriver", "terminal", "clock.arrow.circlepath", "text.magnifyingglass",
  ]
}
extension Color {
  static let qAccent = Color(
    nsColor: NSColor(name: nil) { appearance in
      appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        ? NSColor(srgbRed: 0.79, green: 0.47, blue: 0.98, alpha: 1)
        : NSColor(srgbRed: 0.392, green: 0.082, blue: 0.733, alpha: 1)
    })
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
      ConnectionView().environmentObject(app)
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
      SidebarView().frame(width: 236).background(Color.qPanel)
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
          Text(Sections.title(for: app.section)).font(.system(size: 12, weight: .medium))
          Text("/").foregroundStyle(.tertiary)
          Text(string(app.project, "name", "No project")).font(.system(size: 12)).foregroundStyle(
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
          Button("Connect…") { app.showConnection = true }.disabled(
            !app.connected || app.project.isEmpty)
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
        if app.project.isEmpty {
          GettingStartedView(draftStore: app.draftStore)
        } else {
          GeometryReader { geometry in
            Group {
              switch app.section {
              case "Harness Hub": HubView()
              case "Models": ModelsView()
              case "Evaluations": EvaluationView()
              case "Optimization": OptimizationView()
              case "Tools": ToolsView()
              case "Terminal": ProjectTerminalView(terminals: app.terminals)
              case "Checkpoints": CheckpointsView().id(app.projectID)
              case "Review": ReviewWorkspaceView(commentStore: app.reviewCommentStore).id(app.projectID + "\n" + app.selectedJob)
              case "Files": FilesView().id(app.projectID)
              default: CodingView()
              }
            }.id(app.section).transition(.opacity).disabled(app.openingProject || app.restoringNavigation).frame(
              width: geometry.size.width, height: geometry.size.height, alignment: .topLeading
            )
            .background(Color.qPanel)
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.primary.opacity(0.07)))
          }.padding(.horizontal, 20).padding(.bottom, 20)
        }
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
    }.animation(
      reduceMotion || !animatedInterface ? nil : .easeInOut(duration: 0.18), value: app.section
    )

  }
}
struct SidebarView: View {
  @EnvironmentObject var app: Workspace
  @AppStorage("nativeExpandedNavigation") private var expandedNavigation = false
  var body: some View {
    VStack(alignment: .leading, spacing: 0) {
      Button {
        app.showWelcome = true
      } label: {
        HStack(spacing: 10) {
          BrandMark().frame(width: 36, height: 36).accessibilityHidden(true)
          VStack(alignment: .leading, spacing: 2) {
            BrandWordmark()
            Text("Build · Evaluate · Evolve").font(.caption)
              .foregroundStyle(.secondary)
          }
        }
      }.buttonStyle(.plain).help("Welcome to SuperQode")
        .accessibilityLabel("SuperQode, Welcome")
        .accessibilityHint("Return to the welcome page without closing your project.")
        .padding(.horizontal, 20).padding(.top, 26).padding(.bottom, 24)
      Button(action: app.chooseProject) {
        HStack {
          Image(systemName: "folder")
          Text(string(app.project, "name", "Open project")).lineLimit(1)
          Spacer()
          Image(systemName: "plus").font(.caption)
        }.padding(10)
      }.buttonStyle(.plain).outlinedSurface(radius: 8).padding(.horizontal, 14)
      if !app.projects.isEmpty {
        Menu {
          ForEach(app.projects, id: \.projectRowID) { row in
            Button(URL(fileURLWithPath: string(row, "path")).lastPathComponent) {
              app.perform { try await app.open(string(row, "path")) }
            }
          }
        } label: {
          Label("Recent projects", systemImage: "clock").font(.caption).foregroundStyle(.primary)
        }.menuStyle(.borderlessButton).padding(.horizontal, 24).padding(.vertical, 10)
      }
      navigationItems
      Divider().padding(18)
      HStack {
        Text("RECENT RUNS").font(.system(size: 11, weight: .bold, design: .monospaced)).tracking(
          1.5
        )
        .foregroundStyle(.secondary)
        Spacer()
        Button {
          app.selectJob("", targetSection: "Workspace")
        } label: {
          Image(systemName: "plus")
        }.buttonStyle(.plain).disabled(app.openingProject || app.restoringNavigation || app.busy)
      }.padding(.horizontal, 24)
      recentRuns
      Spacer(minLength: 8)
      HStack(spacing: 8) {
        Circle().fill(app.connected ? Color.green : Color.orange).frame(width: 6, height: 6)
        Text(app.connected ? "LOCAL ENGINE" : "ENGINE OFFLINE").font(
          .system(size: 11, design: .monospaced))
        Spacer()
        SettingsLink { Image(systemName: "gearshape") }.buttonStyle(.plain)
      }.foregroundStyle(.secondary).padding(20)
    }.frame(maxHeight: .infinity, alignment: .top).clipped()
  }
  private var navigationItems: some View {
    VStack(spacing: 4) {
      ForEach(["Workspace", "Review", "Files", "Terminal"], id: \.self) { name in
        navigationButton(name)
      }
      DisclosureGroup("Improve & more", isExpanded: $expandedNavigation) {
        VStack(spacing: 3) {
          ForEach(
            Sections.names.filter { !["Workspace", "Review", "Files", "Terminal"].contains($0) }, id: \.self
          ) { name in
            navigationButton(name)
          }
        }.padding(.top, 6)
      }.font(.system(size: 12)).padding(.horizontal, 10).padding(.top, 8)
    }.padding(.horizontal, 14).padding(.top, 14)
      .onChange(of: app.section) { _, name in
        if !["Workspace", "Review", "Files", "Terminal"].contains(name) { expandedNavigation = true }
      }
  }
  private func navigationButton(_ name: String) -> some View {
    let index = Sections.names.firstIndex(of: name) ?? 0
    return Button {
      app.section = name
    } label: {
      HStack(spacing: 12) {
        Image(systemName: Sections.icons[index]).frame(width: 19)
        Text(Sections.title(for: name)).font(.system(size: 13, weight: app.section == name ? .semibold : .regular))
        Spacer()
      }.padding(.horizontal, 12).padding(.vertical, 9)
        .foregroundStyle(app.section == name ? Color.primary : Color.primary.opacity(0.75))
        .background(
          Color.qPanel,
          in: RoundedRectangle(cornerRadius: 7))
        .overlay(RoundedRectangle(cornerRadius: 7).stroke(app.section == name ? Color.qAccent : Color.clear, lineWidth: 1))
    }.buttonStyle(.plain).disabled((app.project.isEmpty && name != "Workspace") || app.openingProject || app.restoringNavigation)
      .accessibilityAddTraits(app.section == name ? .isSelected : [])
  }
  private var recentRuns: some View {
    ScrollView {
      LazyVStack(spacing: 3) {
        ForEach(app.recentConversations, id: \.projectRowID) { job in
          Button {
            let destinationSection =
              string(job, "kind") == "tool"
              ? "Tools"
              : ["optimization", "tuning"].contains(string(job, "kind"))
                ? "Optimization" : string(job, "kind") == "evaluation" ? "Evaluations" : "Workspace"
            app.selectJob(string(job, "id"), targetSection: destinationSection)
          } label: {
            VStack(alignment: .leading, spacing: 5) {
              Text(string(job, "conversation_title", string(job, "title"))).font(.system(size: 12)).lineLimit(2)
              Text(string(job, "kind") + " · " + string(job, "status")).font(
                .system(size: 11, design: .monospaced)
              ).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(
              Color.qPanel,
              in: RoundedRectangle(cornerRadius: 6))
              .overlay(RoundedRectangle(cornerRadius: 6).stroke(app.selectedConversationID == string(job, "conversation_id", string(job, "id")) ? Color.qAccent : Color.clear, lineWidth: 1))
          }.buttonStyle(.plain)
        }
      }.padding(.horizontal, 14).padding(.top, 8)
    }
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
  var body: some View {
    HStack(spacing: 0) {
      VStack(spacing: 0) {
        HStack(spacing: 12) {
          Text(app.selectedJob.isEmpty ? "New conversation" : string(app.detail, "title", "Conversation"))
            .font(.system(size: 16, weight: .semibold)).lineLimit(1)
          Spacer()
          if app.active { BrandActivityIndicator(status: string(app.detail, "status")) }
          if !app.selectedJob.isEmpty {
            Button("New conversation", systemImage: "square.and.pencil") { app.selectJob("") }
              .disabled(app.active || app.busy)
            Button { app.inspectorVisible.toggle() } label: { Image(systemName: "sidebar.right") }
              .help("Show changes and run details").accessibilityLabel("Show changes and run details")
          }
        }.padding(.horizontal, 24).padding(.vertical, 14)
        Divider()
        if app.selectedJob.isEmpty {
          GettingStartedView(draftStore: app.draftStore).frame(minHeight: 220, maxHeight: .infinity)
        } else {
          EventStream().id(app.projectID + "\n" + app.selectedJob).frame(minHeight: 220, maxHeight: .infinity)
        }
        CodingComposer(draftStore: app.draftStore)
      }.frame(minWidth: 500, maxWidth: .infinity, maxHeight: .infinity)
      if !app.selectedJob.isEmpty && app.inspectorVisible {
        Divider()
        InspectorView().frame(width: 300)
      }
    }
  }
}
struct CodingComposer: View {
  @ObservedObject var draftStore: DraftStore
  @EnvironmentObject var app: Workspace
  @State private var showQueue = false
  @State private var showContext = false
  @State private var showOptions = false
  @FocusState private var composerFocused: Bool
  private var route: [String: Any] {
    app.harnesses.first { string($0, "id") == app.harness } ?? [:]
  }
  private var connectionName: String {
    app.connectionDisconnected ? "No connection" : app.isManaged ? string(route, "name", "Coding agent")
      : (app.model.isEmpty ? "Choose a connection" : app.model)
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
    .onChange(of: draftStore.text) { _, _ in app.scheduleDraftSave() }
    .onChange(of: app.selectedJob) { _, _ in composerFocused = true }
  }
  private var composer: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack(spacing: 10) {
        Image(systemName: app.isManaged ? "terminal" : "cpu").foregroundStyle(Brand.gradient)
        Text(connectionName).font(.system(size: 13, weight: .semibold)).lineLimit(1)
        Text(app.connectionDisconnected ? "Not connected" : app.isACP ? "ACP" : app.isManaged ? "Subscription / agent" : app.provider)
          .font(.caption).foregroundStyle(.secondary).lineLimit(1)
        Spacer()
        Button(app.connectionDisconnected ? "Connect…" : "Change connection…") { app.showConnection = true }
          .disabled(app.active || app.busy)
        if !app.connectionDisconnected {
          nativeButton("connection.disconnect", action: app.disconnectConnection, title: "Disconnect coding agent") {
            Label("Disconnect", systemImage: "xmark.circle").font(.caption)
          }.disabled(app.anyActive || app.busy).help("Disconnect from this Agent Space. Saved sign-ins remain on your Mac.")
        }
        Button { showOptions.toggle() } label: { Image(systemName: "slider.horizontal.3") }
          .disabled(app.connectionDisconnected)
          .accessibilityLabel("Connection and model options").help("Connection and model options")
          .popover(isPresented: $showOptions, arrowEdge: .top) {
            connectionOptions
          }
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
      PromptEditor(text: $draftStore.text) { app.send(continueSession: continuesConversation) }
        .focused($composerFocused)
        .frame(height: app.draft.contains("\n") ? 92 : 54).padding(8)
        .outlinedSurface(radius: 8)
        .overlay(alignment: .topLeading) {
          if app.draft.isEmpty {
            Text(app.active ? "Draft your next message…" : continuesConversation ? "Ask a follow-up or describe the next change…" : "Describe the change you want to make…")
              .font(.system(size: 14)).foregroundStyle(.secondary).padding(13).allowsHitTesting(false)
          }
        }
        .accessibilityLabel("Message your coding agent")
      HStack(spacing: 12) {
        Menu {
          Button("Project text files…", action: app.attachFiles)
          Button("Images…", action: app.attachImages)
          Button("Paste image", action: app.pasteImage)
        } label: { Image(systemName: "paperclip") }
          .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().frame(width: 24)
          .accessibilityLabel("Attach context").disabled(app.projectID.isEmpty || app.active)
        Button("Context…") { showContext = true }.font(.caption)
        Menu("Tasks") {
          Button("Open queue…") { showQueue = true }
          Button("Add draft to queue", action: app.enqueueDraft).disabled(app.draft.isEmpty || app.connectionDisconnected)
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
        } else {
          Text(app.connectionDisconnected ? "Connect an agent to start coding" : continuesConversation ? "Continuing conversation" : "Enter to send · Shift+Enter for a new line")
            .font(.caption).foregroundStyle(.secondary)
        }
        Button {
          app.send(continueSession: continuesConversation)
        } label: {
          Label(app.busy ? "Starting…" : "Send", systemImage: "arrow.up")
        }.buttonStyle(BrandButtonStyle())
          .disabled(app.busy || app.active || app.checkingConnection || app.projectID.isEmpty
            || app.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            || app.connectionDisconnected || (!app.isManaged && app.model.isEmpty))
          .keyboardShortcut(.return, modifiers: .command)
      }
    }.padding(16).brandSurface().padding(.horizontal, 20).padding(.bottom, 16).padding(.top, 8)
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
          ResponseDocument(text: response)
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
            Color.clear.frame(height: 1).id("bottom")
          }.scrollTargetLayout().padding(24).frame(maxWidth: .infinity, alignment: .leading)
        }.scrollPosition(id: $visibleAnchor, anchor: .top)
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
    }.onDisappear { savePosition(); app.flushRecovery() }
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
          Text(pretty(data["tool"])).font(.system(size: 11, design: .monospaced)).textSelection(
            .enabled)
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
          Button("Change connection…") { app.showConnection = true }
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
  @EnvironmentObject var app: Workspace
  @State private var tab = "Changes"
  @State private var command = ""
  @State private var commit = ""
  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      Picker("Inspector", selection: $tab) {
        Text("Changes").tag("Changes")
        Text("Checks").tag("Checks")
        Text("Evidence").tag("Evidence")
      }.pickerStyle(.segmented)
      if tab == "Changes" {
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
        Button("Stage tracked changes") { app.gitAction("git.stage") }.disabled(app.anyActive)
        TextField("Commit message", text: $commit).textFieldStyle(.roundedBorder)
        Button("Commit staged changes") { app.gitAction("git.commit", message: commit) }.disabled(
          commit.isEmpty || app.anyActive)
      } else if tab == "Checks" {
        Text("Run a command in this project").font(.headline)
        Text(
          "Commands run with your Mac account’s permissions. Review commands before running them."
        ).font(.caption).foregroundStyle(.secondary)
        TextField("e.g. uv run pytest -q", text: $command).textFieldStyle(.roundedBorder)
        Button("Run check") { app.start("checks.start", extra: ["command": command]) }.disabled(
          command.isEmpty || app.busy || app.anyActive)
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
          Text(line).foregroundStyle(ink(for: line)).textSelection(.enabled)
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
