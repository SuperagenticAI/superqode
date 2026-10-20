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
          "Quitting stops active runs and discards unsaved file-edit drafts (\(workspace.fileDrafts.count)). Recorded run history remains on this Mac.",
          button: "Quit")
      else { return .terminateCancel }
    }
    workspace?.shutdown()
    return .terminateNow
  }
  func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool { false }
}

@main struct SuperQodeApp: App {
  @NSApplicationDelegateAdaptor(ApplicationDelegate.self) var delegate
  @StateObject private var workspace = Workspace()
  var body: some Scene {
    Window("SuperQode", id: "main") {
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
    }
    .defaultSize(width: 1440, height: 900)
    .windowStyle(.hiddenTitleBar)
    .commands {
      CommandGroup(replacing: .newItem) {
        Button("Open Project…") { workspace.chooseProject() }.keyboardShortcut("o")
        Button("New Task") {
          workspace.showWelcome = workspace.project.isEmpty
          workspace.section = "Workspace"
          workspace.selectJob("")
        }.keyboardShortcut("n")
      }
      CommandGroup(replacing: .help) {
        Button("Welcome to SuperQode") { workspace.showWelcome = true }
        Divider()
        Button("Getting Started & Learning") { workspace.showLearningGuide = true }
          .keyboardShortcut("?", modifiers: .command)
      }
      CommandMenu("Workspace") {
        ForEach(Array(Sections.names.enumerated()), id: \.offset) { index, name in
          Button(name) {
            workspace.showWelcome = workspace.project.isEmpty
            workspace.section = name
          }.keyboardShortcut(
            KeyEquivalent(Character(String(index + 1))))
        }
        Divider()
        Button("Back", action: workspace.goBack).keyboardShortcut("[", modifiers: .command)
          .disabled(
            workspace.navigationHistory.isEmpty
              && !(workspace.showWelcome && !workspace.project.isEmpty))
        Button("Refresh Changes") { workspace.perform { await workspace.refreshGit() } }
          .keyboardShortcut("r")
        Button("Export Run Evidence…") { workspace.exportEvidence() }.disabled(
          workspace.selectedJob.isEmpty)
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
  static let names = [
    "Workspace", "Harness Hub", "Models", "Evaluations", "Optimization", "Files", "Tools",
    "Terminal", "Checkpoints",
  ]
  static let icons = [
    "chevron.left.forwardslash.chevron.right", "square.stack.3d.up", "cpu", "checkmark.seal",
    "slider.horizontal.3", "folder", "wrench.and.screwdriver", "terminal", "clock.arrow.circlepath",
  ]
}
extension Color {
  static let qAccent = Color(
    nsColor: NSColor(name: nil) { appearance in
      appearance.bestMatch(from: [.aqua, .darkAqua]) == .darkAqua
        ? NSColor(srgbRed: 0.79, green: 0.47, blue: 0.98, alpha: 1)
        : NSColor(srgbRed: 0.392, green: 0.082, blue: 0.733, alpha: 1)
    })
  static let qPanel = Color(nsColor: .controlBackgroundColor)
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
    }.background(.black.opacity(0.13), in: RoundedRectangle(cornerRadius: 9))
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
  }
  private var workspaceShell: some View {
    HStack(spacing: 0) {
      SidebarView().frame(width: 236).background(.regularMaterial)
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
            .disabled(app.navigationHistory.isEmpty).help("Back to previous page")
          Text(app.section).font(.system(size: 12, weight: .medium))
          Text("/").foregroundStyle(.tertiary)
          Text(string(app.project, "name", "No project")).font(.system(size: 12)).foregroundStyle(
            .secondary)
          Spacer()
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
          GettingStartedView()
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
              case "Checkpoints": CheckpointsView()
              case "Files": FilesView().id(app.projectID)
              default: CodingView()
              }
            }.id(app.section).transition(.opacity).frame(
              width: geometry.size.width, height: geometry.size.height, alignment: .topLeading
            )
            .background(Color(nsColor: .controlBackgroundColor).opacity(0.22))
            .clipShape(RoundedRectangle(cornerRadius: 16))
            .overlay(RoundedRectangle(cornerRadius: 16).strokeBorder(.primary.opacity(0.07)))
          }.padding(.horizontal, 20).padding(.bottom, 20)
        }
        if !app.notice.isEmpty {
          HStack {
            Text(app.notice).font(.caption)
            Spacer()
            Button {
              app.notice = ""
            } label: {
              Image(systemName: "xmark")
            }.buttonStyle(.plain)
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
      }.buttonStyle(.plain).background(
        .primary.opacity(0.055), in: RoundedRectangle(cornerRadius: 8)
      ).padding(.horizontal, 14)
      if !app.projects.isEmpty {
        Menu("Recent projects") {
          ForEach(app.projects, id: \.projectRowID) { row in
            Button(URL(fileURLWithPath: string(row, "path")).lastPathComponent) {
              app.perform { try await app.open(string(row, "path")) }
            }
          }
        }.font(.caption).padding(.horizontal, 24).padding(.vertical, 10)
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
          app.selectJob("")
          app.section = "Workspace"
        } label: {
          Image(systemName: "plus")
        }.buttonStyle(.plain)
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
      ForEach(["Workspace", "Files", "Terminal"], id: \.self) { name in
        navigationButton(name)
      }
      DisclosureGroup("Improve & more", isExpanded: $expandedNavigation) {
        VStack(spacing: 3) {
          ForEach(
            Sections.names.filter { !["Workspace", "Files", "Terminal"].contains($0) }, id: \.self
          ) { name in
            navigationButton(name)
          }
        }.padding(.top, 6)
      }.font(.system(size: 12)).padding(.horizontal, 10).padding(.top, 8)
    }.padding(.horizontal, 14).padding(.top, 14)
      .onChange(of: app.section) { _, name in
        if !["Workspace", "Files", "Terminal"].contains(name) { expandedNavigation = true }
      }
  }
  private func navigationButton(_ name: String) -> some View {
    let index = Sections.names.firstIndex(of: name) ?? 0
    return Button {
      app.section = name
    } label: {
      HStack(spacing: 12) {
        Image(systemName: Sections.icons[index]).frame(width: 19)
        Text(name).font(.system(size: 13, weight: app.section == name ? .semibold : .regular))
        Spacer()
      }.padding(.horizontal, 12).padding(.vertical, 9)
        .foregroundStyle(app.section == name ? Color.primary : Color.primary.opacity(0.75))
        .background(
          app.section == name ? Brand.pink.opacity(0.13) : .clear,
          in: RoundedRectangle(cornerRadius: 7))
    }.buttonStyle(.plain).disabled(app.project.isEmpty && name != "Workspace")
      .accessibilityAddTraits(app.section == name ? .isSelected : [])
  }
  private var recentRuns: some View {
    ScrollView {
      LazyVStack(spacing: 3) {
        ForEach(app.projectJobs, id: \.projectRowID) { job in
          Button {
            app.selectJob(string(job, "id"))
            app.section =
              string(job, "kind") == "tool"
              ? "Tools"
              : string(job, "kind") == "optimization"
                ? "Optimization" : string(job, "kind") == "evaluation" ? "Evaluations" : "Workspace"
          } label: {
            VStack(alignment: .leading, spacing: 5) {
              Text(string(job, "title")).font(.system(size: 12)).lineLimit(2)
              Text(string(job, "kind") + " · " + string(job, "status")).font(
                .system(size: 11, design: .monospaced)
              ).foregroundStyle(.secondary)
            }.frame(maxWidth: .infinity, alignment: .leading).padding(10).background(
              app.selectedJob == string(job, "id") ? Color.primary.opacity(0.06) : Color.clear,
              in: RoundedRectangle(cornerRadius: 6))
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
  @State private var continueSession = false
  @State private var showQueue = false
  @State private var showContext = false
  @FocusState private var composerFocused: Bool
  @State private var showAdvanced = false
  @State private var showInspector = false
  var body: some View {
    HStack(spacing: 0) {
      VStack(alignment: .leading, spacing: 0) {
        HStack {
          VStack(alignment: .leading, spacing: 7) {
            Text(
              app.selectedJob.isEmpty
                ? "What shall we build?" : string(app.detail, "title", "Loading run…")
            ).font(.system(size: 24, weight: .medium)).lineLimit(2)
            Text("Code on your Mac. Evaluate the result. Improve your harness.").font(
              .system(size: 12)
            )
            .foregroundStyle(.secondary)
          }
          Spacer()
          if !app.selectedJob.isEmpty {
            Button {
              showInspector.toggle()
            } label: {
              Image(systemName: "sidebar.right")
            }.help(showInspector ? "Hide run details" : "Show run details and changes")
            Pill(
              title: string(app.detail, "status", "loading"), color: app.active ? .orange : .qAccent
            )
          }
        }.padding(26)
        Divider()
        if app.selectedJob.isEmpty {
          GettingStartedView().frame(minHeight: 0, maxHeight: .infinity)
        } else {
          EventStream().frame(minHeight: 80, maxHeight: .infinity)
        }
        VStack(alignment: .leading, spacing: 12) {
          HStack(spacing: 10) {
            Image(systemName: app.isManaged ? "terminal" : "cpu").foregroundStyle(Brand.gradient)
            VStack(alignment: .leading, spacing: 3) {
              Text(
                app.isManaged
                  ? string(
                    app.harnesses.first { string($0, "id") == app.harness } ?? [:], "name",
                    "Coding agent")
                  : (app.model.isEmpty ? "Choose an agent or model to start" : app.model)
              )
              .font(.system(size: 12, weight: .semibold)).lineLimit(1)
              Text(
                app.isManaged
                  ? "Agent-owned connection"
                  : (app.model.isEmpty ? "Use your existing setup" : app.provider)
              )
              .font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button("Context…") { showContext = true }
            Button("Change…") { app.showConnection = true }
          }
          if !app.isManaged {
            DisclosureGroup("Advanced routing", isExpanded: $showAdvanced) {
              RouteControls().padding(.top, 8)
            }.font(.caption)
          }
          RouteReadiness()
          if !app.isManaged {
            HStack {
              Picker("Interaction", selection: $app.interactionMode) {
                Text("Code").tag("code")
                Text("Chat").tag("chat")
              }.labelsHidden().pickerStyle(.segmented).frame(width: 160).disabled(app.active)
              if app.interactionMode == "chat" {
                Text("Messages and images only · no project instructions or tools").font(.caption)
                  .foregroundStyle(.secondary)
              }
            }
          }

          if app.active { BrandActivityIndicator() }

          if app.isACP && !app.agentSession.isEmpty { AgentControlsView() }
          if app.isACP && !app.agentCommands.isEmpty {
            Menu("Agent commands") {
              ForEach(app.agentCommands, id: \.projectRowID) { command in
                Button("/" + string(command, "name")) {
                  app.draft = "/" + string(command, "name") + " "
                }
              }
            }.disabled(app.active)
          }
          if !app.imageAttachments.isEmpty {
            ScrollView(.horizontal) {
              HStack {
                ForEach(app.imageAttachments, id: \.projectRowID) { image in
                  HStack {
                    if let preview = NSImage(contentsOfFile: string(image, "path")) {
                      Image(nsImage: preview).resizable().scaledToFit().frame(width: 44, height: 36)
                    }
                    Text(string(image, "name")).font(.caption).lineLimit(1)
                    Button {
                      app.imageAttachments.removeAll { string($0, "id") == string(image, "id") }
                    } label: {
                      Image(systemName: "xmark.circle")
                    }.buttonStyle(.borderless)
                  }.padding(6).brandSurface(radius: 8)
                }
              }
            }
          }
          if !app.contextFiles.isEmpty {
            ScrollView(.horizontal) {
              HStack {
                ForEach(app.contextFiles, id: \.self) { path in
                  Button {
                    app.contextFiles.removeAll { $0 == path }
                  } label: {
                    Label(path, systemImage: "xmark.circle").font(.caption)
                  }.buttonStyle(.borderless).help("Remove attachment")
                }
              }
            }
          }
          TextEditor(text: $app.draft).focused($composerFocused).font(
            .system(size: 13, design: .monospaced)
          )
          .scrollContentBackground(.hidden).frame(height: 100).padding(8).background(
            .black.opacity(0.08), in: RoundedRectangle(cornerRadius: 6)
          ).overlay(alignment: .topLeading) {
            if app.draft.isEmpty {
              Text("Describe the change you want to make…").font(
                .system(size: 13, design: .monospaced)
              ).foregroundStyle(.tertiary).padding(14).allowsHitTesting(false)
            }
          }
          HStack {
            Menu("Tasks") {
              Button("Open queue…") { showQueue = true }
              Button("Add draft to queue", action: app.enqueueDraft)
                .disabled(app.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }.menuStyle(.borderlessButton).fixedSize().disabled(app.projectID.isEmpty)
            Menu {
              Button("Project text files…", action: app.attachFiles)
              Button("Images…", action: app.attachImages)
              Button("Paste image", action: app.pasteImage)
            } label: {
              Image(systemName: "paperclip")
            }
            .menuStyle(.borderlessButton).menuIndicator(.hidden).fixedSize().frame(width: 28)
            .help("Attach project text files or images").accessibilityLabel("Attach context")
            .disabled(app.projectID.isEmpty || app.active)
            Button {
              composerFocused = true
              DispatchQueue.main.async {
                NSApp.sendAction(NSSelectorFromString("startDictation:"), to: nil, from: nil)
              }
            } label: {
              Image(systemName: "mic")
            }.help("Start macOS Dictation in the focused text editor").accessibilityLabel(
              "Dictate prompt")
            if !app.selectedJob.isEmpty
              && ["task", "compaction"].contains(string(app.detail, "kind"))
            {
              Toggle("Continue session", isOn: $continueSession).font(.caption).disabled(
                !app.canContinue)
            }
            Spacer()
            if app.canSteer {
              Button("Steer run", action: app.steerDraft).disabled(
                app.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            }
            if app.active {
              Button(
                app.isRemote ? "Cancel remote task" : "Stop run", role: .destructive,
                action: app.cancel
              ).help(
                app.isRemote
                  ? "Request cancellation from the remote server and report its acknowledgement."
                  : "Stop this local run")
            }
            Button {
              app.send(continueSession: continueSession && !app.selectedJob.isEmpty)
            } label: {
              Label(
                app.interactionMode == "chat" ? "Send message" : "Start coding",
                systemImage: "arrow.up")
            }.buttonStyle(BrandButtonStyle()).disabled(
              app.busy || app.active
                || app.draft.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
                || (!app.isManaged && app.model.isEmpty)
            ).keyboardShortcut(.return, modifiers: .command)
          }
        }.padding(16).brandSurface().padding(20)
      }.frame(minWidth: 500, maxWidth: .infinity, maxHeight: .infinity, alignment: .top)
      if !app.selectedJob.isEmpty && showInspector {
        Divider()
        InspectorView().frame(width: 300)
      }
    }.centeredDialog(isPresented: $showQueue, title: "Task queue") {
      TaskQueueView().environmentObject(app)
    }
    .centeredDialog(isPresented: $showContext, title: "Project context") {
      ContextPreviewView().environmentObject(app)
    }
    .onChange(of: app.draft) { _, _ in app.saveDraft() }.onChange(of: app.selectedJob) { _, _ in
      continueSession = false
    }
  }
}
/// Coalesce consecutive model deltas for readable paragraphs while retaining raw evidence.
func displayEvents(_ events: [[String: Any]]) -> [[String: Any]] {
  var rows: [[String: Any]] = []
  for event in events {
    let data = event["data"] as? [String: Any] ?? [:]
    let payload = data["payload"] as? [String: Any] ?? [:]
    let delta =
      string(event, "type") == "harness_event"
      && ["delta", "model_delta", "message.delta"].contains(string(data, "event"))
    let answer = string(event, "type") == "answer"
    if delta || answer {
      let text = answer ? string(data, "text") : string(payload, "text", string(payload, "content"))
      if rows.last?["coalesced"] as? Bool == true {
        var last = rows.removeLast()
        let old = last["data"] as? [String: Any] ?? [:]
        last["data"] = ["text": string(old, "text") + text]
        rows.append(last)
      } else {
        rows.append(["type": "output", "data": ["text": text], "coalesced": true])
      }
    } else {
      rows.append(event)
    }
  }
  return rows
}
/// Keep approvals, tool work, errors and unknown events visible. Routine engine
/// bookkeeping stays available through Activity details and full evidence export.
func conversationEvents(_ events: [[String: Any]], includeDetails: Bool) -> [[String: Any]] {
  let rows = displayEvents(events)
  guard !includeDetails else { return rows }
  return rows.filter { row in
    let type = string(row, "type")
    if ["stage", "provenance", "checkpoint", "control_capabilities"].contains(type) {
      return false
    }
    if type == "harness_event" {
      let data = row["data"] as? [String: Any] ?? [:]
      return !["run_start", "run_end", "model_request", "control_capabilities", "thinking"]
        .contains(string(data, "event"))
    }
    return true
  }
}
struct EventStream: View {
  @EnvironmentObject var app: Workspace
  @State private var follow = true
  @State private var showActivity = false
  var body: some View {
    VStack(spacing: 0) {
      HStack {
        Text("CONVERSATION").font(.system(size: 11, design: .monospaced)).foregroundStyle(
          .secondary)
        Spacer()
        Toggle("Activity details", isOn: $showActivity).toggleStyle(.checkbox).font(.caption)
        Toggle("Follow", isOn: $follow).toggleStyle(.checkbox).font(.caption)
        Button("Export…", action: app.exportEvidence).font(.caption)
      }.padding(.horizontal, 20).padding(.top, 10)
      ScrollViewReader { proxy in
        ScrollView {
          LazyVStack(alignment: .leading, spacing: 10) {
            if let request = app.detail["request"] as? [String: Any],
              !string(request, "prompt").isEmpty
            {
              VStack(alignment: .leading, spacing: 8) {
                Text("YOU").font(.system(size: 11, weight: .semibold, design: .monospaced))
                  .foregroundStyle(Color.qAccent)
                Text(string(request, "prompt")).font(.system(size: 13)).textSelection(.enabled)
              }.padding(16).frame(maxWidth: .infinity, alignment: .leading).background(
                Color.qAccent.opacity(0.07), in: RoundedRectangle(cornerRadius: 10)
              ).padding(.bottom, 10)
            }
            ForEach(
              Array(conversationEvents(app.events, includeDetails: showActivity).enumerated()),
              id: \.offset
            ) { _, event in
              EventRow(event: event)
            }
            Color.clear.frame(height: 1).id("bottom")
          }.padding(20)
        }.onChange(of: app.events.count) { _, _ in
          if follow { proxy.scrollTo("bottom", anchor: .bottom) }
        }
      }
    }
  }
}
struct EventRow: View {
  @EnvironmentObject var app: Workspace
  let event: [String: Any]
  var type: String { string(event, "type") }
  var data: [String: Any] { event["data"] as? [String: Any] ?? [:] }
  var body: some View {
    Group {
      if type == "approval" {
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
        if ["delta", "model_delta", "message.delta"].contains(name) {
          AgentResponseView(text: string(payload, "text", string(payload, "content")))
        } else {
          DisclosureGroup(name) {
            Text(pretty(payload)).font(.system(size: 11, design: .monospaced)).textSelection(
              .enabled
            ).frame(maxWidth: .infinity, alignment: .leading)
          }.font(.caption).padding(10).background(
            .primary.opacity(0.025), in: RoundedRectangle(cornerRadius: 6))
        }
      } else if type == "output" {
        if event["coalesced"] as? Bool == true {
          AgentResponseView(text: string(data, "text"))
        } else {
          Text(string(data, "text")).font(.system(size: 12, design: .monospaced)).textSelection(
            .enabled)
        }
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
    }.padding(18).frame(maxHeight: .infinity, alignment: .top).background(.primary.opacity(0.018))
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
    }.background(.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 8))
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
